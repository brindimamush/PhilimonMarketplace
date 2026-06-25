# handlers/admin_users.py
from telegram import Update
from telegram.ext import ContextTypes
from database.session import SessionLocal
from database.models import User, UserMetrics
from keyboards.admin import get_user_profile_keyboard
from config import ADMIN_TELEGRAM_ID

async def search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: /user [telegram_id | @username | phone]")
        return

    search_term = context.args[0]
    db = SessionLocal()
    
    # Query logic
    query = db.query(User)
    if search_term.startswith('@'):
        user = query.filter(User.username == search_term.replace('@', '')).first()
    elif search_term.isdigit() and len(search_term) > 8: # Likely phone or TG ID
        user = query.filter((User.telegram_id == int(search_term)) | (User.phone.like(f"%{search_term}%"))).first()
    else:
        user = None

    if not user:
        await update.message.reply_text("❌ User not found.")
        db.close()
        return

    # Fetch Metrics
    metrics = db.query(UserMetrics).filter(UserMetrics.user_id == user.id).first()
    is_suspended = metrics.suspended if metrics else False
    
    status_icon = "⛔ Suspended" if is_suspended else ("✅ Active" if user.status == 'active' else "⏳ Pending")

    profile_text = (
        f"👤 *User Profile*\n\n"
        f"**Name:** {user.full_name}\n"
        f"**Username:** @{user.username or 'N/A'}\n"
        f"**Phone:** {user.phone or 'N/A'}\n"
        f"**Role:** {user.role.capitalize()}\n"
        f"**Status:** {status_icon}\n\n"
    )

    if metrics:
        if user.role == 'buyer':
            profile_text += f"🛒 *Buyer Stats*\nRequests: {metrics.total_requests} | Completed: {metrics.completed_purchases}\nScore: {metrics.buyer_score}\n"
        else:
            profile_text += f"🏭 *Seller Stats*\nAccepted: {metrics.accepted_requests} | Completed: {metrics.completed_sales}\nScore: {metrics.seller_score}\n"

    await update.message.reply_text(
        profile_text, 
        parse_mode="Markdown", 
        reply_markup=get_user_profile_keyboard(user.id, is_suspended)
    )
    db.close()