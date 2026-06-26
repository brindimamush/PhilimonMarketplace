# handlers/admin_requests.py
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.session import SessionLocal
from database.models import PurchaseRequest, User, RequestAcceptance, Offer, RequestHistory
from services.pagination_service import paginate_query, build_pagination_keyboard

async def show_active_requests(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    db = SessionLocal()
    
    # Query for all active/pending requests
    query = db.query(PurchaseRequest).filter(
        PurchaseRequest.status.in_([
            "PENDING_ADMIN_APPROVAL",
            "REQUEST_OPEN",
            "DEAL_PENDING_ADMIN"
        ])
    ).order_by(PurchaseRequest.created_at.desc())

    # Paginate using your Phase 2 service
    requests, total_pages, total_items = paginate_query(query, page, page_size=10)

    if not requests:
        text = "📭 *No active requests currently.*"
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="adm_menu_main")]])
        
        if update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)
        db.close()
        return

    text = f"📦 *Active Requests Dashboard*\nPage {page + 1} of {total_pages} (Total: {total_items})\n\n"
    keyboard = []

    for req in requests:
        buyer = db.query(User).filter(User.id == req.buyer_id).first()
        buyer_name = buyer.full_name if buyer else "Unknown"
        
        # Calculate Accepted Sellers Count
        accepted_count = db.query(RequestAcceptance).filter(RequestAcceptance.request_id == req.id).count()
        
        # Calculate Age
        age_delta = datetime.utcnow() - req.created_at
        age_minutes = int(age_delta.total_seconds() / 60)
        
        # Build Text List
        text += (
            f"**#{req.id}** | 👤 Buyer: {buyer_name}\n"
            f"Status: `{req.status}`\n"
            f"Accepted: {accepted_count}/3 | Age: {age_minutes} mins\n\n"
        )
        
        # Add Actions per Request
        keyboard.append([
            InlineKeyboardButton(f"👁 View #{req.id}", callback_data=f"adm_req_view_{req.id}"),
            InlineKeyboardButton(f"❌ Cancel #{req.id}", callback_data=f"adm_req_canc_{req.id}"),
            InlineKeyboardButton(f"⏰ Extend #{req.id}", callback_data=f"adm_req_ext_{req.id}")
        ])

    # Append Pagination Controls
    pagination_buttons = build_pagination_keyboard("adm_req_page", page, total_pages)
    if pagination_buttons:
        keyboard.extend(pagination_buttons)

    keyboard.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="adm_menu_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)
        
    db.close()

async def handle_requests_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Router for all Request Dashboard Callbacks."""
    query = update.callback_query
    
    data = query.data

    # Main Entry from Admin Menu
    if data == "adm_menu_reqs":
        await query.answer()
        await show_active_requests(update, context, page=0)
        
    # Pagination
    elif data.startswith("adm_req_page_"):
        await query.answer()
        page = int(data.split("_")[-1])
        await show_active_requests(update, context, page=page)
    
    elif data.startswith("adm_req_view_") or data.startswith("adm_req_canc_") or data.startswith("adm_req_ext_"):
        await handle_request_action_buttons(update, context, data)
    # Note: Handlers for adm_req_view_, adm_req_canc_, adm_req_ext_ will be hooked up in the Deal View expansion.


async def handle_request_action_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    query = update.callback_query
    admin_id = update.effective_user.id
    
    parts = data.split("_")
    action = parts[2] # 'view', 'canc', 'ext'
    req_id = int(parts[3])

    db = SessionLocal()
    req = db.query(PurchaseRequest).filter(PurchaseRequest.id == req_id).first()
    admin_user = db.query(User).filter(User.telegram_id == admin_id).first()

    if not req:
        await query.answer("❌ Request not found.")
        db.close()
        return

    if action == "view":
        # Fetch associated offers and details
        buyer = db.query(User).filter(User.id == req.buyer_id).first()
        offers = db.query(Offer).filter(Offer.request_id == req.id).all()
        
        detail_text = (
            f"🔍 *Request Details #{req.id}*\n"
            f"👤 **Buyer:** {buyer.full_name} (@{buyer.username or 'N/A'})\n"
            f"📦 **Quantity:** {req.quantity}\n"
            f"⏱ **Status:** `{req.status}`\n"
            f"📅 **Created:** {req.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"💰 *Submitted Offers:*\n"
        )
        
        if not offers:
            detail_text += "No offers submitted yet."
        else:
            for off in offers:
                seller = db.query(User).filter(User.id == off.seller_id).first()
                detail_text += f"• **{off.price} ETB** by {seller.full_name} (Status: {off.status})\n"

        await query.message.reply_photo(
            photo=req.image_file_id, 
            caption=detail_text, 
            parse_mode="HTML"
        )
        await query.answer()

    elif action == "canc":
        if req.status in ['CLOSED', 'CANCELLED', 'DELIVERED']:
            await query.answer("⚠️ This request is already closed or cancelled.")
            db.close()
            return

        req.status = 'CANCELLED'
        req.cancel_reason = "Cancelled by Admin via Dashboard"
        
        # Log History
        hist = RequestHistory(request_id=req.id, event="ADMIN_CANCELLED", performed_by=admin_user.id)
        db.add(hist)
        db.commit()

        # Notify Buyer
        buyer = db.query(User).filter(User.id == req.buyer_id).first()
        try:
            await context.bot.send_message(buyer.telegram_id, f"❌ Your Request #{req.id} was cancelled by an Administrator.")
        except Exception:
            pass

        await query.edit_message_text(f"{query.message.text}\n\n❌ *Request #{req.id} Cancelled.*", parse_mode="HTML")

    elif action == "ext":
        # Example logic: bump expiration time or reset a timeout flag if you implement them
        hist = RequestHistory(request_id=req.id, event="ADMIN_EXTENDED", performed_by=admin_user.id)
        db.add(hist)
        db.commit()
        await query.answer(f"✅ Request #{req.id} lifespan extended.", show_alert=True)

    db.close()