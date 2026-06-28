# handlers/admin_requests.py
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.session import db_transaction
from database.models import PurchaseRequest, User, RequestAcceptance, Offer, RequestHistory
from services.pagination_service import paginate_query, build_pagination_keyboard

logger = logging.getLogger(__name__)

async def show_active_requests(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    try:
        with db_transaction() as db:
            query = db.query(PurchaseRequest).filter(
                PurchaseRequest.status.in_([
                    "PENDING_ADMIN_APPROVAL",
                    "REQUEST_OPEN",
                    "DEAL_PENDING_ADMIN"
                ])
            ).order_by(PurchaseRequest.created_at.desc())

            requests, total_pages, total_items = paginate_query(query, page, page_size=10)

            if not requests:
                text = "📭 *No active requests currently.*"
                reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="adm_menu_main")]])
                if update.callback_query:
                    await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
                else:
                    await update.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)
                return

            text = f"📦 *Active Requests Dashboard*\nPage {page + 1} of {total_pages} (Total: {total_items})\n\n"
            keyboard = []

            for req in requests:
                buyer = db.query(User).filter(User.id == req.buyer_id).first()
                buyer_name = buyer.full_name if buyer else "Unknown"
                accepted_count = db.query(RequestAcceptance).filter(RequestAcceptance.request_id == req.id).count()
                age_delta = datetime.utcnow() - req.created_at
                age_minutes = int(age_delta.total_seconds() / 60)

                text += (
                    f"**#{req.id}** | 👤 Buyer: {buyer_name}\n"
                    f"Status: `{req.status}`\n"
                    f"Accepted: {accepted_count}/3 | Age: {age_minutes} mins\n\n"
                )
                keyboard.append([
                    InlineKeyboardButton(f"👁 View #{req.id}", callback_data=f"adm_req_view_{req.id}"),
                    InlineKeyboardButton(f"❌ Cancel #{req.id}", callback_data=f"adm_req_canc_{req.id}"),
                    InlineKeyboardButton(f"⏰ Extend #{req.id}", callback_data=f"adm_req_ext_{req.id}")
                ])

    except Exception as e:
        logger.error(f"show_active_requests failed on page {page}: {e}")
        if update.callback_query:
            await update.callback_query.edit_message_text("❌ Error loading requests.")
        else:
            await update.message.reply_text("❌ Error loading requests.")
        return

    pagination_buttons = build_pagination_keyboard("adm_req_page", page, total_pages)
    if pagination_buttons:
        keyboard.extend(pagination_buttons)
    keyboard.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="adm_menu_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)


async def handle_requests_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "adm_menu_reqs":
        await query.answer()
        await show_active_requests(update, context, page=0)

    elif data.startswith("adm_req_page_"):
        await query.answer()
        page = int(data.split("_")[-1])
        await show_active_requests(update, context, page=page)

    elif data.startswith("adm_req_view_") or data.startswith("adm_req_canc_") or data.startswith("adm_req_ext_"):
        await handle_request_action_buttons(update, context, data)


async def handle_request_action_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    query = update.callback_query
    admin_id = update.effective_user.id

    parts = data.split("_")
    action = parts[2]  # 'view', 'canc', 'ext'
    req_id = int(parts[3])

    if action == "view":
        try:
            with db_transaction() as db:
                req = db.query(PurchaseRequest).filter(PurchaseRequest.id == req_id).first()
                if not req:
                    await query.answer("❌ Request not found.")
                    return
                buyer = db.query(User).filter(User.id == req.buyer_id).first()
                offers = db.query(Offer).filter(Offer.request_id == req.id).all()

                detail_text = (
                    f"🔍 *Request Details #{req.id}*\n"
                    f"👤 **Buyer:** {buyer.full_name} (@{buyer.username or 'N/A'})\n"
                    f"📦 **Quantity:** {req.quantity}\n"
                    f"⏱ **Status:** `{req.status}`\n"
                    f"📅 **Created:** {req.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"💰 *Submitted Offers:*\n"
                )
                if not offers:
                    detail_text += "No offers submitted yet."
                else:
                    for off in offers:
                        seller = db.query(User).filter(User.id == off.seller_id).first()
                        detail_text += f"• **{off.price} ETB** by {seller.full_name} (Status: {off.status})\n"

                image_id = req.image_file_id

            await query.message.reply_photo(photo=image_id, caption=detail_text, parse_mode="HTML")
            await query.answer()
        except Exception as e:
            logger.error(f"adm_req_view_ failed for req {req_id}: {e}")
            await query.answer("⚠️ Error loading request details.", show_alert=True)

    elif action == "canc":
        try:
            buyer_tg_id = None
            with db_transaction() as db:
                req = db.query(PurchaseRequest).filter(PurchaseRequest.id == req_id).first()
                admin_user = db.query(User).filter(User.telegram_id == admin_id).first()

                if not req:
                    await query.answer("❌ Request not found.")
                    return
                if req.status in ['CLOSED', 'CANCELLED', 'DELIVERED']:
                    await query.answer("⚠️ This request is already closed or cancelled.")
                    return

                req.status = 'CANCELLED'
                req.cancel_reason = "Cancelled by Admin via Dashboard"
                hist = RequestHistory(request_id=req.id, event="ADMIN_CANCELLED", performed_by=admin_user.id)
                db.add(hist)

                buyer = db.query(User).filter(User.id == req.buyer_id).first()
                buyer_tg_id = buyer.telegram_id if buyer else None

            if buyer_tg_id:
                try:
                    await context.bot.send_message(buyer_tg_id, f"❌ Your Request #{req_id} was cancelled by an Administrator.")
                except Exception:
                    pass
            await query.edit_message_text(f"{query.message.text}\n\n❌ *Request #{req_id} Cancelled.*", parse_mode="HTML")
        except Exception as e:
            logger.error(f"adm_req_canc_ failed for req {req_id}: {e}")
            await query.answer("⚠️ Database error. Please try again.", show_alert=True)

    elif action == "ext":
        try:
            with db_transaction() as db:
                admin_user = db.query(User).filter(User.telegram_id == admin_id).first()
                hist = RequestHistory(request_id=req_id, event="ADMIN_EXTENDED", performed_by=admin_user.id)
                db.add(hist)
            await query.answer(f"✅ Request #{req_id} lifespan extended.", show_alert=True)
        except Exception as e:
            logger.error(f"adm_req_ext_ failed for req {req_id}: {e}")
            await query.answer("⚠️ Database error. Please try again.", show_alert=True)