# keyboards/seller.py
from telegram import ReplyKeyboardMarkup
from utils.helpers import get_text

def get_seller_home_keyboard(lang: str = "en"):
    keyboard = [
        
        [get_text(lang, "language_btn"), get_text(lang, "switch_mode")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)