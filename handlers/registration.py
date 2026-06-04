# handlers/registration.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from database.session import SessionLocal
from database.models import User, SellerProfile
from keyboards.buyer import get_buyer_home_keyboard
from keyboards.seller import get_seller_home_keyboard
from config import ADMIN_TELEGRAM_ID

# Conversation States for Seller Profile Setup
BUSINESS_NAME, PHONE, LOCATION, CATEGORY = range(4)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    username = update.effective_user.username
    
    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    
    if user:
        # User already exists, guide them to their home menu
        if user.role == 'buyer':
            await update.message.reply_text("Welcome back!", reply_markup=get_buyer_home_keyboard())
        elif user.role == 'seller' and user.status == 'active':
            await update.message.reply_text("Welcome back!", reply_markup=get_seller_home_keyboard())
        else:
            await update.message.reply_text("Your account is pending admin approval.")
        db.close()
        return

    # New User Flow
    keyboard = [
        [InlineKeyboardButton("Buyer 🛒", callback_data="join_buyer"),
         InlineKeyboardButton("Seller 🏭", callback_data="join_seller")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welcome to the Marketplace! Please select your mode:", reply_markup=reply_markup)
    db.close()

async def join_buyer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    db = SessionLocal()
    # Auto-approve buyer
    new_user = User(
        telegram_id=query.from_user.id,
        username=query.from_user.username,
        role='buyer',
        status='active'
    )
    db.add(new_user)
    db.commit()
    db.close()
    
    await query.message.delete()
    await query.message.reply_text("Registered successfully as a Buyer!", reply_markup=get_buyer_home_keyboard())

async def join_seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    
    await query.message.reply_text("Let's set up your Seller profile.\nEnter your Business Name:", reply_markup=ReplyKeyboardRemove())
    return BUSINESS_NAME

async def seller_business_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['business_name'] = update.message.text
    await update.message.reply_text("Enter your Phone Number:")
    return PHONE

async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    await update.message.reply_text("Enter your Location (e.g. Addis Ababa):")
    return LOCATION

async def seller_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['location'] = update.message.text
    await update.message.reply_text("Enter your Product Category (e.g. Electronics, Agri):")
    return CATEGORY

async def seller_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['category'] = update.message.text
    
    db = SessionLocal()
    # Create user with pending status
    new_user = User(
        telegram_id=update.effective_user.id,
        username=update.effective_user.username,
        role='seller',
        status='pending'
    )
    db.add(new_user)
    db.flush() # execution ensures we grab new_user.id
    
    profile = SellerProfile(
        user_id=new_user.id,
        business_name=context.user_data['business_name'],
        phone=context.user_data['phone'],
        location=context.user_data['location'],
        category=context.user_data['category']
    )
    db.add(profile)
    db.commit()
    
    await update.message.reply_text("Application submitted! Waiting for Admin approval.")
    
    # Send application notification to Admin
    admin_kb = [
        [InlineKeyboardButton("Approve ✅", callback_data=f"adm_app_{new_user.id}"),
         InlineKeyboardButton("Reject ❌", callback_data=f"adm_rej_{new_user.id}")]
    ]
    
    admin_text = (
        f"🆕 *New Seller Request*\n\n"
        f"**Business:** {profile.business_name}\n"
        f"**Category:** {profile.category}\n"
        f"**Location:** {profile.location}\n"
        f"**Phone:** {profile.phone}"
    )
    
    await context.bot.send_message(
        chat_id=ADMIN_TELEGRAM_ID, 
        text=admin_text, 
        parse_mode="Markdown", 
        reply_markup=InlineKeyboardMarkup(admin_kb)
    )
    db.close()
    return ConversationHandler.END

# Mode Switching Logic
async def switch_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == tg_id).first()
    
    if not user:
        db.close()
        return

    if user.role == 'buyer':
        # Check if they have an approved seller profile to switch directly
        # For simplicity in Phase 1, if they want to switch to seller but are registered as buyer, 
        # let's change their role to seller if they already exist as active seller, or prompt to register.
        profile = db.query(SellerProfile).filter(SellerProfile.user_id == user.id).first()
        if profile and user.status == 'active':
            user.role = 'seller'
            db.commit()
            await update.message.reply_text("Switched to Seller Mode.", reply_markup=get_seller_home_keyboard())
        else:
            # If they are a buyer but never made a seller profile, launch application selection
            keyboard = [[InlineKeyboardButton("Apply to become Seller 🏭", callback_data="join_seller")]]
            await update.message.reply_text("You need a Seller account first.", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif user.role == 'seller':
        user.role = 'buyer'
        db.commit()
        await update.message.reply_text("Switched to Buyer Mode.", reply_markup=get_buyer_home_keyboard())
        
    db.close()