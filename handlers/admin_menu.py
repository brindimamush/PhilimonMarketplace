# handlers/admin_menu.py
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_TELEGRAM_ID
from keyboards.admin import get_admin_main_keyboard

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return
        
    text = "🛠 *Admin Dashboard*\nSelect a module to manage the marketplace:"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_admin_main_keyboard())