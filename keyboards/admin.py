# keyboards/admin.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_admin_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("👥 Users", callback_data="adm_menu_users"),
         InlineKeyboardButton("📦 Requests", callback_data="adm_menu_reqs")],
        [InlineKeyboardButton("🤝 Deals", callback_data="adm_menu_deals"),
         InlineKeyboardButton("📊 Statistics", callback_data="adm_menu_stats")],
        [InlineKeyboardButton("⛔ Suspended", callback_data="adm_menu_susp"),
         InlineKeyboardButton("🔍 Search", callback_data="adm_menu_search")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_user_profile_keyboard(user_id: int, is_suspended: bool):
    susp_btn = InlineKeyboardButton("✅ Unsuspend", callback_data=f"adm_unsuspend_{user_id}") if is_suspended else InlineKeyboardButton("⛔ Suspend", callback_data=f"adm_suspend_{user_id}")
    keyboard = [
        [susp_btn],
        [InlineKeyboardButton("📜 History", callback_data=f"adm_hist_{user_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)