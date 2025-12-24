from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from functools import wraps
import sys
import os
import secrets
import html
import logging
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.database import (
    get_all_orders, get_all_users, get_spam_logs,
    get_statistics, update_order_status, get_orders_by_status,
    get_all_reviews, get_review_stats, moderate_review, get_average_rating,
    get_order, delete_order, delete_orders_bulk
)
import io
import csv

BOT_TOKEN = os.getenv('BOT_TOKEN')

STATUS_MESSAGES = {
    'in_progress': '🧵 Отличные новости! Ваш заказ #{order_id} уже в работе!\n\nНаши мастера с любовью трудятся над вашим изделием. Совсем скоро всё будет готово! ✨',
    'issued': '📤 Ваш заказ #{order_id} выдан!\n\nСпасибо, что выбрали нашу мастерскую. Будем рады видеть вас снова! 🪡',
    'completed': '''🎉 Ваш заказ #{order_id} выполнен!

Спасибо, что доверили нам свою вещь! Мы очень старались и надеемся, что результат вас порадует.

📍 <b>Забрать можно по адресу:</b>
г.Москва, м. Ховрино, ТЦ \"Бусиново\", 1 этаж

⏰ <b>Часы работы:</b>
Пн-Чт: 10:00-19:50
Пт: 10:00-19:00
Сб: 10:00-17:00
Вс: выходной

📞 +7 (968) 396-91-52

---

🙏 <b>Будем признательны за ваш отзыв!</b>

Поделитесь своими честными впечатлениями о нашей работе — это поможет нам стать лучше и подскажет другим клиентам.

👉 <a href="https://yandex.ru/maps/org/shveyny_hub/1233246900/reviews/?ll=37.488846%2C55.881644&z=13">Оставить отзыв на Яндекс.Картах</a>

Ждём вас! 🪡''',
    'cancelled': '😔 К сожалению, ваш заказ #{order_id} был отменён.\n\nЕсли у вас остались вопросы или вы хотите оформить новый заказ — мы всегда рады помочь!\n\n📞 +7 (968) 396-91-52'
}

def send_telegram_notification(user_id: int, message: str) -> bool:
    """Отправить уведомление клиенту через Telegram API"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not configured")
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
            logger.error(f"Failed to send notification: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        return False

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

def get_service_name(service_type):
    """Получить русское название услуги"""
    return SERVICE_NAMES.get(service_type, service_type or 'Услуга')

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))

ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')

logger.info(f"ADMIN_USERNAME loaded: '{ADMIN_USERNAME}'")
logger.info(f"ADMIN_PASSWORD exists: {ADMIN_PASSWORD is not None and len(ADMIN_PASSWORD) > 0}")


def check_auth(username, password):
    """Check if a username/password combination is valid"""
    logger.info(f"Login attempt: user='{username}', expected='{ADMIN_USERNAME}'")
    logger.info(f"Password match: {password == ADMIN_PASSWORD}")
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD


def requires_auth(f):
    """Decorator that requires session authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def sanitize_input(text):
    """Sanitize user input to prevent XSS"""
    if text is None:
        return None
    return html.escape(str(text))


@app.route('/health')
def health():
    """Health check эндпоинт"""
    import time
    stats = get_statistics()
    return jsonify({
        "status": "alive",
        "timestamp": time.time(),
        "orders": stats.get('total_orders', 0),
        "users": stats.get('total_users', 0)
    })


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        if check_auth(username, password):
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('index'))
        else:
            error = 'Неверный логин или пароль'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    """Logout"""
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@requires_auth
def index():
    """Главная страница админки"""
    stats = get_statistics()
    return render_template('index.html', stats=stats)


@app.route('/orders')
@requires_auth
def orders():
    """Страница заказов с фильтрами"""
    from datetime import datetime, timedelta
    
    status = request.args.get('status', None)
    period = request.args.get('period', None)
    user_id_filter = request.args.get('user_id', None)
    date_from = request.args.get('date_from', None)
    date_to = request.args.get('date_to', None)
    month_filter = request.args.get('month', None)
    year_filter = request.args.get('year', None)
    
    all_orders = get_all_orders(limit=500)
    
    if user_id_filter:
        try:
            user_id_int = int(user_id_filter)
            all_orders = [o for o in all_orders if o.user_id == user_id_int]
        except ValueError:
            pass
    
    now = datetime.now()
    
    if date_from and date_to:
        try:
            start = datetime.strptime(date_from, '%Y-%m-%d')
            end = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            all_orders = [o for o in all_orders if o.created_at and start <= o.created_at <= end]
        except ValueError:
            pass
    elif period:
        if period == 'today':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            all_orders = [o for o in all_orders if o.created_at and o.created_at >= start_date]
        elif period == 'yesterday':
            start_date = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            all_orders = [o for o in all_orders if o.created_at and start_date <= o.created_at < end_date]
        elif period == 'week':
            start_date = now - timedelta(days=7)
            all_orders = [o for o in all_orders if o.created_at and o.created_at >= start_date]
        elif period == 'month':
            start_date = now - timedelta(days=30)
            all_orders = [o for o in all_orders if o.created_at and o.created_at >= start_date]
    
    if month_filter and year_filter:
        try:
            m = int(month_filter)
            y = int(year_filter)
            all_orders = [o for o in all_orders if o.created_at and o.created_at.month == m and o.created_at.year == y]
        except ValueError:
            pass
    elif year_filter:
        try:
            y = int(year_filter)
            all_orders = [o for o in all_orders if o.created_at and o.created_at.year == y]
        except ValueError:
            pass
    
    counts = {
        'all': len(all_orders),
        'new': len([o for o in all_orders if o.status == 'new']),
        'in_progress': len([o for o in all_orders if o.status == 'in_progress']),
        'completed': len([o for o in all_orders if o.status == 'completed']),
        'issued': len([o for o in all_orders if o.status == 'issued']),
        'cancelled': len([o for o in all_orders if o.status == 'cancelled']),
    }
    
    if status:
        orders_list = [o for o in all_orders if o.status == status]
    else:
        orders_list = all_orders
    
    orders_list = sorted(orders_list, key=lambda x: x.created_at or datetime.min, reverse=True)
    
    years_available = sorted(set(o.created_at.year for o in get_all_orders(limit=500) if o.created_at), reverse=True)
    if not years_available:
        years_available = [now.year]
    
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
                          years_available=years_available)


@app.route('/users')
@requires_auth
def users():
    """Страница пользователей"""
    users_list = get_all_users()
    all_orders = get_all_orders(limit=1000)
    
    order_counts = {}
    for order in all_orders:
        uid = order.user_id
        if uid:
            order_counts[uid] = order_counts.get(uid, 0) + 1
    
    return render_template('users.html', users=users_list, order_counts=order_counts)


@app.route('/spam')
@requires_auth
def spam():
    """Страница журнала спама"""
    spam_list = get_spam_logs(limit=50)
    return render_template('spam.html', spam_logs=spam_list)


@app.route('/reviews')
@requires_auth
def reviews():
    """Страница отзывов"""
    filter_type = request.args.get('filter', 'all')
    
    if filter_type == 'approved':
        reviews_list = get_all_reviews(approved_only=True)
    else:
        reviews_list = get_all_reviews()
    
    stats = get_review_stats()
    return render_template('reviews.html', reviews=reviews_list, stats=stats, filter_type=filter_type)


@app.route('/api/reviews')
@requires_auth
def api_reviews():
    """API: Список отзывов"""
    reviews_list = get_all_reviews()
    return jsonify([{
        'id': r.id,
        'order_id': r.order_id,
        'user_id': r.user_id,
        'rating': r.rating,
        'comment': sanitize_input(r.comment),
        'is_approved': r.is_approved,
        'rejected_reason': sanitize_input(r.rejected_reason),
        'created_at': r.created_at.isoformat() if r.created_at else None
    } for r in reviews_list])


@app.route('/api/review/<int:review_id>/moderate', methods=['POST'])
@requires_auth
def api_moderate_review(review_id):
    """API: Модерация отзыва"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request body'}), 400
    
    approve = bool(data.get('approve', True))
    reason = sanitize_input(data.get('reason'))
    
    if reason and len(reason) > 500:
        return jsonify({'error': 'Reason too long'}), 400
    
    success = moderate_review(review_id, approve, reason)
    
    if success:
        return jsonify({'success': True, 'review_id': review_id, 'approved': approve})
    else:
        return jsonify({'error': 'Review not found'}), 404


@app.route('/api/reviews/stats')
@requires_auth
def api_review_stats():
    """API: Статистика отзывов"""
    stats = get_review_stats()
    return jsonify(stats)


@app.route('/api/stats')
@requires_auth
def api_stats():
    """API: Статистика"""
    stats = get_statistics()
    return jsonify(stats)


@app.route('/api/orders')
@requires_auth
def api_orders():
    """API: Список заказов"""
    orders_list = get_all_orders(limit=50)
    return jsonify([{
        'id': o.id,
        'user_id': o.user_id,
        'service_type': sanitize_input(o.service_type),
        'client_name': sanitize_input(o.client_name),
        'client_phone': sanitize_input(o.client_phone),
        'status': o.status,
        'created_at': o.created_at.isoformat() if o.created_at else None
    } for o in orders_list])


@app.route('/api/order/<int:order_id>/status', methods=['POST'])
@requires_auth
def api_update_order_status(order_id):
    """API: Обновить статус заказа"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request body'}), 400
    
    new_status = data.get('status')
    
    if new_status not in ['new', 'in_progress', 'completed', 'issued', 'cancelled']:
        return jsonify({'error': 'Invalid status'}), 400
    
    order = get_order(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    user_id = order.user_id
    
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
def api_send_confirmation(order_id):
    """API: Отправить подтверждение клиенту с номером заказа"""
    order = get_order(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    if not order.user_id:
        return jsonify({'error': 'User ID not found'}), 400
    
    try:
        confirmation_text = (
            f"✅ Ваш заказ №{order_id} успешно принят!\n\n"
            f"Спасибо за заказ. Скоро мы свяжемся с вами по телефону для уточнения деталей."
        )
        
        if BOT_TOKEN and order.user_id:
            url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
            payload = {
                'chat_id': order.user_id,
                'text': confirmation_text
            }
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                return jsonify({'success': True, 'message': 'Confirmation sent'})
            else:
                return jsonify({'error': 'Failed to send Telegram message'}), 500
        else:
            return jsonify({'error': 'Bot token or user_id missing'}), 400
            
    except Exception as e:
        logger.error(f"Error sending confirmation: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/users')
@requires_auth
def api_users():
    """API: Список пользователей"""
    users_list = get_all_users()
    return jsonify([{
        'id': u.id,
        'user_id': u.user_id,
        'username': sanitize_input(u.username),
        'first_name': sanitize_input(u.first_name),
        'phone': sanitize_input(u.phone),
        'is_blocked': u.is_blocked,
        'created_at': u.created_at.isoformat() if u.created_at else None
    } for u in users_list])


@app.route('/api/orders/export-csv')
@requires_auth
def api_export_csv():
    """API: Экспорт заказов в CSV"""
    from datetime import datetime, timedelta
    from flask import Response
    
    status = request.args.get('status', None)
    period = request.args.get('period', None)
    date_from = request.args.get('date_from', None)
    date_to = request.args.get('date_to', None)
    month_filter = request.args.get('month', None)
    year_filter = request.args.get('year', None)
    
    all_orders = get_all_orders(limit=1000)
    now = datetime.now()
    
    if date_from and date_to:
        try:
            start = datetime.strptime(date_from, '%Y-%m-%d')
            end = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            all_orders = [o for o in all_orders if o.created_at and start <= o.created_at <= end]
        except ValueError:
            pass
    elif period:
        if period == 'today':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            all_orders = [o for o in all_orders if o.created_at and o.created_at >= start_date]
        elif period == 'yesterday':
            start_date = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            all_orders = [o for o in all_orders if o.created_at and start_date <= o.created_at < end_date]
        elif period == 'week':
            start_date = now - timedelta(days=7)
            all_orders = [o for o in all_orders if o.created_at and o.created_at >= start_date]
        elif period == 'month':
            start_date = now - timedelta(days=30)
            all_orders = [o for o in all_orders if o.created_at and o.created_at >= start_date]
    
    if month_filter and year_filter:
        try:
            m = int(month_filter)
            y = int(year_filter)
            all_orders = [o for o in all_orders if o.created_at and o.created_at.month == m and o.created_at.year == y]
        except ValueError:
            pass
    elif year_filter:
        try:
            y = int(year_filter)
            all_orders = [o for o in all_orders if o.created_at and o.created_at.year == y]
        except ValueError:
            pass
    
    if status:
        all_orders = [o for o in all_orders if o.status == status]
    
    STATUS_LABELS = {
        'new': 'Новый',
        'in_progress': 'В работе',
        'completed': 'Готов',
        'issued': 'Выдан',
        'cancelled': 'Отменён'
    }
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['ID', 'Услуга', 'Клиент', 'Телефон', 'Статус', 'Дата создания'])
    
    for order in all_orders:
        writer.writerow([
            order.id,
            SERVICE_NAMES.get(order.service_type, order.service_type or ''),
            order.client_name or '',
            order.client_phone or '',
            STATUS_LABELS.get(order.status, order.status),
            order.created_at.strftime('%d.%m.%Y %H:%M') if order.created_at else ''
        ])
    
    output.seek(0)
    filename = f"orders_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@app.route('/api/orders/bulk-delete', methods=['POST'])
@requires_auth
def api_bulk_delete_orders():
    """API: Массовое удаление заказов"""
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
def api_delete_order(order_id):
    """API: Удалить один заказ"""
    success = delete_order(order_id)
    if success:
        logger.info(f"Deleted order {order_id}")
        return jsonify({'success': True, 'order_id': order_id})
    else:
        return jsonify({'error': 'Order not found or could not be deleted'}), 404


def run_webapp():
    """Запустить веб-приложение"""
    app.run(host='0.0.0.0', port=5000, debug=False)


if __name__ == '__main__':
    run_webapp()
