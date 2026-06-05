# bot.py
import logging
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters
from config import BOT_TOKEN
from handlers.registration import (
    start, join_buyer, join_seller_start, 
    seller_business_name, seller_phone, seller_location, seller_category,
    switch_mode, BUSINESS_NAME, PHONE, LOCATION, CATEGORY
)
from handlers.admin import handle_admin_approval

from handlers.buyer import (
    start_purchase_request, process_image, process_quantity, cancel_request,
    BUYER_IMAGE, BUYER_QUANTITY
)


# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    # Build PTB Application 
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Conversation setup for onboarding sellers
    seller_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(join_seller_start, pattern="^join_seller$")],
        states={
            BUSINESS_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_business_name)],
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone)],
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_location)],
            CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_category)],
        },
        fallbacks=[],
        allow_reentry=True
    )

    # Buyer Request Conversation
    buyer_request_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ New Request$"), start_purchase_request)],
        states={
            BUYER_IMAGE: [MessageHandler(filters.PHOTO, process_image)],
            BUYER_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_quantity)],
        },
        fallbacks=[CommandHandler("cancel", cancel_request)],
        allow_reentry=True
    )

    # Handlers Registration
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(join_buyer, pattern="^join_buyer$"))
    application.add_handler(seller_conv)
    application.add_handler(buyer_request_conv)
    application.add_handler(MessageHandler(filters.Regex("^🔄 Switch Mode$"), switch_mode))
    
    # Admin Callbacks
    application.add_handler(CallbackQueryHandler(handle_admin_approval, pattern="^adm_"))

    # Start polling
    print("Bot is up and running...")
    application.run_polling()

if __name__ == '__main__':
    main()