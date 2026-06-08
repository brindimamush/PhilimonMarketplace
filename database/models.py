# database/models.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, index=True)
    username = Column(String, nullable=True)
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

    user = relationship("User", back_populates="seller_profile")

class PurchaseRequest(Base):
    __tablename__ = 'purchase_requests'
    id = Column(Integer, primary_key=True)
    buyer_id = Column(Integer, ForeignKey('users.id'))
    image_file_id = Column(String)
    quantity = Column(Integer)
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class RequestAcceptance(Base):
    __tablename__ = 'request_acceptances'
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey('purchase_requests.id'))
    seller_id = Column(Integer, ForeignKey('users.id'))
    accepted_at = Column(DateTime, default=datetime.utcnow)

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