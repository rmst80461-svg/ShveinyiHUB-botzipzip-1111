"""
Улучшенная система управления заказами с пагинацией, фильтрацией и поиском.
"""
import os
import logging
from typing import Optional, List, Tuple

from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.database import (
    get_orders_by_status,
    get_order,
    update_order_status,
    get_all_orders,
    search_orders_by_name,
    search_orders_by_id,
    get_orders_count_by_status,
)
from handlers.orders import format_order_id, SERVICE_NAMES
from handlers.admin import is_user_admin

logger = logging.getLogger(__name__)

ORDERS_PER_PAGE = 8

STATUS_EMOJI = {
    "new": "🆕",
    "accepted": "✅",
    "in_progress": "🔄",
    "completed": "✅",
    "issued": "📤",
    "cancelled": "❌",
    "spam": "🚫",
    "all": "📦",
}

STATUS_NAMES = {
    "new": "Новые",
    "accepted": "Приняты",
    "in_progress": "В работе",
    "completed": "Готовые",
    "issued": "Выданные",
    "cancelled": "Отменённые",
    "spam": "Спам",
    "all": "Все заказы",
}

NEXT_STATUS = {
    "new": "accepted",
    "accepted": "in_progress",
    "in_progress": "completed",
    "completed": "issued",
}


def create_orders_list_keyboard(
    orders: list,
    status: str,
    page: int,
    total_pages: int
) -> InlineKeyboardMarkup:
    """Создать клавиатуру для списка заказов с пагинацией"""
    keyboard = []
    
    for order in orders:
        formatted_id = format_order_id(order.id, order.created_at)
        service_display = SERVICE_NAMES.get(order.service_type, "❓ Другая услуга")
        emoji = STATUS_EMOJI.get(order.status, "❓")
        
        btn_text = f"{emoji} {formatted_id} — {order.client_name or 'Аноним'}"
        keyboard.append([
            InlineKeyboardButton(
                btn_text,
                callback_data=f"odetail_{order.id}_{status}_{page}"
            )
        ])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton("◀️ Назад", callback_data=f"olist_{status}_{page-1}")
        )
    
    nav_buttons.append(
        InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="orders_page_info")
    )
    
    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton("Вперёд ▶️", callback_data=f"olist_{status}_{page+1}")
        )
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    filter_row1 = [
        InlineKeyboardButton(
            f"{'✓ ' if status == 'all' else ''}📦 Все заказы",
            callback_data="olist_all_0"
        ),
        InlineKeyboardButton(
            f"{'✓ ' if status == 'in_progress' else ''}📋 В работе",
            callback_data="olist_in_progress_0"
        ),
    ]
    filter_row2 = [
        InlineKeyboardButton(
            f"{'✓ ' if status == 'accepted' else ''}⏳ Приняты",
            callback_data="olist_accepted_0"
        ),
        InlineKeyboardButton(
            f"{'✓ ' if status == 'completed' else ''}✅ Готовые",
            callback_data="olist_completed_0"
        ),
    ]
    filter_row3 = [
        InlineKeyboardButton(
            f"{'✓ ' if status == 'new' else ''}🆕 Новые",
            callback_data="olist_new_0"
        ),
        InlineKeyboardButton(
            f"{'✓ ' if status == 'issued' else ''}📤 Выданные",
            callback_data="olist_issued_0"
        ),
    ]
    keyboard.append(filter_row1)
    keyboard.append(filter_row2)
    keyboard.append(filter_row3)
    
    action_buttons = [
        InlineKeyboardButton("🔍 Поиск", callback_data="osearch_menu"),
        InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
        InlineKeyboardButton("◀️ Меню", callback_data="admin_back_menu"),
    ]
    keyboard.append(action_buttons)
    
    return InlineKeyboardMarkup(keyboard)


def create_order_detail_keyboard(
    order_id: int,
    order_status: str,
    back_status: str,
    back_page: int
) -> InlineKeyboardMarkup:
    """Создать клавиатуру для детального просмотра заказа"""
    keyboard = []
    
    status_buttons = []
    if order_status == "new":
        status_buttons.append(
            InlineKeyboardButton("✅ Принять вещь", callback_data=f"ostatus_{order_id}_accepted")
        )
        status_buttons.append(
            InlineKeyboardButton("❌ Отменить", callback_data=f"ostatus_{order_id}_cancelled")
        )
    elif order_status == "accepted":
        status_buttons.append(
            InlineKeyboardButton("🔄 В работу", callback_data=f"ostatus_{order_id}_in_progress")
        )
        status_buttons.append(
            InlineKeyboardButton("❌ Отменить", callback_data=f"ostatus_{order_id}_cancelled")
        )
    elif order_status == "in_progress":
        status_buttons.append(
            InlineKeyboardButton("✅ Готов", callback_data=f"ostatus_{order_id}_completed")
        )
        status_buttons.append(
            InlineKeyboardButton("❌ Отменить", callback_data=f"ostatus_{order_id}_cancelled")
        )
    elif order_status == "completed":
        status_buttons.append(
            InlineKeyboardButton("📤 Выдан", callback_data=f"ostatus_{order_id}_issued")
        )
    
    if status_buttons:
        keyboard.append(status_buttons)
    
    keyboard.append([
        InlineKeyboardButton("✉️ Написать клиенту", callback_data=f"contact_client_{order_id}")
    ])
    
    if order_status in ["issued", "cancelled"]:
        keyboard.append([
            InlineKeyboardButton("🗑 Удалить заказ", callback_data=f"odelete_{order_id}")
        ])
    
    keyboard.append([
        InlineKeyboardButton("◀️ К списку", callback_data=f"olist_{back_status}_{back_page}")
    ])
    
    return InlineKeyboardMarkup(keyboard)


async def show_orders_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    status: str = "all",
    page: int = 0
) -> None:
    """Показать список заказов с пагинацией"""
    query = update.callback_query
    
    # Пытаемся получить статус из callback_data, если он там есть
    if query and query.data and query.data.startswith("olist_"):
        try:
            parts = query.data.split("_")
            if len(parts) >= 3:
                status = parts[1]
                page = int(parts[2])
        except Exception:
            pass
    
    # Если вызвано из текстового меню "Все заказы", статус может быть передан как "all"
    # или взят из context.user_data (уже обработано в admin.py)

    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if query:
            await query.answer("⛔ Нет доступа", show_alert=True)
        return
    
    # Загружаем заказы в зависимости от фильтра
    from utils.database import get_session, Order
    session = get_session()
    
    # ПРИНУДИТЕЛЬНО СБРАСЫВАЕМ КЭШ СЕССИИ И ЗАКРЫВАЕМ ПРЕДЫДУЩИЕ СОЕДИНЕНИЯ
    session.expire_all()
    
    try:
        # Нормализуем статус: убираем эмодзи и пробелы
        current_status = str(status).lower()
        for emoji in ["📊", "📦", "📋", "⏳", "✅", "📤"]:
            current_status = current_status.replace(emoji, "")
        current_status = current_status.strip()
        
        # ЛОГИРУЕМ ЧТО ПРИШЛО
        logger.info(f"show_orders_list called with status: '{status}', normalized: '{current_status}'")
        
        # Проверка на "Все заказы" - максимально широкая
        is_all = (not current_status or 
                  current_status == "all" or 
                  "все" in current_status or 
                  "all" in current_status or
                  status == "all")
        
        if is_all:
            # Прямой запрос ВСЕХ заказов
            orders = session.query(Order).order_by(Order.created_at.desc()).all()
            logger.info(f"Loaded ALL orders: {len(orders)} items")
            status = "all" # Нормализуем для дальнейшего использования
        else:
            orders = session.query(Order).filter(Order.status == current_status).order_by(Order.created_at.desc()).all()
            logger.info(f"Loaded orders for status '{current_status}': {len(orders)} items")
    except Exception as e:
        logger.error(f"Error loading orders: {e}")
        orders = []
    finally:
        session.close()
    
    total_orders = len(orders)
    
    if total_orders == 0:
        text = f"📋 *{STATUS_EMOJI.get(status, '📦')} {STATUS_NAMES.get(status, status)}*\n\n📭 Заказов нет"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🆕 Новые", callback_data="olist_new_0"),
                InlineKeyboardButton("🔄 В работе", callback_data="olist_in_progress_0"),
            ],
            [
                InlineKeyboardButton("✅ Готовые", callback_data="olist_completed_0"),
                InlineKeyboardButton("📤 Выданные", callback_data="olist_issued_0"),
            ],
            [
                InlineKeyboardButton("◀️ В админку", callback_data="admin_back_menu")
            ]
        ])
        
        if query:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            effective_message = update.effective_message or (query.message if query else None)
            if effective_message:
                await effective_message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return
    
    total_pages = (total_orders + ORDERS_PER_PAGE - 1) // ORDERS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * ORDERS_PER_PAGE
    end_idx = start_idx + ORDERS_PER_PAGE
    current_orders = orders[start_idx:end_idx]
    
    text = f"📋 *{STATUS_EMOJI.get(status, '📦')} {STATUS_NAMES.get(status, status)}* — {total_orders} шт.\n\n"
    
    for order in current_orders:
        from handlers.orders import format_order_id
        fid = format_order_id(int(order.id), order.created_at)
        service_display = SERVICE_NAMES.get(order.service_type, "❓ Другая услуга")
        phone_display = order.client_phone or "📲 Через бота"
        
        status_info = ""
        if order.status == "accepted" and order.ready_date:
            status_info = f" | 📅 Готов {order.ready_date} ⚠️"
        elif order.status == "in_progress" and order.ready_date:
            status_info = f" | 📅 До {order.ready_date}"
        
        text += f"📦 *{fid}* — {order.client_name or 'Аноним'}{status_info}\n"
        text += f"🛠 _{service_display}_ | 📞 {phone_display}\n\n"
    
    text += f"📄 Страница {page + 1} из {total_pages}"
    
    keyboard = create_orders_list_keyboard(current_orders, status, page, total_pages)
    
    effective_message = update.effective_message
    if not effective_message and query:
        effective_message = query.message

    if query:
        try:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            if effective_message:
                await effective_message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    elif effective_message:
        await effective_message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def show_order_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    order_id: int,
    back_status: str = "new",
    back_page: int = 0
) -> None:
    """Показать детали заказа"""
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if query:
            await query.answer("⛔ Нет доступа", show_alert=True)
        return
    
    order = get_order(order_id)
    if not order:
        if query:
            await query.answer("❌ Заказ не найден", show_alert=True)
        return
    
    formatted_id = format_order_id(order.id, order.created_at)
    service_display = SERVICE_NAMES.get(order.service_type, "❓ Другая услуга")
    status_emoji = STATUS_EMOJI.get(order.status, "❓")
    status_name = STATUS_NAMES.get(order.status, order.status)
    phone_display = (
        order.client_phone
        if order.client_phone and order.client_phone not in {"Telegram", "TG"}
        else "📲 Через бота"
    )
    date_str = order.created_at.strftime('%d.%m.%Y %H:%M') if order.created_at else 'Н/Д'
    
    # Получаем количество заказов пользователя
    from utils.database import get_session, Order
    session = get_session()
    user_order_count = session.query(Order).filter(Order.user_id == order.user_id).count()
    session.close()
    
    client_status = "✨ Постоянный клиент" if user_order_count > 1 else "🆕 Новый клиент"
    
    text = (
        f"📦 *Заказ {formatted_id}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 *Клиент:* {order.client_name or 'Аноним'} ({client_status}, заказов: {user_order_count})\n"
        f"📊 *Статус:* {status_emoji} {status_name}\n"
    )
    
    if order.ready_date:
        text += f"📅 *Срок готовности:* {order.ready_date}\n"
    
    if order.master_comment:
        text += f"💬 *Комментарий мастера:* {order.master_comment}\n"
        
    text += (
        f"🏷 *Услуга:* {service_display}\n"
        f"👤 *Клиент:* {order.client_name or 'Аноним'}\n"
        f"📞 *Телефон:* {phone_display}\n"
        f"📝 *Описание:* {order.description or 'Нет описания'}\n"
        f"📅 *Дата:* {date_str}\n"
    )
    
    keyboard = create_order_detail_keyboard(order.id, order.status, back_status, back_page)
    
    try:
        if query and query.message:
            try:
                await query.message.delete()
            except:
                pass
        
        if order.photo_file_id:
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
        logger.error(f"Error showing order detail: {e}")
        if query:
            try:
                await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
            except:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )


async def handle_order_status_change(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    order_id: int,
    new_status: str
) -> None:
    """Обработка изменения статуса заказа"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return
    
    if new_status == "accepted":
        # Переходим в режим ввода даты и комментария
        context.user_data["awaiting_ready_date"] = order_id
        
        # Обновляем статус в базе сразу (или можно после ввода даты, но для консистентности UI лучше сразу)
        update_order_status(order_id, "accepted")
        
        await query.message.reply_text(
            f"📅 Введите срок готовности для заказа #{order_id} (например: 31.01) или нажмите /skip:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Пропустить", callback_data=f"skip_ready_date_{order_id}")],
                [InlineKeyboardButton("❌ Отмена", callback_data=f"olist_new_0")]
            ])
        )
        return

    success = update_order_status(order_id, new_status)
    
    if not success:
        await query.answer("❌ Не удалось обновить статус", show_alert=True)
        return
    
    order = get_order(order_id)
    if order and order.user_id:
        try:
            formatted_id = format_order_id(order.id, order.created_at)
            client_name = order.client_name or "Дорогой клиент"
            client_messages = {
                "in_progress": (
                    f"Швейный HUB\n"
                    f"🔄 Статус заказа обновлён\n\n"
                    f"{client_name}, отличные новости! 🎉\n"
                    f"Ваш заказ {formatted_id} уже на столе у мастера и активно преображается! ✨\n\n"
                    f"🧵 Иголочка взяла ваш заказ на карандаш\n"
                    f"Я лично слежу за процессом и держу вас в курсе!\n\n"
                    f"⏳ Что дальше?\n"
                    f"Как только всё будет идеально — вам тут же придёт уведомление здесь.\n\n"
                    f"🔍 Хотите заглянуть «за кулисы»?\n"
                    f"Используйте меню бота ↓ или просто напишите «Статус» в любой момент.\n\n"
                    f"Иголочка на связи! 💫"
                ),
                "completed": (
                    f"Швейный HUB\n"
                    f"✅ Заказ готов к выдаче!\n\n"
                    f"{client_name}, ура! Ваш заказ {formatted_id} готов и ждёт встречи с вами! ✨\n\n"
                    f"📋 Чтобы всё прошло гладко, не забудьте:\n"
                    f"• Назвать номер заказа\n"
                    f"• Показать это сообщение (или ваш чек)\n\n"
                    f"🏪 Часы работы мастерской:\n"
                    f"🕐 Пн–Чт: 10:00–19:50\n"
                    f"🕐 Пятница: 10:00–19:00\n"
                    f"🕐 Суббота: 10:00–17:00\n"
                    f"🚫 Воскресенье: выходной\n\n"
                    f"📞 Есть вопросы?\n"
                    f"Пишите в этот чат или звоните!\n\n"
                    f"Жду вас!\n"
                    f"Ваша Иголочка 🪡"
                ),
                "issued": (
                    f"{client_name}, спасибо что выбрали нас! 💜🧵\n"
                    f"Заказ {formatted_id} выдан.\n"
                    f"Буду рада видеть вас снова! Ваша Иголочка 🪡"
                ),
                "cancelled": f"Заказ {formatted_id} отменён.\nЕсли есть вопросы — я на связи! Ваша Иголочка 🪡",
            }
            # Для "accepted" уведомление клиенту НЕ отправляем по ТЗ
            msg = client_messages.get(new_status)
            if msg:
                await context.bot.send_message(chat_id=order.user_id, text=msg)
        except Exception as e:
            logger.warning(f"Не удалось уведомить клиента: {e}")
    
    status_text = f"{STATUS_EMOJI.get(new_status, '')} {STATUS_NAMES.get(new_status, new_status)}"
    await query.answer(f"✅ Статус изменён на {status_text}")
    
    await show_order_detail(update, context, order_id, new_status, 0)


async def handle_order_delete(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    order_id: int
) -> None:
    """Удаление заказа"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return
    
    from utils.database import delete_order
    
    if delete_order(order_id):
        await query.answer("✅ Заказ удалён")
        await query.message.edit_text(f"🗑 Заказ #{order_id} был удалён из базы данных.")
    else:
        await query.answer("❌ Ошибка при удалении", show_alert=True)


async def show_search_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Показать меню поиска"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return
    
    text = (
        "🔍 *Поиск заказов*\n\n"
        "Выберите способ поиска или введите номер/имя клиента:"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔢 По номеру заказа", callback_data="osearch_id")],
        [InlineKeyboardButton("👤 По имени клиента", callback_data="osearch_name")],
        [InlineKeyboardButton("◀️ Назад к списку", callback_data="olist_new_0")],
    ])
    
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def start_search_by_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Начать поиск по номеру заказа"""
    query = update.callback_query
    await query.answer()
    
    context.user_data["search_mode"] = "order_id"
    
    text = (
        "🔢 *Поиск по номеру заказа*\n\n"
        "Введите номер заказа (только цифры, например: 15):\n\n"
        "❌ Отмена: /cancel"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Отмена", callback_data="osearch_menu")],
    ])
    
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def start_search_by_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Начать поиск по имени клиента"""
    query = update.callback_query
    await query.answer()
    
    context.user_data["search_mode"] = "client_name"
    
    text = (
        "👤 *Поиск по имени клиента*\n\n"
        "Введите имя или часть имени клиента:\n\n"
        "❌ Отмена: /cancel"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Отмена", callback_data="osearch_menu")],
    ])
    
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def handle_search_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Обработка ввода поиска. Возвращает True если обработано."""
    if not update.message or not update.message.text:
        return False
    
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        return False
    
    search_mode = context.user_data.get("search_mode")
    if not search_mode:
        return False
    
    query_text = update.message.text.strip()
    
    if query_text == "/cancel":
        context.user_data.pop("search_mode", None)
        await update.message.reply_text("❌ Поиск отменён.")
        return True
    
    context.user_data.pop("search_mode", None)
    
    if search_mode == "order_id":
        try:
            order_id = int(query_text.replace("#", "").strip())
            order = get_order(order_id)
            if order:
                await show_search_results(update, context, [order], f"по номеру #{order_id}")
            else:
                await update.message.reply_text(
                    f"❌ Заказ #{order_id} не найден.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔍 Новый поиск", callback_data="osearch_menu")],
                        [InlineKeyboardButton("◀️ К списку", callback_data="olist_new_0")],
                    ])
                )
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат. Введите число.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Попробовать снова", callback_data="osearch_id")],
                ])
            )
    
    elif search_mode == "client_name":
        orders = search_orders_by_name(query_text)
        if orders:
            await show_search_results(update, context, orders, f"по имени «{query_text}»")
        else:
            await update.message.reply_text(
                f"❌ Заказы с именем «{query_text}» не найдены.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Новый поиск", callback_data="osearch_menu")],
                    [InlineKeyboardButton("◀️ К списку", callback_data="olist_new_0")],
                ])
            )
    
    return True


async def show_search_results(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    orders: list,
    search_description: str
) -> None:
    """Показать результаты поиска"""
    text = f"🔍 *Результаты поиска* {search_description}\n"
    text += f"Найдено: {len(orders)}\n\n"
    
    keyboard = []
    
    for order in orders[:10]:
        formatted_id = format_order_id(order.id, order.created_at)
        emoji = STATUS_EMOJI.get(order.status, "❓")
        
        text += f"{emoji} *{formatted_id}* — {order.client_name or 'Аноним'}\n"
        
        keyboard.append([
            InlineKeyboardButton(
                f"{emoji} {formatted_id}",
                callback_data=f"odetail_{order.id}_new_0"
            )
        ])
    
    if len(orders) > 10:
        text += f"\n_...и ещё {len(orders) - 10} заказов_"
    
    keyboard.append([
        InlineKeyboardButton("🔍 Новый поиск", callback_data="osearch_menu"),
        InlineKeyboardButton("◀️ К списку", callback_data="olist_new_0"),
    ])
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def handle_admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Обработка текстового ввода для админов (срок, комментарий, поиск)"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        return False
        
    text = update.message.text.strip()
    
    # 1. Обработка ввода срока готовности
    if context.user_data.get("awaiting_ready_date"):
        order_id = context.user_data.pop("awaiting_ready_date")
        from utils.database import get_session, Order
        session = get_session()
        try:
            order = session.query(Order).filter(Order.id == order_id).first()
            if order:
                order.ready_date = text
                order.status = "accepted"
                order.accepted_at = datetime.utcnow()
                session.commit()
                
                await update.message.reply_text(f"✅ Заказ #{order_id} принят. Срок готовности: {text}")
                # Сразу показываем карточку заказа (комментарий не обязателен)
                await show_order_detail(update, context, order_id, "accepted", 0)
        finally:
            session.close()
        return True

    # 1. Обработка ввода срока готовности
    if context.user_data.get("awaiting_ready_date"):
        return await handle_ready_date_input(update, context)

    # 2. Обработка ввода комментария мастера
    if context.user_data.get("awaiting_master_comment"):
        order_id = context.user_data.pop("awaiting_master_comment")
        from utils.database import get_session, Order
        session = get_session()
        try:
            order = session.query(Order).filter(Order.id == order_id).first()
            if order:
                order.master_comment = text
                session.commit()
                await update.message.reply_text(f"✅ Заказ #{order_id} принят в мастерскую.")
                await show_order_detail(update, context, order_id, "accepted", 0)
        finally:
            session.close()
        return True

    # 3. Обработка поиска (старая логика)
    return await handle_search_input(update, context)

async def orders_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Главный обработчик callback для системы заказов"""
    query = update.callback_query
    data = query.data
    
    logger.info(f"Processing order callback: {data}")
    
    # Получаем user_id для отправки сообщений
    user_id = update.effective_user.id
    
    # 1. Сначала проверяем системные экшены (skip) - САМЫЙ ВЫСОКИЙ ПРИОРИТЕТ
    if data.startswith("skip_ready_date_"):
        try:
            # Сначала отвечаем на callback МГНОВЕННО
            await query.answer("Срок пропущен")
            
            # Извлекаем order_id корректно
            parts = data.split("_")
            order_id = int(parts[-1])
            
            context.user_data.pop("awaiting_ready_date", None)
            
            logger.info(f"Skipping ready date for order {order_id}, user_id={user_id}")
            
            # Обновляем статус в базе
            update_order_status(order_id, "accepted")
            
            # Удаляем старое сообщение со списком кнопок, чтобы не висело
            try:
                await query.message.delete()
            except Exception as de:
                logger.warning(f"Could not delete message: {de}")

            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ Заказ #{order_id} принят в мастерскую."
            )
            
            # Сразу показываем детали заказа (комментарий не обязателен)
            await show_order_detail(update, context, order_id, "accepted", 0)
        except Exception as e:
            logger.error(f"Error in skip_ready_date: {e}", exc_info=True)
        return

    if data.startswith("skip_master_comment_"):
        try:
            # Сначала отвечаем на callback МГНОВЕННО
            await query.answer("Комментарий пропущен")
            
            # Извлекаем order_id корректно
            parts = data.split("_")
            order_id = int(parts[-1])
            
            context.user_data.pop("awaiting_master_comment", None)
            
            logger.info(f"Skipping master comment for order {order_id}, user_id={user_id}")
            
            # Удаляем старое сообщение
            try:
                await query.message.delete()
            except Exception as de:
                logger.warning(f"Could not delete message: {de}")

            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ Заказ #{order_id} принят в мастерскую."
            )
            
            # Показываем детали заказа
            await show_order_detail(update, context, order_id, "accepted", 0)
        except Exception as e:
            logger.error(f"Error in skip_master_comment: {e}", exc_info=True)
        return
    
    if data.startswith("olist_"):
        parts = data.replace("olist_", "").split("_")
        if len(parts) >= 2:
            status = "_".join(parts[:-1])
            page = int(parts[-1])
            await show_orders_list(update, context, status, page)
        return
    
    if data.startswith("odetail_"):
        parts = data.replace("odetail_", "").split("_")
        if len(parts) >= 3:
            order_id = int(parts[0])
            back_status = "_".join(parts[1:-1])
            back_page = int(parts[-1])
            await show_order_detail(update, context, order_id, back_status, back_page)
        return
    
    if data.startswith("ostatus_"):
        parts = data.replace("ostatus_", "").split("_")
        if len(parts) >= 2:
            order_id = int(parts[0])
            new_status = "_".join(parts[1:])
            await handle_order_status_change(update, context, order_id, new_status)
        return
    
    if data.startswith("odelete_"):
        order_id = int(data.replace("odelete_", ""))
        await handle_order_delete(update, context, order_id)
        return
    
    if data == "osearch_menu":
        await show_search_menu(update, context)
        return
    
    if data == "osearch_id":
        await start_search_by_id(update, context)
        return
    
    if data == "osearch_name":
        await start_search_by_name(update, context)
        return
    
    if data == "orders_page_info":
        await query.answer("Текущая страница")
        return
    
    await query.answer("Неизвестное действие")

async def handle_ready_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Обработка ввода срока готовности и комментария от мастера"""
    if not update.message or not update.message.text:
        return False
    
    order_id = context.user_data.get("awaiting_ready_date")
    if not order_id:
        return False
    
    # Извлекаем текст
    text = update.message.text.strip()
    
    # Если это команда отмены — сбрасываем
    if text.startswith('/'):
        if text == '/skip':
            # Мастер решил пропустить ввод даты
            pass
        else:
            # Другая команда — отменяем ввод даты
            context.user_data.pop("awaiting_ready_date", None)
            return False

    try:
        from utils.database import get_order, update_order_status, get_session, Order
        
        # Обновляем срок напрямую через сессию
        session = get_session()
        order = session.query(Order).filter(Order.id == order_id).first()
        if order:
            if text != '/skip':
                order.ready_date = text
            order.status = "accepted"
            from utils.database import MOSCOW_TZ
            from datetime import datetime
            order.updated_at = datetime.now(MOSCOW_TZ).replace(tzinfo=None)
            session.commit()
            logger.info(f"Order {order_id} ready_date updated to: {order.ready_date}")
        session.close()
        
        # Очищаем состояние
        context.user_data.pop("awaiting_ready_date", None)
        
        await update.message.reply_text(
            f"✅ Заказ #{order_id} принят. Срок готовности: {text if text != '/skip' else 'не указан'}\n"
            f"Теперь он находится в списке «Приняты»."
        )
        
        # Показываем детали заказа
        await show_order_detail(update, context, order_id, "accepted", 0)
        return True
        
    except Exception as e:
        logger.error(f"Error handling ready date input: {e}", exc_info=True)
        # В случае ошибки очищаем состояние, чтобы бот не "висел"
        context.user_data.pop("awaiting_ready_date", None)
        await update.message.reply_text("❌ Произошла ошибка при сохранении данных. Состояние ввода сброшено.")
        return True
