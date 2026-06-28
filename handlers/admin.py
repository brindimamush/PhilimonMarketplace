# handlers/admin.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import asyncio
import html
import logging
from services.broadcast_service import safe_broadcast_to_sellers
from utils.helpers import get_text
from database.session import db_transaction
from database.models import User, Deal, PurchaseRequest, UserMetrics
from keyboards.seller import get_seller_home_keyboard
from config import ADMIN_TELEGRAM_ID

logger = logging.getLogger(__name__)

async def handle_admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("adm_app_"):
        user_id = int(data.replace("adm_app_", ""))
        try:
            with db_transaction() as db:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    user.status = 'active'
                    user.role = 'seller'
                    lang = user.language
                    tg_id = user.telegram_id
                else:
                    lang = None
                    tg_id = None
            if tg_id:
                await query.edit_message_text(text=f"{query.message.text}\n\n✅ Approved!")
                notification_text = get_text(lang, "seller_approved_mode_switched")
                await context.bot.send_message(
                    chat_id=tg_id,
                    text=notification_text,
                    reply_markup=get_seller_home_keyboard(lang)
                )
        except Exception as e:
            logger.error(f"adm_app_ failed for user {user_id}: {e}")
            await query.answer("⚠️ Database error. Please try again.", show_alert=True)

    elif data.startswith("adm_rej_"):
        user_id = int(data.replace("adm_rej_", ""))
        try:
            with db_transaction() as db:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    user.status = 'rejected'
                    tg_id = user.telegram_id
                else:
                    tg_id = None
            if tg_id:
                await query.edit_message_text(text=f"{query.message.text}\n\n❌ Rejected.")
                await context.bot.send_message(
                    chat_id=tg_id,
                    text="❌ Your seller profile application was rejected by the admin.\n Please apply with a correct information using /start"
                )
        except Exception as e:
            logger.error(f"adm_rej_ failed for user {user_id}: {e}")
            await query.answer("⚠️ Database error. Please try again.", show_alert=True)

    elif data.startswith("adm_req_app_"):
        req_id = int(data.replace("adm_req_app_", ""))
        try:
            req_data = {}
            with db_transaction() as db:
                req = db.query(PurchaseRequest).filter(PurchaseRequest.id == req_id).first()
                if req and req.status == 'PENDING_ADMIN_APPROVAL':
                    req.status = 'REQUEST_OPEN'
                    req_data = {
                        'id': req.id,
                        'quantity': req.quantity,
                        'image_file_id': req.image_file_id,
                        'buyer_id': req.buyer_id,
                    }
            if req_data:
                await query.edit_message_caption(
                    caption=f"{query.message.caption}\n\n✅ *Approved & Broadcasted to Sellers!*",
                    parse_mode="HTML"
                )
                with db_transaction() as db:
                    buyer = db.query(User).filter(User.id == req_data['buyer_id']).first()
                    buyer_tg_id = buyer.telegram_id if buyer else None
                    active_sellers = db.query(User).filter(User.role == 'seller', User.status == 'active').all()
                    seller_ids = [s.telegram_id for s in active_sellers]

                if buyer_tg_id:
                    await context.bot.send_message(
                        chat_id=buyer_tg_id,
                        text=f"✅ Good news! Your request #{req_data['id']} for {req_data['quantity']} items was approved and is now being broadcasted to sellers."
                    )
                seller_kb = [[InlineKeyboardButton("Accept 🤝", callback_data=f"sel_acc_{req_data['id']}")]]
                broadcast_text = (
                    f"🔔 *New Buyer Request!*\n\n"
                    f"📦 *Quantity:* {req_data['quantity']}\n\n"
                    f"Click 'Accept' below if you want to submit an offer. Only the first 3 sellers can participate!"
                )
                asyncio.create_task(
                    safe_broadcast_to_sellers(
                        context=context,
                        photo_id=req_data['image_file_id'],
                        caption=broadcast_text,
                        reply_markup=InlineKeyboardMarkup(seller_kb)
                    )
                )
        except Exception as e:
            logger.error(f"adm_req_app_ failed for req {req_id}: {e}")
            await query.answer("⚠️ Database error. Please try again.", show_alert=True)

    elif data.startswith("adm_req_rej_"):
        req_id = int(data.replace("adm_req_rej_", ""))
        try:
            buyer_tg_id = None
            req_display_id = req_id
            with db_transaction() as db:
                req = db.query(PurchaseRequest).filter(PurchaseRequest.id == req_id).first()
                if req and req.status == 'PENDING_ADMIN_APPROVAL':
                    req.status = 'REJECTED'
                    req_display_id = req.id
                    buyer = db.query(User).filter(User.id == req.buyer_id).first()
                    buyer_tg_id = buyer.telegram_id if buyer else None
            if buyer_tg_id:
                await query.edit_message_caption(
                    caption=f"{query.message.caption}\n\n❌ *Request Rejected.*",
                    parse_mode="HTML"
                )
                await context.bot.send_message(
                    chat_id=buyer_tg_id,
                    text=f"❌ Your request #{req_display_id} was reviewed and rejected by the administrator."
                )
        except Exception as e:
            logger.error(f"adm_req_rej_ failed for req {req_id}: {e}")
            await query.answer("⚠️ Database error. Please try again.", show_alert=True)

    elif data.startswith("adm_paid_"):
        deal_id = int(data.replace("adm_paid_", ""))
        try:
            buyer_tg_id = None
            seller_tg_id = None
            with db_transaction() as db:
                deal = db.query(Deal).filter(Deal.id == deal_id).first()
                if deal and deal.status == 'PENDING':
                    req = db.query(PurchaseRequest).filter(PurchaseRequest.id == deal.request_id).first()
                    # Both mutations in one transaction — atomic
                    deal.status = 'PAID'
                    if req:
                        req.status = 'CLOSED'
                    buyer = db.query(User).filter(User.id == deal.buyer_id).first()
                    seller = db.query(User).filter(User.id == deal.seller_id).first()
                    buyer_tg_id = buyer.telegram_id if buyer else None
                    seller_tg_id = seller.telegram_id if seller else None
            if buyer_tg_id:
                await query.edit_message_caption(
                    caption=f"{query.message.caption}\n\n🟢 *Deal Completed: Marked Paid!*",
                    parse_mode="HTML"
                )
                await context.bot.send_message(chat_id=buyer_tg_id, text=f"✅ Admin marked Deal #{deal_id} as PAID. Arrangement finalized!")
                await context.bot.send_message(chat_id=seller_tg_id, text=f"💰 Admin confirmed payment for Deal #{deal_id}. Proceed with shipment/delivery tracking!")
        except Exception as e:
            logger.error(f"adm_paid_ failed for deal {deal_id}: {e}")
            await query.answer("⚠️ Database error. Please try again.", show_alert=True)

    elif data.startswith("adm_can_"):
        deal_id = int(data.replace("adm_can_", ""))
        try:
            buyer_tg_id = None
            seller_tg_id = None
            with db_transaction() as db:
                deal = db.query(Deal).filter(Deal.id == deal_id).first()
                if deal and deal.status == 'PENDING':
                    req = db.query(PurchaseRequest).filter(PurchaseRequest.id == deal.request_id).first()
                    # Both mutations in one transaction — atomic
                    deal.status = 'CANCELLED'
                    if req:
                        req.status = 'REQUEST_OPEN'  # Reset so sellers can bid again
                    buyer = db.query(User).filter(User.id == deal.buyer_id).first()
                    seller = db.query(User).filter(User.id == deal.seller_id).first()
                    buyer_tg_id = buyer.telegram_id if buyer else None
                    seller_tg_id = seller.telegram_id if seller else None
            if buyer_tg_id:
                await query.edit_message_caption(
                    caption=f"{query.message.caption}\n\n🔴 *Deal Cancelled by Admin.*",
                    parse_mode="HTML"
                )
                await context.bot.send_message(chat_id=buyer_tg_id, text=f"❌ Admin has cancelled Deal #{deal_id}. Your request is reopened.")
                await context.bot.send_message(chat_id=seller_tg_id, text=f"⚠️ Deal #{deal_id} has been cancelled by the administrator.")
        except Exception as e:
            logger.error(f"adm_can_ failed for deal {deal_id}: {e}")
            await query.answer("⚠️ Database error. Please try again.", show_alert=True)


async def handle_admin_deal_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("adm_dl_paid_"):
        deal_id = int(data.replace("adm_dl_paid_", ""))
        try:
            buyer_tg_id = None
            seller_tg_id = None
            with db_transaction() as db:
                deal = db.query(Deal).filter(Deal.id == deal_id).first()
                if deal:
                    deal.status = 'PAID'
                    buyer = db.query(User).filter(User.id == deal.buyer_id).first()
                    seller = db.query(User).filter(User.id == deal.seller_id).first()
                    buyer_tg_id = buyer.telegram_id if buyer else None
                    seller_tg_id = seller.telegram_id if seller else None
            if buyer_tg_id:
                await query.edit_message_text(text=f"{query.message.text}\n\n💵 *Status Update:* Marked as PAID!")
                await context.bot.send_message(chat_id=buyer_tg_id, text=f"💵 Admin confirmed payment receipt for Deal #{deal_id}.")
                await context.bot.send_message(chat_id=seller_tg_id, text=f"💵 Admin confirmed payment receipt for Deal #{deal_id}. Proceed to delivery.")
        except Exception as e:
            logger.error(f"adm_dl_paid_ failed for deal {deal_id}: {e}")
            await query.answer("⚠️ Database error. Please try again.", show_alert=True)

    elif data.startswith("adm_dl_delv_"):
        deal_id = int(data.replace("adm_dl_delv_", ""))
        try:
            buyer_tg_id = None
            seller_tg_id = None
            buyer_name = 'Unknown'
            seller_name = 'Unknown'
            buyer_db_id = None
            seller_db_id = None
            with db_transaction() as db:
                deal = db.query(Deal).filter(Deal.id == deal_id).first()
                if deal:
                    req = db.query(PurchaseRequest).filter(PurchaseRequest.id == deal.request_id).first()
                    buyer_metrics = db.query(UserMetrics).filter(UserMetrics.user_id == deal.buyer_id).first()
                    seller_metrics = db.query(UserMetrics).filter(UserMetrics.user_id == deal.seller_id).first()
                    buyer = db.query(User).filter(User.id == deal.buyer_id).first()
                    seller = db.query(User).filter(User.id == deal.seller_id).first()

                    # All 4 mutations in one transaction — fully atomic
                    deal.status = 'DELIVERED'
                    if req:
                        req.status = 'CLOSED'
                    if buyer_metrics:
                        buyer_metrics.completed_purchases += 1
                    if seller_metrics:
                        seller_metrics.completed_sales += 1

                    buyer_tg_id = buyer.telegram_id if buyer else None
                    seller_tg_id = seller.telegram_id if seller else None
                    buyer_name = html.escape(buyer.full_name or 'N/A') if buyer else 'Unknown'
                    seller_name = html.escape(seller.full_name or 'N/A') if seller else 'Unknown'
                    buyer_db_id = deal.buyer_id
                    seller_db_id = deal.seller_id

            if buyer_tg_id:
                success_text = (
                    f"✅ <b>Deal Successfully Closed</b>\n\n"
                    f"<b>Deal ID:</b> <code>#{deal_id}</code>\n"
                    f"💰 <b>Status:</b> PAID & DELIVERED\n\n"
                    f"<b>Participants:</b>\n"
                    f"🛒 Buyer: {buyer_name} (<code>{buyer_db_id}</code>)\n"
                    f"🏭 Seller: {seller_name} (<code>{seller_db_id}</code>)\n\n"
                    f"<i>Automated metrics have been updated for both parties.</i>"
                )
                await query.edit_message_text(text=success_text, parse_mode="HTML")
                await context.bot.send_message(chat_id=buyer_tg_id, text=f"🎉 Deal #{deal_id} has been fully marked as Delivered! Thank you.")
                await context.bot.send_message(chat_id=seller_tg_id, text=f"🎉 Deal #{deal_id} has been fully marked as Delivered! Lifecycle closed.")
        except Exception as e:
            logger.error(f"adm_dl_delv_ failed for deal {deal_id}: {e}")
            await query.answer("⚠️ Database error. Please try again.", show_alert=True)

    elif data.startswith("adm_dl_canc_"):
        deal_id = int(data.replace("adm_dl_canc_", ""))
        try:
            buyer_tg_id = None
            seller_tg_id = None
            with db_transaction() as db:
                deal = db.query(Deal).filter(Deal.id == deal_id).first()
                if deal:
                    req = db.query(PurchaseRequest).filter(PurchaseRequest.id == deal.request_id).first()
                    buyer = db.query(User).filter(User.id == deal.buyer_id).first()
                    seller = db.query(User).filter(User.id == deal.seller_id).first()
                    # Both mutations in one transaction — atomic
                    deal.status = 'CANCELLED'
                    if req:
                        req.status = 'CLOSED'
                    buyer_tg_id = buyer.telegram_id if buyer else None
                    seller_tg_id = seller.telegram_id if seller else None
            if buyer_tg_id:
                await query.edit_message_text(text=f"{query.message.text}\n\n❌ *Status Update:* Deal Cancelled.")
                await context.bot.send_message(chat_id=buyer_tg_id, text=f"❌ Admin has cancelled Deal #{deal_id}.")
                await context.bot.send_message(chat_id=seller_tg_id, text=f"❌ Admin has cancelled Deal #{deal_id}.")
        except Exception as e:
            logger.error(f"adm_dl_canc_ failed for deal {deal_id}: {e}")
            await query.answer("⚠️ Database error. Please try again.", show_alert=True)


async def admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return

    try:
        with db_transaction() as db:
            total_buyers = db.query(User).filter(User.role == 'buyer').count()
            total_sellers = db.query(User).filter(User.role == 'seller').count()
            active_requests = db.query(PurchaseRequest).filter(PurchaseRequest.status == 'REQUEST_OPEN').count()
            completed_deals = db.query(Deal).filter(Deal.status == 'PAID').count()
            suspended_users = db.query(UserMetrics).filter(UserMetrics.suspended == True).count()
    except Exception as e:
        logger.error(f"admin_dashboard query failed: {e}")
        await update.message.reply_text("❌ Error loading dashboard stats.")
        return

    stats_text = (
        f"📊 *Marketplace Analytics*\n\n"
        f"👥 *Buyers:* {total_buyers}\n"
        f"🏭 *Sellers:* {total_sellers}\n"
        f"📦 *Active Requests:* {active_requests}\n"
        f"✅ *Completed Deals:* {completed_deals}\n"
        f"⛔ *Suspended Users:* {suspended_users}\n"
    )

    await update.message.reply_text(stats_text, parse_mode="HTML")