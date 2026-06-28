# handlers/admin_users.py
import html
from datetime import datetime
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.session import db_transaction
from database.models import User, UserMetrics, AdminAction, SellerProfile
from keyboards.admin import get_user_profile_keyboard
from config import ADMIN_TELEGRAM_ID
from services.pagination_service import paginate_query, build_pagination_keyboard

logger = logging.getLogger(__name__)

async def handle_user_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    admin_id = update.effective_user.id

    try:
        parts = data.split("_")
        action_type = parts[1]  # 'suspend', 'unsuspend', 'hist'
        target_user_id = int(parts[2])

        if action_type in ["suspend", "unsuspend"]:
            target_tg_id = None
            target_name = None
            target_role = None
            target_status = None

            with db_transaction() as db:
                admin_user = db.query(User).filter(User.telegram_id == admin_id).first()
                if not admin_user:
                    return

                target_user = db.query(User).filter(User.id == target_user_id).first()
                metrics = db.query(UserMetrics).filter(UserMetrics.user_id == target_user_id).first()

                if not target_user:
                    await query.message.reply_text("❌ User not found in database.")
                    return
                if target_user.telegram_id == ADMIN_TELEGRAM_ID:
                    await query.answer("⛔ You cannot take action on the admin account.", show_alert=True)
                    return

                if action_type == "suspend":
                    if metrics:
                        metrics.suspended = True
                    target_user.status = 'suspended'
                    status_text = "⛔ Suspended"
                else:
                    if metrics:
                        metrics.suspended = False
                    target_user.status = 'active'
                    status_text = "✅ Active"

                new_action = AdminAction(
                    admin_id=admin_user.id,
                    target_user_id=target_user_id,
                    action=action_type.upper(),
                    reason="Triggered via Admin Dashboard"
                )
                db.add(new_action)

                target_tg_id = target_user.telegram_id
                target_name = target_user.full_name
                target_role = target_user.role

            # Telegram notifications outside the transaction
            try:
                if action_type == "suspend":
                    await context.bot.send_message(target_tg_id, "⚠️ Your account has been suspended by an administrator.")
                else:
                    await context.bot.send_message(target_tg_id, "✅ Your account has been reactivated. Welcome back!")
            except Exception:
                pass

            new_keyboard = get_user_profile_keyboard(target_user_id, is_suspended=(action_type == "suspend"))
            timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
            confirmation_text = (
                f"{status_text} <b>Admin Action Executed</b>\n\n"
                f"👤 <b>Target User:</b> {html.escape(target_name or 'N/A')}\n"
                f"🆔 <b>Telegram ID:</b> <code>{target_tg_id}</code>\n"
                f"🏷 <b>Role:</b> {target_role.capitalize()}\n"
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
            with db_transaction() as db:
                target_user = db.query(User).filter(User.id == target_user_id).first()
                actions = db.query(AdminAction).filter(
                    AdminAction.target_user_id == target_user_id
                ).order_by(AdminAction.created_at.desc()).limit(5).all()

                if not actions:
                    await query.message.reply_text("📜 No administrative history found for this user.")
                else:
                    hist_text = f"📜 <b>Recent History for {html.escape(target_user.full_name or 'N/A')}</b>\n\n"
                    for act in actions:
                        hist_text += f"• <code>{act.created_at.strftime('%Y-%m-%d %H:%M')}</code> - <b>{act.action}</b>\n"
                    await query.message.reply_text(hist_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error handling user actions: {e}")
        await query.answer("⚠️ Database error. Please try again.", show_alert=True)


async def search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return

    if not context.args:
        await update.message.reply_text("⚠️ Usage: /user [telegram_id | @username]")
        return

    search_term = context.args[0]

    try:
        with db_transaction() as db:
            if search_term.startswith('@'):
                user = db.query(User).filter(User.username == search_term.replace('@', '')).first()
            elif search_term.isdigit():
                user = db.query(User).filter(User.telegram_id == int(search_term)).first()
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

            user_id = user.id

        await update.message.reply_text(
            profile_text,
            parse_mode="HTML",
            reply_markup=get_user_profile_keyboard(user_id, is_suspended)
        )
    except Exception as e:
        logger.error(f"Error during search profile: {e}")
        await update.message.reply_text("❌ Error looking up user.")


async def show_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    try:
        with db_transaction() as db:
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
        logger.error(f"Error displaying user list: {e}")
        await update.callback_query.edit_message_text("❌ Error loading users.")


async def show_suspended_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    try:
        with db_transaction() as db:
            query = db.query(User).join(UserMetrics).filter(UserMetrics.suspended == True).order_by(User.created_at.desc())
            suspended_users, total_pages, total_items = paginate_query(query, page, page_size=10)

            if not suspended_users:
                reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_menu_main")]])
                await update.callback_query.edit_message_text("📭 <b>No suspended accounts currently.</b>", parse_mode="HTML", reply_markup=reply_markup)
                return

            text = f"⛔ <b>Suspended Accounts</b>\nPage {page + 1} of {total_pages} (Total: {total_items})\n\n"
            for u in suspended_users:
                text += f"❌ <b>{html.escape(u.full_name or 'N/A')}</b> (<code>{u.telegram_id}</code>)\nRole: {u.role.capitalize()} | @{html.escape(u.username or 'N/A')}\n\n"

        keyboard = build_pagination_keyboard("adm_susp_page", page, total_pages)
        keyboard.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="adm_menu_main")])
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error displaying suspended users: {e}")
        await update.callback_query.edit_message_text("❌ Error loading suspended users.")


async def show_pending_sellers_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    try:
        with db_transaction() as db:
            # Fetch pending sellers
            query = db.query(User).filter(User.status == 'pending').order_by(User.created_at.desc())
            pending_users, total_pages, total_items = paginate_query(query, page, page_size=5)

            if not pending_users:
                reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_menu_main")]])
                await update.callback_query.edit_message_text("📭 <b>No pending seller requests currently.</b>", parse_mode="HTML", reply_markup=reply_markup)
                return

            text = f"⏳ <b>Pending Seller Requests</b>\nPage {page + 1} of {total_pages} (Total: {total_items})\n\n"
            keyboard = []
            
            for u in pending_users:
                profile = db.query(SellerProfile).filter(SellerProfile.user_id == u.id).first()
                biz_name = html.escape(profile.business_name) if profile and profile.business_name else "N/A"
                
                text += f"👤 <b>{html.escape(u.full_name or 'N/A')}</b> (<code>{u.telegram_id}</code>)\n🏢 Business: {biz_name}\n\n"
                # Add a button to review this specific user
                keyboard.append([InlineKeyboardButton(f"👁 Review: {u.full_name or u.telegram_id}", callback_data=f"adm_pend_view_{u.id}")])

        # Add pagination and back buttons
        pagination_btns = build_pagination_keyboard("adm_pend_page", page, total_pages)
        if pagination_btns:
            keyboard.extend(pagination_btns)
        keyboard.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="adm_menu_main")])
        
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error displaying pending sellers: {e}")
        await update.callback_query.edit_message_text("❌ Error loading pending sellers.")


async def view_pending_seller(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    try:
        with db_transaction() as db:
            user = db.query(User).filter(User.id == user_id).first()
            if not user or user.status != 'pending':
                await update.callback_query.answer("⚠️ User is no longer pending.", show_alert=True)
                # Redirect back to the list
                return await show_pending_sellers_list(update, context, 0)
            
            profile = db.query(SellerProfile).filter(SellerProfile.user_id == user.id).first()
            
            text = (
                f"🆕 <b>Pending Seller Details</b>\n\n"
                f"<b>Name:</b> {html.escape(user.full_name or 'N/A')}\n"
                f"<b>Business:</b> {html.escape(profile.business_name if profile else 'N/A')}\n"
                f"<b>Shop No:</b> {html.escape(profile.shop_number if profile else 'N/A')}\n"
                f"<b>Category:</b> {html.escape(profile.category if profile else 'N/A')}\n"
                f"<b>Location:</b> {html.escape(profile.location if profile else 'N/A')}\n"
                f"<b>Phone:</b> +{html.escape(user.phone or 'N/A')}"
            )
            
            # Hooks right into your existing `adm_app_` and `adm_rej_` logic handled in admin.py
            keyboard = [
                [InlineKeyboardButton("Approve ✅", callback_data=f"adm_app_{user.id}"),
                 InlineKeyboardButton("Reject ❌", callback_data=f"adm_rej_{user.id}")],
                [InlineKeyboardButton("⬅️ Back to List", callback_data="adm_pend_page_0")]
            ]
            
            await update.callback_query.edit_message_text(
                text=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        logger.error(f"Error viewing pending seller {user_id}: {e}")
        await update.callback_query.answer("❌ Error loading seller details.", show_alert=True)