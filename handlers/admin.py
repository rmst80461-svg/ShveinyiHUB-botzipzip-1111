from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import (
    get_statistics, get_all_orders, get_all_users, 
    get_spam_logs, set_admin, is_admin, get_orders_by_status
)
import os
import logging

logger = logging.getLogger(__name__)

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

ADMIN_IDS = []


def load_admin_ids():
    """Load admin IDs from environment"""
    global ADMIN_IDS
    admin_id = os.getenv('ADMIN_ID')
    if admin_id:
        try:
            ADMIN_IDS = [int(admin_id)]
        except ValueError:
            pass


def is_user_admin(user_id: int) -> bool:
    """Check if user is admin"""
    load_admin_ids()
    return user_id in ADMIN_IDS or is_admin(user_id)


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Статистика бота"""
    user_id = update.effective_user.id
    
    if not is_user_admin(user_id):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    stats = get_statistics()
    
    text = (
        "📊 *Статистика бота*\n\n"
        f"👥 Пользователей: {stats['total_users']}\n"
        f"📦 Всего заказов: {stats['total_orders']}\n"
        f"🆕 Новых: {stats['new_orders']}\n"
        f"🔄 В работе: {stats['in_progress']}\n"
        f"✅ Выполнено: {stats['completed']}\n"
        f"🚫 Заблокировано: {stats['blocked_users']}\n"
        f"🛑 Спам-атак: {stats['spam_count']}"
    )
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Список заказов"""
    user_id = update.effective_user.id
    
    if not is_user_admin(user_id):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    orders = get_all_orders(limit=20)
    
    if not orders:
        await update.message.reply_text("📋 Заказов пока нет.")
        return
    
    text = "📋 *Последние заказы:*\n\n"
    
    for order in orders:
        status_emoji = {
            'new': '🆕',
            'in_progress': '🔄',
            'completed': '✅',
            'cancelled': '❌'
        }.get(order.status, '❓')
        
        service_name = SERVICE_NAMES.get(order.service_type, order.service_type or 'Услуга')
        
        text += (
            f"{status_emoji} *#{order.id}* - {service_name}\n"
            f"   👤 {order.client_name or 'Не указано'} | 📞 {order.client_phone or 'Нет'}\n\n"
        )
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def admin_new_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Новые заказы"""
    user_id = update.effective_user.id
    
    if not is_user_admin(user_id):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    orders = get_orders_by_status('new')
    
    if not orders:
        await update.message.reply_text("✅ Новых заказов нет!")
        return
    
    text = f"🆕 *Новые заказы ({len(orders)}):*\n\n"
    
    for order in orders[:10]:
        service_name = SERVICE_NAMES.get(order.service_type, order.service_type or 'Услуга')
        text += (
            f"*#{order.id}* - {service_name}\n"
            f"👤 {order.client_name or 'Не указано'}\n"
            f"📞 {order.client_phone or 'Нет'}\n"
            f"📸 Фото: {'Да' if order.photo_file_id else 'Нет'}\n\n"
        )
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Список пользователей"""
    user_id = update.effective_user.id
    
    if not is_user_admin(user_id):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    users = get_all_users()
    
    text = f"👥 *Пользователи ({len(users)}):*\n\n"
    
    for user in users[:20]:
        name = user.first_name or user.username or f"ID: {user.user_id}"
        text += f"• {name}"
        if user.phone:
            text += f" ({user.phone})"
        text += "\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def admin_spam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Журнал спама"""
    user_id = update.effective_user.id
    
    if not is_user_admin(user_id):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    spam_logs = get_spam_logs(limit=10)
    
    if not spam_logs:
        await update.message.reply_text("🛑 Спам-атак не зафиксировано.")
        return
    
    text = "🛑 *Последние спам-атаки:*\n\n"
    
    for log in spam_logs:
        text += (
            f"👤 ID пользователя: {log.user_id}\n"
            f"💬 {log.message[:50]}...\n"
            f"🏷 Причина: {log.reason}\n\n"
        )
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начало рассылки"""
    user_id = update.effective_user.id
    
    if not is_user_admin(user_id):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    context.user_data['broadcast_mode'] = True
    
    await update.message.reply_text(
        "📣 *Режим рассылки*\n\n"
        "Введите сообщение для рассылки всем пользователям.\n"
        "Для отмены введите /cancel",
        parse_mode="Markdown"
    )


async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправка рассылки"""
    if not context.user_data.get('broadcast_mode'):
        return
    
    user_id = update.effective_user.id
    
    if not is_user_admin(user_id):
        return
    
    message = update.message.text
    
    if message == '/cancel':
        context.user_data['broadcast_mode'] = False
        await update.message.reply_text("❌ Рассылка отменена.")
        return
    
    users = get_all_users()
    sent = 0
    failed = 0
    
    await update.message.reply_text(f"📤 Отправка рассылки {len(users)} пользователям...")
    
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user.user_id,
                text=f"📣 *Сообщение от мастерской:*\n\n{message}",
                parse_mode="Markdown"
            )
            sent += 1
        except Exception as e:
            failed += 1
            logger.error(f"Failed to send broadcast to {user.user_id}: {e}")
    
    context.user_data['broadcast_mode'] = False
    
    await update.message.reply_text(
        f"✅ *Рассылка завершена*\n\n"
        f"📨 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}",
        parse_mode="Markdown"
    )


async def set_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Добавить админа"""
    user_id = update.effective_user.id
    
    if not is_user_admin(user_id):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    if not context.args:
        await update.message.reply_text("Использование: /setadmin <user_id>")
        return
    
    try:
        new_admin_id = int(context.args[0])
        set_admin(new_admin_id, True)
        await update.message.reply_text(f"✅ Пользователь {new_admin_id} добавлен как админ.")
    except ValueError:
        await update.message.reply_text("❌ Неверный ID пользователя.")


def get_admin_menu_keyboard(stats=None):
    """Клавиатура админ-меню"""
    if stats is None:
        stats = get_statistics()
    
    new_count = stats.get('new_orders', 0)
    in_progress = stats.get('in_progress', 0)
    completed = stats.get('completed', 0)
    issued = stats.get('issued', 0)
    
    keyboard = [
        [
            InlineKeyboardButton(f"🆕 Новые ({new_count})", callback_data="admin_orders_new"),
            InlineKeyboardButton(f"🔄 В работе ({in_progress})", callback_data="admin_orders_in_progress")
        ],
        [
            InlineKeyboardButton(f"✅ Готовые ({completed})", callback_data="admin_orders_completed"),
            InlineKeyboardButton(f"📤 Выданные ({issued})", callback_data="admin_orders_issued")
        ],
        [
            InlineKeyboardButton("👥 Клиенты", callback_data="admin_clients"),
            InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton("📅 За сегодня", callback_data="admin_stats_today"),
            InlineKeyboardButton("📆 За неделю", callback_data="admin_stats_week")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ-меню для управления заказами"""
    user_id = update.effective_user.id
    
    if not is_user_admin(user_id):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    stats = get_statistics()
    
    text = (
        "📋 *Админ-панель заказов*\n\n"
        f"🆕 Новых: {stats['new_orders']}\n"
        f"🔄 В работе: {stats['in_progress']}\n"
        f"✅ Готовых: {stats['completed']}\n"
        f"📤 Выданных: {stats.get('issued', 0)}\n\n"
        "Выберите категорию:"
    )
    
    await update.message.reply_text(
        text,
        reply_markup=get_admin_menu_keyboard(stats),
        parse_mode="Markdown"
    )


async def admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатий в админ-меню"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return
    
    data = query.data
    
    if data == "admin_stats":
        stats = get_statistics()
        text = (
            "📊 *Общая статистика*\n\n"
            f"👥 Пользователей: {stats['total_users']}\n"
            f"📦 Всего заказов: {stats['total_orders']}\n"
            f"🆕 Новых: {stats['new_orders']}\n"
            f"🔄 В работе: {stats['in_progress']}\n"
            f"✅ Готовых: {stats['completed']}\n"
            f"📤 Выданных: {stats.get('issued', 0)}\n"
            f"🚫 Заблокировано: {stats['blocked_users']}\n"
            f"🛑 Спам-атак: {stats['spam_count']}"
        )
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
    
    if data == "admin_stats_today":
        from datetime import datetime, timedelta
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        orders = get_all_orders(limit=500)
        today_orders = [o for o in orders if o.created_at and o.created_at >= today]
        
        new_count = len([o for o in today_orders if o.status == 'new'])
        in_progress = len([o for o in today_orders if o.status == 'in_progress'])
        completed = len([o for o in today_orders if o.status == 'completed'])
        issued = len([o for o in today_orders if o.status == 'issued'])
        
        text = (
            "📅 *Статистика за сегодня*\n\n"
            f"📦 Всего заказов: {len(today_orders)}\n"
            f"🆕 Новых: {new_count}\n"
            f"🔄 В работе: {in_progress}\n"
            f"✅ Готовых: {completed}\n"
            f"📤 Выданных: {issued}"
        )
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
    
    if data == "admin_stats_week":
        from datetime import datetime, timedelta
        week_ago = datetime.now() - timedelta(days=7)
        orders = get_all_orders(limit=500)
        week_orders = [o for o in orders if o.created_at and o.created_at >= week_ago]
        
        new_count = len([o for o in week_orders if o.status == 'new'])
        in_progress = len([o for o in week_orders if o.status == 'in_progress'])
        completed = len([o for o in week_orders if o.status == 'completed'])
        issued = len([o for o in week_orders if o.status == 'issued'])
        
        text = (
            "📆 *Статистика за неделю*\n\n"
            f"📦 Всего заказов: {len(week_orders)}\n"
            f"🆕 Новых: {new_count}\n"
            f"🔄 В работе: {in_progress}\n"
            f"✅ Готовых: {completed}\n"
            f"📤 Выданных: {issued}"
        )
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
    
    if data == "admin_clients":
        users = get_all_users()
        orders = get_all_orders(limit=1000)
        
        order_counts = {}
        for order in orders:
            uid = order.user_id
            if uid:
                order_counts[uid] = order_counts.get(uid, 0) + 1
        
        sorted_users = sorted(users, key=lambda u: order_counts.get(u.user_id, 0), reverse=True)
        
        text = f"👥 *Клиенты* ({len(users)})\n\n"
        
        for user in sorted_users[:15]:
            count = order_counts.get(user.user_id, 0)
            name = user.first_name or user.username or f"ID: {user.user_id}"
            
            if count >= 5:
                badge = "🏆"
            elif count >= 3:
                badge = "⭐"
            elif count >= 1:
                badge = "👤"
            else:
                badge = "🆕"
            
            text += f"{badge} {name} — {count} заказов\n"
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
    
    if data == "open_web_admin":
        web_admin_url = os.getenv('REPLIT_DEV_DOMAIN', '')
        if web_admin_url:
            web_admin_url = f"https://{web_admin_url}"
        else:
            web_admin_url = "https://workspace.replit.app"
        
        keyboard = [
            [InlineKeyboardButton("🌐 Открыть веб-админку", url=web_admin_url)],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")]
        ]
        await query.edit_message_text(
            "🌐 *Веб-панель управления*\n\n"
            "Нажмите кнопку ниже для перехода:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    if data == "admin_back_menu":
        stats = get_statistics()
        text = (
            "📋 *Админ-панель заказов*\n\n"
            f"🆕 Новых: {stats['new_orders']}\n"
            f"🔄 В работе: {stats['in_progress']}\n"
            f"✅ Готовых: {stats['completed']}\n"
            f"📤 Выданных: {stats.get('issued', 0)}\n\n"
            "Выберите категорию:"
        )
        await query.edit_message_text(text, reply_markup=get_admin_menu_keyboard(stats), parse_mode="Markdown")
        return
    
    status_map = {
        "admin_orders_new": ("new", "🆕 Новые заказы"),
        "admin_orders_in_progress": ("in_progress", "🔄 Заказы в работе"),
        "admin_orders_completed": ("completed", "✅ Готовые заказы"),
        "admin_orders_issued": ("issued", "📤 Выданные заказы")
    }
    
    if data in status_map:
        status, title = status_map[data]
        orders = get_orders_by_status(status)
        
        if not orders:
            text = f"{title}\n\n📭 Заказов нет"
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return
        
        text = f"*{title}* ({len(orders)}):\n\n"
        keyboard = []
        
        for order in orders[:10]:
            service_name = SERVICE_NAMES.get(order.service_type, order.service_type or 'Услуга')
            phone = order.client_phone or "📲 Telegram"
            text += f"#{order.id} • {service_name}\n👤 {order.client_name or 'Аноним'} | {phone}\n\n"
            keyboard.append([InlineKeyboardButton(f"📦 Заказ #{order.id}", callback_data=f"admin_view_{order.id}")])
        
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def admin_view_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Просмотр отдельного заказа"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        return
    
    from utils.database import get_order
    
    order_id = int(query.data.replace("admin_view_", ""))
    order = get_order(order_id)
    
    if not order:
        await query.answer("Заказ не найден", show_alert=True)
        return
    
    service_name = SERVICE_NAMES.get(order.service_type, order.service_type or 'Услуга')
    status_text = {
        'new': '🆕 Новый',
        'in_progress': '🔄 В работе',
        'completed': '✅ Готов',
        'issued': '📤 Выдан',
        'cancelled': '❌ Отменён'
    }.get(order.status, order.status)
    
    phone_display = order.client_phone if order.client_phone and order.client_phone != "Telegram" else "📲 Telegram"
    
    text = (
        f"📦 *Заказ #{order.id}*\n\n"
        f"🏷 *Услуга:* {service_name}\n"
        f"👤 *Клиент:* {order.client_name or 'Не указано'}\n"
        f"📞 *Телефон:* {phone_display}\n"
        f"📊 *Статус:* {status_text}\n"
        f"📅 *Дата:* {order.created_at.strftime('%d.%m.%Y %H:%M') if order.created_at else 'Н/Д'}\n"
        f"📸 *Фото:* {'Да' if order.photo_file_id else 'Нет'}"
    )
    
    keyboard = []
    
    if order.status == 'new':
        keyboard.append([
            InlineKeyboardButton("🔄 В работу", callback_data=f"status_in_progress_{order.id}"),
            InlineKeyboardButton("❌ Отменить", callback_data=f"status_cancelled_{order.id}")
        ])
    elif order.status == 'in_progress':
        keyboard.append([
            InlineKeyboardButton("✅ Готов", callback_data=f"status_completed_{order.id}"),
            InlineKeyboardButton("❌ Отменить", callback_data=f"status_cancelled_{order.id}")
        ])
    elif order.status == 'completed':
        keyboard.append([
            InlineKeyboardButton("📤 Выдан", callback_data=f"status_issued_{order.id}")
        ])
    
    keyboard.append([
        InlineKeyboardButton(f"✉️ Написать", url=f"tg://user?id={order.user_id}"),
        InlineKeyboardButton(f"🧾 Квитанция", callback_data=f"resend_receipt_{order.id}")
    ])
    
    back_status = {
        'new': 'admin_orders_new',
        'in_progress': 'admin_orders_in_progress',
        'completed': 'admin_orders_completed',
        'issued': 'admin_orders_issued'
    }.get(order.status, 'admin_back_menu')
    
    keyboard.append([InlineKeyboardButton("◀️ Назад к списку", callback_data=back_status)])
    
    if order.photo_file_id:
        try:
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=order.photo_file_id,
                caption=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except Exception:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def open_web_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открыть веб-админку"""
    query = update.callback_query
    await query.answer()
    
    domain = os.getenv('REPLIT_DEV_DOMAIN', '')
    if domain:
        url = f"https://{domain}"
    else:
        url = "Веб-панель недоступна"
    
    await query.message.reply_text(
        f"🌐 *Веб-панель администратора*\n\n"
        f"Откройте ссылку для управления:\n{url}",
        parse_mode="Markdown"
    )
