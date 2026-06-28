# services/timeout_service.py
import logging
from datetime import datetime
from database.session import db_transaction
from database.models import RequestAcceptance, UserMetrics

logger = logging.getLogger(__name__)

def expire_price_deadlines():
    try:
        with db_transaction() as db:
            expired = db.query(RequestAcceptance).filter(
                RequestAcceptance.price_submitted == False,
                RequestAcceptance.deadline_at < datetime.utcnow()
            ).all()

            count = len(expired)
            for acc in expired:
                metrics = db.query(UserMetrics).filter(UserMetrics.user_id == acc.seller_id).first()
                if metrics:
                    metrics.missed_price_deadlines += 1
                    metrics.seller_score -= 5
                db.delete(acc)
            # Single commit: all metrics updates and deletes land together or none do

        logger.info(f"Cleared {count} expired seller slots.")
        print(f"Cleared {count} expired seller slots.")
    except Exception as e:
        logger.error(f"expire_price_deadlines failed: {e}")