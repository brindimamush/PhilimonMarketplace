# keyboards/seller.py
from telegram import ReplyKeyboardMarkup

def get_seller_home_keyboard():
    keyboard = [
        [ "💰 My Offers"],
        [ "🔄 Switch Mode"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)