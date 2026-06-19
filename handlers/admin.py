# handlers/admin.py
from telegram import Update
from telegram.ext import ContextTypes
from database.session import SessionLocal
from database.models import User,Deal, PurchaseRequest, UserMetrics
from keyboards.seller import get_seller_home_keyboard
from config import ADMIN_TELEGRAM_ID

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

    elif data.startswith("adm_paid_"):
        deal_id = int(data.replace("adm_paid_", ""))
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        
        if deal and deal.status == 'PENDING':
            deal.status = 'PAID'
            req = db.query(PurchaseRequest).filter(PurchaseRequest.id == deal.request_id).first()
            req.status = 'CLOSED'
            db.commit()
            
            buyer = db.query(User).filter(User.id == deal.buyer_id).first()
            seller = db.query(User).filter(User.id == deal.seller_id).first()
            
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n🟢 *Deal Completed: Marked Paid!*", parse_mode="HTML")
            
            # Message both parties to close out interaction safely
            await context.bot.send_message(chat_id=buyer.telegram_id, text=f"✅ Admin marked Deal #{deal_id} as PAID. Arrangement finalized!")
            await context.bot.send_message(chat_id=seller.telegram_id, text=f"💰 Admin confirmed payment for Deal #{deal_id}. Proceed with shipment/delivery tracking!")
            
    elif data.startswith("adm_can_"):
        deal_id = int(data.replace("adm_can_", ""))
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        
        if deal and deal.status == 'PENDING':
            deal.status = 'CANCELLED'
            req = db.query(PurchaseRequest).filter(PurchaseRequest.id == deal.request_id).first()
            req.status = 'REQUEST_OPEN' # Reset so sellers can bid again or try over
            db.commit()
            
            buyer = db.query(User).filter(User.id == deal.buyer_id).first()
            seller = db.query(User).filter(User.id == deal.seller_id).first()
            
            await query.edit_message_caption(caption=f"{query.message.caption}\n\n🔴 *Deal Cancelled by Admin.*", parse_mode="HTML")
            await context.bot.send_message(chat_id=buyer.telegram_id, text=f"❌ Admin has cancelled Deal #{deal_id}. Your request is reopened.")
            await context.bot.send_message(chat_id=seller.telegram_id, text=f"⚠️ Deal #{deal_id} has been cancelled by the administrator.")
            
    db.close()

async def handle_admin_deal_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    db = SessionLocal()
    
    # Extract Deal ID out of string
    if data.startswith("adm_dl_paid_"):
        deal_id = int(data.replace("adm_dl_paid_", ""))
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if deal:
            deal.status = 'PAID'
            db.commit()
            await query.edit_message_text(text=f"{query.message.text}\n\n💵 *Status Update:* Marked as PAID!")
            
            # Notify members
            buyer = db.query(User).filter(User.id == deal.buyer_id).first()
            seller = db.query(User).filter(User.id == deal.seller_id).first()
            await context.bot.send_message(chat_id=buyer.telegram_id, text=f"💵 Admin confirmed payment receipt for Deal #{deal_id}.")
            await context.bot.send_message(chat_id=seller.telegram_id, text=f"💵 Admin confirmed payment receipt for Deal #{deal_id}. Proceed to delivery.")

    elif data.startswith("adm_dl_delv_"):
        deal_id = int(data.replace("adm_dl_delv_", ""))
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if deal:
            deal.status = 'DELIVERED'
            # Close out the purchase request completely
            req = db.query(PurchaseRequest).filter(PurchaseRequest.id == deal.request_id).first()
            if req:
                req.status = 'CLOSED'
            db.commit()
            await query.edit_message_text(text=f"{query.message.text}\n\n🚚 *Status Update:* Marked as DELIVERED & closed.")
            
            buyer = db.query(User).filter(User.id == deal.buyer_id).first()
            seller = db.query(User).filter(User.id == deal.seller_id).first()
            await context.bot.send_message(chat_id=buyer.telegram_id, text=f"🎉 Deal #{deal_id} has been fully marked as Delivered! Thank you.")
            await context.bot.send_message(chat_id=seller.telegram_id, text=f"🎉 Deal #{deal_id} has been fully marked as Delivered! Lifecycle closed.")

    elif data.startswith("adm_dl_canc_"):
        deal_id = int(data.replace("adm_dl_canc_", ""))
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if deal:
            deal.status = 'CANCELLED'
            req = db.query(PurchaseRequest).filter(PurchaseRequest.id == deal.request_id).first()
            if req:
                req.status = 'CLOSED'
            db.commit()
            await query.edit_message_text(text=f"{query.message.text}\n\n❌ *Status Update:* Deal Cancelled.")
            
            buyer = db.query(User).filter(User.id == deal.buyer_id).first()
            seller = db.query(User).filter(User.id == deal.seller_id).first()
            await context.bot.send_message(chat_id=buyer.telegram_id, text=f"❌ Admin has cancelled Deal #{deal_id}.")
            await context.bot.send_message(chat_id=seller.telegram_id, text=f"❌ Admin has cancelled Deal #{deal_id}.")

    db.close()


async def admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_TELEGRAM_ID:
        return

    db = SessionLocal()
    total_buyers = db.query(User).filter(User.role == 'buyer').count()
    total_sellers = db.query(User).filter(User.role == 'seller').count()
    active_requests = db.query(PurchaseRequest).filter(PurchaseRequest.status == 'REQUEST_OPEN').count()
    completed_deals = db.query(Deal).filter(Deal.status == 'DELIVERED').count()
    suspended_users = db.query(UserMetrics).filter(UserMetrics.suspended == True).count()

    stats_text = (
        f"📊 *Marketplace Analytics*\n\n"
        f"👥 *Buyers:* {total_buyers}\n"
        f"🏭 *Sellers:* {total_sellers}\n"
        f"📦 *Active Requests:* {active_requests}\n"
        f"✅ *Completed Deals:* {completed_deals}\n"
        f"⛔ *Suspended Users:* {suspended_users}\n"
    )

    await update.message.reply_text(stats_text, parse_mode="Markdown")
    db.close()    