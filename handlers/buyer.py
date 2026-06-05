# handlers/buyer.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from database.session import SessionLocal
from database.models import User, PurchaseRequest
from keyboards.buyer import get_buyer_home_keyboard

# Conversation States for creating a request
BUYER_IMAGE, BUYER_QUANTITY = range(2)

async def check_buyer_role(update: Update) -> User:
    """Helper to ensure the user is an active buyer."""
    tg_id = update.effective_user.id
    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == tg_id, User.role == 'buyer', User.status == 'active').first()
    db.close()
    return user

async def start_purchase_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await check_buyer_role(update)
    if not user:
        await update.message.reply_text("This action is only available for active buyers.")
        return ConversationHandler.END
        
    await update.message.reply_text(
        "📸 Please send an image of the product you want to request:",
        reply_markup=ReplyKeyboardRemove()
    )
    return BUYER_IMAGE

async def process_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Get the largest available photo version file_id
    photo_file_id = update.message.photo[-1].file_id
    context.user_data['request_photo_id'] = photo_file_id
    
    await update.message.reply_text("🔢 Great! Now enter the quantity you need (e.g., 50):")
    return BUYER_QUANTITY

async def process_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quantity_text = update.message.text
    
    if not quantity_text.isdigit():
        await update.message.reply_text("❌ Please enter a valid number for quantity:")
        return BUYER_QUANTITY
        
    quantity = int(quantity_text)
    tg_id = update.effective_user.id
    
    db = SessionLocal()
    buyer = db.query(User).filter(User.telegram_id == tg_id).first()
    
    # 1. Save Request to Database
    new_request = PurchaseRequest(
        buyer_id=buyer.id,
        image_file_id=context.user_data['request_photo_id'],
        quantity=quantity,
        status='REQUEST_OPEN'
    )
    db.add(new_request)
    db.commit() # Save to get the new_request.id
    
    await update.message.reply_text(
        "✅ Your purchase request has been created and broadcasted to active sellers!",
        reply_markup=get_buyer_home_keyboard()
    )
    
    # 2. Broadcast to All Active Sellers (Phase 3)
    active_sellers = db.query(User).filter(User.role == 'seller', User.status == 'active').all()
    
    # Inline keyboard button for sellers to fight for slots
    seller_kb = [
        [InlineKeyboardButton("Accept 🤝", callback_data=f"sel_acc_{new_request.id}")]
    ]
    reply_markup = InlineKeyboardMarkup(seller_kb)
    
    broadcast_text = (
        f"🔔 *New Buyer Request!*\n\n"
        f"📦 *Quantity:* {quantity}\n\n"
        f"Click 'Accept' below if you want to submit an offer. Only the first 3 sellers can participate!"
    )
    
    for seller in active_sellers:
        try:
            await context.bot.send_photo(
                chat_id=seller.telegram_id,
                photo=new_request.image_file_id,
                caption=broadcast_text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except Exception as e:
            # Prevent one bad chat ID from breaking the whole broadcast loop
            print(f"Failed to send broadcast to seller {seller.telegram_id}: {e}")
            
    db.close()
    context.user_data.clear() # Wipe session data for this request wizard
    return ConversationHandler.END

async def cancel_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Request creation cancelled.", reply_markup=get_buyer_home_keyboard())
    context.user_data.clear()
    return ConversationHandler.END