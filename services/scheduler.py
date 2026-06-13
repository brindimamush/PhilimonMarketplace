from apscheduler.schedulers.asyncio import AsyncIOScheduler
from services.timeout_service import expire_price_deadlines

def start_scheduler():
    scheduler = AsyncIOScheduler()
    # Runs every 5 minutes
    scheduler.add_job(expire_price_deadlines, 'interval', minutes=5)
    scheduler.start()
    print("Background jobs scheduler started.")