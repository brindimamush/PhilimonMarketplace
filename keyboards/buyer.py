# keyboards/buyer.py
from telegram import ReplyKeyboardMarkup

def get_buyer_home_keyboard():
    keyboard = [
        ["➕ New Request"],
        [ "🔄 Switch Mode"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)