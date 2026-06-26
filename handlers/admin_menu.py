# handlers/admin_menu.py
from telegram import Update
from handlers.admin import admin_dashboard
from telegram.ext import ContextTypes
from config import ADMIN_TELEGRAM_ID
from keyboards.admin import get_admin_main_keyboard

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return
        
    text = "🛠 *Admin Dashboard*\nSelect a module to manage the marketplace:"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_admin_main_keyboard())

async def handle_main_menu_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "adm_menu_main":
        text = "🛠 *Admin Dashboard*\nSelect a module to manage the marketplace:"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=get_admin_main_keyboard())
        
    elif data == "adm_menu_search":
        await query.message.reply_text("🔍 To search for a user, type: `/user @username` or `/user 123456789`", parse_mode="Markdown")
        
    elif data == "adm_menu_stats":
        # Reuse your existing /dashboard command logic!
        class FakeUpdate:
            effective_user = update.effective_user
            message = query.message
        await admin_dashboard(FakeUpdate, context)