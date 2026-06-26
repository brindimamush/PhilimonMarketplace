# bot.py
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters, ContextTypes
from config import BOT_TOKEN
from services.scheduler import start_scheduler
from handlers.admin import admin_dashboard
from handlers.admin_users import search_user, handle_user_actions, show_users_list
from handlers.admin_menu import admin_menu, handle_main_menu_callbacks
from handlers.admin_requests import handle_requests_callbacks
from handlers.admin_deals import show_deals_list


# Updated imports covering new pipeline
from handlers.registration import (
    start, cmd_menu, cmd_language, cmd_help, handle_language_selection, 
    handle_role_selection, handle_rules_agreement, process_contact, seller_business_name, process_full_name, 
    seller_location, seller_category, seller_shop_number, switch_mode,
    SELECT_LANG, SELECT_ROLE,AGREE_RULES, SHARE_PHONE,FULL_NAME, BUSINESS_NAME, LOCATION, CATEGORY, SHOP_NUMBER
)
from handlers.admin import handle_admin_approval, handle_admin_deal_actions

from handlers.buyer import (
    start_purchase_request, select_offer, process_image, process_quantity, 
    cancel_request, view_my_requests, handle_offer_selection,
    BUYER_IMAGE, BUYER_QUANTITY
)
from handlers.seller import handle_seller_accept, process_seller_price, SELLER_PRICE

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def master_admin_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    
    # ALWAYS answer the query immediately to stop the loading spinner!
    await query.answer()

    # Route to the correct view based on the button clicked
    if data in ["adm_menu_main", "adm_menu_search", "adm_menu_stats"]:
        await handle_main_menu_callbacks(update, context)
        
    elif data == "adm_menu_users" or data.startswith("adm_usr_page_"):
        page = int(data.split("_")[-1]) if "page_" in data else 0
        await show_users_list(update, context, page)
        
    elif data == "adm_menu_deals" or data.startswith("adm_deal_page_"):
        page = int(data.split("_")[-1]) if "page_" in data else 0
        await show_deals_list(update, context, page)
        
    elif data == "adm_menu_susp":
        await query.message.reply_text("⛔ Suspended list view coming next!")

def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    start_scheduler()
    # Core Onboarding Unified Flow
    onboarding_conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("language", cmd_language),
            MessageHandler(filters.Regex("^(🌐 Language|🌐 ቋንቋ)$"), cmd_language),
            CallbackQueryHandler(handle_role_selection, pattern="^role_")
        ],
        states={
            SELECT_LANG: [CallbackQueryHandler(handle_language_selection, pattern="^lang_")],
            SELECT_ROLE: [CallbackQueryHandler(handle_role_selection, pattern="^role_")],
            AGREE_RULES: [CallbackQueryHandler(handle_rules_agreement, pattern="^rules_agree$")],
            SHARE_PHONE: [MessageHandler(filters.CONTACT, process_contact)],
            FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_full_name)],
            BUSINESS_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_business_name)],
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_location)],
            CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_category)],
            SHOP_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_shop_number)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )
    
    buyer_request_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(➕ New Request|➕ አዲስ ጥያቄ)$"), start_purchase_request)],
        states={
            BUYER_IMAGE: [MessageHandler(filters.PHOTO, process_image)],
            BUYER_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_quantity)],
        },
        fallbacks=[CommandHandler("cancel", cancel_request)],
        allow_reentry=True
    )

    seller_bidding_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_seller_accept, pattern="^sel_acc_")],
        states={
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_seller_price)]
        },
        fallbacks=[],
        allow_reentry=True
    )
    
    # Core system commands
    application.add_handler(CommandHandler("menu", cmd_menu))
    application.add_handler(CommandHandler("help", cmd_help))
    
    # Registration Flow
    application.add_handler(onboarding_conv)
    
    # Feature Flows
    application.add_handler(buyer_request_conv)
    application.add_handler(seller_bidding_conv)
    
    # Button Listeners (English & Amharic Bindings)
    application.add_handler(CallbackQueryHandler(select_offer, pattern="^buy_sel_"))
    application.add_handler(MessageHandler(filters.Regex("^(🔄 Switch Mode|🔄 ሞድ ቀይር)$"), switch_mode))
    
    # Admin Callbacks
    application.add_handler(CallbackQueryHandler(handle_admin_deal_actions, pattern="^adm_dl_"))
    application.add_handler(CallbackQueryHandler(handle_admin_approval, pattern="^(adm_app_|adm_rej_|adm_req_app_|adm_req_rej_|adm_paid_|adm_can_)"))
    
    application.add_handler(CommandHandler("dashboard", admin_dashboard))
    application.add_handler(CallbackQueryHandler(
        handle_requests_callbacks, 
        pattern="^(adm_menu_reqs|adm_req_page_|adm_req_view_|adm_req_canc_|adm_req_ext_)"
    ))

    application.add_handler(CallbackQueryHandler(
        master_admin_router, 
        pattern="^(adm_menu_|adm_usr_page_|adm_deal_page_)"
    ))

    application.add_handler(CallbackQueryHandler(
        handle_user_actions, 
        pattern="^(adm_suspend_|adm_unsuspend_|adm_ban_|adm_hist_)"
    ))
    application.add_handler(CommandHandler("admin", admin_menu))
    application.add_handler(CommandHandler("user", search_user))
    print("Marketplace upgraded and polling...")
    application.run_polling()

if __name__ == '__main__':
    main()