# handlers/seller.py
from datetime import datetime
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters
from database.session import SessionLocal
from database.models import User, PurchaseRequest, RequestAcceptance, Offer
from keyboards.seller import get_seller_home_keyboard

# Conversation State for Seller Pricing
SELLER_PRICE = range(1)

async def handle_seller_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Extract request ID from callback data (e.g., "sel_acc_12")
    request_id = int(query.data.replace("sel_acc_", ""))
    tg_id = query.from_user.id
    
    db = SessionLocal()
    
    # Find the seller's internal DB ID
    seller = db.query(User).filter(User.telegram_id == tg_id, User.role == 'seller', User.status == 'active').first()
    if not seller:
        await query.message.reply_text("❌ You must be an active seller to accept requests.")
        db.close()
        return ConversationHandler.END

    # Check if the purchase request is still valid and open
    req = db.query(PurchaseRequest).filter(PurchaseRequest.id == request_id).first()
    if not req or req.status != 'REQUEST_OPEN':
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ This request is no longer accepting offers.")
        db.close()
        return ConversationHandler.END

    # Check if this seller has already accepted this request
    already_accepted = db.query(RequestAcceptance).filter(
        RequestAcceptance.request_id == request_id,
        RequestAcceptance.seller_id == seller.id
    ).first()
    
    if already_accepted:
        await query.message.reply_text("⚠️ You have already accepted this request! Please send your price.")
        context.user_data['bidding_request_id'] = request_id
        db.close()
        return SELLER_PRICE

    # Count how many sellers have already accepted
    acceptance_count = db.query(RequestAcceptance).filter(RequestAcceptance.request_id == request_id).count()
    
    if acceptance_count >= 3:
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Slots full! 3 sellers have already taken this deal.")
        db.close()
        return ConversationHandler.END

    # Record this acceptance (Locking a slot)
    new_acceptance = RequestAcceptance(request_id=request_id, seller_id=seller.id)
    db.add(new_acceptance)
    db.commit()
    
    # Save request ID contextually for the next state step
    context.user_data['bidding_request_id'] = request_id
    
    await query.message.reply_text(
        "🎉 Slot secured! You are one of the 3 chosen sellers.\n\n"
        "💰 Please reply with your offer price in ETB (numbers only, e.g., 12000):",
        reply_markup=ReplyKeyboardRemove()
    )
    
    db.close()
    return SELLER_PRICE

async def process_seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price_text = update.message.text
    request_id = context.user_data.get('bidding_request_id')
    tg_id = update.effective_user.id
    
    if not request_id:
        await update.message.reply_text("❌ Session expired. Please try accepting the request again.", reply_markup=get_seller_home_keyboard())
        return ConversationHandler.END

    # Basic numeric conversion/validation
    try:
        price = float(price_text.replace(",", "").strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid price format. Please enter a clean number (e.g., 11850 or 12000):")
        return SELLER_PRICE

    db = SessionLocal()
    seller = db.query(User).filter(User.telegram_id == tg_id).first()
    
    # Check if an offer from this seller already exists to avoid duplicate logic
    existing_offer = db.query(Offer).filter(Offer.request_id == request_id, Offer.seller_id == seller.id).first()
    
    if existing_offer:
        existing_offer.price = price
        existing_offer.created_at = datetime.utcnow()
        db.commit()
        await update.message.reply_text("🔄 Your offer price has been successfully updated!", reply_markup=get_seller_home_keyboard())
    else:
        # Create a clean new offer
        new_offer = Offer(
            request_id=request_id,
            seller_id=seller.id,
            price=price,
            status='OFFER_SUBMITTED'
        )
        db.add(new_offer)
        db.commit()
        await update.message.reply_text("🚀 Offer submitted successfully! The buyer will review it anonymously.", reply_markup=get_seller_home_keyboard())

    db.close()
    context.user_data.clear()
    return ConversationHandler.END