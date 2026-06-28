# handlers/buyer.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from database.session import db_transaction
from database.models import User, PurchaseRequest, Offer, Deal, SellerProfile, UserMetrics
from keyboards.buyer import get_buyer_home_keyboard
from config import ADMIN_TELEGRAM_ID
from utils.helpers import get_text, get_user_lang, flag_user_to_admin
from services.buyer_reliability_service import can_create_request

logger = logging.getLogger(__name__)

# Conversation States for creating a request
BUYER_IMAGE, BUYER_QUANTITY = range(2)

async def check_buyer_role(update: Update) -> User:
    """Helper to ensure the user is an active buyer."""
    tg_id = update.effective_user.id
    with db_transaction() as db:
        user = db.query(User).filter(User.telegram_id == tg_id, User.role == 'buyer', User.status.in_(['active', 'pending'])).first()
        # Detach from session so it can be used outside
        if user:
            db.expunge(user)
    return user

async def start_purchase_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await check_buyer_role(update)
    lang = get_user_lang(update.effective_user.id)
    if not user:
        return ConversationHandler.END

    can_create, message = can_create_request(user.id)
    if not can_create:
        await update.message.reply_text(message)
        if "Score too low" in message:
            await flag_user_to_admin(context, user, "Buyer score dropped to critical levels. Request creation blocked.")
        return ConversationHandler.END

    if not await check_buyer_limit(user.id):
        await update.message.reply_text("⚠️ You have reached the limit of 3 active requests. Please wait for current deals to close.")
        return ConversationHandler.END

    await update.message.reply_text(
        get_text(lang, "buyer_send_image"),
        reply_markup=ReplyKeyboardRemove()
    )
    return BUYER_IMAGE

async def check_buyer_limit(user_id: int) -> bool:
    with db_transaction() as db:
        active_count = db.query(PurchaseRequest).filter(
            PurchaseRequest.buyer_id == user_id,
            PurchaseRequest.status.in_(["REQUEST_OPEN", "DEAL_PENDING_ADMIN"])
        ).count()
    return active_count < 3

async def process_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file_id = update.message.photo[-1].file_id
    context.user_data['request_photo_id'] = photo_file_id
    lang = get_user_lang(update.effective_user.id)
    await update.message.reply_text(get_text(lang, "buyer_enter_qty"))
    return BUYER_QUANTITY

async def process_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quantity_text = update.message.text
    tg_id = update.effective_user.id
    lang = get_user_lang(tg_id)

    if not quantity_text.isdigit():
        await update.message.reply_text(get_text(lang, "buyer_invalid_qty"))
        return BUYER_QUANTITY

    quantity = int(quantity_text)

    try:
        # Atomic: save request AND increment metrics together
        request_id = None
        image_file_id = None
        buyer_name = None
        buyer_username = None
        buyer_phone = None
        buyer_tg_id = None

        with db_transaction() as db:
            buyer = db.query(User).filter(User.telegram_id == tg_id).first()

            new_request = PurchaseRequest(
                buyer_id=buyer.id,
                image_file_id=context.user_data['request_photo_id'],
                quantity=quantity,
                status='PENDING_ADMIN_APPROVAL'
            )
            db.add(new_request)
            db.flush()  # Get new_request.id without committing yet

            metrics = db.query(UserMetrics).filter(UserMetrics.user_id == buyer.id).first()
            if not metrics:
                metrics = UserMetrics(user_id=buyer.id)
                db.add(metrics)
            metrics.total_requests += 1

            # Capture values before session closes
            request_id = new_request.id
            image_file_id = new_request.image_file_id
            buyer_name = buyer.full_name
            buyer_username = buyer.username
            buyer_phone = buyer.phone
            buyer_tg_id = buyer.telegram_id

        # Telegram messages outside the transaction
        await update.message.reply_text(
            "✅ Your purchase request has been submitted and is pending Admin approval.",
            reply_markup=get_buyer_home_keyboard(lang)
        )
        try:
            admin_kb = [
            [InlineKeyboardButton("Approve & Broadcast ✅", callback_data=f"adm_req_app_{request_id}"),
             InlineKeyboardButton("Reject ❌", callback_data=f"adm_req_rej_{request_id}")]
            ]
            buyer_phone_str = f'<a href="tel:+{buyer_phone}">+{buyer_phone}</a>' if buyer_phone else 'N/A'
            admin_text = (
                f"🔔 *New Buyer Request Pending Approval*\n\n"
                f"👤 *Buyer:* {buyer_name}\n"
                f"• User Name: @{buyer_username or 'N/A'}\n"
                f"• Phone: {buyer_phone_str}\n"
                f"• ID: `{buyer_tg_id}`\n"
                f"📦 *Quantity:* {quantity}\n\n"
                f"Approve to broadcast this to all active sellers."
                )
            await context.bot.send_photo(
                chat_id=ADMIN_TELEGRAM_ID,
                photo=image_file_id,
                caption=admin_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(admin_kb)
            )

        except Exception as e:
            logger.error(f"Failed to notify admin for request {request_id}: {e}")
            await update.message.reply_text("⚠️ Request submitted, but failed to notify Admin. Please contact support or try again")

    except Exception as e:
        logger.error(f"process_quantity failed for user {tg_id}: {e}")
        await update.message.reply_text("❌ An error occurred submitting your request. Please try again.")
        return BUYER_QUANTITY

    context.user_data.clear()
    return ConversationHandler.END

async def cancel_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    lang = get_user_lang(tg_id)

    try:
        with db_transaction() as db:
            user = db.query(User).filter(User.telegram_id == tg_id).first()
            if user:
                metrics = db.query(UserMetrics).filter(UserMetrics.user_id == user.id).first()
                if metrics:
                    metrics.abandoned_requests += 1
    except Exception as e:
        logger.error(f"cancel_request metrics update failed: {e}")

    await update.message.reply_text(get_text(lang, "req_cancelled"), reply_markup=get_buyer_home_keyboard(lang))
    context.user_data.clear()
    return ConversationHandler.END

async def select_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    offer_id = int(query.data.replace("buy_sel_", ""))

    try:
        new_deal_id = None
        seller_tg_id = None
        seller_price = None
        req_id = None
        admin_data = {}

        with db_transaction() as db:
            selected_offer = db.query(Offer).filter(Offer.id == offer_id).first()
            if not selected_offer:
                await query.message.reply_text("❌ Offer not found.")
                return

            req = db.query(PurchaseRequest).filter(PurchaseRequest.id == selected_offer.request_id).first()
            if req.status == 'DEAL_PENDING_ADMIN':
                await query.message.reply_text("⚠️ You have already selected an offer for this request.")
                return

            # Atomic: update offer, request, all losing offers, and create deal
            selected_offer.status = 'SELECTED'
            req.status = 'DEAL_PENDING_ADMIN'
            db.query(Offer).filter(Offer.request_id == req.id, Offer.id != offer_id).update({"status": "LOST"})

            new_deal = Deal(
                request_id=req.id,
                offer_id=selected_offer.id,
                buyer_id=req.buyer_id,
                seller_id=selected_offer.seller_id,
                status='PENDING'
            )
            db.add(new_deal)
            db.flush()  # Get new_deal.id

            seller = db.query(User).filter(User.id == selected_offer.seller_id).first()
            buyer = db.query(User).filter(User.id == req.buyer_id).first()
            seller_profile = db.query(SellerProfile).filter(SellerProfile.user_id == seller.id).first()

            new_deal_id = new_deal.id
            seller_tg_id = seller.telegram_id
            seller_price = selected_offer.price
            req_id = req.id
            admin_data = {
                'req_id': req.id,
                'deal_id': new_deal.id,
                'price': selected_offer.price,
                'quantity': req.quantity,
                'image_file_id': req.image_file_id,
                'buyer_name': buyer.full_name or 'N/A',
                'buyer_username': buyer.username or 'N/A',
                'buyer_phone': buyer.phone,
                'buyer_tg_id': buyer.telegram_id,
                'seller_name': seller.full_name or 'N/A',
                'seller_username': seller.username or 'N/A',
                'seller_phone': seller.phone,
                'seller_tg_id': seller.telegram_id,
                'seller_db_id': seller.id,
                'shop_num': seller_profile.shop_number if seller_profile and seller_profile.shop_number else 'N/A',
            }

        # Telegram messages outside the transaction
        buyer_phone_str = f'<a href="tel:+{admin_data["buyer_phone"]}">+{admin_data["buyer_phone"]}</a>' if admin_data["buyer_phone"] else 'N/A'
        seller_phone_str = f'<a href="tel:+{admin_data["seller_phone"]}">+{admin_data["seller_phone"]}</a>' if admin_data["seller_phone"] else 'N/A'

        admin_text = (
            f"🤝 *Deal Selected - Action Required*\n\n"
            f"**Request ID:** #{admin_data['req_id']}\n"
            f"**Deal ID:** #{admin_data['deal_id']}\n"
            f"**Price:** {admin_data['price']} ETB\n"
            f"**Quantity:** {admin_data['quantity']}\n\n"
            f"👤 *Buyer Details*\n"
            f"• Full Name: {admin_data['buyer_name']}\n"
            f"• Username: @{admin_data['buyer_username']}\n"
            f"• Phone: {buyer_phone_str}\n"
            f"• Telegram ID: `{admin_data['buyer_tg_id']}`\n\n"
            f"🏭 *Seller Details*\n"
            f"• Full Name: {admin_data['seller_name']}\n"
            f"• Shop Number: {admin_data['shop_num']}\n"
            f"• Username: @{admin_data['seller_username']}\n"
            f"• Phone: {seller_phone_str}\n"
            f"• DB ID: `{admin_data['seller_db_id']}`\n"
            f"• Telegram ID: `{admin_data['seller_tg_id']}`"
        )
        admin_kb = [
            [InlineKeyboardButton("Mark Paid ✅", callback_data=f"adm_paid_{new_deal_id}"),
             InlineKeyboardButton("Cancel Deal ❌", callback_data=f"adm_can_{new_deal_id}")]
        ]
        await context.bot.send_photo(
            chat_id=ADMIN_TELEGRAM_ID,
            photo=admin_data['image_file_id'],
            caption=admin_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(admin_kb)
        )
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n✅ *You selected this offer! Sent to Admin for finalization.*",
            parse_mode="HTML"
        )
        await context.bot.send_message(
            chat_id=seller_tg_id,
            text=f"🎉 Excellent news! Your offer of {seller_price} ETB for Request #{req_id} was selected by the buyer. Admin finalization pending."
        )

    except Exception as e:
        logger.error(f"select_offer failed for offer {offer_id}: {e}")
        await query.message.reply_text("❌ An error occurred processing your offer selection.")

async def view_my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id

    try:
        with db_transaction() as db:
            buyer = db.query(User).filter(User.telegram_id == tg_id).first()
            if not buyer:
                return

            requests = db.query(PurchaseRequest).filter(
                PurchaseRequest.buyer_id == buyer.id,
                PurchaseRequest.status == 'REQUEST_OPEN'
            ).all()

            if not requests:
                await update.message.reply_text("📋 You have no active purchase requests at the moment.")
                return

            # Collect all data before session closes
            requests_data = []
            for req in requests:
                offers = db.query(Offer).filter(Offer.request_id == req.id).all()
                requests_data.append({
                    'id': req.id,
                    'quantity': req.quantity,
                    'created_at': req.created_at,
                    'image_file_id': req.image_file_id,
                    'offers': [{'id': o.id, 'price': o.price} for o in offers]
                })

    except Exception as e:
        logger.error(f"view_my_requests failed for user {tg_id}: {e}")
        await update.message.reply_text("❌ Error loading your requests.")
        return

    for req in requests_data:
        caption_text = (
            f"📦 *Request #{req['id']}*\n"
            f"🔢 *Quantity:* {req['quantity']}\n"
            f"📅 *Created:* {req['created_at'].strftime('%Y-%m-%d %H:%M')}\n\n"
        )
        if not req['offers']:
            caption_text += "⏳ No offers submitted by sellers yet."
            await update.message.reply_photo(
                photo=req['image_file_id'],
                caption=caption_text,
                parse_mode="HTML"
            )
        else:
            caption_text += "💰 *Received Offers (Anonymous):*\n"
            keyboard = []
            letters = ["A", "B", "C"]
            for idx, offer in enumerate(req['offers']):
                if idx >= len(letters):
                    break
                letter = letters[idx]
                caption_text += f"▪️ *Offer {letter}:* {offer['price']} ETB\n"
                keyboard.append([InlineKeyboardButton(f"Select Offer {letter} 🏷️", callback_data=f"byr_sel_{offer['id']}")])
            await update.message.reply_photo(
                photo=req['image_file_id'],
                caption=caption_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

async def handle_offer_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    offer_id = int(query.data.replace("byr_sel_", ""))

    try:
        new_deal_id = None
        admin_data = {}

        with db_transaction() as db:
            offer = db.query(Offer).filter(Offer.id == offer_id).first()
            if not offer or offer.status != 'OFFER_SUBMITTED':
                await query.message.reply_text("❌ This offer is no longer available.")
                return

            req = db.query(PurchaseRequest).filter(PurchaseRequest.id == offer.request_id).first()
            if not req or req.status != 'REQUEST_OPEN':
                await query.message.reply_text("❌ This request is already closed or processed.")
                return

            buyer_user = db.query(User).filter(User.id == req.buyer_id).first()
            seller_user = db.query(User).filter(User.id == offer.seller_id).first()
            seller_profile = db.query(SellerProfile).filter(SellerProfile.user_id == seller_user.id).first()

            # Atomic: update request, selected offer, mark losers, create deal
            req.status = 'DEAL_PENDING_ADMIN'
            offer.status = 'SELECTED'
            db.query(Offer).filter(Offer.request_id == req.id, Offer.id != offer.id).update({"status": "LOST"})

            new_deal = Deal(
                request_id=req.id,
                offer_id=offer.id,
                buyer_id=buyer_user.id,
                seller_id=seller_user.id,
                status='PENDING'
            )
            db.add(new_deal)
            db.flush()

            new_deal_id = new_deal.id
            admin_data = {
                'req_id': req.id,
                'deal_id': new_deal.id,
                'price': offer.price,
                'quantity': req.quantity,
                'image_file_id': req.image_file_id,
                'buyer_name': buyer_user.full_name or 'N/A',
                'buyer_username': buyer_user.username or 'N/A',
                'buyer_phone': buyer_user.phone,
                'buyer_tg_id': buyer_user.telegram_id,
                'seller_name': seller_user.full_name or 'N/A',
                'seller_username': seller_user.username or 'N/A',
                'seller_phone': seller_user.phone,
                'seller_tg_id': seller_user.telegram_id,
                'seller_db_id': seller_user.id,
                'shop_num': seller_profile.shop_number if seller_profile and seller_profile.shop_number else 'N/A',
            }

        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n✅ Offer selected! Awaiting admin finalization."
        )

        admin_kb = [
            [InlineKeyboardButton("Mark Paid 💵", callback_data=f"adm_dl_paid_{new_deal_id}")],
            [InlineKeyboardButton("Mark Delivered 🚚", callback_data=f"adm_dl_delv_{new_deal_id}")],
            [InlineKeyboardButton("Cancel Deal ❌", callback_data=f"adm_dl_canc_{new_deal_id}")]
        ]
        buyer_phone_str = f'<a href="tel:+{admin_data["buyer_phone"]}">+{admin_data["buyer_phone"]}</a>' if admin_data["buyer_phone"] else 'N/A'
        seller_phone_str = f'<a href="tel:+{admin_data["seller_phone"]}">+{admin_data["seller_phone"]}</a>' if admin_data["seller_phone"] else 'N/A'

        admin_text = (
            f"🤝 *Deal Selected For Verification*\n\n"
            f"📋 *Request:* #{admin_data['req_id']}\n"
            f"🆔 *Deal reference:* #{admin_data['deal_id']}\n"
            f"💰 *Final Price:* {admin_data['price']} ETB\n\n"
            f"👤 *Buyer Details*\n"
            f"• Full Name: {admin_data['buyer_name']}\n"
            f"• Username: @{admin_data['buyer_username']}\n"
            f"• Phone: {buyer_phone_str}\n"
            f"• Telegram ID: `{admin_data['buyer_tg_id']}`\n\n"
            f"🏭 *Seller Details*\n"
            f"• Full Name: {admin_data['seller_name']}\n"
            f"• Shop Number: {admin_data['shop_num']}\n"
            f"• Username: @{admin_data['seller_username']}\n"
            f"• Phone: {seller_phone_str}\n"
            f"• DB ID: `{admin_data['seller_db_id']}`\n"
            f"• Telegram ID: `{admin_data['seller_tg_id']}`"
        )
        await context.bot.send_message(
            chat_id=ADMIN_TELEGRAM_ID,
            text=admin_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(admin_kb)
        )

    except Exception as e:
        logger.error(f"handle_offer_selection failed for offer {offer_id}: {e}")
        await query.message.reply_text("❌ An error occurred processing your selection.")