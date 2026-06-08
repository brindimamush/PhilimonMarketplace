# keyboards/buyer.py
from telegram import ReplyKeyboardMarkup
from utils.helpers import get_text

def get_buyer_home_keyboard(lang: str = "en"):
    keyboard = [
        [get_text(lang, "new_request")],
        [get_text(lang, "language_btn"), get_text(lang, "switch_mode")]
    ]
    # is_persistent=True ensures the keyboard stays attached to the input field
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)