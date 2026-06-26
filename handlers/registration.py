# handlers/registration.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from database.session import SessionLocal
from database.models import User, SellerProfile
from keyboards.buyer import get_buyer_home_keyboard
from keyboards.seller import get_seller_home_keyboard
from utils.helpers import get_text, get_user_lang
from config import ADMIN_TELEGRAM_ID

# Expanded Conversation States
SELECT_LANG, SELECT_ROLE, AGREE_RULES, SHARE_PHONE, FULL_NAME, BUSINESS_NAME, LOCATION, CATEGORY, SHOP_NUMBER = range(9)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_lang(update.effective_user.id)
    await update.message.reply_text(get_text(lang, "help_text"), parse_mode="Markdown")

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    
    if not user:
        db.close()
        return await start(update, context) # Fallback to start if not registered
        
    lang = user.language
    if user.role == 'buyer':
        await update.message.reply_text(get_text(lang, "welcome_back"), reply_markup=get_buyer_home_keyboard(lang))
    elif user.role == 'seller' and user.status == 'active':
        await update.message.reply_text(get_text(lang, "welcome_back"), reply_markup=get_seller_home_keyboard(lang))
    else:
        await update.message.reply_text(get_text(lang, "pending_admin"))
    
    db.close()

async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for users explicitly requesting a language change."""
    keyboard = [
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
         InlineKeyboardButton("🇪🇹 አማርኛ", callback_data="lang_am")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Please select your language / እባክዎ ቋንቋዎን ይምረጡ:", reply_markup=reply_markup)
    return SELECT_LANG

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    
    # User Recovery Protocol
    if user:
        db.close()
        await cmd_menu(update, context)
        return ConversationHandler.END

    db.close()
    # New User Protocol -> Language First
    keyboard = [
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
         InlineKeyboardButton("🇪🇹 አማርኛ", callback_data="lang_am")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welcome! Please select your language:\nእንኳን ደህና መጡ! እባክዎ ቋንቋዎን ይምረጡ፡", reply_markup=reply_markup)
    return SELECT_LANG

async def handle_language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    lang_choice = query.data.split("_")[1] # 'en' or 'am'
    context.user_data['lang'] = lang_choice
    
    # Update DB if user exists (i.e., triggered by /language command)
    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
    if user:
        user.language = lang_choice
        db.commit()
        db.close()
        await query.message.delete()
        # Automatically restore their menu with the new language
        class FakeUpdate:
            effective_user = update.effective_user
            message = query.message # Reuse previous message object reference
        await cmd_menu(FakeUpdate, context) 
        return ConversationHandler.END
        
    db.close()

    # If new user, proceed to role selection
    keyboard = [
        [InlineKeyboardButton(get_text(lang_choice, "buyer_btn"), callback_data="role_buyer"),
         InlineKeyboardButton(get_text(lang_choice, "seller_btn"), callback_data="role_seller")]
    ]
    await query.edit_message_text(get_text(lang_choice, "select_mode"), reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_ROLE


async def handle_role_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    target_role = query.data.split("_")[1]
    context.user_data['target_role'] = target_role
    
    # Try to get language from DB first, fallback to context
    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
    lang = user.language if user else context.user_data.get('lang', 'en')
    
    db.close()

    rule_key = "buyer_rules" if target_role == "buyer" else "seller_rules"
    
    keyboard = [
        [InlineKeyboardButton(get_text(lang, "agree_btn"), callback_data="rules_agree")]
    ]
    
    await query.edit_message_text(
        get_text(lang, rule_key), 
        parse_mode="Markdown", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return AGREE_RULES

async def handle_rules_agreement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    target_role = context.user_data.get('target_role')
    
    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
    lang = user.language if user else context.user_data.get('lang', 'en')
    
    await query.message.delete()
    
    # Step 3: Run target registration logic pathways after authorization agreement
    if user and user.phone and target_role == 'seller':
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=get_text(lang, "seller_bus_name"),
            reply_markup=ReplyKeyboardRemove()
        )
        db.close()
        return BUSINESS_NAME
        
    db.close()

    contact_btn = [[KeyboardButton(text=get_text(lang, "share_phone"), request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(contact_btn, resize_keyboard=True, one_time_keyboard=True)
    
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=get_text(lang, "share_phone_prompt"),
        reply_markup=reply_markup
    )
    return SHARE_PHONE

async def process_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    lang = context.user_data.get('lang', 'en')
    
    # Security Validation: Reject forwarded contacts
    if contact.user_id != update.effective_user.id:
        await update.message.reply_text(get_text(lang, "reject_forwarded_contact"))
        return SHARE_PHONE
        
    # 2. Ethiopian Phone Validation (Must start with 251)
    phone = contact.phone_number.replace("+", "") # Ensure no '+' prefix
    if not phone.startswith("251"):
        await update.message.reply_text(
            "❌ Only Ethiopian phone numbers starting with '251' are accepted."
        )
        return SHARE_PHONE
    
    target_role = context.user_data.get('target_role')
    
    db = SessionLocal()
    new_user = User(
        telegram_id=update.effective_user.id,
        username=update.effective_user.username,
        phone=phone,
        language=lang,
        role=target_role,
        status='active' if target_role == 'buyer' else 'pending'
    )
    db.add(new_user)
    db.commit()
    db.close()

    await update.message.reply_text(
        get_text(lang, "enter_full_name"),
        reply_markup=ReplyKeyboardRemove()
    )
    return FULL_NAME

async def process_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    full_name = update.message.text
    lang = context.user_data.get('lang', 'en')
    target_role = context.user_data.get('target_role')

    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
    if user:
        user.full_name = full_name
        db.commit()
    db.close()

    if target_role == 'buyer':
        await update.message.reply_text(get_text(lang, "reg_success_buyer"), reply_markup=get_buyer_home_keyboard(lang))
        return ConversationHandler.END
    else:
        # Seller continues to profile setup
        await update.message.reply_text(get_text(lang, "seller_bus_name"), reply_markup=ReplyKeyboardRemove())
        return BUSINESS_NAME

async def seller_business_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['business_name'] = update.message.text
    lang = get_user_lang(update.effective_user.id)
    await update.message.reply_text(get_text(lang, "seller_loc"))
    return LOCATION

async def seller_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['location'] = update.message.text
    lang = get_user_lang(update.effective_user.id)
    await update.message.reply_text(get_text(lang, "seller_cat"))
    return CATEGORY

async def seller_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['category'] = update.message.text
    lang = get_user_lang(update.effective_user.id)
    # Route to shop number instead of finishing
    await update.message.reply_text(get_text(lang, "seller_shop_num"))
    return SHOP_NUMBER

async def seller_shop_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['shop_number'] = update.message.text
    lang = get_user_lang(update.effective_user.id)
    
    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
    
    profile = SellerProfile(
        user_id=user.id,
        business_name=context.user_data['business_name'],
        location=context.user_data['location'],
        category=context.user_data['category'],
        shop_number=context.user_data['shop_number']
    )
    db.add(profile)
    db.commit()
    
    await update.message.reply_text(get_text(lang, "seller_app_submitted"), reply_markup=ReplyKeyboardRemove())
    
    # Notify Admin (Updated to include Name and Shop Number)
    admin_kb = [
        [InlineKeyboardButton("Approve ✅", callback_data=f"adm_app_{user.id}"),
         InlineKeyboardButton("Reject ❌", callback_data=f"adm_rej_{user.id}")]
    ]
    admin_text = (
        f"🆕 *New Seller Request*\n\n"
        f"**Name:** {user.full_name}\n"
        f"**Business:** {profile.business_name}\n"
        f"**Shop No:** {profile.shop_number}\n"
        f"**Category:** {profile.category}\n"
        f"**Location:** {profile.location}\n"
        f"**Phone:** {user.phone}"
    )
    await context.bot.send_message(chat_id=ADMIN_TELEGRAM_ID, text=admin_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(admin_kb))
    
    db.close()
    return ConversationHandler.END

async def switch_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == tg_id).first()
    
    if not user:
        db.close()
        return

    lang = user.language

    if user.role == 'buyer':
        profile = db.query(SellerProfile).filter(SellerProfile.user_id == user.id).first()
        if profile and user.status == 'active':
            user.role = 'seller'
            db.commit()
            await update.message.reply_text(get_text(lang, "switched_seller"), reply_markup=get_seller_home_keyboard(lang))
        else:
            # Need an explicit fallback if they don't have a seller profile
            keyboard = [[InlineKeyboardButton(get_text(lang, "apply_seller_btn"), callback_data="role_seller")]]
            await update.message.reply_text(get_text(lang, "need_seller_acc"), reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif user.role == 'seller':
        user.role = 'buyer'
        db.commit()
        await update.message.reply_text(get_text(lang, "switched_buyer"), reply_markup=get_buyer_home_keyboard(lang))
        
    db.close()