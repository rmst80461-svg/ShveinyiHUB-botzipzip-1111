"""
Полнофункциональный обработчик админ-панели для бота.
"""
import os
import logging
import asyncio
from typing import List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# Локальные зависимости
from utils.database import (
    get_statistics,
    get_all_orders,
    get_all_users,
    get_spam_logs,
    set_admin,
    is_admin,
    get_orders_by_status,
    get_order,
    update_order_status,
    get_admins,
    delete_order,
)
from keyboards import (
    get_admin_main_menu,
    get_admin_orders_submenu,
    get_admin_back_menu,
    get_admin_order_detail_keyboard,
)

logger = logging.getLogger(__name__)


def get_env_admin_ids() -> List[int]:
    """Получить актуальный список админов из переменных окружения"""
    admin_ids = []
    env_ids = str(os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID") or "")
    clean_env_ids = env_ids.replace(";", ",").replace(" ", ",")
    for id_str in clean_env_ids.split(","):
        if id_str.strip():
            try:
                admin_ids.append(int(id_str.strip()))
            except ValueError:
                pass
    return admin_ids


def _get_web_admin_orders_url() -> str:
    """Сформировать URL веб-админки для страницы заказов"""
    web_admin_url = os.getenv("WEB_ADMIN_URL") or (f"https://{os.getenv('REPLIT_DEV_DOMAIN')}" if os.getenv('REPLIT_DEV_DOMAIN') else "")
    if web_admin_url:
        return f"{web_admin_url.rstrip('/')}/orders"
    return ""


def get_admin_ids() -> List[int]:
    """Вернуть список всех admin ids (ENV + БД)"""
    ids = get_env_admin_ids()
    try:
        db_admins = get_admins() if callable(get_admins) else []
        for a in db_admins:
            try:
                uid = int(a.user_id)
                if uid not in ids:
                    ids.append(uid)
            except Exception:
                pass
    except Exception:
        logger.debug("get_admins not available or failed")
    return ids


def is_user_admin(user_id: int) -> bool:
    """Проверка прав администратора: ENV_ADMIN_IDS или флаг is_admin из БД"""
    if not user_id:
        return False
    
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return False
    
    admin_ids = get_env_admin_ids()
    if user_id in admin_ids:
        return True
        
    try:
        from utils.database import is_admin as db_is_admin
        return bool(db_is_admin(user_id))
    except Exception as e:
        logger.error(f"Error checking admin status in DB for {user_id}: {e}")
        return False


# ---------------- Команды ----------------


async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/admin — показать главное админ-меню"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ У вас нет доступа к этой команде.")
        return

    text = "📋 *Админ-панель*\n\nВыберите раздел для управления:"
    await update.effective_message.reply_text(
        text, reply_markup=get_admin_main_menu(), parse_mode="Markdown"
    )


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats — показать статистику"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ У вас нет доступа.")
        return

    try:
        stats = get_statistics()
        text = (
            "📊 *Статистика бота*\n\n"
            f"👥 Пользователей: {stats.get('total_users', 0)}\n"
            f"📦 Всего заказов: {stats.get('total_orders', 0)}\n"
            f"🆕 Новых: {stats.get('new_orders', 0)}\n"
            f"🔄 В работе: {stats.get('in_progress', 0)}\n"
            f"✅ Выполнено: {stats.get('completed', 0)}\n"
            f"📤 Выдано: {stats.get('issued', 0)}\n"
            f"🚫 Заблокировано: {stats.get('blocked_users', 0)}\n"
            f"🛑 Спам-записей: {stats.get('spam_count', 0)}"
        )
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats"),
            InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")
        ]])
        
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await update.effective_message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    except Exception:
        logger.exception("Ошибка при формировании статистики")
        error_text = "❌ Ошибка при получении статистики."
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(error_text)
        else:
            await update.effective_message.reply_text(error_text)


async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/orders — вывести заказы с пагинацией"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ У вас нет доступа.")
        return

    status_filter = context.user_data.get('admin_orders_filter', 'all')
    status_str = str(status_filter).lower()
    if "все заказы" in status_str or "📊" in status_str or not status_filter:
        status_filter = "all"
    
    normalized_filter = status_str
    for emoji in ["📊", "📦", "📋", "⏳", "✅", "📤"]:
        normalized_filter = normalized_filter.replace(emoji, "")
    normalized_filter = normalized_filter.strip()
    
    if "сегодня в работе" in normalized_filter:
        status_filter = "in_progress"
    elif "приняты" in normalized_filter:
        status_filter = "accepted"
    elif "готовы к выдаче" in normalized_filter:
        status_filter = "completed"
    elif status_filter != "all":
        status_filter = normalized_filter
        
    context.user_data.pop('admin_orders_filter', None)
    
    valid_statuses = ['all', 'new', 'accepted', 'in_progress', 'completed', 'issued', 'cancelled', 'spam']
    if status_filter not in valid_statuses:
        status_filter = 'all'
    
    from handlers.admin_orders import show_orders_list
    await show_orders_list(update, context, status=status_filter, page=0)


async def admin_new_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/neworders — показать новые заказы"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ У вас нет доступа.")
        return

    try:
        orders = get_orders_by_status("new")
        if not orders:
            await update.effective_message.reply_text("✅ Новых заказов нет.")
            return
        from handlers.orders import format_order_id
        text = f"🆕 *Новые заказы ({len(orders)}):*\n\n"
        for order in orders[:20]:
            formatted = format_order_id(order.id, order.created_at)
            text += f"*{formatted}* — {order.client_name or '—'} | 📞 {order.client_phone or '—'}\n"
        await update.effective_message.reply_text(text, parse_mode="Markdown")
    except Exception:
        logger.exception("Ошибка при получении новых заказов")
        if update.effective_message:
            await update.effective_message.reply_text("❌ Ошибка при получении новых заказов.")


async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/users — список пользователей"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ У вас нет доступа.")
        return

    try:
        users = get_all_users()
        if not users:
            msg = "👥 Пользователей нет."
            if hasattr(update, 'callback_query') and update.callback_query:
                await update.callback_query.edit_message_text(msg)
            else:
                await update.effective_message.reply_text(msg)
            return
        text = f"👥 *Пользователи ({len(users)}):*\n\n"
        for u in users[:50]:
            name = u.first_name or u.username or f"ID: {u.user_id}"
            line = f"• {name}"
            if getattr(u, 'phone', None):
                line += f" ({u.phone})"
            text += line + "\n"
        
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown")
        else:
            await update.effective_message.reply_text(text, parse_mode="Markdown")
    except Exception:
        logger.exception("Ошибка при получении пользователей")


async def admin_spam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/spam — показать журнал спама"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ У вас нет доступа.")
        return

    try:
        logs = get_spam_logs(limit=50)
        if not logs:
            await update.effective_message.reply_text("🛑 Записей спама нет.")
            return
        text = "🛑 *Последние спам-записи:*\n\n"
        for l in logs[:50]:
            text += f"👤 {l.user_id} • {l.reason}\n{(l.message[:120] + '...') if l.message else ''}\n\n"
        await update.effective_message.reply_text(text, parse_mode="Markdown")
    except Exception:
        logger.exception("Ошибка при получении spam logs")
        if update.effective_message:
            await update.effective_message.reply_text("❌ Ошибка при получении журнала спама.")


async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запустить режим рассылки"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if update.message:
            await update.message.reply_text("⛔ У вас нет доступа.")
        return
    
    context.user_data["broadcast_mode"] = True
    context.user_data["broadcast_text"] = None
    
    text = (
        "📣 *Режим рассылки*\n\n"
        "Введите текст сообщения для всех пользователей бота.\n\n"
        "💡 Можно использовать Markdown для оформления."
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")]
    ])
    
    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard, parse_mode="Markdown")


async def set_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setadmin <user_id> — назначить пользователя админом"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ У вас нет доступа.")
        return

    if not context.args:
        await update.effective_message.reply_text("Использование: /setadmin <user_id>")
        return

    try:
        new_admin_id = int(context.args[0])
        ok = set_admin(new_admin_id, True)
        if ok:
            await update.effective_message.reply_text(f"✅ Пользователь {new_admin_id} назначен админом.")
        else:
            await update.effective_message.reply_text("❌ Не удалось назначить администратора.")
    except Exception:
        logger.exception("Ошибка в set_admin_command")
        if update.effective_message:
            await update.effective_message.reply_text("❌ Ошибка при назначении администратора.")


# ---------------- Callback-обработчики ----------------


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    return await admin_menu_callback(update, context)


async def admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка callback-запросов админ-панели"""
    query = getattr(update, 'callback_query', None)
    if query:
        await query.answer()
    
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id or not is_user_admin(user_id):
        if query:
            await query.answer("⛔ Нет доступа", show_alert=True)
        return

    data = getattr(query, 'data', "") if query else ""

    if data == "admin_back_menu":
        if query and query.message:
            try:
                await query.message.delete()
            except Exception:
                pass
        await context.bot.send_message(
            chat_id=user_id,
            text="📋 *Админ-панель*\n\nВыберите раздел:",
            reply_markup=get_admin_main_menu(),
            parse_mode="Markdown"
        )
        return

    if data == "admin_stats":
        await admin_stats(update, context)
        return

    if data == "admin_clients":
        await admin_users(update, context)
        return

    if data == "open_web_admin":
        url = _get_web_admin_orders_url() or "Веб-панель недоступна"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Открыть веб-админку", url=url)],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")]
        ])
        if query:
            await query.edit_message_text(f"🌐 Веб-панель: {url}", reply_markup=keyboard, parse_mode="Markdown")
        return

    status_map = {
        "admin_orders_new": ("new", "🆕 Новые заказы"),
        "admin_orders_accepted": ("accepted", "⏳ Принятые заказы"),
        "admin_orders_in_progress": ("in_progress", "🔄 Заказы в работе"),
        "admin_orders_completed": ("completed", "✅ Готовые заказы"),
        "admin_orders_issued": ("issued", "📤 Выданные заказы"),
    }
    
    if data in status_map:
        status, title = status_map[data]
        try:
            orders = get_orders_by_status(status)
            if not orders:
                if query:
                    await query.edit_message_text(
                        f"{title}\n\n📭 Заказов нет",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")
                        ]]),
                        parse_mode="Markdown"
                    )
                return
            from handlers.orders import format_order_id, SERVICE_NAMES
            text = f"📋 *{title}* — {len(orders)} шт.\n\n"
            keyboard = []
            for order in orders[:20]:
                formatted = format_order_id(int(order.id), order.created_at)
                phone = order.client_phone or "📲 TG"
                service_display = SERVICE_NAMES.get(order.service_type, order.service_type or '—')
                text += f"📦 {formatted} — {order.client_name or 'Аноним'}\n🛠 _{service_display}_\n📞 {phone}\n\n"
                keyboard.append([
                    InlineKeyboardButton(f"📦 {formatted}", callback_data=f"admin_view_{order.id}")
                ])
            keyboard.append([
                InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")
            ])
            if query:
                await query.edit_message_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
        except Exception:
            logger.exception("Ошибка получения заказов по статусу")
            if query:
                await query.edit_message_text(
                    "❌ Ошибка при получении заказов.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")
                    ]])
                )
        return

    if data.startswith("admin_view_"):
        await admin_view_order(update, context)
        return

    if data.startswith("status_"):
        await change_order_status(update, context)
        return

    if data.startswith("contact_client_"):
        await contact_client(update, context)
        return

    if data.startswith("status_deleted_"):
        try:
            order_id = int(data.replace("status_deleted_", ""))
            if delete_order(order_id):
                if query:
                    await query.answer("✅ Заказ удален")
                    await query.message.edit_text(f"🗑 Заказ #{order_id} был удален из базы данных.")
            else:
                if query:
                    await query.answer("❌ Ошибка при удалении", show_alert=True)
        except Exception as e:
            logger.error(f"Error deleting order: {e}")
            if query:
                await query.answer("❌ Ошибка", show_alert=True)
        return

    if query:
        await query.answer("Неизвестное действие.", show_alert=True)


async def admin_view_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Просмотр заказа"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    try:
        order_id = int(query.data.replace("admin_view_", ""))
    except Exception:
        await query.answer("❌ Неверный ID заказа", show_alert=True)
        return

    order = get_order(order_id)
    if not order:
        await query.answer("❌ Заказ не найден", show_alert=True)
        return

    from handlers.orders import format_order_id, SERVICE_NAMES
    formatted = format_order_id(order.id, order.created_at)
    service_display = SERVICE_NAMES.get(order.service_type, order.service_type or '—')
    
    status_emoji = {
        "new": "🆕",
        "accepted": "⏳",
        "in_progress": "🔄",
        "completed": "✅",
        "cancelled": "❌",
        "issued": "📤",
        "spam": "🚫",
    }.get(str(order.status), "❓")
    
    status_text_display = {
        "new": "Новый",
        "accepted": "Принят",
        "in_progress": "В работе",
        "completed": "Готов",
        "issued": "Выдан",
        "cancelled": "Отменён",
        "spam": "Спам"
    }.get(str(order.status), str(order.status))

    keyboard = get_admin_order_detail_keyboard(order.id, order.status)
    phone_display = order.client_phone if order.client_phone and order.client_phone != "Telegram" else "📲 Telegram"

    text = (
        f"📦 *Заказ {formatted}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 *Статус:* {status_emoji} {status_text_display}\n"
        f"🏷 *Услуга:* {service_display}\n"
        f"👤 *Клиент:* {order.client_name or 'Аноним'}\n"
        f"📞 *Телефон:* {phone_display}\n"
        f"📝 *Описание:* {order.description or 'Нет описания'}\n"
        f"📅 *Дата:* {order.created_at.strftime('%d.%m.%Y %H:%M') if order.created_at else 'Н/Д'}\n"
    )
    
    try:
        try:
            await query.message.delete()
        except Exception:
            pass

        if getattr(order, 'photo_file_id', None):
            await context.bot.send_photo(
                chat_id=user_id,
                photo=order.photo_file_id,
                caption=text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error in admin_view_order display: {e}")


async def change_order_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Изменение статуса заказа админом"""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if not is_user_admin(user.id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    data = query.data or ""
    parts = data.split("_")
    if len(parts) < 3:
        await query.answer("❌ Неверный формат данных", show_alert=True)
        return

    try:
        new_status = parts[1]
        order_id = int(parts[-1])
    except Exception:
        await query.answer("❌ Неверный ID заказа", show_alert=True)
        return

    mapping = {
        "in": "in_progress",
        "inprogress": "in_progress",
        "in_progress": "in_progress",
        "completed": "completed",
        "issued": "issued",
        "cancelled": "cancelled",
        "cancel": "cancelled",
    }
    new_status_norm = mapping.get(new_status, new_status)

    try:
        updated = update_order_status(order_id, new_status_norm)
    except Exception:
        logger.exception("Ошибка при обновлении статуса заказа в БД")
        await query.answer("❌ Ошибка при обновлении статуса", show_alert=True)
        return

    if not updated:
        await query.answer("❌ Заказ не найден или не обновлён", show_alert=True)
        return

    order = get_order(order_id)
    try:
        from handlers.orders import format_order_id
        formatted = format_order_id(order.id, order.created_at) if order else f"#{order_id}"
        client_msgs = {
            "in_progress": f"✂️ Ваша вещь в работе.\nЗаказ: {formatted}",
            "completed": f"🎉 Заказ готов!\nЗаказ: {formatted}\nПриходите за выдачей.",
            "issued": f"📤 Заказ выдан.\nЗаказ: {formatted}",
            "cancelled": f"❌ Заказ отменён.\nЗаказ: {formatted}",
            "new": f"🆕 Ваш заказ зарегистрирован: {formatted}"
        }
        client_text = client_msgs.get(new_status_norm, f"📦 Статус заказа обновлён: {new_status_norm}")
        if order and getattr(order, "user_id", None):
            try:
                await context.bot.send_message(chat_id=order.user_id, text=client_text)
            except Exception:
                logger.warning(f"Не удалось уведомить пользователя {order.user_id}")
    except Exception:
        logger.exception("Ошибка при уведомлении клиента после изменения статуса")

    try:
        status_text_map = {
            "in_progress": "🔄 В работе",
            "completed": "✅ Готов",
            "issued": "📤 Выдан",
            "cancelled": "❌ Отменён",
            "new": "🆕 Новый",
            "accepted": "⏳ Принят",
            "spam": "🚫 Спам"
        }
        status_text = status_text_map.get(new_status_norm, new_status_norm)
        admin_name = user.username or user.first_name or str(user.id)
        formatted_id = f"#{order_id}"
        if order:
            try:
                from handlers.orders import format_order_id
                formatted_id = format_order_id(order.id, order.created_at)
            except Exception:
                pass
                
        new_text = f"✅ Заказ {formatted_id} обновлён\n\n{status_text}\n\n👤 Обновил: @{admin_name}"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ К списку заказов", callback_data="admin_orders_menu")
        ]])
        
        if query.message and getattr(query.message, "photo", None):
            try:
                await query.message.edit_caption(caption=new_text, reply_markup=keyboard)
            except Exception:
                await query.edit_message_text(text=new_text, reply_markup=keyboard)
        else:
            await query.edit_message_text(text=new_text, reply_markup=keyboard)
    except Exception:
        logger.exception("Ошибка при обновлении сообщения админа")


async def contact_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показать способы связи с клиентом"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    try:
        order_id = int(query.data.replace("contact_client_", ""))
    except Exception:
        await query.answer("❌ Неверный ID заказа", show_alert=True)
        return

    order = get_order(order_id)
    if not order:
        await query.answer("❌ Заказ не найден", show_alert=True)
        return

    phone = order.client_phone or "Не указан"
    tg_url = f"tg://user?id={order.user_id}" if order.user_id else None
    buttons = []
    if tg_url:
        buttons.append([InlineKeyboardButton("✉️ Написать в Telegram", url=tg_url)])
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data=f"admin_view_{order_id}")])
    
    await query.edit_message_text(
        f"✉️ *Связь с клиентом*\n\n👤 {order.client_name or 'Не указано'}\n📞 {phone}\n\nНажмите кнопку для связи.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def open_web_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открытие веб-админки"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    url = _get_web_admin_orders_url()
    if not url:
        await query.answer("❌ Веб-панель не настроена", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Открыть веб-админку", url=url)],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")]
    ])
    await query.edit_message_text(
        f"🌐 *Веб-панель администратора*\n\n{url}",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


def get_admin_menu_keyboard(stats: Optional[dict] = None) -> InlineKeyboardMarkup:
    """Клавиатура админ-меню"""
    if stats is None:
        try:
            stats = get_statistics()
        except Exception:
            stats = {}
    new_count = stats.get("new_orders", 0)
    in_progress = stats.get("in_progress", 0)
    completed = stats.get("completed", 0)
    issued = stats.get("issued", 0)
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
            InlineKeyboardButton("🌐 Веб-админка", callback_data="open_web_admin"),
            InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
