# services/pagination_service.py
from telegram import InlineKeyboardButton

def paginate_query(query, page: int, page_size: int = 10):
    """Returns a paginated slice of a SQLAlchemy query and total counts."""
    total_items = query.count()
    total_pages = (total_items + page_size - 1) // page_size
    items = query.offset(page * page_size).limit(page_size).all()
    
    return items, total_pages, total_items

def build_pagination_keyboard(callback_prefix: str, current_page: int, total_pages: int) -> list:
    """Builds standard ⬅️ ➡️ pagination buttons."""
    buttons = []
    if current_page > 0:
        buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{callback_prefix}_{current_page - 1}"))
    if current_page < total_pages - 1:
        buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"{callback_prefix}_{current_page + 1}"))
    
    return [buttons] if buttons else []