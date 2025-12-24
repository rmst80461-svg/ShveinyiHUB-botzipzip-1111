from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from keyboards import get_services_menu, get_main_menu, get_back_button, get_admin_main_menu
from utils.database import create_order, get_admins, add_user
from utils.knowledge_loader import knowledge
import logging
import os
import random
from datetime import datetime, timezone, timedelta

MOSCOW_TZ = timezone(timedelta(hours=3))

logger = logging.getLogger(__name__)

SELECT_SERVICE, SEND_PHOTO, ENTER_NAME, ENTER_PHONE, CONFIRM_ORDER = range(5)

WORKSHOP_PHONE = "+7 (968) 396-91-52"
WORKSHOP_ADDRESS = "г.Москва, м. Ховрино, ул.Маршала Федоренко д.12, 1 этаж"

WORK_HOURS = {
    0: "10:00-19:50",  # Пн
    1: "10:00-19:50",  # Вт
    2: "10:00-19:50",  # Ср
    3: "10:00-19:50",  # Чт
    4: "10:00-19:00",  # Пт
    5: "10:00-17:00",  # Сб
    6: None  # Вс - выходной
}

def get_today_hours():
    """Получить время работы на сегодня (по московскому времени)"""
    weekday = datetime.now(MOSCOW_TZ).weekday()
    hours = WORK_HOURS.get(weekday)
    if hours:
        return f"с {hours.replace('-', ' до ')}"
    return None

def is_workday():
    """Проверить, рабочий ли сегодня день (по московскому времени)"""
    return WORK_HOURS.get(datetime.now(MOSCOW_TZ).weekday()) is not None

CONFIRMATION_PHRASES_WORKDAY = [
    "Супер! Заказчик нашёлся! 🎉\nЖдём-поджидаем вас сегодня! Кстати, мы тут не скучаем — работаем {hours}.\nПриходите, покажем, как можно починить почти всё!",
    "Отлично, мы уже готовимся к вашему визиту! ❤️\nСегодня ждём вас {hours} — специально выделили время на консультацию.\nРасскажете историю вещи, а мы найдём для неё лучшее решение!",
    "Прекрасно! Ваша вещь уже в очереди на спасение! 🦸‍♀️\nЖдём вас сегодня {hours} — приходите, обсудим детали.\nОбещаем, результат вас приятно удивит!",
    "Иголочка всё записала! ✨\nЖдём вас сегодня в мастерской — мы работаем {hours}.\nПриходите, обсудим детали и примемся за работу!",
]

CONFIRMATION_PHRASES_WEEKEND = [
    "Иголочка всё записала! ✨\nСегодня у нас выходной, но завтра с 10:00 уже ждём вас в мастерской!\nОтдыхайте, а мы скоро примемся за работу!",
    "Супер! Заказ принят! 🎉\nСегодня воскресенье — даже иголки отдыхают. 😊\nЖдём вас завтра с 10:00!",
    "Отлично, заказ оформлен! ❤️\nСегодня выходной, но уже завтра с 10:00 будем рады вас видеть!\nСвяжемся с вами в понедельник.",
    "Прекрасно! Ваша вещь уже в очереди на спасение! 🦸‍♀️\nСегодня мы отдыхаем, но завтра с 10:00 — за работу!\nДо скорой встречи!",
]

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


async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало создания заказа"""
    user_id = update.effective_user.id
    logger.info(f"order_start called by user {user_id}")
    
    from handlers.admin import is_user_admin
    if is_user_admin(user_id):
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                text="⚠️ *Администраторы не создают заказы через бота*\n\n"
                     "Используйте веб-панель для управления заказами.\n"
                     "Клиенты могут создавать заказы самостоятельно.",
                reply_markup=get_admin_main_menu(),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                text="⚠️ *Администраторы не создают заказы через бота*\n\n"
                     "Используйте веб-панель для управления заказами.",
                reply_markup=get_admin_main_menu(),
                parse_mode="Markdown"
            )
        return ConversationHandler.END
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text="➕ *Оформление заказа*\n\nВыберите категорию услуги:",
            reply_markup=get_services_menu(),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text="➕ *Оформление заказа*\n\nВыберите категорию услуги:",
            reply_markup=get_services_menu(),
            parse_mode="Markdown"
        )
    logger.info(f"order_start returning SELECT_SERVICE ({SELECT_SERVICE})")
    return SELECT_SERVICE


async def select_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор услуги"""
    logger.info(f"select_service called: {update.callback_query.data}")
    await update.callback_query.answer()
    
    if update.callback_query.data == "back_menu":
        await update.callback_query.edit_message_text(
            text="Главное меню:",
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END
    
    service = update.callback_query.data.replace("service_", "")
    context.user_data['service'] = service
    context.user_data['service_name'] = SERVICE_NAMES.get(service, service)
    
    prices = knowledge.get_category_prices(service)
    
    keyboard = [
        [InlineKeyboardButton("⏭ Пропустить фото", callback_data="skip_photo")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
    ]
    
    await update.callback_query.edit_message_text(
        text=f"✅ Вы выбрали: {SERVICE_NAMES.get(service, service)}\n\n"
        f"{prices if prices else ''}\n\n"
        f"📸 *Шаг 1/4*: Отправьте фото вашей вещи\n"
        f"(или нажмите 'Пропустить')",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SEND_PHOTO


def get_user_display_name(user) -> str:
    """Получить отображаемое имя пользователя"""
    if user.first_name:
        return user.first_name
    if user.username:
        return user.username
    return f"Пользователь {user.id}"


async def ask_name(update, context, is_callback=False):
    """Спросить имя у пользователя"""
    user = update.effective_user
    user_name = get_user_display_name(user)
    context.user_data['suggested_name'] = user_name
    
    keyboard = [
        [InlineKeyboardButton(f"✅ Да, я {user_name}", callback_data="use_tg_name")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
    ]
    
    text = (
        f"📸 Фото получено!\n\n" if not is_callback else ""
    ) + (
        f"👤 *Шаг 2/3*: Как к вам обращаться?\n\n"
        f"Обращаться к вам *{user_name}*?\n"
        f"Или напишите другое имя:"
    )
    
    if is_callback:
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение фото"""
    if update.message and update.message.photo:
        photo = update.message.photo[-1]
        context.user_data['photo_file_id'] = photo.file_id
        await ask_name(update, context, is_callback=False)
        return ENTER_NAME
    
    await update.message.reply_text(
        "Пожалуйста, отправьте фото или нажмите 'Пропустить'."
    )
    return SEND_PHOTO


async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропуск фото"""
    await update.callback_query.answer()
    context.user_data['photo_file_id'] = None
    await ask_name(update, context, is_callback=True)
    return ENTER_NAME


async def use_tg_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Использовать имя из Telegram"""
    await update.callback_query.answer()
    name = context.user_data.get('suggested_name', get_user_display_name(update.effective_user))
    context.user_data['client_name'] = name
    
    keyboard = [
        [InlineKeyboardButton("⏭ Пропустить (уведомлю сюда)", callback_data="skip_phone")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
    ]
    
    await update.callback_query.edit_message_text(
        text=f"Отлично, {name}! 👋\n\n"
        "📞 *Шаг 3/3*: Укажите номер телефона\n\n"
        "Введите номер для SMS о готовности\n"
        "или нажмите «Пропустить» — пришлём уведомление сюда",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ENTER_PHONE


async def enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ввод имени"""
    name = update.message.text.strip()
    
    if len(name) < 2 or len(name) > 50:
        await update.message.reply_text("Пожалуйста, введите корректное имя (2-50 символов).")
        return ENTER_NAME
    
    context.user_data['client_name'] = name
    
    keyboard = [
        [InlineKeyboardButton("⏭ Пропустить (уведомлю сюда)", callback_data="skip_phone")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
    ]
    
    await update.message.reply_text(
        text=f"Приятно познакомиться, {name}! 👋\n\n"
        "📞 *Шаг 3/3*: Укажите номер телефона\n\n"
        "Введите номер для SMS о готовности\n"
        "или нажмите «Пропустить» — пришлём уведомление сюда",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ENTER_PHONE


async def skip_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропуск телефона"""
    await update.callback_query.answer()
    context.user_data['client_phone'] = "Telegram"
    return await show_confirmation(update, context, is_callback=True)


async def enter_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ввод телефона"""
    phone = update.message.text.strip()
    
    digits = ''.join(filter(str.isdigit, phone))
    if len(digits) < 10 or len(digits) > 15:
        keyboard = [
            [InlineKeyboardButton("⏭ Пропустить (уведомлю сюда)", callback_data="skip_phone")],
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
        ]
        await update.message.reply_text(
            "Неверный формат номера.\n"
            "Введите номер (например: +7 999 123 45 67)\n"
            "или нажмите «Пропустить»",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ENTER_PHONE
    
    context.user_data['client_phone'] = phone
    return await show_confirmation(update, context, is_callback=False)


async def show_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback: bool) -> int:
    """Показать подтверждение заказа"""
    service_name = context.user_data.get('service_name', 'Услуга')
    client_name = context.user_data.get('client_name', 'Клиент')
    phone = context.user_data.get('client_phone', 'Telegram')
    has_photo = "✅ Фото прикреплено" if context.user_data.get('photo_file_id') else "❌ Без фото"
    
    phone_display = "📲 Telegram" if phone == "Telegram" else f"📞 {phone}"
    
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить заказ", callback_data="confirm_order")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
    ]
    
    text = (
        f"📋 *Проверьте данные заказа:*\n\n"
        f"🔹 Услуга: {service_name}\n"
        f"🔹 Имя: {client_name}\n"
        f"🔹 Связь: {phone_display}\n"
        f"🔹 {has_photo}\n\n"
        f"Всё верно?"
    )
    
    if is_callback:
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    
    return CONFIRM_ORDER


async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение заказа"""
    await update.callback_query.answer()
    
    user = update.effective_user
    user_id = user.id
    
    add_user(
        user_id=user_id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=context.user_data.get('client_phone')
    )
    
    order_id = create_order(
        user_id=user_id,
        service_type=context.user_data.get('service', 'unknown'),
        description=context.user_data.get('service_name', 'Услуга'),
        photo_file_id=context.user_data.get('photo_file_id'),
        client_name=context.user_data.get('client_name'),
        client_phone=context.user_data.get('client_phone')
    )
    
    if is_workday():
        today_hours = get_today_hours()
        confirmation_phrase = random.choice(CONFIRMATION_PHRASES_WORKDAY).format(hours=today_hours)
    else:
        confirmation_phrase = random.choice(CONFIRMATION_PHRASES_WEEKEND)
    
    await update.callback_query.edit_message_text(
        text=f"✅ *Заказ принят!*\n\n"
        f"📋 *Номер вашего заказа: #{order_id}*\n\n"
        f"{confirmation_phrase}\n\n"
        f"📍 {WORKSHOP_ADDRESS}\n"
        f"📞 {WORKSHOP_PHONE}",
        parse_mode="Markdown"
    )
    
    await context.bot.send_message(
        chat_id=user_id,
        text=f"✅ Ваш заказ №{order_id} успешно принят!\n\n"
              f"Спасибо за заказ. Скоро мы свяжемся с вами по телефону {context.user_data.get('client_phone', 'номер')} для уточнения деталей."
    )
    
    await notify_admins(context, order_id, context.user_data, user_id)
    
    context.user_data.clear()
    return ConversationHandler.END


def get_admin_order_keyboard(order_id: int, user_id: int) -> InlineKeyboardMarkup:
    """Создать клавиатуру управления заказом для админа"""
    web_admin_url = os.getenv('REPLIT_DEV_DOMAIN', '')
    if web_admin_url:
        web_admin_url = f"https://{web_admin_url}/orders"
    else:
        web_admin_url = "https://workshop-bot.replit.app/orders"
    
    keyboard = [
        [
            InlineKeyboardButton("✅ В работу", callback_data=f"status_in_progress_{order_id}"),
            InlineKeyboardButton("📦 Готов", callback_data=f"status_completed_{order_id}")
        ],
        [
            InlineKeyboardButton("❌ Отменить", callback_data=f"status_cancelled_{order_id}"),
            InlineKeyboardButton("🌐 Веб-админка", url=web_admin_url)
        ],
        [
            InlineKeyboardButton("✉️ Написать клиенту", url=f"tg://user?id={user_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def notify_admins(context: ContextTypes.DEFAULT_TYPE, order_id: int, order_data: dict, user_id: int = None):
    """Уведомить админов о новом заказе"""
    try:
        admins = get_admins()
        
        admin_ids = [os.getenv('ADMIN_ID')]
        for admin in admins:
            if admin.user_id not in admin_ids:
                admin_ids.append(admin.user_id)
        
        now = datetime.now(MOSCOW_TZ)
        date_str = now.strftime("%d.%m.%Y %H:%M")
        
        service_key = order_data.get('service', 'unknown')
        service_name = SERVICE_NAMES.get(service_key, order_data.get('service_name', service_key))
        
        message = (
            f"📁 *Заказ #{order_id}*\n\n"
            f"◆ Услуга: {service_name}\n"
            f"◆ Клиент: {order_data.get('client_name', 'Не указано')}\n"
            f"◆ Телефон: {order_data.get('client_phone', 'Не указан')}\n"
            f"◆ Статус: new\n"
            f"◆ Дата: {date_str}\n"
            f"◆ Фото: {'Да' if order_data.get('photo_file_id') else 'Нет'}"
        )
        
        keyboard = get_admin_order_keyboard(order_id, user_id or 0)
        
        for admin_id in admin_ids:
            if admin_id:
                try:
                    admin_id = int(admin_id) if isinstance(admin_id, str) else admin_id
                    
                    if order_data.get('photo_file_id'):
                        await context.bot.send_photo(
                            chat_id=admin_id,
                            photo=order_data['photo_file_id'],
                            caption=message,
                            reply_markup=keyboard,
                            parse_mode="Markdown"
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=message,
                            reply_markup=keyboard,
                            parse_mode="Markdown"
                        )
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_id}: {e}")
    except Exception as e:
        logger.error(f"Error notifying admins: {e}")


async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена заказа"""
    await update.callback_query.answer()
    context.user_data.clear()
    
    await update.callback_query.edit_message_text(
        text="❌ Заказ отменён.\n\nВы можете оформить новый заказ в любое время.",
        reply_markup=get_main_menu()
    )
    return ConversationHandler.END


async def handle_order_status_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Изменение статуса заказа админом"""
    await update.callback_query.answer()
    
    data = update.callback_query.data
    admin_user = update.effective_user
    admin_name = admin_user.username or admin_user.first_name or str(admin_user.id)
    
    from utils.database import update_order_status, get_order
    
    order_id = None
    status_text = ""
    new_status = ""
    
    if data.startswith("status_in_progress_"):
        order_id = int(data.replace("status_in_progress_", ""))
        update_order_status(order_id, "in_progress")
        status_text = "🔄 В работе"
        new_status = "in_progress"
    elif data.startswith("status_completed_"):
        order_id = int(data.replace("status_completed_", ""))
        update_order_status(order_id, "completed")
        status_text = "✅ Готов"
        new_status = "completed"
    elif data.startswith("status_issued_"):
        order_id = int(data.replace("status_issued_", ""))
        update_order_status(order_id, "issued")
        status_text = "📤 Выдан"
        new_status = "issued"
    elif data.startswith("status_cancelled_"):
        order_id = int(data.replace("status_cancelled_", ""))
        update_order_status(order_id, "cancelled")
        status_text = "❌ Отменён"
        new_status = "cancelled"
    elif data.startswith("admin_open_"):
        order_id = int(data.replace("admin_open_", ""))
        await update.callback_query.answer("Откройте веб-админку для управления заказом", show_alert=True)
        return
    else:
        return
    
    order = get_order(order_id)
    if order and new_status not in ("cancelled", "issued"):
        try:
            client_message = {
                "in_progress": (
                    f"✂️ Ваша вещь уже в работе!\n\n"
                    f"Делаем всё качественно и аккуратно. "
                    f"Мы свяжемся с вами, когда заказ будет готов."
                ),
                "completed": (
                    f"🎉 Заказ выполнен!\n\n"
                    f"Ждём вас на выдачу в удобное время.\n\n"
                    f"📍 {WORKSHOP_ADDRESS}\n"
                    f"⏰ Пн-Чт: 10:00-19:50, Пт: 10:00-19:00, Сб: 10:00-17:00\n"
                    f"📞 {WORKSHOP_PHONE}"
                )
            }
            await context.bot.send_message(
                chat_id=order.user_id,
                text=client_message.get(new_status, f"📦 Статус заказа: {status_text}")
            )
        except Exception as e:
            logger.error(f"Failed to notify user about status change: {e}")
    
    next_list = {
        "in_progress": "admin_orders_in_progress",
        "completed": "admin_orders_completed",
        "issued": "admin_orders_issued",
        "cancelled": "admin_back_menu"
    }.get(new_status, "admin_back_menu")
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ К списку заказов", callback_data=next_list)]
    ])
    
    new_text = f"✅ Заказ #{order_id} обновлён\n\n{status_text}\n\n👤 Обработал: @{admin_name}"
    
    try:
        if update.callback_query.message.photo:
            await update.callback_query.edit_message_caption(
                caption=new_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await update.callback_query.edit_message_text(
                text=new_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Failed to update admin message: {e}")
