from database.session import SessionLocal
from database.models import UserMetrics

def check_seller_status(user_id: int) -> tuple[bool, str, int]:
    db = SessionLocal()
    metrics = db.query(UserMetrics).filter(UserMetrics.user_id == user_id).first()
    if not metrics:
        metrics = UserMetrics(user_id=user_id)
        db.add(metrics)
        db.commit()

    score = metrics.seller_score
    
    # Phase 4: Automatic Suspension
    if score < 30 and not metrics.suspended:
        metrics.suspended = True
        metrics.suspension_reason = "Automatic suspension: Seller score fell below 30."
        db.commit()

    if metrics.suspended:
        db.close()
        return False, "⛔ Account suspended. Contact support.", 0
    
    # Limited Level
    allowed_bids = 3 
    if score < 50:
        allowed_bids = 1

    # Warning Level
    warning = "⚠️ Your seller reliability score is dropping." if score < 70 else ""
    db.close()
    return True, warning, allowed_bids

def update_seller_score(user_id: int, points: int, metric_field: str = None):
    db = SessionLocal()
    metrics = db.query(UserMetrics).filter(UserMetrics.user_id == user_id).first()
    if metrics:
        metrics.seller_score += points
        if metric_field and hasattr(metrics, metric_field):
            setattr(metrics, metric_field, getattr(metrics, metric_field) + 1)
        db.commit()
    db.close()