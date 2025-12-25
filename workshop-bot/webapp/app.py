from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from functools import wraps
import sys
import os
import secrets
import html
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.database import (get_all_orders, get_all_users, get_spam_logs,
                            get_statistics, update_order_status, get_order,
                            delete_order)

BOT_TOKEN = os.getenv('BOT_TOKEN')

SERVICE_NAMES = {
    'jacket': 'Ремонт куртки',
    'leather': 'Ремонт кожи',
    'curtains': 'Ремонт штор',
    'coat': 'Ремонт пальто',
    'fur': 'Ремонт меха',
    'outerwear': 'Ремонт верхней одежды',
    'pants': 'Ремонт брюк',
    'dress': 'Ремонт платья'
}

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))

ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')


def check_auth(username, password):
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD


def requires_auth(f):

    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated


def sanitize_input(text):
    if text is None:
        return None
    return html.escape(str(text))


@app.route('/health')
def health():
    import time
    stats = get_statistics()
    return jsonify({
        'status': 'alive',
        'timestamp': time.time(),
        'orders': stats.get('total_orders', 0),
        'users': stats.get('total_users', 0)
    })


@app.route('/login', methods=['GET', 'POST'])
def login():
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
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@requires_auth
def index():
    stats = get_statistics()
    return render_template('index.html', stats=stats)


@app.route('/orders')
@requires_auth
def orders():
    from datetime import datetime, timedelta

    status = request.args.get('status', None)
    period = request.args.get('period', None)
    date_from = request.args.get('datefrom', None)
    date_to = request.args.get('dateto', None)
    month_filter = request.args.get('month', None)
    year_filter = request.args.get('year', None)

    all_orders = get_all_orders(limit=500)
    now = datetime.now()

    # Apply filters
    if date_from and date_to:
        try:
            start = datetime.strptime(date_from, '%Y-%m-%d')
            end = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23,
                                                                 minute=59,
                                                                 second=59)
            all_orders = [
                o for o in all_orders
                if o.created_at and start <= o.created_at <= end
            ]
        except ValueError:
            pass
    elif period:
        if period == 'today':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            all_orders = [
                o for o in all_orders
                if o.created_at and o.created_at >= start_date
            ]
        elif period == 'week':
            start_date = now - timedelta(days=7)
            all_orders = [
                o for o in all_orders
                if o.created_at and o.created_at >= start_date
            ]
        elif period == 'month':
            start_date = now - timedelta(days=30)
            all_orders = [
                o for o in all_orders
                if o.created_at and o.created_at >= start_date
            ]

    if month_filter and year_filter:
        try:
            m = int(month_filter)
            y = int(year_filter)
            all_orders = [
                o for o in all_orders if o.created_at
                and o.created_at.month == m and o.created_at.year == y
            ]
        except ValueError:
            pass

    counts = {
        'all': len(all_orders),
        'new': len([o for o in all_orders if o.status == 'new']),
        'inprogress': len([o for o in all_orders if o.status == 'inprogress']),
        'completed': len([o for o in all_orders if o.status == 'completed']),
        'issued': len([o for o in all_orders if o.status == 'issued']),
        'cancelled': len([o for o in all_orders if o.status == 'cancelled'])
    }

    if status:
        orders_list = [o for o in all_orders if o.status == status]
    else:
        orders_list = all_orders

    orders_list = sorted(orders_list,
                         key=lambda x: x.created_at or datetime.min,
                         reverse=True)

    years_available = sorted(set(o.created_at.year
                                 for o in get_all_orders(limit=500)
                                 if o.created_at),
                             reverse=True)
    if not years_available:
        years_available = [now.year]

    return render_template('orders.html',
                           orders=orders_list,
                           servicenames=SERVICE_NAMES,
                           counts=counts,
                           currentstatus=status,
                           period=period,
                           datefrom=date_from,
                           dateto=date_to,
                           monthfilter=month_filter,
                           yearfilter=year_filter,
                           yearsavailable=years_available)


@app.route('/users')
@requires_auth
def users():
    users_list = get_all_users()
    all_orders = get_all_orders(limit=1000)

    order_counts = {}
    for order in all_orders:
        uid = order.user_id
        if uid:
            order_counts[uid] = order_counts.get(uid, 0) + 1

    return render_template('users.html',
                           users=users_list,
                           ordercounts=order_counts)


@app.route('/spam')
@requires_auth
def spam():
    spam_list = get_spam_logs(limit=50)
    return render_template('spam.html', spamlogs=spam_list)


@app.route('/api/stats')
@requires_auth
def api_stats():
    stats = get_statistics()
    return jsonify(stats)


@app.route('/api/orders')
@requires_auth
def api_orders():
    orders_list = get_all_orders(limit=50)
    return jsonify([{
        'id':
        o.id,
        'userid':
        o.user_id,
        'servicetype':
        sanitize_input(o.service_type),
        'clientname':
        sanitize_input(o.client_name),
        'clientphone':
        sanitize_input(o.client_phone),
        'status':
        o.status,
        'createdat':
        o.created_at.isoformat() if o.created_at else None
    } for o in orders_list])


@app.route('/api/order/<int:order_id>/status', methods=['POST'])
@requires_auth
def api_update_order_status(order_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request body'}), 400

    new_status = data.get('status')
    if new_status not in [
            'new', 'inprogress', 'completed', 'issued', 'cancelled'
    ]:
        return jsonify({'error': 'Invalid status'}), 400

    order = get_order(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404

    success = update_order_status(order_id, new_status)
    if success:
        return jsonify({
            'success': True,
            'orderid': order_id,
            'status': new_status
        })
    else:
        return jsonify({'error': 'Failed to update status'}), 500


@app.route('/api/order/<int:order_id>', methods=['DELETE'])
@requires_auth
def api_delete_order(order_id):
    success = delete_order(order_id)
    if success:
        logger.info(f"Deleted order {order_id}")
        return jsonify({'success': True, 'orderid': order_id})
    else:
        return jsonify({'error': 'Order not found'}), 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
