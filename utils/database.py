import os
import logging
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, DateTime, Boolean, Text, Date, func
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, date, timezone, timedelta

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///workshop.db')

MOSCOW_TZ = timezone(timedelta(hours=3))

engine = create_engine(DATABASE_URL, echo=False)


def get_user_info(user_id: int) -> dict:
    """Получение информации о пользователе"""
    # Заглушка - возвращаем пустой словарь
    return {}


def add_user(user_id: int,
             username: str = None,
             first_name: str = None) -> None:
    """Добавление пользователя"""
    pass


def is_user_blocked(user_id: int) -> bool:
    """Проверка, заблокирован ли пользователь"""
    return False


SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

logger = logging.getLogger(__name__)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    service_type = Column(String)
    description = Column(Text)
    photo_file_id = Column(String)
    client_name = Column(String)
    client_phone = Column(String)
    status = Column(String, default='new')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime,
                        default=datetime.utcnow,
                        onupdate=datetime.utcnow)
    completed_at = Column(DateTime)
    feedback_requested = Column(Boolean, default=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    phone = Column(String)
    is_blocked = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)
    last_visit_date = Column(Date)
    tone_preference = Column(String,
                             default='friendly')  # friendly, formal, playful
    questions_count = Column(Integer, default=0)


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    message = Column(Text)
    response = Column(Text)
    topic = Column(String)  # repair, price, info, offtopic
    complexity = Column(String)  # simple, medium, complex
    created_at = Column(DateTime, default=datetime.utcnow)


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, unique=True, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5 stars
    comment = Column(Text)
    is_approved = Column(Boolean, default=True)
    rejected_reason = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime)


class SpamLog(Base):
    __tablename__ = "spam_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    message = Column(Text)
    reason = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    emoji = Column(String, default="")
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


class Price(Base):
    __tablename__ = "prices"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    price = Column(String, nullable=False)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


def init_db():
    """Initialize database"""
    Base.metadata.create_all(bind=engine)


def get_session():
    """Get database session"""
    return SessionLocal()


def create_order(user_id: int,
                 service_type: str,
                 description: str = None,
                 photo_file_id: str = None,
                 client_name: str = None,
                 client_phone: str = None) -> int:
    """Create new order with full details"""
    session = get_session()
    try:
        order = Order(user_id=user_id,
                      service_type=service_type,
                      description=description,
                      photo_file_id=photo_file_id,
                      client_name=client_name,
                      client_phone=client_phone,
                      status='new')
        session.add(order)
        session.commit()
        order_id = order.id
        return order_id
    finally:
        session.close()


def update_order_status(order_id: int, status: str) -> bool:
    """Update order status"""
    session = get_session()
    try:
        order = session.query(Order).filter(Order.id == order_id).first()
        if order:
            order.status = status
            order.updated_at = datetime.now(MOSCOW_TZ)
            if status == 'completed' and not order.completed_at:
                order.completed_at = datetime.now(MOSCOW_TZ)
            session.commit()
            return True
        return False
    finally:
        session.close()


def get_order(order_id: int):
    """Get order by id"""
    session = get_session()
    try:
        return session.query(Order).filter(Order.id == order_id).first()
    finally:
        session.close()


def delete_order(order_id: int) -> bool:
    """Delete order by id"""
    session = get_session()
    try:
        order = session.query(Order).filter(Order.id == order_id).first()
        if order:
            session.delete(order)
            session.commit()
            return True
        return False
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


def delete_orders_bulk(order_ids: list) -> int:
    """Delete multiple orders by ids, return count of deleted"""
    session = get_session()
    try:
        deleted_count = session.query(Order).filter(
            Order.id.in_(order_ids)).delete(synchronize_session=False)
        session.commit()
        return deleted_count
    except Exception:
        session.rollback()
        return 0
    finally:
        session.close()


def get_user_orders(user_id: int):
    """Get all orders for user"""
    session = get_session()
    try:
        return session.query(Order).filter(Order.user_id == user_id).order_by(
            Order.created_at.desc()).all()
    finally:
        session.close()


def get_all_orders(limit: int = 50):
    """Get all orders"""
    session = get_session()
    try:
        return session.query(Order).order_by(
            Order.created_at.desc()).limit(limit).all()
    finally:
        session.close()


def get_orders_by_status(status: str):
    """Get orders by status"""
    session = get_session()
    try:
        return session.query(Order).filter(Order.status == status).order_by(
            Order.created_at.desc()).all()
    finally:
        session.close()


def search_orders_by_name(name: str, limit: int = 50):
    """Search orders by client name (partial match)"""
    session = get_session()
    try:
        return session.query(Order).filter(
            Order.client_name.ilike(f"%{name}%")
        ).order_by(Order.created_at.desc()).limit(limit).all()
    finally:
        session.close()


def search_orders_by_id(order_id: int):
    """Search order by exact ID"""
    return get_order(order_id)


def get_orders_count_by_status(status: str) -> int:
    """Get count of orders by status"""
    session = get_session()
    try:
        return session.query(Order).filter(Order.status == status).count()
    finally:
        session.close()


def add_user(user_id: int,
             username: str = "",
             first_name: str = "",
             last_name: str = "",
             phone: str = ""):
    """Add or update user"""
    session = get_session()
    try:
        user = session.query(User).filter(User.user_id == user_id).first()
        if user:
            user.username = username or user.username
            user.first_name = first_name or user.first_name
            user.last_name = last_name or user.last_name
            user.phone = phone or user.phone
            user.last_active = datetime.utcnow()
        else:
            user = User(user_id=user_id,
                        username=username,
                        first_name=first_name,
                        last_name=last_name,
                        phone=phone)
            session.add(user)
        session.commit()
        return user.id
    except Exception:
        session.rollback()
        return None
    finally:
        session.close()


def get_user(user_id: int):
    """Get user by telegram id"""
    session = get_session()
    try:
        return session.query(User).filter(User.user_id == user_id).first()
    finally:
        session.close()


def get_all_users():
    """Get all users"""
    session = get_session()
    try:
        return session.query(User).filter(User.is_blocked == False).all()
    finally:
        session.close()


def block_user(user_id: int, blocked: bool = True):
    """Block or unblock user"""
    session = get_session()
    try:
        user = session.query(User).filter(User.user_id == user_id).first()
        if user:
            user.is_blocked = blocked
            session.commit()
            return True
        return False
    finally:
        session.close()


def is_user_blocked(user_id: int) -> bool:
    """Check if user is blocked"""
    session = get_session()
    try:
        user = session.query(User).filter(User.user_id == user_id).first()
        return user.is_blocked if user else False
    finally:
        session.close()


def set_admin(user_id: int, is_admin: bool = True):
    """Set user as admin"""
    session = get_session()
    try:
        user = session.query(User).filter(User.user_id == user_id).first()
        if user:
            user.is_admin = is_admin
            session.commit()
            return True
        return False
    finally:
        session.close()


def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    session = get_session()
    try:
        user = session.query(User).filter(User.user_id == user_id).first()
        return user.is_admin if user else False
    finally:
        session.close()


def get_admins():
    """Get all admin users"""
    session = get_session()
    try:
        return session.query(User).filter(User.is_admin == True).all()
    finally:
        session.close()


def log_spam(user_id: int, message: str, reason: str):
    """Log spam message"""
    session = get_session()
    try:
        spam = SpamLog(user_id=user_id, message=message[:500], reason=reason)
        session.add(spam)
        session.commit()
    finally:
        session.close()


def get_spam_logs(limit: int = 50):
    """Get spam logs"""
    session = get_session()
    try:
        return session.query(SpamLog).order_by(
            SpamLog.created_at.desc()).limit(limit).all()
    finally:
        session.close()


def get_statistics():
    """Get bot statistics"""
    session = get_session()
    try:
        total_users = session.query(User).count()
        total_orders = session.query(Order).count()
        new_orders = session.query(Order).filter(Order.status == 'new').count()
        in_progress = session.query(Order).filter(
            Order.status == 'in_progress').count()
        completed = session.query(Order).filter(
            Order.status == 'completed').count()
        issued = session.query(Order).filter(Order.status == 'issued').count()
        blocked_users = session.query(User).filter(
            User.is_blocked == True).count()
        spam_count = session.query(SpamLog).count()
        return {
            "total_users": total_users,
            "total_orders": total_orders,
            "new_orders": new_orders,
            "in_progress": in_progress,
            "completed": completed,
            "issued": issued,
            "blocked_users": blocked_users,
            "spam_count": spam_count
        }
    finally:
        session.close()


def get_moscow_date():
    """Get current date in Moscow timezone"""
    return datetime.now(MOSCOW_TZ).date()


def check_today_first_visit(user_id: int) -> bool:
    """Check if this is user's first visit today (Moscow time) and update last_visit_date"""
    session = get_session()
    try:
        today = get_moscow_date()
        user = session.query(User).filter(User.user_id == user_id).first()

        if not user:
            return True

        is_first_visit = user.last_visit_date != today

        if is_first_visit:
            user.last_visit_date = today
            user.last_active = datetime.now(MOSCOW_TZ)
            session.commit()

        return is_first_visit
    except Exception:
        session.rollback()
        return True
    finally:
        session.close()


def save_chat_history(user_id: int,
                      message: str,
                      response: str,
                      topic: str = 'general',
                      complexity: str = 'simple'):
    """Save chat message to history"""
    session = get_session()
    try:
        history = ChatHistory(user_id=user_id,
                              message=message[:500],
                              response=response[:1000],
                              topic=topic,
                              complexity=complexity)
        session.add(history)

        user = session.query(User).filter(User.user_id == user_id).first()
        if user:
            user.questions_count = (user.questions_count or 0) + 1

        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Error saving chat history: {e}")
    finally:
        session.close()


def get_user_chat_history(user_id: int, limit: int = 5):
    """Get recent chat history for user"""
    session = get_session()
    try:
        return session.query(ChatHistory).filter(
            ChatHistory.user_id == user_id).order_by(
                ChatHistory.created_at.desc()).limit(limit).all()
    finally:
        session.close()


def get_user_context(user_id: int) -> dict:
    """Get user context for adaptive prompts"""
    session = get_session()
    try:
        user = session.query(User).filter(User.user_id == user_id).first()
        history = session.query(ChatHistory).filter(
            ChatHistory.user_id == user_id).order_by(
                ChatHistory.created_at.desc()).limit(5).all()

        if not user:
            return {
                'is_new': True,
                'tone': 'friendly',
                'questions_count': 0,
                'recent_topics': [],
                'name': None
            }

        recent_topics = [h.topic for h in history if h.topic]

        return {
            'is_new': False,
            'tone': user.tone_preference or 'friendly',
            'questions_count': user.questions_count or 0,
            'recent_topics': recent_topics,
            'name': user.first_name
        }
    finally:
        session.close()


def update_user_tone(user_id: int, tone: str):
    """Update user's preferred tone"""
    session = get_session()
    try:
        user = session.query(User).filter(User.user_id == user_id).first()
        if user:
            user.tone_preference = tone
            session.commit()
            return True
        return False
    finally:
        session.close()


def complete_order(order_id: int) -> bool:
    """Mark order as completed and set completed_at"""
    session = get_session()
    try:
        order = session.query(Order).filter(Order.id == order_id).first()
        if order:
            order.status = 'completed'
            order.completed_at = datetime.now(MOSCOW_TZ)
            order.updated_at = datetime.now(MOSCOW_TZ)
            session.commit()
            return True
        return False
    finally:
        session.close()


def get_orders_pending_feedback():
    """Get orders that need feedback request (completed 3+ days ago, not requested)"""
    session = get_session()
    try:
        three_days_ago = datetime.now(MOSCOW_TZ) - timedelta(days=3)
        return session.query(Order).filter(
            Order.status == 'completed', Order.completed_at <= three_days_ago,
            Order.feedback_requested == False).all()
    finally:
        session.close()


def mark_feedback_requested(order_id: int):
    """Mark that feedback was requested for this order"""
    session = get_session()
    try:
        order = session.query(Order).filter(Order.id == order_id).first()
        if order:
            order.feedback_requested = True
            session.commit()
    finally:
        session.close()


def create_review(order_id: int,
                  user_id: int,
                  rating: int,
                  comment: str = None,
                  is_approved: bool = True,
                  rejected_reason: str = None) -> int:
    """Create a review for an order"""
    session = get_session()
    try:
        existing = session.query(Review).filter(
            Review.order_id == order_id).first()
        if existing:
            return None

        review = Review(
            order_id=order_id,
            user_id=user_id,
            rating=rating,
            comment=comment,
            is_approved=is_approved,
            rejected_reason=rejected_reason,
            published_at=datetime.now(MOSCOW_TZ) if is_approved else None)
        session.add(review)
        session.commit()
        return review.id
    except Exception as e:
        session.rollback()
        logger.error(f"Error creating review: {e}")
        return None
    finally:
        session.close()


def get_all_reviews(limit: int = 50, approved_only: bool = False):
    """Get all reviews"""
    session = get_session()
    try:
        query = session.query(Review)
        if approved_only:
            query = query.filter(Review.is_approved == True)
        return query.order_by(Review.created_at.desc()).limit(limit).all()
    finally:
        session.close()


def get_average_rating() -> float:
    """Get average rating from approved reviews"""
    session = get_session()
    try:
        result = session.query(func.avg(
            Review.rating)).filter(Review.is_approved == True).scalar()
        return round(float(result), 1) if result else 0.0
    finally:
        session.close()


def get_review_stats() -> dict:
    """Get review statistics"""
    session = get_session()
    try:
        total = session.query(Review).count()
        approved = session.query(Review).filter(
            Review.is_approved == True).count()
        pending = session.query(Review).filter(
            Review.is_approved == False,
            Review.rejected_reason == None).count()
        rejected = session.query(Review).filter(
            Review.rejected_reason != None).count()
        avg_rating = session.query(func.avg(
            Review.rating)).filter(Review.is_approved == True).scalar()

        rating_distribution = {}
        for i in range(1, 6):
            count = session.query(Review).filter(
                Review.rating == i, Review.is_approved == True).count()
            rating_distribution[i] = count

        return {
            'total': total,
            'approved': approved,
            'pending': pending,
            'rejected': rejected,
            'average_rating':
            round(float(avg_rating), 1) if avg_rating else 0.0,
            'distribution': rating_distribution
        }
    finally:
        session.close()


def moderate_review(review_id: int, approve: bool, reason: str = None) -> bool:
    """Approve or reject a review"""
    session = get_session()
    try:
        review = session.query(Review).filter(Review.id == review_id).first()
        if review:
            review.is_approved = approve
            if approve:
                review.published_at = datetime.now(MOSCOW_TZ)
                review.rejected_reason = None
            else:
                review.rejected_reason = reason
            session.commit()
            return True
        return False
    finally:
        session.close()


def has_review(order_id: int) -> bool:
    """Check if order already has a review"""
    session = get_session()
    try:
        return session.query(Review).filter(
            Review.order_id == order_id).first() is not None
    finally:
        session.close()


def get_user_reviews(user_id: int):
    """Get all reviews by user"""
    return []


def update_review_status(review_id: int, status: str):
    """Update review status"""
    pass


def get_recent_reviews(limit: int = 10):
    """Get recent reviews"""
    return []
