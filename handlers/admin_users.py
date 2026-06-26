# handlers/admin_users.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.session import SessionLocal
from database.models import User, UserMetrics, AdminAction, UserMetrics
from keyboards.admin import get_user_profile_keyboard
from config import ADMIN_TELEGRAM_ID
from services.pagination_service import paginate_query, build_pagination_keyboard

async def handle_user_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    admin_id = update.effective_user.id

    db = SessionLocal()
    admin_user = db.query(User).filter(User.telegram_id == admin_id).first()
    
    if not admin_user:
        db.close()
        return

    # Extract user ID and action
    parts = data.split("_")
    action_type = parts[1]  # 'suspend', 'unsuspend', 'ban', 'hist'
    target_user_id = int(parts[2])

    target_user = db.query(User).filter(User.id == target_user_id).first()
    metrics = db.query(UserMetrics).filter(UserMetrics.user_id == target_user_id).first()

    if not target_user:
        await query.message.reply_text("❌ User not found in database.")
        db.close()
        return

    if action_type in ["suspend", "unsuspend", "ban"]:
        # 1. Update User Status
        if action_type == "suspend":
            if metrics: metrics.suspended = True
            target_user.status = 'suspended'
            status_text = "⛔ Suspended"
            
        elif action_type == "unsuspend":
            if metrics: metrics.suspended = False
            target_user.status = 'active'
            status_text = "✅ Active"
            
        elif action_type == "ban":
            if metrics: metrics.suspended = True
            target_user.status = 'banned'
            status_text = "🚫 Banned"

        # 2. Log to AdminAction (Phase 5)
        new_action = AdminAction(
            admin_id=admin_user.id,
            target_user_id=target_user_id,
            action=action_type.upper(),
            reason="Triggered via Admin Dashboard"
        )
        db.add(new_action)
        db.commit()

        # 3. Update the UI
        new_keyboard = get_user_profile_keyboard(target_user_id, is_suspended=(action_type in ["suspend", "ban"]))
        
        # Notify the target user (optional but recommended)
        try:
            if action_type == "suspend":
                await context.bot.send_message(target_user.telegram_id, "⚠️ Your account has been suspended by an administrator. You can no longer place or accept requests.")
            elif action_type == "unsuspend":
                await context.bot.send_message(target_user.telegram_id, "✅ Your account has been reactivated. Welcome back!")
        except Exception:
            pass # User might have blocked the bot

        await query.edit_message_text(
            f"{query.message.text}\n\n*Update:* User marked as {status_text}.", 
            reply_markup=new_keyboard,
            parse_mode="Markdown"
        )

    elif action_type == "hist":
        # Phase 5: View History
        actions = db.query(AdminAction).filter(AdminAction.target_user_id == target_user_id).order_by(AdminAction.created_at.desc()).limit(5).all()
        
        if not actions:
            await query.message.reply_text("📜 No administrative history found for this user.")
        else:
            hist_text = f"📜 *Recent History for {target_user.full_name}*\n\n"
            for act in actions:
                hist_text += f"• `{act.created_at.strftime('%Y-%m-%d %H:%M')}` - **{act.action}**\n"
            
            await query.message.reply_text(hist_text, parse_mode="Markdown")

    db.close()

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

async def show_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    db = SessionLocal()
    # Order by newest first
    query = db.query(User).order_by(User.created_at.desc())
    
    users, total_pages, total_items = paginate_query(query, page, page_size=10)
    
    if not users:
        text = "📭 *No users found.*"
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_menu_main")]])
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
        db.close()
        return

    text = f"👥 *User Directory*\nPage {page + 1} of {total_pages} (Total: {total_items})\n\n"
    for u in users:
        # Visual indicators for status
        status_emoji = "✅" if u.status == "active" else ("⏳" if u.status == "pending" else "⛔")
        text += f"{status_emoji} **{u.full_name}** (`{u.telegram_id}`)\nRole: {u.role.capitalize()} | @{u.username or 'N/A'}\n\n"

    # Build pagination and add the Back button
    keyboard = build_pagination_keyboard("adm_usr_page", page, total_pages)
    keyboard.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="adm_menu_main")])
    
    await update.callback_query.edit_message_text(
        text, 
        parse_mode="Markdown", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    db.close()