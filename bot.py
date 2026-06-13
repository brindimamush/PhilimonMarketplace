# bot.py
import logging
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters
from config import BOT_TOKEN
from services.scheduler import start_scheduler
from handlers.admin import admin_dashboard

# Updated imports covering new pipeline
from handlers.registration import (
    start, cmd_menu, cmd_language, cmd_help, handle_language_selection, 
    handle_role_selection, process_contact, seller_business_name, 
    seller_location, seller_category, switch_mode,
    SELECT_LANG, SELECT_ROLE, SHARE_PHONE, BUSINESS_NAME, LOCATION, CATEGORY
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
            SHARE_PHONE: [MessageHandler(filters.CONTACT, process_contact)],
            BUSINESS_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_business_name)],
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_location)],
            CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_category)],
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
    application.add_handler(CallbackQueryHandler(handle_admin_approval, pattern="^adm_"))
    
    application.add_handler(CommandHandler("dashboard", admin_dashboard))

    print("Marketplace upgraded and polling...")
    application.run_polling()

if __name__ == '__main__':
    main()