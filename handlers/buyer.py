# handlers/buyer.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters
from database.session import SessionLocal
from database.models import User, PurchaseRequest, Offer, Deal
from keyboards.buyer import get_buyer_home_keyboard
from database.models import Offer, Deal
from config import ADMIN_TELEGRAM_ID
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
    if not user:
        await update.message.reply_text("This action is only available for active buyers.")
        return ConversationHandler.END
        
    await update.message.reply_text(
        "📸 Please send an image of the product you want to request:",
        reply_markup=ReplyKeyboardRemove()
    )
    return BUYER_IMAGE

async def process_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Get the largest available photo version file_id
    photo_file_id = update.message.photo[-1].file_id
    context.user_data['request_photo_id'] = photo_file_id
    
    await update.message.reply_text("🔢 Great! Now enter the quantity you need (e.g., 50):")
    return BUYER_QUANTITY

async def process_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quantity_text = update.message.text
    
    if not quantity_text.isdigit():
        await update.message.reply_text("❌ Please enter a valid number for quantity:")
        return BUYER_QUANTITY
        
    quantity = int(quantity_text)
    tg_id = update.effective_user.id
    
    db = SessionLocal()
    buyer = db.query(User).filter(User.telegram_id == tg_id).first()
    
    # 1. Save Request to Database
    new_request = PurchaseRequest(
        buyer_id=buyer.id,
        image_file_id=context.user_data['request_photo_id'],
        quantity=quantity,
        status='REQUEST_OPEN'
    )
    db.add(new_request)
    db.commit() # Save to get the new_request.id
    
    await update.message.reply_text(
        "✅ Your purchase request has been created and broadcasted to active sellers!",
        reply_markup=get_buyer_home_keyboard()
    )
    
    # 2. Broadcast to All Active Sellers (Phase 3)
    active_sellers = db.query(User).filter(User.role == 'seller', User.status == 'active').all()
    
    # Inline keyboard button for sellers to fight for slots
    seller_kb = [
        [InlineKeyboardButton("Accept 🤝", callback_data=f"sel_acc_{new_request.id}")]
    ]
    reply_markup = InlineKeyboardMarkup(seller_kb)
    
    broadcast_text = (
        f"🔔 *New Buyer Request!*\n\n"
        f"📦 *Quantity:* {quantity}\n\n"
        f"Click 'Accept' below if you want to submit an offer. Only the first 3 sellers can participate!"
    )
    
    for seller in active_sellers:
        try:
            await context.bot.send_photo(
                chat_id=seller.telegram_id,
                photo=new_request.image_file_id,
                caption=broadcast_text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except Exception as e:
            # Prevent one bad chat ID from breaking the whole broadcast loop
            print(f"Failed to send broadcast to seller {seller.telegram_id}: {e}")
            
    db.close()
    context.user_data.clear() # Wipe session data for this request wizard
    return ConversationHandler.END

async def cancel_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Request creation cancelled.", reply_markup=get_buyer_home_keyboard())
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
        
        # 4. Construct complete detail dispatch for Admin
        admin_text = (
            f"🤝 *Deal Selected - Action Required*\n\n"
            f"**Request ID:** #{req.id}\n"
            f"**Deal ID:** #{new_deal.id}\n"
            f"**Price:** {selected_offer.price} ETB\n"
            f"**Quantity:** {req.quantity}\n\n"
            f"👤 *Buyer:* @{buyer.username or 'No Username'} (ID: {buyer.telegram_id})\n"
            f"🏭 *Seller:* @{seller.username or 'No Username'} (ID: {seller.telegram_id})"
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
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(admin_kb)
        )
        
        await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ *You selected this offer! Sent to Admin for finalization.*", parse_mode="Markdown")
        
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
                parse_mode="Markdown"
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
                parse_mode="Markdown",
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
    
    admin_text = (
        f"🤝 *Deal Selected For Verification*\n\n"
        f"📋 *Request:* #{req.id}\n"
        f"🆔 *Deal reference:* #{new_deal.id}\n"
        f"👤 *Buyer Link:* [{buyer_user.username or 'No Username'}](tg://user?id={buyer_user.telegram_id})\n"
        f"🏭 *Seller Link:* [{seller_user.username or 'No Username'}](tg://user?id={seller_user.telegram_id})\n"
        f"💰 *Final Price:* {offer.price} ETB"
    )
    
    await context.bot.send_message(
        chat_id=ADMIN_TELEGRAM_ID,
        text=admin_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(admin_kb)
    )
    db.close()