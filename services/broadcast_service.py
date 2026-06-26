import asyncio
import logging
from telegram.error import RetryAfter, TelegramError
from database.session import SessionLocal
from database.models import User

logger = logging.getLogger(__name__)

async def safe_broadcast_to_sellers(context, photo_id: str, caption: str, reply_markup):
    """
    Safely broadcasts purchase requests to all active sellers 
    while respecting Telegram's strict rate limits (~30 messages/sec).
    """
    db = SessionLocal()
    try:
        # Fetch fresh active sellers directly to avoid detached session states
        active_sellers = db.query(User).filter(User.role == 'seller', User.status == 'active').all()
        seller_ids = [seller.telegram_id for seller in active_sellers]
    finally:
        db.close()

    if not seller_ids:
        logger.info("No active sellers found to broadcast to.")
        return

    logger.info(f"Starting safe broadcast to {len(seller_ids)} sellers.")
    
    for tg_id in seller_ids:
        try:
            await context.bot.send_photo(
                chat_id=tg_id,
                photo=photo_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            # Sleep briefly to ensure we never cross the ~30 msgs/second boundary 
            # 0.05 seconds = 20 messages per second (safe zone)
            await asyncio.sleep(0.05)

        except RetryAfter as e:
            logger.warning(f"Flood limit reached. Sleeping for {e.retry_after} seconds.")
            await asyncio.sleep(e.retry_after)
            # Retry sending to the current seller after sleeping
            try:
                await context.bot.send_photo(chat_id=tg_id, photo=photo_id, caption=caption, parse_mode="HTML", reply_markup=reply_markup)
            except Exception as retry_err:
                logger.error(f"Failed retry for seller {tg_id}: {retry_err}")

        except TelegramError as e:
            # Handles blocked bots, deactivated accounts, etc.
            logger.error(f"Telegram error for seller {tg_id}: {e}")
            
        except Exception as e:
            logger.error(f"Unexpected error broadcasting to seller {tg_id}: {e}")

    logger.info("Broadcast sequence finished completed.")