# utils/helpers.py
from database.session import SessionLocal
from database.models import User
from locales.en import MESSAGES as EN_MESSAGES
from locales.am import MESSAGES as AM_MESSAGES

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