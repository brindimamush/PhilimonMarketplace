# handlers/admin.py
from telegram import Update
from telegram.ext import ContextTypes
from database.session import SessionLocal
from database.models import User
from keyboards.seller import get_seller_home_keyboard

async def handle_admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    db = SessionLocal()
    
    if data.startswith("adm_app_"):
        user_id = int(data.replace("adm_app_", ""))
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.status = 'active'
            db.commit()
            await query.edit_message_text(text=f"{query.message.text}\n\n✅ Approved!")
            # Notify the Seller
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text="🎉 Congratulations! Your seller profile has been approved.",
                reply_markup=get_seller_home_keyboard()
            )
            
    elif data.startswith("adm_rej_"):
        user_id = int(data.replace("adm_rej_", ""))
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.status = 'rejected'
            db.commit()
            await query.edit_message_text(text=f"{query.message.text}\n\n❌ Rejected.")
            # Notify the Seller
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text="❌ Your seller profile application was rejected by the admin."
            )
            
    db.close()