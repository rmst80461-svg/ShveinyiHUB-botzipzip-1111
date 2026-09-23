"""
Secure Flask admin application
- Uses password hashing (Werkzeug)
- CSRF protection (Flask-WTF) for forms, API endpoints are exempted
- Improved requires_auth decorator: returns JSON 401 for API requests
- Centralized order filtering function (DRY)
- CSV export with UTF-8 BOM for Excel
- Session cookie security flags

Requirements (install in your venv):
pip install flask flask-wtf python-dotenv requests werkzeug

Configure environment variables (recommended):
- FLASK_SECRET_KEY
- ADMIN_USERNAME (default: admin)
- ADMIN_PASSWORD_HASH (if not present, an .admin_password.hash file will be used/created)
- ADMIN_PASSWORD_FILE (optional; path to store the password hash)
- BOT_TOKEN (optional for Telegram notifications)
- PORT (default 5000)
- FLASK_ENV (development/production)

Note: templates and utils.database module should exist (same API as in your original code).
"""

from flask import Flask, render_template, jsonify, request, redirect, url_for, session, Response, make_response, current_app
from werkzeug.middleware.proxy_fix import ProxyFix
from functools import wraps
import sys
import os
import secrets
import html
import logging
import requests
from dotenv import load_dotenv
import io
import csv
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import CSRFProtect

# Create the application before defining any route handlers.
app = Flask(__name__)

# ----------------------------
# Load .env
# ----------------------------
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    # also try local .env
    local_env = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(local_env):
        load_dotenv(local_env)

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ----------------------------
# Add project root to path for utils import
# ----------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ----------------------------
# Import database utils
# ----------------------------
try:
    from utils.database import (
        get_all_orders, get_all_users, get_spam_logs,
        get_statistics, update_order_status, get_orders_by_status,
        get_all_reviews, get_review_stats, moderate_review, get_average_rating,
        get_order, delete_order, delete_orders_bulk, set_admin, get_user,
        get_funnel_stats, get_daily_stats, get_abandonment_stats
    )
except Exception as e:
    logger.critical(f"Failed to import database module: {e}")
    raise

# ----------------------------
# Configuration from env
# ----------------------------
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Persistent secret key - generate once and save to file if not in env
SECRET_KEY_FILE = os.path.join(os.path.dirname(__file__), '.flask_secret_key')
def get_or_create_secret_key():
    env_key = os.getenv('FLASK_SECRET_KEY')
    if env_key:
        return env_key
    # Try to load from file
    if os.path.exists(SECRET_KEY_FILE):
        try:
            with open(SECRET_KEY_FILE, 'r') as f:
                return f.read().strip()
        except:
            pass
    # Generate and save new key
    new_key = secrets.token_hex(32)
    try:
        with open(SECRET_KEY_FILE, 'w') as f:
            f.write(new_key)
        logger.info(f"Generated new Flask secret key and saved to {SECRET_KEY_FILE}")
    except:
        pass
    return new_key

FLASK_SECRET_KEY = get_or_create_secret_key()
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD_HASH = os.getenv('ADMIN_PASSWORD_HASH')  # preferred
ADMIN_PASSWORD_FILE = os.getenv('ADMIN_PASSWORD_FILE') or os.path.join(os.path.dirname(__file__), '.admin_password.hash')

# ----------------------------
# Password hash helpers
# ----------------------------

def load_password_hash():
    global ADMIN_PASSWORD_HASH
    if ADMIN_PASSWORD_HASH:
        return ADMIN_PASSWORD_HASH
    # try file
    try:
        if os.path.exists(ADMIN_PASSWORD_FILE):
            with open(ADMIN_PASSWORD_FILE, 'r', encoding='utf-8') as f:
                ADMIN_PASSWORD_HASH = f.read().strip()
                logger.info(f"Loaded admin password hash from {ADMIN_PASSWORD_FILE}")
                return ADMIN_PASSWORD_HASH
    except Exception as e:
        logger.warning(f"Could not read password file: {e}")

    # fallback: create default 'admin' hash (WARNING)
    fallback = generate_password_hash('admin')
    try:
        with open(ADMIN_PASSWORD_FILE, 'w', encoding='utf-8') as f:
            f.write(fallback)
            logger.warning(f"No admin password found — created default hash file at {ADMIN_PASSWORD_FILE}. Please change the password ASAP.")
    except Exception as e:
        logger.warning(f"Could not write default password file: {e}")
    ADMIN_PASSWORD_HASH = fallback
    return ADMIN_PASSWORD_HASH


def save_password_hash(new_hash: str):
    global ADMIN_PASSWORD_HASH
    ADMIN_PASSWORD_HASH = new_hash
    try:
        with open(ADMIN_PASSWORD_FILE, 'w', encoding='utf-8') as f:
            f.write(new_hash)
            logger.info(f"Saved new admin password hash to {ADMIN_PASSWORD_FILE}")
    except Exception as e:
        logger.warning(f"Could not save password hash to file: {e}")

# Ensure password hash is loaded
load_password_hash()

# ----------------------------
# Flask app init
# ----------------------------
# Добавляем ProxyFix для корректной работы за прокси (Bothost)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
app.secret_key = FLASK_SECRET_KEY

# Session configuration - persistent sessions
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),  # Session lasts 7 days
    SESSION_REFRESH_EACH_REQUEST=True  # Refresh session on each request
)
# Enable SESSION_COOKIE_SECURE only if running under https (controlled by env)
if os.getenv('FORCE_SECURE_COOKIES') == '1' or os.getenv('FLASK_ENV') == 'production':
    app.config['SESSION_COOKIE_SECURE'] = True

# CSRF protection for forms (API routes will be exempted individually)
csrf = CSRFProtect(app)

logger.info(f"ADMIN_USERNAME loaded: '{ADMIN_USERNAME}'")
logger.info("Application initialized.")

@app.before_request
def log_request_info():
    app.logger.info(f"Входящий запрос: {request.method} {request.url}")

@app.after_request
def log_response_info(response):
    app.logger.info(f"Ответ: {response.status}")
    return response

# ----------------------------
# Constants
# ----------------------------
STATUS_MESSAGES = {
    'in_progress': '🧵 Отличные новости! Ваш заказ #{order_id} уже в работе!\n\nНаши мастера с любовью трудятся над вашим изделием. Совсем скоро всё будет готово! ✨',
    'completed': ('🎉 Ваш заказ #{order_id} выполнен!\n\n'
                  '<b>Забрать можно по адресу:</b> г. Москва, (МЦД/м. Ховрино) ул. Маршала Федоренко д.12, , ТЦ "Бусиново", 1 этаж\n\n'
                  '<b>Часы работы:</b>\nПн-Чт: 10:00-19:50\nПт: 10:00-19:00\nСб: 10:00-17:00\nВс: выходной\n\n'
                  '📞 +7 (968) 396-91-52\n\n---\n\n🙏 <b>Будем признательны за ваш отзыв!</b>\n\n'
                  '👉 <a href="https://yandex.ru/maps/org/shveyny_hub/1233246900/reviews/">Оставить отзыв на Яндекс.Картах</a>\n\nЖдём вас! 🪡'),
    'issued': '📤 Ваш заказ #{order_id} выдан!\n\nСпасибо, что выбрали нашу мастерскую. Будем рады видеть вас снова! 🪡',
    'cancelled': '😔 К сожалению, ваш заказ #{order_id} был отменён.\n\nЕсли у вас остались вопросы или вы хотите оформить новый заказ — мы всегда рады помочь!\n\n📞 +7 (968) 396-91-52'
}

SERVICE_NAMES = {
    "jacket": "🧥 Ремонт пиджака",
    "leather": "🎒 Изделия из кожи",
    "curtains": "🪟 Пошив штор",
    "coat": "🧥 Ремонт куртки",
    "fur": "🐾 Шубы и дублёнки",
    "outerwear": "🧥 Плащ/пальто",
    "pants": "👖 Брюки/джинсы",
    "dress": "👗 Юбки/платья"
}

# ----------------------------
# Helpers
# ----------------------------
def send_telegram_notification(user_id: int, message: str) -> bool:
    """Send Telegram notification; returns True on success"""
    if not BOT_TOKEN:
        logger.debug("BOT_TOKEN not configured; skipping Telegram notification")
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": user_id,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=data, timeout=10)
        if response.status_code == 200:
            logger.info(f"Notification sent to user {user_id}")
            return True
        else:
            logger.warning(f"Telegram API returned {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")
        return False


def send_telegram_admin_message(user_id: int, message: str) -> bool:
    """Send a manually entered admin message through the bot."""
    return send_telegram_notification(
        user_id, f"📨 Сообщение от администратора:\n\n{html.escape(message)}"
    )


def get_service_name(service_type):
    return SERVICE_NAMES.get(service_type, service_type or 'Услуга')


def sanitize_input(text):
    if text is None:
        return None
    return html.escape(str(text))


def check_auth(username, password):
    """Check username/password using stored hash"""
    if username != ADMIN_USERNAME:
        return False
    pw_hash = load_password_hash()
    if not pw_hash:
        return False
    try:
        return check_password_hash(pw_hash, password)
    except Exception:
        return False


def requires_auth(f):
    """Decorator that requires session authentication. Returns JSON 401 for API calls."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            wants_json = (
                request.path.startswith('/api/')
                or request.is_json
                or 'application/json' in request.headers.get('Accept', '')
            )
            if wants_json:
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ----------------------------
# Centralized order filtering
# ----------------------------

def filter_orders(orders, *, user_id=None, date_from=None, date_to=None, period=None, month=None, year=None):
    """Filter orders list based on provided parameters. Assumes orders have .created_at (datetime) and .user_id, .status."""
    result = list(orders)
    now = datetime.now()

    if user_id is not None:
        try:
            uid = int(user_id)
            result = [o for o in result if getattr(o, 'user_id', None) == uid]
        except (ValueError, TypeError):
            pass

    if date_from and date_to:
        try:
            start = datetime.strptime(date_from, '%Y-%m-%d')
            end = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            result = [o for o in result if getattr(o, 'created_at', None) and start <= o.created_at <= end]
        except ValueError:
            pass
    elif period:
        if period == 'today':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            result = [o for o in result if getattr(o, 'created_at', None) and o.created_at >= start_date]
        elif period == 'yesterday':
            start_date = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            result = [o for o in result if getattr(o, 'created_at', None) and start_date <= o.created_at < end_date]
        elif period == 'week':
            start_date = now - timedelta(days=7)
            result = [o for o in result if getattr(o, 'created_at', None) and o.created_at >= start_date]
        elif period == 'month':
            start_date = now - timedelta(days=30)
            result = [o for o in result if getattr(o, 'created_at', None) and o.created_at >= start_date]

    if month and year:
        try:
            m = int(month)
            y = int(year)
            result = [o for o in result if getattr(o, 'created_at', None) and o.created_at.month == m and o.created_at.year == y]
        except ValueError:
            pass
    elif year:
        try:
            y = int(year)
            result = [o for o in result if getattr(o, 'created_at', None) and o.created_at.year == y]
        except ValueError:
            pass

    return result

# ----------------------------
# Routes
# ----------------------------
@app.route('/health')
def health():
    stats = get_statistics()
    return jsonify({
        "status": "alive",
        "timestamp": datetime.now().isoformat(),
        "orders": stats.get('total_orders', 0),
        "users": stats.get('total_users', 0)
    })


@app.route('/login', methods=['GET', 'POST'])
@csrf.exempt
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if check_auth(username, password):
            # Prevent session fixation
            session.clear()
            session.permanent = True  # Make session persistent (7 days)
            session['logged_in'] = True
            session['username'] = username
            logger.info(f"User '{username}' logged in successfully")
            return redirect(url_for('index'))
        else:
            logger.warning(f"Failed login attempt for username: '{username}'")
            error = 'Неверный логин или пароль'
    return render_template('login.html', error=error)


@app.route('/change-password', methods=['GET', 'POST'])
@requires_auth
def change_password():
    error = None
    success = None
    if request.method == 'POST':
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        if not new_password:
            error = 'Пароль не может быть пустым'
        elif len(new_password) < 6:
            error = 'Пароль слишком короткий (мин. 6 символов)'
        elif new_password != confirm_password:
            error = 'Пароли не совпадают'
        else:
            new_hash = generate_password_hash(new_password)
            save_password_hash(new_hash)
            success = 'Пароль успешно изменён!'
    return render_template('change_password.html', error=error, success=success)


@app.route('/logout')
def logout():
    username = session.get('username', 'unknown')
    session.clear()
    logger.info(f"User '{username}' logged out")
    return redirect(url_for('login'))


@app.route('/')
@requires_auth
def index():
    stats = get_statistics()
    return render_template('index.html', stats=stats)


@app.route('/analytics')
@requires_auth
def analytics():
    days = request.args.get('days', 30, type=int)
    
    funnel = get_funnel_stats(days)
    daily = get_daily_stats(days)
    abandonment = get_abandonment_stats(days)
    
    return render_template('analytics.html', 
                           funnel=funnel, 
                           daily=daily, 
                           abandonment=abandonment,
                           days=days)


@app.route('/api/analytics')
@requires_auth
def api_analytics():
    days = request.args.get('days', 30, type=int)
    
    funnel = get_funnel_stats(days)
    daily = get_daily_stats(days)
    abandonment = get_abandonment_stats(days)
    
    return jsonify({
        'funnel': funnel,
        'daily': daily,
        'abandonment': abandonment
    })


@app.route('/orders')
@requires_auth
def orders():
    status = request.args.get('status', None)
    period = request.args.get('period', None)
    user_id_filter = request.args.get('user_id', None)
    date_from = request.args.get('date_from', None)
    date_to = request.args.get('date_to', None)
    month_filter = request.args.get('month', None)
    year_filter = request.args.get('year', None)

    all_orders = get_all_orders(limit=1000)

    filtered = filter_orders(all_orders,
                             user_id=user_id_filter,
                             date_from=date_from,
                             date_to=date_to,
                             period=period,
                             month=month_filter,
                             year=year_filter)

    counts = {
        'all': len(filtered),
        'new': len([o for o in filtered if getattr(o, 'status', 'none') == 'new']),
        'accepted': len([o for o in filtered if getattr(o, 'status', 'none') == 'accepted']),
        'in_progress': len([o for o in filtered if getattr(o, 'status', 'none') == 'in_progress']),
        'completed': len([o for o in filtered if getattr(o, 'status', 'none') == 'completed']),
        'issued': len([o for o in filtered if getattr(o, 'status', 'none') == 'issued']),
        'cancelled': len([o for o in filtered if getattr(o, 'status', 'none') == 'cancelled']),
    }

    if status:
        orders_list = [o for o in filtered if getattr(o, 'status', 'none') == status]
    else:
        orders_list = filtered

    orders_list = sorted(orders_list, key=lambda x: getattr(x, 'created_at', datetime.min) or datetime.min, reverse=True)

    years_available = sorted({o.created_at.year for o in get_all_orders(limit=1000) if getattr(o, 'created_at', None)}, reverse=True)
    if not years_available:
        years_available = [datetime.now().year]

    # Получаем количество заказов для каждого пользователя для пометки "Постоянный клиент"
    user_order_counts = {}
    from utils.database import get_session, Order
    session = get_session()
    try:
        from sqlalchemy import func
        counts_data = session.query(Order.user_id, func.count(Order.id)).group_by(Order.user_id).all()
        user_order_counts = {str(uid): count for uid, count in counts_data}
    finally:
        session.close()

    return render_template('orders.html',
                          orders=orders_list,
                          service_names=SERVICE_NAMES,
                          counts=counts,
                          current_status=status,
                          period=period,
                          date_from=date_from,
                          date_to=date_to,
                          month_filter=month_filter,
                          year_filter=year_filter,
                          years_available=years_available,
                          user_order_counts=user_order_counts)


@app.route('/users')
@requires_auth
def users():
    users_list = get_all_users()
    all_orders = get_all_orders(limit=1000)

    order_counts = {}
    for order in all_orders:
        uid = getattr(order, 'user_id', None)
        if uid:
            order_counts[uid] = order_counts.get(uid, 0) + 1

    return render_template('users.html', users=users_list, order_counts=order_counts)


@app.route('/spam')
@requires_auth
def spam():
    spam_list = get_spam_logs(limit=50)
    return render_template('spam.html', spam_logs=spam_list)


@app.route('/reviews')
@requires_auth
def reviews():
    filter_type = request.args.get('filter', 'all')
    if filter_type == 'approved':
        reviews_list = get_all_reviews(approved_only=True)
    else:
        reviews_list = get_all_reviews()
    stats = get_review_stats()
    return render_template('reviews.html', reviews=reviews_list, stats=stats, filter_type=filter_type)


# ----------------------------
# API routes (JSON) — exempted from CSRF
# ----------------------------
@app.route('/api/reviews')
@requires_auth
@csrf.exempt
def api_reviews():
    reviews_list = get_all_reviews()
    return jsonify([{
        'id': r.id,
        'order_id': r.order_id,
        'user_id': r.user_id,
        'rating': r.rating,
        'comment': sanitize_input(r.comment),
        'is_approved': r.is_approved,
        'rejected_reason': sanitize_input(r.rejected_reason),
        'created_at': r.created_at.isoformat() if getattr(r, 'created_at', None) else None
    } for r in reviews_list])


@app.route('/api/review/<int:review_id>/moderate', methods=['POST'])
@requires_auth
@csrf.exempt
def api_moderate_review(review_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request body'}), 400

    approve = bool(data.get('approve', True))
    reason = sanitize_input(data.get('reason'))

    if reason and len(reason) > 500:
        return jsonify({'error': 'Reason too long'}), 400

    success = moderate_review(review_id, approve, reason or "")

    if success:
        return jsonify({'success': True, 'review_id': review_id, 'approved': approve})
    else:
        return jsonify({'error': 'Review not found'}), 404


@app.route('/api/reviews/stats')
@requires_auth
@csrf.exempt
def api_review_stats():
    stats = get_review_stats()
    return jsonify(stats)


@app.route('/api/stats')
@requires_auth
@csrf.exempt
def api_stats():
    stats = get_statistics()
    return jsonify(stats)


@app.route('/api/orders')
@requires_auth
@csrf.exempt
def api_orders():
    orders_list = get_all_orders(limit=50)
    return jsonify([{
        'id': o.id,
        'user_id': o.user_id,
        'service_type': sanitize_input(o.service_type),
        'client_name': sanitize_input(o.client_name),
        'client_phone': sanitize_input(o.client_phone),
        'status': o.status,
        'created_at': o.created_at.isoformat() if getattr(o, 'created_at', None) else None
    } for o in orders_list])


@app.route('/api/order/<int:order_id>/status', methods=['POST'])
@requires_auth
@csrf.exempt
def api_update_order_status(order_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request body'}), 400

    new_status = data.get('status')

    if new_status not in ['new', 'in_progress', 'completed', 'issued', 'cancelled']:
        return jsonify({'error': 'Invalid status'}), 400

    order = get_order(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404

    user_id = getattr(order, 'user_id', None)

    success = update_order_status(order_id, new_status)

    if success:
        if new_status in STATUS_MESSAGES and user_id:
            message = STATUS_MESSAGES[new_status].format(order_id=order_id)
            notification_sent = send_telegram_notification(user_id, message)
            logger.info(f"Status update notification for order {order_id}: sent={notification_sent}")

        return jsonify({'success': True, 'order_id': order_id, 'status': new_status})
    else:
        return jsonify({'error': 'Failed to update status'}), 500


@app.route('/api/order/<int:order_id>/confirmation', methods=['POST'])
@requires_auth
@csrf.exempt
def api_send_confirmation(order_id):
    return jsonify({'success': True, 'message': 'Confirmation disabled to avoid duplicates'})


@app.route('/api/order/<int:order_id>/message', methods=['POST'])
@requires_auth
@csrf.exempt
def api_send_order_message(order_id):
    """Send a manually entered message to an order's Telegram client."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON request body'}), 400

    message = data.get('message')
    if not isinstance(message, str):
        return jsonify({'error': 'Message must be a string'}), 400
    message = message.strip()
    if not message:
        return jsonify({'error': 'Message cannot be empty'}), 400
    if len(message) > 4000:
        return jsonify({'error': 'Message is too long (maximum 4000 characters)'}), 400

    order = get_order(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404

    user_id = getattr(order, 'user_id', None)
    if not user_id:
        return jsonify({'error': 'Order has no Telegram user'}), 400
    if not BOT_TOKEN:
        logger.error("Cannot send manual order message: BOT_TOKEN is not configured")
        return jsonify({'error': 'Telegram bot is not configured'}), 503

    try:
        sent = send_telegram_admin_message(int(user_id), message)
    except Exception:
        logger.exception("Unexpected error sending manual message for order %s", order_id)
        sent = False

    if not sent:
        logger.error("Telegram rejected manual message for order %s (user %s)", order_id, user_id)
        return jsonify({'error': 'Failed to send Telegram message'}), 502

    logger.info("Manual Telegram message sent for order %s to user %s", order_id, user_id)
    return jsonify({'success': True, 'order_id': order_id})


@app.route('/api/users')
@requires_auth
@csrf.exempt
def api_users():
    users_list = get_all_users()
    return jsonify([{
        'id': u.id,
        'user_id': u.user_id,
        'username': sanitize_input(u.username),
        'first_name': sanitize_input(u.first_name),
        'phone': sanitize_input(u.phone),
        'is_blocked': u.is_blocked,
        'created_at': u.created_at.isoformat() if getattr(u, 'created_at', None) else None
    } for u in users_list])


@app.route('/api/users/<int:user_id>/toggle-admin', methods=['POST'])
@requires_auth
@csrf.exempt
def api_toggle_admin(user_id):
    """Назначить или снять права администратора"""
    try:
        user = get_user(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'Пользователь не найден'}), 404
        
        new_status = not getattr(user, 'is_admin', False)
        set_admin(user_id, new_status)
        
        return jsonify({
            'success': True,
            'is_admin': new_status,
            'message': f"{'Назначен администратором' if new_status else 'Права администратора сняты'}"
        })
    except Exception as e:
        logger.error(f"Error toggling admin status: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/orders/export-csv')
@requires_auth
@csrf.exempt
def api_export_csv():
    status = request.args.get('status', None)
    period = request.args.get('period', None)
    date_from = request.args.get('date_from', None)
    date_to = request.args.get('date_to', None)
    month_filter = request.args.get('month', None)
    year_filter = request.args.get('year', None)

    all_orders = get_all_orders(limit=1000)

    filtered = filter_orders(all_orders,
                             date_from=date_from,
                             date_to=date_to,
                             period=period,
                             month=month_filter,
                             year=year_filter)

    if status:
        filtered = [o for o in filtered if getattr(o, 'status', None) == status]

    STATUS_LABELS = {
        'new': 'Новый',
        'in_progress': 'В работе',
        'completed': 'Готов',
        'issued': 'Выдан',
        'cancelled': 'Отменён'
    }

    output = io.StringIO()
    # BOM for Excel (Windows) compatibility
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['ID', 'Услуга', 'Клиент', 'Телефон', 'Статус', 'Дата создания'])

    for order in filtered:
        writer.writerow([
            getattr(order, 'id', ''),
            SERVICE_NAMES.get(getattr(order, 'service_type', None), getattr(order, 'service_type', '') or ''),
            getattr(order, 'client_name', '') or '',
            getattr(order, 'client_phone', '') or '',
            STATUS_LABELS.get(getattr(order, 'status', None), getattr(order, 'status', '')),
            order.created_at.strftime('%d.%m.%Y %H:%M') if getattr(order, 'created_at', None) else ''
        ])

    output.seek(0)
    filename = f"orders_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response


@app.route('/api/orders/bulk-delete', methods=['POST'])
@requires_auth
@csrf.exempt
def api_bulk_delete_orders():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request body'}), 400

    order_ids = data.get('ids', [])

    if not order_ids or not isinstance(order_ids, list):
        return jsonify({'error': 'No order ids provided'}), 400

    try:
        order_ids = [int(oid) for oid in order_ids]
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid order ids'}), 400

    if len(order_ids) > 100:
        return jsonify({'error': 'Too many orders to delete at once (max 100)'}), 400

    valid_ids = [oid for oid in order_ids if 0 < oid < 2147483647]
    if not valid_ids:
        return jsonify({'error': 'No valid order ids'}), 400

    deleted_count = delete_orders_bulk(valid_ids)
    logger.info(f"Bulk deleted {deleted_count} orders: {valid_ids}")

    return jsonify({'success': True, 'deleted': deleted_count})


@app.route('/api/order/<int:order_id>', methods=['DELETE'])
@requires_auth
@csrf.exempt
def api_delete_order(order_id):
    success = delete_order(order_id)
    if success:
        logger.info(f"Deleted order {order_id}")
        return jsonify({'success': True, 'order_id': order_id})
    else:
        return jsonify({'error': 'Order not found or could not be deleted'}), 404


# ----------------------------
# Error handlers for JSON APIs
# ----------------------------
@app.errorhandler(401)
def unauthorized(e):
    if request.path.startswith('/api/') or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({'error': 'Unauthorized'}), 401
    return redirect(url_for('login'))


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/') or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({'error': 'Not found'}), 404
    return "<h1>404 Not Found</h1>", 404


@app.errorhandler(500)
def server_error(e):
    logger.exception('Server error')
    if request.path.startswith('/api/') or 'application/json' in request.headers.get('Accept', ''):
        return jsonify({'error': 'Internal server error'}), 500
    return "<h1>500 Internal Server Error</h1>", 500


# ----------------------------
# Run
# ----------------------------
def run_webapp():
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)


if __name__ == '__main__':
    run_webapp()
