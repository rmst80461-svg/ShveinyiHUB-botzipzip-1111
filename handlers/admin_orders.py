"""
Улучшенная система управления заказами с пагинацией, фильтрацией и поиском.
"""
import os
import logging
from typing import Optional, List, Tuple

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
    "in_progress": "🔄",
    "completed": "✅",
    "issued": "📤",
    "cancelled": "❌",
    "spam": "🚫",
}

STATUS_NAMES = {
    "new": "Новые",
    "in_progress": "В работе",
    "completed": "Готовые",
    "issued": "Выданные",
    "cancelled": "Отменённые",
    "spam": "Спам",
}

NEXT_STATUS = {
    "new": "in_progress",
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
        service_display = SERVICE_NAMES.get(order.service_type, order.service_type or '—')
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
            f"{'✓ ' if status == 'new' else ''}🆕 Новые",
            callback_data="olist_new_0"
        ),
        InlineKeyboardButton(
            f"{'✓ ' if status == 'in_progress' else ''}🔄 В работе",
            callback_data="olist_in_progress_0"
        ),
    ]
    filter_row2 = [
        InlineKeyboardButton(
            f"{'✓ ' if status == 'completed' else ''}✅ Готовые",
            callback_data="olist_completed_0"
        ),
        InlineKeyboardButton(
            f"{'✓ ' if status == 'issued' else ''}📤 Выданные",
            callback_data="olist_issued_0"
        ),
    ]
    keyboard.append(filter_row1)
    keyboard.append(filter_row2)
    
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
    status: str = "new",
    page: int = 0
) -> None:
    """Показать список заказов с пагинацией"""
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if query:
            await query.answer("⛔ Нет доступа", show_alert=True)
        return
    
    orders = get_orders_by_status(status)
    total_orders = len(orders)
    
    if total_orders == 0:
        text = f"📋 *{STATUS_EMOJI.get(status, '')} {STATUS_NAMES.get(status, status)}*\n\n📭 Заказов нет"
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
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return
    
    total_pages = (total_orders + ORDERS_PER_PAGE - 1) // ORDERS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * ORDERS_PER_PAGE
    end_idx = start_idx + ORDERS_PER_PAGE
    current_orders = orders[start_idx:end_idx]
    
    text = f"📋 *{STATUS_EMOJI.get(status, '')} {STATUS_NAMES.get(status, status)}* — {total_orders} шт.\n\n"
    
    for order in current_orders:
        formatted_id = format_order_id(order.id, order.created_at)
        service_display = SERVICE_NAMES.get(order.service_type, order.service_type or '—')
        phone_display = order.client_phone or "📲 TG"
        date_str = order.created_at.strftime('%d.%m.%Y %H:%M') if order.created_at else '—'
        
        text += f"📦 *{formatted_id}*\n"
        text += f"👤 {order.client_name or 'Аноним'} | {phone_display}\n"
        text += f"🛠 _{service_display}_ | 📅 {date_str}\n\n"
    
    text += f"📄 Страница {page + 1} из {total_pages}"
    
    keyboard = create_orders_list_keyboard(current_orders, status, page, total_pages)
    
    if query:
        try:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


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
    service_display = SERVICE_NAMES.get(order.service_type, order.service_type or '—')
    status_emoji = STATUS_EMOJI.get(order.status, "❓")
    status_name = STATUS_NAMES.get(order.status, order.status)
    phone_display = order.client_phone if order.client_phone and order.client_phone != "Telegram" else "📲 Telegram"
    date_str = order.created_at.strftime('%d.%m.%Y %H:%M') if order.created_at else 'Н/Д'
    
    text = (
        f"📦 *Заказ {formatted_id}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 *Статус:* {status_emoji} {status_name}\n"
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
                    f"{client_name}, привет! 😊\n\n"
                    f"Ваш заказ уже у наших мастеров в работе ✂️\n\n"
                    f"Заказ: {formatted_id}\n\n"
                    f"Как только всё будет готово — сразу напишем!\n\n"
                    f"Команда «Швейный HUB» 🧵"
                ),
                "completed": (
                    f"{client_name}, отличные новости! 🎉\n\n"
                    f"Ваш заказ готов!\n"
                    f"Заказ: {formatted_id}\n\n"
                    f"Ждём вас на выдачу!\n\n"
                    f"До встречи!\nКоманда «Швейный HUB» 🧵"
                ),
                "issued": (
                    f"{client_name}, спасибо что были с нами! 💜\n\n"
                    f"Заказ {formatted_id} выдан.\n\n"
                    f"Будем рады видеть вас снова!\n"
                    f"Команда «Швейный HUB» 🧵"
                ),
                "cancelled": f"Заказ {formatted_id} отменён.\n\nЕсли есть вопросы — мы на связи!\nКоманда «Швейный HUB»",
            }
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


async def orders_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Главный обработчик callback для системы заказов"""
    query = update.callback_query
    data = query.data
    
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
