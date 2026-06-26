# handlers/buyer.py

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from database.session import SessionLocal
from database.models import User, PurchaseRequest, Offer, Deal, SellerProfile, UserMetrics
from keyboards.buyer import get_buyer_home_keyboard
from config import ADMIN_TELEGRAM_ID
from utils.helpers import get_text, get_user_lang, flag_user_to_admin
from services.buyer_reliability_service import can_create_request

# Conversation States for creating a request
BUYER_IMAGE, BUYER_QUANTITY = range(2)

async def check_buyer_role(update: Update) -> User:
    """Helper to ensure the user is an active buyer."""
    tg_id = update.effective_user.id
    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == tg_id, User.role == 'buyer', User.status == 'active').first()
    db.close()
    return user

async def start_purchase_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await check_buyer_role(update)
    lang = get_user_lang(update.effective_user.id)
    if not user: return ConversationHandler.END

    can_create, message = can_create_request(user.id)
    if not can_create:
        await update.message.reply_text(message)
        if "Score too low" in message:
            await flag_user_to_admin(context, user, "Buyer score dropped to critical levels. Request creation blocked.")
        return ConversationHandler.END
    
    # New Limit Check
    if not await check_buyer_limit(user.id):
        await update.message.reply_text("⚠️ You have reached the limit of 3 active requests. Please wait for current deals to close.")
        return ConversationHandler.END
    
            
    await update.message.reply_text(
        get_text(lang, "buyer_send_image"),
        reply_markup=ReplyKeyboardRemove()
    )
    return BUYER_IMAGE
# Add this logic to handlers/buyer.py
async def check_buyer_limit(user_id: int) -> bool:
    db = SessionLocal()
    # Count open requests
    active_count = db.query(PurchaseRequest).filter(
        PurchaseRequest.buyer_id == user_id,
        PurchaseRequest.status.in_(["REQUEST_OPEN", "DEAL_PENDING_ADMIN"])
    ).count()
    db.close()
    return active_count < 3  # Limit is 3

async def process_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Get the largest available photo version file_id
    photo_file_id = update.message.photo[-1].file_id
    context.user_data['request_photo_id'] = photo_file_id
    lang = get_user_lang(update.effective_user.id)
    
    await update.message.reply_text(get_text(lang, "buyer_enter_qty"))
    return BUYER_QUANTITY

async def process_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quantity_text = update.message.text
    tg_id = update.effective_user.id
    lang = get_user_lang(tg_id)
    
    if not quantity_text.isdigit():
        await update.message.reply_text(get_text(lang, "buyer_invalid_qty"))
        return BUYER_QUANTITY
        
    quantity = int(quantity_text)
    
    db = SessionLocal()
    buyer = db.query(User).filter(User.telegram_id == tg_id).first()
    
    # 1. Save Request to Database with Pending status
    new_request = PurchaseRequest(
        buyer_id=buyer.id,
        image_file_id=context.user_data['request_photo_id'],
        quantity=quantity,
        status='PENDING_ADMIN_APPROVAL'
    )
    db.add(new_request)
    db.commit() # Save to get the new_request.id

    metrics = db.query(UserMetrics).filter(UserMetrics.user_id == buyer.id).first()
    if not metrics:
        metrics = UserMetrics(user_id=buyer.id)
        db.add(metrics)
    metrics.total_requests += 1
    #NOTIFY THE BUYER ITS UNDER REVIEW
    await update.message.reply_text(
        "✅ Your purchase request has been submitted and is pending Admin approval.",
        reply_markup=get_buyer_home_keyboard(lang)
    )

    # 2. Forward to Admin for Approval instead of Sellers
    admin_kb = [
        [InlineKeyboardButton("Approve & Broadcast ✅", callback_data=f"adm_req_app_{new_request.id}"),
         InlineKeyboardButton("Reject ❌", callback_data=f"adm_req_rej_{new_request.id}")]
    ]
    buyer_phone_str = f'<a href="tel:+{buyer.phone}">+{buyer.phone}</a>' if buyer.phone else 'N/A'
    admin_text = (
        f"🔔 *New Buyer Request Pending Approval*\n\n"
        f"👤 *Buyer:* {buyer.full_name}\n" 
        f"• User Name: @{buyer.username or 'N/A'}\n"
        f"• Phone: {buyer_phone_str}\n"
        f"• ID: `{buyer.telegram_id}`\n"
        
        f"📦 *Quantity:* {quantity}\n\n"
        
        
        f"Approve to broadcast this to all active sellers."
    )
    
    await context.bot.send_photo(
        chat_id=ADMIN_TELEGRAM_ID,
        photo=new_request.image_file_id,
        caption=admin_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(admin_kb)
    )
            
    db.close()
    context.user_data.clear() # Wipe session data for this request wizard
    return ConversationHandler.END

async def cancel_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    lang = get_user_lang(tg_id)

    db = SessionLocal()
    user = db.query(User).filter(User.telegram_id == tg_id).first()
    if user:
        metrics = db.query(UserMetrics).filter(UserMetrics.user_id == user.id).first()
        if metrics:
            metrics.abandoned_requests += 1
            db.commit()
    db.close()

    await update.message.reply_text(get_text(lang, "req_cancelled"), reply_markup=get_buyer_home_keyboard(lang))
    context.user_data.clear()
    return ConversationHandler.END

# FIXED SELECT OFFER CALL
async def select_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    offer_id = int(query.data.replace("buy_sel_", ""))
    db = SessionLocal()
    
    try:
        selected_offer = db.query(Offer).filter(Offer.id == offer_id).first()
        if not selected_offer:
            await query.message.reply_text("❌ Offer not found.")
            db.close()
            return
            
        req = db.query(PurchaseRequest).filter(PurchaseRequest.id == selected_offer.request_id).first()
        
        # Guard clause: make sure the request wasn't already assigned a deal
        if req.status == 'DEAL_PENDING_ADMIN':
            await query.message.reply_text("⚠️ You have already selected an offer for this request.")
            db.close()
            return

        # 1. Update states
        selected_offer.status = 'SELECTED'
        req.status = 'DEAL_PENDING_ADMIN'
        
        # 2. Update remaining offers to LOST
        db.query(Offer).filter(Offer.request_id == req.id, Offer.id != offer_id).update({"status": "LOST"})
        
        # 3. Insert accurate Deal item row tracking data
        new_deal = Deal(
            request_id=req.id,
            offer_id=selected_offer.id,
            buyer_id=req.buyer_id,
            seller_id=selected_offer.seller_id,
            status='PENDING'
        )
        db.add(new_deal)
        db.commit()
        
        # Fetch actual entity rows for usernames
        seller = db.query(User).filter(User.id == selected_offer.seller_id).first()
        buyer = db.query(User).filter(User.id == req.buyer_id).first()
        
        
        # Query Seller Profile to get the Shop Number
        seller_profile = db.query(SellerProfile).filter(SellerProfile.user_id == seller.id).first()
        shop_num = seller_profile.shop_number if seller_profile and seller_profile.shop_number else 'N/A'
        
        buyer_phone_str = f'<a href="tel:+{buyer.phone}">+{buyer.phone}</a>' if buyer.phone else 'N/A'
        seller_phone_str = f'<a href="tel:+{seller.phone}">+{seller.phone}</a>' if seller.phone else 'N/A'
        # 4. Construct complete detail dispatch for Admin
        admin_text = (
            f"🤝 *Deal Selected - Action Required*\n\n"
            f"**Request ID:** #{req.id}\n"
            f"**Deal ID:** #{new_deal.id}\n"
            f"**Price:** {selected_offer.price} ETB\n"
            f"**Quantity:** {req.quantity}\n\n"
            f"👤 *Buyer Details*\n"
            f"• Full Name: {buyer.full_name or 'N/A'}\n"
            f"• Username: @{buyer.username or 'N/A'}\n"
            f"• Phone: {buyer_phone_str}\n"
            f"• Telegram ID: `{buyer.telegram_id}`\n\n"
            f"🏭 *Seller Details*\n"
            f"• Full Name: {seller.full_name or 'N/A'}\n"
            f"• Shop Number: {shop_num}\n"
            f"• Username: @{seller.username or 'N/A'}\n"
            f"• Phone: {seller_phone_str}\n"
            f"• DB ID: `{seller.id}`\n"
            f"• Telegram ID: `{seller.telegram_id}`"
        )
        
        admin_kb = [
            [InlineKeyboardButton("Mark Paid ✅", callback_data=f"adm_paid_{new_deal.id}"),
             InlineKeyboardButton("Cancel Deal ❌", callback_data=f"adm_can_{new_deal.id}")]
        ]
        
        # Deliver clear overview with product visualization back to Admin
        await context.bot.send_photo(
            chat_id=ADMIN_TELEGRAM_ID,
            photo=req.image_file_id,
            caption=admin_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(admin_kb)
        )
        
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ *You selected this offer! Sent to Admin for finalization.*", parse_mode="HTML")
        
        # Notify the seller who won the bid
        await context.bot.send_message(
            chat_id=seller.telegram_id,
            text=f"🎉 Excellent news! Your offer of {selected_offer.price} ETB for Request #{req.id} was selected by the buyer. Admin finalization pending."
        )
        
    except Exception as e:
        print(f"Error executing select_offer operation sequence: {e}")
        await query.message.reply_text("❌ An error occurred processing your offer selection.")
    finally:
        db.close()

async def view_my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    db = SessionLocal()
    
    buyer = db.query(User).filter(User.telegram_id == tg_id).first()
    if not buyer:
        db.close()
        return
        
    # Find all open requests belonging to this buyer
    requests = db.query(PurchaseRequest).filter(
        PurchaseRequest.buyer_id == buyer.id,
        PurchaseRequest.status == 'REQUEST_OPEN'
    ).all()
    
    if not requests:
        await update.message.reply_text("📋 You have no active purchase requests at the moment.")
        db.close()
        return
        
    for req in requests:
        # Fetch all submitted quotes for this request
        offers = db.query(Offer).filter(Offer.request_id == req.id).all()
        
        caption_text = (
            f"📦 *Request #{req.id}*\n"
            f"🔢 *Quantity:* {req.quantity}\n"
            f"📅 *Created:* {req.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
        )
        
        if not offers:
            caption_text += "⏳ No offers submitted by sellers yet."
            await update.message.reply_photo(
                photo=req.image_file_id,
                caption=caption_text,
                parse_mode="HTML"
            )
        else:
            caption_text += "💰 *Received Offers (Anonymous):*\n"
            keyboard = []
            letters = ["A", "B", "C"]
            
            for idx, offer in enumerate(offers):
                if idx >= len(letters):
                    break
                letter = letters[idx]
                caption_text += f"▪️ *Offer {letter}:* {offer.price} ETB\n"
                keyboard.append([InlineKeyboardButton(f"Select Offer {letter} 🏷️", callback_data=f"byr_sel_{offer.id}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_photo(
                photo=req.image_file_id,
                caption=caption_text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            
    db.close()

async def handle_offer_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    offer_id = int(query.data.replace("byr_sel_", ""))
    db = SessionLocal()
    
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if not offer or offer.status != 'OFFER_SUBMITTED':
        await query.message.reply_text("❌ This offer is no longer available.")
        db.close()
        return

    req = db.query(PurchaseRequest).filter(PurchaseRequest.id == offer.request_id).first()
    if not req or req.status != 'REQUEST_OPEN':
        await query.message.reply_text("❌ This request is already closed or processed.")
        db.close()
        return

    # Phase 7 Transitions: Update statuses
    req.status = 'DEAL_PENDING_ADMIN'
    offer.status = 'SELECTED'
    
    # Set losing bids to LOST
    losing_offers = db.query(Offer).filter(Offer.request_id == req.id, Offer.id != offer.id).all()
    for lose in losing_offers:
        lose.status = 'LOST'
        
    # Create the internal Deal tracking record
    buyer_user = db.query(User).filter(User.id == req.buyer_id).first()
    seller_user = db.query(User).filter(User.id == offer.seller_id).first()
    
    # Query Seller Profile to get the Shop Number
    seller_profile = db.query(SellerProfile).filter(SellerProfile.user_id == seller_user.id).first()
    shop_num = seller_profile.shop_number if seller_profile and seller_profile.shop_number else 'N/A'

    new_deal = Deal(
        request_id=req.id,
        offer_id=offer.id,
        buyer_id=buyer_user.id,
        seller_id=seller_user.id,
        status='PENDING'
    )
    db.add(new_deal)
    db.commit()
    
    await query.edit_message_caption(
        caption=f"{query.message.caption}\n\n✅ Offer selected! Awaiting admin finalization."
    )
    
    # Phase 8: Alert Admin instantly
    from config import ADMIN_TELEGRAM_ID
    admin_kb = [
        [InlineKeyboardButton("Mark Paid 💵", callback_data=f"adm_dl_paid_{new_deal.id}")],
        [InlineKeyboardButton("Mark Delivered 🚚", callback_data=f"adm_dl_delv_{new_deal.id}")],
        [InlineKeyboardButton("Cancel Deal ❌", callback_data=f"adm_dl_canc_{new_deal.id}")]
    ]

    buyer_phone_str = f'<a href="tel:+{buyer_user.phone}">+{buyer_user.phone}</a>' if buyer_user.phone else 'N/A'
    seller_phone_str = f'<a href="tel:+{seller_user.phone}">+{seller_user.phone}</a>' if seller_user.phone else 'N/A'
    
    admin_text = (
        f"🤝 *Deal Selected For Verification*\n\n"
        f"📋 *Request:* #{req.id}\n"
        f"🆔 *Deal reference:* #{new_deal.id}\n"
        f"💰 *Final Price:* {offer.price} ETB\n\n"
        f"👤 *Buyer Details*\n"
        f"• Full Name: {buyer_user.full_name or 'N/A'}\n"
        f"• Username: @{buyer_user.username or 'N/A'}\n"
        f"• Phone: {buyer_phone_str}\n"
        f"• Telegram ID: `{buyer_user.telegram_id}`\n\n"
        f"🏭 *Seller Details*\n"
        f"• Full Name: {seller_user.full_name or 'N/A'}\n"
        f"• Shop Number: {shop_num}\n"
        f"• Username: @{seller_user.username or 'N/A'}\n"
        f"• Phone: {seller_phone_str}\n"
        f"• DB ID: `{seller_user.id}`\n"
        f"• Telegram ID: `{seller_user.telegram_id}`"
    )
    
    await context.bot.send_message(
        chat_id=ADMIN_TELEGRAM_ID,
        text=admin_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(admin_kb)
    )
    db.close()