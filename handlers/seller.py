# handlers/seller.py
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from database.session import db_transaction
from database.models import User, PurchaseRequest, RequestAcceptance, Offer
from keyboards.seller import get_seller_home_keyboard
from services.seller_reliability_service import check_seller_status, update_seller_score

logger = logging.getLogger(__name__)
SELLER_PRICE = range(1)

async def handle_seller_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    request_id = int(query.data.replace("sel_acc_", ""))
    tg_id = query.from_user.id

    try:
        with db_transaction() as db:
            seller = db.query(User).filter(User.telegram_id == tg_id, User.role == 'seller', User.status == 'active').first()
            if not seller:
                await query.message.reply_text("❌ You must be an active seller to accept requests.")
                return ConversationHandler.END

            req = db.query(PurchaseRequest).filter(PurchaseRequest.id == request_id).first()
            if not req or req.status != 'REQUEST_OPEN':
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ This request is no longer accepting offers.")
                return ConversationHandler.END

            already_accepted = db.query(RequestAcceptance).filter(
                RequestAcceptance.request_id == request_id,
                RequestAcceptance.seller_id == seller.id
            ).first()

            if already_accepted:
                await query.message.reply_text("⚠️ You have already accepted this request! Please send your price.")
                context.user_data['bidding_request_id'] = request_id
                return SELLER_PRICE

            acceptance_count = db.query(RequestAcceptance).filter(RequestAcceptance.request_id == request_id).count()
            seller_id = seller.id

        # Check seller status outside DB block (it opens its own session)
        is_active, warning, allowed_bids = check_seller_status(seller_id)
        if not is_active:
            await query.message.reply_text(warning)
            return ConversationHandler.END
        if warning:
            await context.bot.send_message(chat_id=tg_id, text=warning)

        if acceptance_count >= 3:
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ Slots full! 3 sellers have already taken this deal.")
            return ConversationHandler.END

        with db_transaction() as db:
            new_acceptance = RequestAcceptance(
                request_id=request_id,
                seller_id=seller_id,
                deadline_at=datetime.utcnow() + timedelta(minutes=30)
            )
            db.add(new_acceptance)

        context.user_data['bidding_request_id'] = request_id
        update_seller_score(seller_id, 0, 'accepted_requests')
        await query.message.reply_text(
            "🎉 Slot secured! You are one of the 3 chosen sellers.\n\n"
            "💰 Please reply with your offer price in ETB (numbers only):",
            reply_markup=ReplyKeyboardRemove()
        )
        return SELLER_PRICE

    except Exception as e:
        logger.error(f"handle_seller_accept failed for request {request_id}: {e}")
        await query.message.reply_text("❌ An error occurred. Please try again.")
        return ConversationHandler.END

async def process_seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price_text = update.message.text
    request_id = context.user_data.get('bidding_request_id')
    tg_id = update.effective_user.id

    if not request_id:
        await update.message.reply_text("❌ Session expired.", reply_markup=get_seller_home_keyboard())
        return ConversationHandler.END

    try:
        price = float(price_text.replace(",", "").strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid price. Please enter numbers only (e.g., 12000):")
        return SELLER_PRICE

    try:
        seller_id = None
        buyer_tg_id = None
        req_data = {}
        all_offers_data = []

        with db_transaction() as db:
            seller = db.query(User).filter(User.telegram_id == tg_id).first()
            seller_id = seller.id

            acceptance = db.query(RequestAcceptance).filter(
                RequestAcceptance.request_id == request_id,
                RequestAcceptance.seller_id == seller.id
            ).first()
            if acceptance:
                acceptance.price_submitted = True

            existing_offer = db.query(Offer).filter(
                Offer.request_id == request_id,
                Offer.seller_id == seller.id
            ).first()
            if existing_offer:
                existing_offer.price = price
                existing_offer.created_at = datetime.utcnow()
            else:
                new_offer = Offer(
                    request_id=request_id,
                    seller_id=seller.id,
                    price=price,
                    status='OFFER_SUBMITTED'
                )
                db.add(new_offer)

            # Collect buyer push data inside the same transaction
            purchase_req = db.query(PurchaseRequest).filter(PurchaseRequest.id == request_id).first()
            buyer_user = db.query(User).filter(User.id == purchase_req.buyer_id).first()
            all_offers = db.query(Offer).filter(Offer.request_id == request_id).order_by(Offer.created_at.asc()).all()

            buyer_tg_id = buyer_user.telegram_id
            req_data = {'id': purchase_req.id, 'quantity': purchase_req.quantity, 'image_file_id': purchase_req.image_file_id}
            all_offers_data = [{'id': o.id, 'price': o.price} for o in all_offers]

        # Telegram messages outside the transaction
        await update.message.reply_text("🚀 Offer submitted successfully!", reply_markup=get_seller_home_keyboard())
        update_seller_score(seller_id, 1, 'submitted_prices')

        buyer_text = (
            f"💰 *New Offer Update for Request #{request_id}*\n"
            f"📦 *Your Requested Quantity:* {req_data['quantity']}\n\n"
            f"Here are the current anonymous bidding choices:\n"
        )
        keyboard = []
        labels = ["A", "B", "C"]
        for i, off in enumerate(all_offers_data):
            label = labels[i]
            buyer_text += f"🔹 *Offer {label}:* {off['price']} ETB\n"
            keyboard.append([InlineKeyboardButton(f"Select Offer {label}", callback_data=f"buy_sel_{off['id']}")])
        buyer_text += "\nClick your preferred price option below to select it and submit the deal to the Admin."

        try:
            await context.bot.send_photo(
                chat_id=buyer_tg_id,
                photo=req_data['image_file_id'],
                caption=buyer_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Error sending offer update to buyer: {e}")

    except Exception as e:
        logger.error(f"process_seller_price failed for request {request_id}: {e}")
        await update.message.reply_text("❌ An error occurred submitting your offer. Please try again.")
        return SELLER_PRICE

    context.user_data.clear()
    return ConversationHandler.END