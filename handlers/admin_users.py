# handlers/admin_users.py
import html
from datetime import datetime
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.session import SessionLocal
from database.models import User, UserMetrics, AdminAction
from keyboards.admin import get_user_profile_keyboard
from config import ADMIN_TELEGRAM_ID
from services.pagination_service import paginate_query, build_pagination_keyboard

logger = logging.getLogger(__name__)

async def handle_user_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    admin_id = update.effective_user.id

    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.telegram_id == admin_id).first()
        if not admin_user:
            return

        parts = data.split("_")
        action_type = parts[1]  # 'suspend', 'unsuspend', 'ban', 'hist'
        target_user_id = int(parts[2])

        target_user = db.query(User).filter(User.id == target_user_id).first()
        metrics = db.query(UserMetrics).filter(UserMetrics.user_id == target_user_id).first()

        if not target_user:
            await query.message.reply_text("❌ User not found in database.")
            return
        if target_user.telegram_id == ADMIN_TELEGRAM_ID:
            await query.answer("⛔ You cannot take action on the admin account.", show_alert=True)
            return
        if action_type in ["suspend", "unsuspend", "ban"]:
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

            new_action = AdminAction(
                admin_id=admin_user.id,
                target_user_id=target_user_id,
                action=action_type.upper(),
                reason="Triggered via Admin Dashboard"
            )
            db.add(new_action)
            db.commit()

            new_keyboard = get_user_profile_keyboard(target_user_id, is_suspended=(action_type in ["suspend", "ban"]))
            
            try:
                if action_type == "suspend":
                    await context.bot.send_message(target_user.telegram_id, "⚠️ Your account has been suspended by an administrator.")
                elif action_type == "unsuspend":
                    await context.bot.send_message(target_user.telegram_id, "✅ Your account has been reactivated. Welcome back!")
            except Exception:
                pass 
            
            timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')

            confirmation_text = (
                f"{status_text} <b>Admin Action Executed</b>\n\n"
                f"👤 <b>Target User:</b> {html.escape(target_user.full_name or 'N/A')}\n"
                f"🆔 <b>Telegram ID:</b> <code>{target_user.telegram_id}</code>\n"
                f"🏷 <b>Role:</b> {target_user.role.capitalize()}\n"
                f"🛠 <b>Action Taken:</b> {status_text}\n"
                f"🕒 <b>Time:</b> {timestamp}\n\n"
                f"<i>Note: The user has been notified of this status change.</i>"
                )

            await query.edit_message_text(
                text=confirmation_text,
                reply_markup=new_keyboard,
                parse_mode="HTML"
            )

        elif action_type == "hist":
            actions = db.query(AdminAction).filter(AdminAction.target_user_id == target_user_id).order_by(AdminAction.created_at.desc()).limit(5).all()
            if not actions:
                await query.message.reply_text("📜 No administrative history found for this user.")
            else:
                hist_text = f"📜 <b>Recent History for {html.escape(target_user.full_name or 'N/A')}</b>\n\n"
                for act in actions:
                    hist_text += f"• <code>{act.created_at.strftime('%Y-%m-%d %H:%M')}</code> - <b>{act.action}</b>\n"
                await query.message.reply_text(hist_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error handling user actions: {e}")
    finally:
        db.close()

async def search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: /user [telegram_id | @username]")
        return

    search_term = context.args[0]
    db = SessionLocal()
    
    try:
        query = db.query(User)
        if search_term.startswith('@'):
            user = query.filter(User.username == search_term.replace('@', '')).first()
        elif search_term.isdigit():
            user = query.filter(User.telegram_id == int(search_term)).first()
        else:
            user = None

        if not user:
            await update.message.reply_text("❌ User not found.")
            return

        metrics = db.query(UserMetrics).filter(UserMetrics.user_id == user.id).first()
        is_suspended = metrics.suspended if metrics else False
        status_icon = "⛔ Suspended" if is_suspended else ("✅ Active" if user.status == 'active' else "⏳ Pending")

        profile_text = (
            f"👤 <b>User Profile</b>\n\n"
            f"<b>Name:</b> {html.escape(user.full_name or 'N/A')}\n"
            f"<b>Username:</b> @{html.escape(user.username or 'N/A')}\n"
            f"<b>Phone:</b> +{html.escape(user.phone or 'N/A')}\n"
            f"<b>Role:</b> {user.role.capitalize()}\n"
            f"<b>Status:</b> {status_icon}\n\n"
        )

        if metrics:
            if user.role == 'buyer':
                profile_text += f"🛒 <b>Buyer Stats</b>\nRequests: {metrics.total_requests} | Completed: {metrics.completed_purchases}\nScore: {metrics.buyer_score}\n"
            else:
                profile_text += f"🏭 <b>Seller Stats</b>\nAccepted: {metrics.accepted_requests} | Completed: {metrics.completed_sales}\nScore: {metrics.seller_score}\n"

        await update.message.reply_text(
            profile_text, 
            parse_mode="HTML", 
            reply_markup=get_user_profile_keyboard(user.id, is_suspended)
        )
    except Exception as e:
        logger.error(f"Error during search profile yield: {e}")
    finally:
        db.close()

async def show_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    db = SessionLocal()
    try:
        query = db.query(User).order_by(User.created_at.desc())
        users, total_pages, total_items = paginate_query(query, page, page_size=10)
        
        if not users:
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_menu_main")]])
            await update.callback_query.edit_message_text("📭 <b>No users found.</b>", parse_mode="HTML", reply_markup=reply_markup)
            return

        text = f"👥 <b>User Directory</b>\nPage {page + 1} of {total_pages} (Total: {total_items})\n\n"
        for u in users:
            status_emoji = "✅" if u.status == "active" else ("⏳" if u.status == "pending" else "⛔")
            text += f"{status_emoji} <b>{html.escape(u.full_name or 'N/A')}</b> (<code>{u.telegram_id}</code>)\nRole: {u.role.capitalize()} | @{html.escape(u.username or 'N/A')}\n\n"

        keyboard = build_pagination_keyboard("adm_usr_page", page, total_pages)
        keyboard.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="adm_menu_main")])
        
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error displaying user catalog list: {e}")
    finally:
        db.close()

async def show_suspended_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """Completely covers the previously broken suspended list dashboard entry."""
    db = SessionLocal()
    try:
        query = db.query(User).join(UserMetrics).filter(UserMetrics.suspended == True).order_by(User.created_at.desc())
        suspended_users, total_pages, total_items = paginate_query(query, page, page_size=10)
        
        if not suspended_users:
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_menu_main")]])
            await update.callback_query.edit_message_text("📭 <b>No suspended accounts currently match filters.</b>", parse_mode="HTML", reply_markup=reply_markup)
            return

        text = f"⛔ <b>Suspended Accounts Blacklist</b>\nPage {page + 1} of {total_pages} (Total: {total_items})\n\n"
        for u in suspended_users:
            text += f"❌ <b>{html.escape(u.full_name or 'N/A')}</b> (<code>{u.telegram_id}</code>)\nRole: {u.role.capitalize()} | @{html.escape(u.username or 'N/A')}\n\n"

        keyboard = build_pagination_keyboard("adm_susp_page", page, total_pages)
        keyboard.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="adm_menu_main")])
        
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error handling suspended checklist rendering: {e}")
    finally:
        db.close()