# utils/helpers.py
from database.session import SessionLocal
from database.models import User
from locales.en import MESSAGES as EN_MESSAGES
from locales.am import MESSAGES as AM_MESSAGES

import html
from telegram.ext import ContextTypes
from config import ADMIN_TELEGRAM_ID

async def flag_user_to_admin(context: ContextTypes.DEFAULT_TYPE, user, reason: str):
    flag_text = (
        f"🚩 <b>Account Flagged for Review</b>\n\n"
        f"👤 <b>User:</b> {html.escape(user.full_name or 'N/A')}\n"
        f"🆔 <b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
        f"🏷 <b>Role:</b> {user.role.capitalize()}\n\n"
        f"<b>Reason:</b> {reason}\n\n"
        f"To investigate, use:\n<code>/user {user.telegram_id}</code>"
    )
    
    try:
        await context.bot.send_message(
            chat_id=ADMIN_TELEGRAM_ID, 
            text=flag_text, 
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Failed to send admin flag alert: {e}")

def get_user_lang(telegram_id: int) -> str:
    """Safely retrieves the user's language setting from the database."""
    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    lang = user.language if user else "en"
    db.close()
    return lang

def get_text(lang: str, key: str) -> str:
    """Retrieves the translated text for a given key."""
    if lang == 'am':
        return AM_MESSAGES.get(key, EN_MESSAGES.get(key, key))
    return EN_MESSAGES.get(key, key)