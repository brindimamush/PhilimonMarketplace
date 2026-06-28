# handlers/admin_deals.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database.session import db_transaction
from database.models import Deal, User
from services.pagination_service import paginate_query, build_pagination_keyboard

logger = logging.getLogger(__name__)

async def show_deals_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    try:
        with db_transaction() as db:
            query = db.query(Deal).order_by(Deal.created_at.desc())
            deals, total_pages, total_items = paginate_query(query, page, page_size=10)

            if not deals:
                text = "📭 *No deals found.*"
                reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_menu_main")]])
                await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
                return

            text = f"🤝 *Deals Directory*\nPage {page + 1} of {total_pages} (Total: {total_items})\n\n"
            for d in deals:
                buyer = db.query(User).filter(User.id == d.buyer_id).first()
                seller = db.query(User).filter(User.id == d.seller_id).first()
                buyer_name = buyer.full_name if buyer else 'Unknown'
                seller_name = seller.full_name if seller else 'Unknown'
                text += f"**Deal #{d.id}** | Status: `{d.status}`\n🛒 Buyer: {buyer_name}\n🏭 Seller: {seller_name}\n\n"

    except Exception as e:
        logger.error(f"show_deals_list failed on page {page}: {e}")
        await update.callback_query.edit_message_text("❌ Error loading deals.")
        return

    keyboard = build_pagination_keyboard("adm_deal_page", page, total_pages)
    keyboard.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data="adm_menu_main")])

    await update.callback_query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )