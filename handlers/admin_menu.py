# handlers/admin_menu.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import ADMIN_TELEGRAM_ID
from keyboards.admin import get_admin_main_keyboard
from database.session import db_transaction
from database.models import User, PurchaseRequest, Deal, UserMetrics

logger = logging.getLogger(__name__)

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return

    text = "🛠 <b>Admin Dashboard</b>\nSelect a module to manage the marketplace:"
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_admin_main_keyboard())

async def handle_main_menu_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "adm_menu_main":
        text = "🛠 <b>Admin Dashboard</b>\nSelect a module to manage the marketplace:"
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_admin_main_keyboard())

    elif data == "adm_menu_search":
        text = "🔍 <b>User Search Tool</b>\n\nTo look up a user profile, send the command manually:\n<code>/user @username</code>\n<code>/user telegram_id</code>"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_menu_main")]])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)

    elif data == "adm_menu_stats":
        try:
            with db_transaction() as db:
                total_buyers = db.query(User).filter(User.role == 'buyer').count()
                total_sellers = db.query(User).filter(User.role == 'seller').count()
                active_requests = db.query(PurchaseRequest).filter(PurchaseRequest.status == 'REQUEST_OPEN').count()
                completed_deals = db.query(Deal).filter(Deal.status == 'PAID').count()
                suspended_users = db.query(UserMetrics).filter(UserMetrics.suspended == True).count()

            stats_text = (
                f"📊 <b>Marketplace Analytics Overview</b>\n\n"
                f"👥 <b>Total Buyers:</b> {total_buyers}\n"
                f"🏭 <b>Total Sellers:</b> {total_sellers}\n"
                f"📦 <b>Active Requests:</b> {active_requests}\n"
                f"✅ <b>Completed Deals (Paid):</b> {completed_deals}\n"
                f"⛔ <b>Suspended Accounts:</b> {suspended_users}\n"
            )
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="adm_menu_main")]])
            await query.edit_message_text(stats_text, parse_mode="HTML", reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Error compiling statistics: {e}")
            await query.edit_message_text(
                "❌ Error loading statistics module.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_menu_main")]])
            )