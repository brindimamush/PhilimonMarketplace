# services/buyer_reliability_service.py
import logging
from database.session import db_transaction
from database.models import UserMetrics, PurchaseRequest

logger = logging.getLogger(__name__)

def can_create_request(user_id: int) -> tuple[bool, str]:
    try:
        with db_transaction() as db:
            metrics = db.query(UserMetrics).filter(UserMetrics.user_id == user_id).first()
            if not metrics:
                metrics = UserMetrics(user_id=user_id)
                db.add(metrics)
                db.flush()

            if metrics.suspended:
                return False, "⛔ Account suspended. Contact support."

            active_count = db.query(PurchaseRequest).filter(
                PurchaseRequest.buyer_id == user_id,
                PurchaseRequest.status.in_(["REQUEST_OPEN", "DEAL_PENDING_ADMIN"])
            ).count()

            score = metrics.buyer_score
            limit = 3
            if score > 120:
                limit = 5
            elif score < 40:
                limit = 0
            elif score < 70:
                limit = 1

            if limit == 0:
                return False, "⚠️ Score too low. New requests blocked. Admin review required."

            if active_count >= limit:
                return False, f"⚠️ Limit reached ({active_count}/{limit} active requests allowed based on your score)."

        return True, ""
    except Exception as e:
        logger.error(f"can_create_request failed for user {user_id}: {e}")
        return False, "❌ Service error. Please try again."

def record_request_completed(user_id: int):
    try:
        with db_transaction() as db:
            metrics = db.query(UserMetrics).filter(UserMetrics.user_id == user_id).first()
            if metrics:
                metrics.completed_purchases += 1
                metrics.buyer_score += 2
    except Exception as e:
        logger.error(f"record_request_completed failed for user {user_id}: {e}")