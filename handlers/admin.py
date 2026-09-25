"""
Компактный обработчик админ-панели для бота.
"""

import asyncio
import logging
import os
from functools import wraps
from typing import List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from keyboards import (
    get_admin_back_menu, get_admin_main_menu,
    get_admin_order_detail_keyboard, get_admin_orders_submenu,
)
from utils.database import (
    get_admins, get_all_orders, get_all_users, get_order,
    get_orders_by_status, get_spam_logs, get_statistics,
    is_admin, set_admin, update_order_status, delete_order
)

logger = logging.getLogger(__name__)

# Единый справочник статусов: (emoji, text, client_notification_template)
STATUSES = {
    "new": ("🆕", "Новый", "🆕 Ваш заказ зарегистрирован: {}"),
    "in_progress": ("🔄", "В работе", "✂️ Ваша вещь в работе.\nЗаказ: {}"),
    "completed": ("✅", "Готов", "🎉 Заказ готов!\nЗаказ: {}\nПриходите за выдачей."),
    "issued": ("📤", "Выдан", "📤 Заказ выдан.\nЗаказ: {}"),
    "cancelled": ("❌", "Отменён", "❌ Заказ отменён.\nЗаказ: {}"),
    "spam": ("🚫", "Спам", "")
}

def get_env_admin_ids() -> List[int]:
    """Получить актуальный список админов из переменных окружения"""
    env_ids = str(os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID") or "").replace(";", ",").replace(" ", ",")
    return [int(x.strip()) for x in env_ids.split(",") if x.strip().isdigit()]

def _get_web_admin_orders_url() -> str:
    url = os.getenv("WEB_ADMIN_URL") or (f"https://{os.getenv('REPLIT_DEV_DOMAIN')}" if os.getenv("REPLIT_DEV_DOMAIN") else "")
    return f"{url.rstrip('/')}/orders" if url else ""

def is_user_admin(user_id: int) -> bool:
    if not user_id: return False
    try:
        if int(user_id) in get_env_admin_ids(): return True
        return bool(is_admin(int(user_id)))
    except Exception as e:
        logger.error(f"Ошибка проверки статуса администратора: {e}")
        return False

def admin_only(func):
    """Декоратор для проверки прав администратора"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not is_user_admin(update.effective_user.id):
            msg = "⛔ Нет доступа."
            if update.callback_query: await update.callback_query.answer(msg, show_alert=True)
            elif update.effective_message: await update.effective_message.reply_text(msg)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

async def send_or_edit(update: Update, text: str, reply_markup=None, **kwargs):
    """Умная отправка или редактирование сообщения"""
    kwargs.setdefault('parse_mode', 'Markdown')
    if update.callback_query:
        try:
            return await update.callback_query.edit_message_text(text, reply_markup=reply_markup, **kwargs)
        except Exception:
            pass
    if update.effective_message:
        return await update.effective_message.reply_text(text, reply_markup=reply_markup, **kwargs)

# ---------------- Команды ----------------

@admin_only
async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, "📋 *Админ-панель*\n\nВыберите раздел для управления:", get_admin_main_menu())

@admin_only
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        s = get_statistics()
        text = (
            f"📊 *Статистика бота*\n\n👥 Пользователей: {s.get('total_users', 0)}\n"
            f"📦 Всего заказов: {s.get('total_orders', 0)}\n🆕 Новых: {s.get('new_orders', 0)}\n"
            f"🔄 В работе: {s.get('in_progress', 0)}\n✅ Выполнено: {s.get('completed', 0)}\n"
            f"📤 Выдано: {s.get('issued', 0)}\n🚫 Заблокировано: {s.get('blocked_users', 0)}\n"
            f"🛑 Спам-записей: {s.get('spam_count', 0)}"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats"),
            InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu"),
        ]])
        await send_or_edit(update, text, kb)
    except Exception:
        logger.exception("Ошибка получения статистики")
        await send_or_edit(update, "❌ Ошибка при получении статистики.")

@admin_only
async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    filt = str(context.user_data.pop("admin_orders_filter", "all")).lower()
    for emoji in ["📊", "📦", "📋", "⏳", "✅", "📤"]: filt = filt.replace(emoji, "")
    filt = filt.strip()
    
    mapping = {"сегодня в работе": "in_progress", "приняты": "accepted", "готовы к выдаче": "completed"}
    status_filter = mapping.get(filt, filt if filt in ["new", "accepted", "in_progress", "completed", "issued", "cancelled", "spam"] else "all")
    
    from handlers.admin_orders import show_orders_list
    await show_orders_list(update, context, status=status_filter, page=0)

@admin_only
async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        users = get_all_users()
        if not users:
            return await send_or_edit(update, "👥 Пользователей нет.")
        
        text = f"👥 *Пользователи ({len(users)}):*\n\n" + "\n".join(
            f"• {u.first_name or u.username or f'ID: {u.user_id}'}" + (f" ({u.phone})" if getattr(u, "phone", None) else "")
            for u in users[:50]
        )
        await send_or_edit(update, text, InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")]]))
    except Exception:
        await send_or_edit(update, "❌ Ошибка при получении пользователей.")

@admin_only
async def admin_spam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        logs = get_spam_logs(limit=50)
        if not logs: return await send_or_edit(update, "🛑 Записей спама нет.")
        text = "🛑 *Последние спам-записи:*\n\n" + "\n\n".join(
            f"👤 {l.user_id} • {l.reason}\n{(l.message[:120] + '...') if l.message else ''}" for l in logs[:50]
        )
        await send_or_edit(update, text)
    except Exception:
        await send_or_edit(update, "❌ Ошибка при получении журнала спама.")

# ---------------- Рассылка ----------------

@admin_only
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.update({"broadcast_mode": True, "broadcast_text": None})
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")]])
    await send_or_edit(update, "📣 *Режим рассылки*\n\nВведите текст сообщения для всех пользователей бота.\n\n💡 Можно использовать Markdown для оформления.", kb)

@admin_only
async def broadcast_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str) -> None:
    context.user_data.update({"broadcast_text": message_text, "broadcast_mode": False})
    user_count = len(get_all_users()) if getattr(get_all_users, '__code__', None) else "?"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Отправить", callback_data="broadcast_confirm"), InlineKeyboardButton("✏️ Редактировать", callback_data="broadcast_edit")],
        [InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")],
    ])
    await send_or_edit(update, f"📋 *Предпросмотр рассылки*\n━━━━━━━━━━━━━━━\n\n{message_text}\n\n━━━━━━━━━━━━━━━\n👥 Получателей: {user_count}", kb)

@admin_only
async def broadcast_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    query = update.callback_query
    
    if action == "cancel":
        context.user_data.update({"broadcast_mode": False, "broadcast_text": None})
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(update.effective_user.id, "❌ Рассылка отменена.", reply_markup=get_admin_main_menu())
        
    elif action == "edit":
        context.user_data["broadcast_mode"] = True
        old_text = context.user_data.get("broadcast_text", "")
        await send_or_edit(update, f"✏️ *Редактирование рассылки*\n\nТекущий текст:\n_{old_text[:200]}..._\n\nВведите новый текст:", 
                           InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")]]))
        
    elif action == "confirm":
        msg = context.user_data.get("broadcast_text")
        if not msg: return await send_or_edit(update, "❌ Текст рассылки не найден. Начните заново.")
        
        users = get_all_users()
        await send_or_edit(update, f"📤 Запускаю рассылку {len(users)} пользователям...")
        sent, failed, delay = 0, 0, float(os.getenv("BROADCAST_DELAY", "0.05"))
        
        for u in users:
            try:
                await context.bot.send_message(chat_id=int(u.user_id), text=msg, parse_mode="Markdown")
                sent += 1
                if delay: await asyncio.sleep(delay)
            except Exception: failed += 1
            
        context.user_data["broadcast_text"] = None
        await context.bot.send_message(update.effective_user.id, f"✅ *Рассылка завершена*\n\n📨 Отправлено: {sent}\n❌ Ошибок: {failed}", parse_mode="Markdown")

@admin_only
async def set_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args: return await send_or_edit(update, "Использование: /setadmin <user_id>")
    try:
        uid = int(context.args[0])
        await send_or_edit(update, f"✅ Пользователь {uid} назначен админом." if set_admin(uid, True) else "❌ Не удалось назначить администратора.")
    except Exception:
        await send_or_edit(update, "❌ Ошибка при назначении администратора.")

# ---------------- Callback-обработчики ----------------

@admin_only
async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    await query.answer()
    data = query.data or ""

    # Простые перенаправления
    routes = {
        "admin_orders_all": admin_orders, "📊 Все заказы": admin_orders,
        "admin_stats": admin_stats, "📈 Статистика": admin_stats,
        "admin_clients": admin_users, "👥 Пользователи": admin_users,
        "broadcast_menu": broadcast_start, "📢 Рассылка": broadcast_start,
    }
    if data in routes:
        return await routes[data](update, context)

    # Меню назад
    if data == "admin_back_menu":
        try: await query.message.delete()
        except: pass
        return await context.bot.send_message(update.effective_user.id, "📋 *Админ-панель*\n\nВыберите раздел:", reply_markup=get_admin_main_menu(), parse_mode="Markdown")

    # Веб-админка
    if data == "open_web_admin":
        url = _get_web_admin_orders_url() or "Веб-панель недоступна"
        return await send_or_edit(update, f"🌐 Веб-панель: {url}", InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Открыть веб-админку", url=url)], [InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")]
        ]))

    # Списки заказов по статусам
    if data.startswith("admin_orders_") and data != "admin_orders_menu":
        status = data.replace("admin_orders_", "")
        title = f"{STATUSES.get(status, ('', 'Заказы'))[1]} заказы"
        orders = get_orders_by_status(status)
        if not orders:
            return await send_or_edit(update, f"{title}\n\n📭 Заказов нет", InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")]]))
        
        from handlers.orders import SERVICE_NAMES, format_order_id
        text, kb = f"📋 *{title}* — {len(orders)} шт.\n\n", []
        for o in orders[:20]:
            fmt_id = format_order_id(int(o.id), o.created_at)
            text += f"📦 {fmt_id} — {o.client_name or 'Аноним'}\n🛠 _{SERVICE_NAMES.get(o.service_type, o.service_type or '—')}_\n📞 {o.client_phone or '📲 Telegram'}\n\n"
            kb.append([InlineKeyboardButton(f"📦 {fmt_id}", callback_data=f"admin_view_{o.id}")])
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")])
        return await send_or_edit(update, text, InlineKeyboardMarkup(kb))

    # Специфичные действия
    if data.startswith("admin_view_"): return await admin_view_order(update, context)
    if data.startswith("status_deleted_"):
        o_id = int(data.split("_")[-1])
        return await (query.message.edit_text(f"🗑 Заказ #{o_id} удален.") if delete_order(o_id) else query.answer("❌ Ошибка при удалении", show_alert=True))
    if data.startswith("status_"): return await change_order_status(update, context)
    if data.startswith("contact_client_"): return await contact_client(update, context)
    if data.startswith("broadcast_"): return await broadcast_action(update, context, data.replace("broadcast_", ""))

    await query.answer("Неизвестное действие.", show_alert=True)

@admin_only
async def admin_view_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    order_id = int(update.callback_query.data.split("_")[-1])
    order = get_order(order_id)
    if not order: return await update.callback_query.answer("❌ Заказ не найден", show_alert=True)

    from handlers.orders import SERVICE_NAMES, format_order_id
    st_info = STATUSES.get(str(order.status), ("❓", str(order.status)))
    
    text = (
        f"📦 *Заказ {format_order_id(order.id, order.created_at)}*\n━━━━━━━━━━━━━━━\n"
        f"📊 *Статус:* {st_info[0]} {st_info[1]}\n🏷 *Услуга:* {SERVICE_NAMES.get(order.service_type, order.service_type or '—')}\n"
        f"👤 *Клиент:* {order.client_name or 'Аноним'}\n📞 *Телефон:* {order.client_phone or '📲 Telegram'}\n"
        f"📝 *Описание:* {order.description or 'Нет описания'}\n📅 *Дата:* {order.created_at.strftime('%d.%m.%Y %H:%M') if order.created_at else 'Н/Д'}\n"
    )
    kb = get_admin_order_detail_keyboard(order.id, order.status)

    try: await update.callback_query.message.delete()
    except: pass
    
    if getattr(order, "photo_file_id", None):
        await context.bot.send_photo(update.effective_user.id, order.photo_file_id, caption=text, reply_markup=kb, parse_mode="Markdown")
    else:
        await context.bot.send_message(update.effective_user.id, text, reply_markup=kb, parse_mode="Markdown")

@admin_only
async def change_order_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    parts = update.callback_query.data.split("_")
    new_status, order_id = parts[1], int(parts[-1])
    new_status = {"in": "in_progress", "inprogress": "in_progress", "cancel": "cancelled"}.get(new_status, new_status)

    if not update_order_status(order_id, new_status):
        return await update.callback_query.answer("❌ Заказ не найден/обновлён", show_alert=True)

    order = get_order(order_id)
    from handlers.orders import format_order_id
    fmt_id = format_order_id(order.id, order.created_at) if order else f"#{order_id}"

    # Уведомление клиента
    if order and getattr(order, "user_id", None):
        try:
            client_text = STATUSES.get(new_status, ("", "", f"📦 Статус заказа обновлён: {new_status}"))[2].format(fmt_id)
            if client_text: await context.bot.send_message(order.user_id, client_text)
        except Exception: logger.warning(f"Не удалось уведомить {order.user_id}")

    # Обновление админ-меню
    st_info = STATUSES.get(new_status, ("", new_status))
    admin_name = update.effective_user.username or update.effective_user.first_name or str(update.effective_user.id)
    new_text = f"✅ Заказ {fmt_id} обновлён\n\n{st_info[0]} {st_info[1]}\n\n👤 Обновил: @{admin_name}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ К списку заказов", callback_data="admin_orders_menu")]])

    msg = update.callback_query.message
    if msg and getattr(msg, "photo", None):
        try: await msg.edit_caption(caption=new_text, reply_markup=kb)
        except Exception: await send_or_edit(update, new_text, kb)
    else:
        await send_or_edit(update, new_text, kb)

@admin_only
async def contact_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    order_id = int(update.callback_query.data.split("_")[-1])
    order = get_order(order_id)
    if not order: return await update.callback_query.answer("❌ Заказ не найден", show_alert=True)

    kb = [[InlineKeyboardButton("✉️ Написать в Telegram", url=f"tg://user?id={order.user_id}")]] if order.user_id else []
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data=f"admin_view_{order_id}")])
    
    await send_or_edit(update, f"✉️ *Связь с клиентом*\n\n👤 {order.client_name or 'Не указано'}\n📞 {order.client_phone or 'Не указан'}\n\nНажмите кнопку для связи.", InlineKeyboardMarkup(kb))

def get_admin_menu_keyboard(stats: Optional[dict] = None) -> InlineKeyboardMarkup:
    try: stats = stats or get_statistics()
    except: stats = {}
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🆕 Новые ({stats.get('new_orders', 0)})", callback_data="admin_orders_new"),
         InlineKeyboardButton(f"🔄 В работе ({stats.get('in_progress', 0)})", callback_data="admin_orders_in_progress")],
        [InlineKeyboardButton(f"✅ Готовые ({stats.get('completed', 0)})", callback_data="admin_orders_completed"),
         InlineKeyboardButton(f"📤 Выданные ({stats.get('issued', 0)})", callback_data="admin_orders_issued")],
        [InlineKeyboardButton("👥 Клиенты", callback_data="admin_clients"), InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("🌐 Веб-админка", callback_data="open_web_admin"), InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")],
    ])
