# services/seller_reliability_service.py
import logging
from database.session import db_transaction
from database.models import UserMetrics

logger = logging.getLogger(__name__)

def check_seller_status(user_id: int) -> tuple[bool, str, int]:
    try:
        with db_transaction() as db:
            metrics = db.query(UserMetrics).filter(UserMetrics.user_id == user_id).first()
            if not metrics:
                metrics = UserMetrics(user_id=user_id)
                db.add(metrics)
                db.flush()

            score = metrics.seller_score

            # Automatic suspension if score falls below threshold
            if score < 30 and not metrics.suspended:
                metrics.suspended = True
                metrics.suspension_reason = "Automatic suspension: Seller score fell below 30."

            if metrics.suspended:
                return False, "⛔ Account suspended. Contact support.", 0

            allowed_bids = 3
            if score < 50:
                allowed_bids = 1

            warning = "⚠️ Your seller reliability score is dropping." if score < 70 else ""

        return True, warning, allowed_bids
    except Exception as e:
        logger.error(f"check_seller_status failed for user {user_id}: {e}")
        return False, "❌ Service error. Please try again.", 0

def update_seller_score(user_id: int, points: int, metric_field: str = None):
    try:
        with db_transaction() as db:
            metrics = db.query(UserMetrics).filter(UserMetrics.user_id == user_id).first()
            if metrics:
                metrics.seller_score += points
                if metric_field and hasattr(metrics, metric_field):
                    setattr(metrics, metric_field, getattr(metrics, metric_field) + 1)
    except Exception as e:
        logger.error(f"update_seller_score failed for user {user_id}: {e}")