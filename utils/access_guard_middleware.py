# utils/access_guard_middleware.py
from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes, ConversationHandler
from database.session import SessionLocal
from database.models import User, UserMetrics
from config import ADMIN_TELEGRAM_ID

EXEMPT_COMMANDS = {"/start"}  # commands that bypass the check


async def suspension_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Runs before every update. Blocks suspended users immediately,
    regardless of what state they are in.
    """
    # Only process messages and callback queries
    if not update.effective_user:
        return
    
    if update.effective_user.id == ADMIN_TELEGRAM_ID:
        return

    # Let /start through so suspended users can see their status
    if update.message and update.message.text in EXEMPT_COMMANDS:
        return

    tg_id = update.effective_user.id

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_id == tg_id).first()
        if not user:
            return  # unregistered — let /start handle it

        metrics = db.query(UserMetrics).filter(UserMetrics.user_id == user.id).first()
        if not (metrics and metrics.suspended):
            return  # not suspended — proceed normally

        reason = metrics.suspension_reason or "Contact support for details."
        msg = f"⛔ Your account has been suspended.\n{reason}"

        # Answer callback queries to stop the spinner
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        elif update.message:
            await update.message.reply_text(msg)

        # Kill any active conversation for this user
        context.user_data.clear()

        # Raise to stop PTB passing this update to any other handler
        raise ApplicationHandlerStop()

    finally:
        db.close()