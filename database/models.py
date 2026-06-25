# database/models.py
from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, index=True)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)      # Moved from SellerProfile
    language = Column(String, default="en")    # Added language tracking
    role = Column(String)                      # 'buyer', 'seller', 'admin'
    status = Column(String)                    # 'active', 'pending', 'banned', 'rejected'
    created_at = Column(DateTime, default=datetime.utcnow)

    seller_profile = relationship("SellerProfile", back_populates="user", uselist=False)

class SellerProfile(Base):
    __tablename__ = 'seller_profiles'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    business_name = Column(String)
    location = Column(String)                  # Phone removed
    category = Column(String)
    shop_number = Column(String, nullable=True)

    user = relationship("User", back_populates="seller_profile")

class PurchaseRequest(Base):
    __tablename__ = 'purchase_requests'
    id = Column(Integer, primary_key=True)
    buyer_id = Column(Integer, ForeignKey('users.id'))
    image_file_id = Column(String)
    quantity = Column(Integer)
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    selected_offer_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    buyer_completed = Column(Boolean, default=False)
    buyer_abandoned = Column(Boolean, default=False)
    last_activity_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    admin_notes = Column(Text, nullable=True)
    cancel_reason = Column(String, nullable=True)

class AdminAction(Base):
    __tablename__ = 'admin_actions'
    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey('users.id'))
    target_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    action = Column(String) # 'SUSPEND', 'BAN', 'UNSUSPEND', 'APPROVE_SELLER'
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class RequestHistory(Base):
    __tablename__ = 'request_history'
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('purchase_requests.id'))
    event = Column(String) # 'CREATED', 'APPROVED', 'SELLER_ACCEPTED', 'DEAL_CLOSED'
    performed_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)    

class RequestAcceptance(Base):
    __tablename__ = 'request_acceptances'
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('purchase_requests.id'))
    seller_id = Column(Integer, ForeignKey('users.id'))
    accepted_at = Column(DateTime, default=datetime.utcnow)
    price_submitted = Column(Boolean, default=False)
    deadline_at = Column(DateTime)

class Offer(Base):
    __tablename__ = 'offers'
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('purchase_requests.id'))
    seller_id = Column(Integer, ForeignKey('users.id'))
    price = Column(Float)
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Deal(Base):
    __tablename__ = 'deals'
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('purchase_requests.id'))
    offer_id = Column(Integer, ForeignKey('offers.id'))
    buyer_id = Column(Integer, ForeignKey('users.id'))
    seller_id = Column(Integer, ForeignKey('users.id'))
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserMetrics(Base):
    __tablename__ = "user_metrics"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    
    # Buyer Metrics
    total_requests = Column(Integer, default=0)
    completed_purchases = Column(Integer, default=0)
    abandoned_requests = Column(Integer, default=0)
    buyer_score = Column(Float, default=100.0)
    
    # Seller Metrics
    accepted_requests = Column(Integer, default=0) # Total times 'Accept' clicked
    submitted_prices = Column(Integer, default=0)  # Total times price submitted
    completed_sales = Column(Integer, default=0)
    missed_price_deadlines = Column(Integer, default=0)
    seller_score = Column(Float, default=100.0)
    
    # System Controls
    suspended = Column(Boolean, default=False)
    suspension_reason = Column(String, nullable=True)
    suspended_at = Column(DateTime, nullable=True)
    suspended_by = Column(Integer, nullable=True)