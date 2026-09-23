import os
import logging
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from keyboards import get_services_menu, get_main_menu, get_admin_main_menu
from utils.database import create_order, get_admins, add_user, get_order, update_order_status, track_event
from utils.knowledge_loader import knowledge
from handlers.admin import is_user_admin

logger = logging.getLogger(__name__)

# Константы для состояний ConversationHandler
SELECT_SERVICE, SEND_PHOTO, ENTER_DESCRIPTION, ENTER_NAME, ENTER_PHONE, CONFIRM_ORDER = range(
    6)

# Контактная информация
WORKSHOP_PHONE = "+7 (968) 396-91-52"
WORKSHOP_ADDRESS = "г. Москва, (МЦД/м. Ховрино) ул. Маршала Федоренко д.12, ТЦ \"Бусиново\", 1 этаж"

# Часы работы (0=Пн, 6=Вс)
WORK_HOURS = {
    0: "10:00-19:50",  # Пн
    1: "10:00-19:50",  # Вт
    2: "10:00-19:50",  # Ср
    3: "10:00-19:50",  # Чт
    4: "10:00-19:00",  # Пт
    5: "10:00-17:00",  # Сб
    6: None  # Вс - выходной
}

# Часовой пояс Москвы (UTC+3)
MOSCOW_TZ = timezone(timedelta(hours=3))

# Фразы подтверждения
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

# Названия услуг
SERVICE_NAMES = {
    "jacket": "🧥 Ремонт пиджака",
    "leather": "🎒 Изделия из кожи",
    "curtains": "🪟 Пошив штор",
    "coat": "🧥 Ремонт куртки",
    "fur": "🐾 Шубы и дублёнки",
    "outerwear": "🧥 Плащ/пальто",
    "pants": "👖 Брюки/джинсы",
    "dress": "👗 Юбки/платья",
    "other": "❓ Другое"
}


def get_moscow_time(dt: Optional[datetime] = None) -> datetime:
    """Получить текущее время в Московском часовом поясе"""
    if dt is None:
        return datetime.now(MOSCOW_TZ)

    if dt.tzinfo is None:
        # Если datetime наивный (без часового пояса), считаем что это UTC
        return dt.replace(tzinfo=timezone.utc).astimezone(MOSCOW_TZ)
    return dt.astimezone(MOSCOW_TZ)


def get_today_hours() -> Optional[str]:
    """Получить время работы на сегодня (по московскому времени)"""
    weekday = get_moscow_time().weekday()
    hours = WORK_HOURS.get(weekday)
    if hours:
        return f"с {hours.replace('-', ' до ')}"
    return None


def is_workday() -> bool:
    """Проверить, рабочий ли сегодня день (по московскому времени)"""
    return WORK_HOURS.get(get_moscow_time().weekday()) is not None


def format_order_id(order_id: int,
                    created_at: Optional[datetime] = None) -> str:
    """Форматировать номер заказа в виде дд-мм.гг-#id

    Args:
        order_id: ID заказа
        created_at: дата создания заказа (если None, использует текущую дату)

    Returns:
        Форматированный номер в виде "24-12.25-#1"
    """
    date_obj = get_moscow_time(created_at)
    day = date_obj.strftime('%d')
    month = date_obj.strftime('%m')
    year = date_obj.strftime('%y')
    return f"{day}-{month}.{year}-#{order_id}"


def get_user_display_name(user) -> str:
    """Получить отображаемое имя пользователя"""
    if user.first_name:
        return user.first_name
    if user.username:
        return f"@{user.username}"
    return f"Пользователь {user.id}"


async def order_start(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало создания заказа"""
    try:
        user = update.effective_user
        user_id = user.id
        logger.info(f"Начало оформления заказа от пользователя {user_id}")

        # Проверяем, является ли пользователь администратором
        if is_user_admin(user_id):
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(
                    text="⚠️ *Администраторы не создают заказы через бота*\n\n"
                    "Используйте веб-панель для управления заказами.\n"
                    "Клиенты могут создавать заказы самостоятельно.",
                    reply_markup=get_admin_main_menu(),
                    parse_mode="Markdown")
            else:
                await update.message.reply_text(
                    text="⚠️ *Администраторы не создают заказы через бота*\n\n"
                    "Используйте веб-панель для управления заказами.",
                    reply_markup=get_admin_main_menu(),
                    parse_mode="Markdown")
            return ConversationHandler.END

        # Очищаем данные предыдущего заказа
        context.user_data.clear()
        
        # Отслеживаем начало оформления заказа
        track_event(user_id, 'order_started')

        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                text="➕ *Оформление заказа*\n\nВыберите категорию услуги:",
                reply_markup=get_services_menu(),
                parse_mode="Markdown")
        else:
            await update.message.reply_text(
                text="➕ *Оформление заказа*\n\nВыберите категорию услуги:",
                reply_markup=get_services_menu(),
                parse_mode="Markdown")

        logger.info(f"Переход к состоянию SELECT_SERVICE")
        return SELECT_SERVICE

    except Exception as e:
        logger.error(f"Ошибка в начале оформления заказа: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при начале оформления заказа. Пожалуйста, попробуйте позже."
        )
        return ConversationHandler.END


async def select_service(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор услуги"""
    try:
        query = update.callback_query
        await query.answer()

        logger.info(f"Выбор услуги: {query.data}")

        if query.data == "back_menu":
            await query.edit_message_text(text="🏠 Возврат в главное меню",
                                          reply_markup=get_main_menu())
            return ConversationHandler.END

        service = query.data.replace("service_", "")
        context.user_data['service'] = service
        context.user_data['service_name'] = SERVICE_NAMES.get(service, "❓ Другая услуга")
        
        # Отслеживаем выбор категории
        user_id = update.effective_user.id
        track_event(user_id, 'order_category_selected', service)

        # Для категории "Другое" сразу переходим к описанию проблемы
        if service == "other":
            keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]]
            await query.edit_message_text(
                text="❓ *Вы выбрали: Другое*\n\n"
                "📝 *Шаг 1/5*: Опишите, что именно вам нужно сделать?\n"
                "(Например: укоротить рукава, вшить молнию, подогнать по фигуре и т.д.)",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown")
            context.user_data['other_description_mode'] = True
            logger.info(f"Переход к состоянию ENTER_DESCRIPTION для категории 'Другое'")
            return ENTER_DESCRIPTION

        # Получаем информацию об услуге
        service_info = ""
        try:
            if knowledge and hasattr(knowledge, 'get_category_prices'):
                prices = knowledge.get_category_prices(service)
                if prices:
                    service_info = f"\n{prices}\n"
        except Exception as e:
            logger.warning(f"Не удалось получить информацию об услуге: {e}")

        keyboard = [[
            InlineKeyboardButton("⏭ Пропустить фото",
                                 callback_data="skip_photo")
        ], [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]]

        await query.edit_message_text(
            text=f"✅ Вы выбрали: *{SERVICE_NAMES.get(service, service)}*\n"
            f"{service_info}\n"
            f"📸 *Шаг 1/5*: Отправьте фото вашей вещи\n"
            f"(или нажмите 'Пропустить')",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown")

        logger.info(f"Переход к состоянию SEND_PHOTO")
        return SEND_PHOTO

    except Exception as e:
        logger.error(f"Ошибка при выборе услуги: {e}")
        await update.callback_query.edit_message_text(
            "❌ Произошла ошибка. Пожалуйста, начните заново с команды /order")
        return ConversationHandler.END


async def receive_photo(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получение фото"""
    try:
        if update.message and update.message.photo:
            photo = update.message.photo[-1]
            context.user_data['photo_file_id'] = photo.file_id
            
            # Отслеживаем добавление фото
            track_event(update.effective_user.id, 'order_photo_added')

            # Для "Другое" описание уже введено — пропускаем шаг описания
            if context.user_data.get('service') == 'other' and context.user_data.get('problem_description'):
                user = update.effective_user
                user_name = get_user_display_name(user)
                context.user_data['suggested_name'] = user_name

                keyboard = [[
                    InlineKeyboardButton(f"✅ Да, я {user_name}",
                                         callback_data="use_tg_name")
                ], [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]]

                await update.message.reply_text(
                    text=f"📸 Фото получено!\n\n"
                    f"👤 *Шаг 3/5*: Как к вам обращаться?\n\n"
                    f"Обращаться к вам *{user_name}*?\n"
                    f"Или напишите другое имя:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown")

                logger.info("Переход к состоянию ENTER_NAME (категория 'Другое', описание уже есть)")
                return ENTER_NAME

            keyboard = [[
                InlineKeyboardButton("⏭ Пропустить описание",
                                     callback_data="skip_description")
            ],
                        [
                            InlineKeyboardButton("❌ Отменить",
                                                 callback_data="cancel_order")
                        ]]

            await update.message.reply_text(
                text="📸 Фото получено!\n\n"
                "📝 *Шаг 2/5*: Кратко опишите проблему\n"
                "(например: 'подшить брюки' или 'замена молнии'):",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown")

            logger.info("Переход к состоянию ENTER_DESCRIPTION (после фото)")
            return ENTER_DESCRIPTION

        await update.message.reply_text(
            "Пожалуйста, отправьте фото или нажмите 'Пропустить'.")
        return SEND_PHOTO

    except Exception as e:
        logger.error(f"Ошибка при получении фото: {e}")
        await update.message.reply_text(
            "❌ Не удалось обработать фото. Пожалуйста, попробуйте еще раз.")
        return SEND_PHOTO


async def skip_photo(update: Update,
                     context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропуск фото"""
    try:
        await update.callback_query.answer()
        context.user_data['photo_file_id'] = None
        
        # Отслеживаем пропуск фото (отдельный тип события)
        track_event(update.effective_user.id, 'order_photo_skipped')

        # Для "Другое" описание уже введено — пропускаем шаг описания
        if context.user_data.get('service') == 'other' and context.user_data.get('problem_description'):
            user = update.effective_user
            user_name = get_user_display_name(user)
            context.user_data['suggested_name'] = user_name

            keyboard = [[
                InlineKeyboardButton(f"✅ Да, я {user_name}",
                                     callback_data="use_tg_name")
            ], [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]]

            await update.callback_query.edit_message_text(
                text=f"👤 *Шаг 3/5*: Как к вам обращаться?\n\n"
                f"Обращаться к вам *{user_name}*?\n"
                f"Или напишите другое имя:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown")

            logger.info("Переход к состоянию ENTER_NAME (категория 'Другое', описание уже есть)")
            return ENTER_NAME

        keyboard = [[
            InlineKeyboardButton("⏭ Пропустить описание",
                                 callback_data="skip_description")
        ], [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]]

        await update.callback_query.edit_message_text(
            text="📝 *Шаг 2/5*: Кратко опишите проблему\n"
            "(например: 'подшить брюки' или 'замена молнии'):",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown")

        logger.info("Переход к состоянию ENTER_DESCRIPTION (пропуск фото)")
        return ENTER_DESCRIPTION

    except Exception as e:
        logger.error(f"Ошибка при пропуске фото: {e}")
        return ConversationHandler.END


async def enter_description(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ввод описания проблемы"""
    try:
        description = update.message.text.strip()
        context.user_data['problem_description'] = description
        
        # Отслеживаем добавление описания
        track_event(update.effective_user.id, 'order_description_added')

        # Для категории "Другое" — после описания переходим к фото
        if context.user_data.get('other_description_mode'):
            context.user_data['other_description_mode'] = False
            keyboard = [[
                InlineKeyboardButton("⏭ Пропустить фото",
                                     callback_data="skip_photo")
            ], [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]]

            await update.message.reply_text(
                text=f"✅ Описание сохранено!\n\n"
                f"📸 *Шаг 2/5*: Отправьте фото вашей вещи\n"
                f"(или нажмите 'Пропустить')",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown")

            logger.info(f"Переход к состоянию SEND_PHOTO (после описания 'Другое': {description})")
            return SEND_PHOTO

        user = update.effective_user
        user_name = get_user_display_name(user)
        context.user_data['suggested_name'] = user_name

        keyboard = [[
            InlineKeyboardButton(f"✅ Да, я {user_name}",
                                 callback_data="use_tg_name")
        ], [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]]

        await update.message.reply_text(
            text=f"👤 *Шаг 3/5*: Как к вам обращаться?\n\n"
            f"Обращаться к вам *{user_name}*?\n"
            f"Или напишите другое имя:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown")

        logger.info(
            f"Переход к состоянию ENTER_NAME (после описания: {description})")
        return ENTER_NAME

    except Exception as e:
        logger.error(f"Ошибка при вводе описания: {e}")
        await update.message.reply_text(
            "❌ Не удалось обработать описание. Пожалуйста, попробуйте еще раз."
        )
        return ENTER_DESCRIPTION


async def skip_description(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропуск описания проблемы"""
    try:
        await update.callback_query.answer()
        context.user_data['problem_description'] = None

        user = update.effective_user
        user_name = get_user_display_name(user)
        context.user_data['suggested_name'] = user_name

        keyboard = [[
            InlineKeyboardButton(f"✅ Да, я {user_name}",
                                 callback_data="use_tg_name")
        ], [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]]

        await update.callback_query.edit_message_text(
            text=f"👤 *Шаг 3/5*: Как к вам обращаться?\n\n"
            f"Обращаться к вам *{user_name}*?\n"
            f"Или напишите другое имя:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown")

        logger.info("Переход к состоянию ENTER_NAME (пропуск описания)")
        return ENTER_NAME

    except Exception as e:
        logger.error(f"Ошибка при пропуске описания: {e}")
        return ConversationHandler.END


async def use_tg_name(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> int:
    """Использовать имя из Telegram"""
    try:
        await update.callback_query.answer()

        name = context.user_data.get(
            'suggested_name', get_user_display_name(update.effective_user))
        context.user_data['client_name'] = name
        
        # Отслеживаем ввод имени
        track_event(update.effective_user.id, 'order_name_added')

        keyboard = [[
            InlineKeyboardButton("⏭ Пропустить (уведомлю сюда)",
                                 callback_data="skip_phone")
        ], [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]]

        await update.callback_query.edit_message_text(
            text=f"Отлично, {name}! 👋\n\n"
            "📞 *Шаг 4/5*: Укажите номер телефона\n\n"
            "Введите номер для SMS о готовности\n"
            "или нажмите «Пропустить» — пришлём уведомление сюда",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown")

        logger.info(
            f"Переход к состоянию ENTER_PHONE (использовано имя из Telegram)")
        return ENTER_PHONE

    except Exception as e:
        logger.error(f"Ошибка при использовании имени из Telegram: {e}")
        return ConversationHandler.END


async def enter_name(update: Update,
                     context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ввод имени"""
    try:
        name = update.message.text.strip()

        if len(name) < 2 or len(name) > 50:
            await update.message.reply_text(
                "❌ Пожалуйста, введите корректное имя (2-50 символов).")
            return ENTER_NAME

        context.user_data['client_name'] = name
        
        # Отслеживаем ввод имени
        track_event(update.effective_user.id, 'order_name_added')

        keyboard = [[
            InlineKeyboardButton("⏭ Пропустить (уведомлю сюда)",
                                 callback_data="skip_phone")
        ], [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]]

        await update.message.reply_text(
            text=f"Приятно познакомиться, {name}! 👋\n\n"
            "📞 *Шаг 4/5*: Укажите номер телефона\n\n"
            "Введите номер для SMS о готовности\n"
            "или нажмите «Пропустить» — пришлём уведомление сюда",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown")

        logger.info(f"Переход к состоянию ENTER_PHONE (введено имя: {name})")
        return ENTER_PHONE

    except Exception as e:
        logger.error(f"Ошибка при вводе имени: {e}")
        await update.message.reply_text(
            "❌ Не удалось обработать имя. Пожалуйста, попробуйте еще раз.")
        return ENTER_NAME


async def skip_phone_handler(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропуск телефона (хендлер для ConversationHandler)"""
    return await skip_phone(update, context)


async def skip_phone(update: Update,
                     context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропуск телефона"""
    try:
        if update.callback_query:
            await update.callback_query.answer()
        context.user_data['client_phone'] = "Telegram"
        
        # Отслеживаем пропуск телефона (отдельный тип события)
        track_event(update.effective_user.id, 'order_phone_skipped')

        logger.info(f"Переход к состоянию CONFIRM_ORDER (пропущен телефон)")
        return await show_confirmation(
            update,
            context,
            is_callback=True if update.callback_query else False)

    except Exception as e:
        logger.error(f"Ошибка при пропуске телефона: {e}")
        return ConversationHandler.END


async def enter_phone(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ввод телефона"""
    try:
        phone = update.message.text.strip()

        # Извлекаем только цифры
        digits = ''.join(filter(str.isdigit, phone))

        if len(digits) < 10 or len(digits) > 15:
            keyboard = [[
                InlineKeyboardButton("⏭ Пропустить (уведомлю сюда)",
                                     callback_data="skip_phone")
            ],
                        [
                            InlineKeyboardButton("❌ Отменить",
                                                 callback_data="cancel_order")
                        ]]
            await update.message.reply_text(
                "❌ Неверный формат номера.\n"
                "Введите номер (например: +7 999 123 45 67)\n"
                "или нажмите «Пропустить»",
                reply_markup=InlineKeyboardMarkup(keyboard))
            return ENTER_PHONE

        # Форматируем номер
        if digits.startswith('7') or digits.startswith('8'):
            formatted_phone = f"+7 {digits[1:4]} {digits[4:7]} {digits[7:9]} {digits[9:]}"
        else:
            formatted_phone = phone

        context.user_data['client_phone'] = formatted_phone
        
        # Отслеживаем ввод телефона
        track_event(update.effective_user.id, 'order_phone_added')

        logger.info(
            f"Переход к состоянию CONFIRM_ORDER (введен телефон: {formatted_phone})"
        )
        return await show_confirmation(update, context, is_callback=False)

    except Exception as e:
        logger.error(f"Ошибка при вводе телефона: {e}")
        await update.message.reply_text(
            "❌ Не удалось обработать номер телефона. Пожалуйста, попробуйте еще раз."
        )
        return ENTER_PHONE


async def show_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            is_callback: bool) -> int:
    """Показать подтверждение заказа"""
    try:
        service_name = context.user_data.get('service_name', 'Услуга')
        problem_description = context.user_data.get('problem_description')
        client_name = context.user_data.get('client_name', 'Клиент')
        phone = context.user_data.get('client_phone', 'Telegram')
        has_photo = "✅ Фото прикреплено" if context.user_data.get(
            'photo_file_id') else "❌ Без фото"

        phone_display = (
            "📲 Через бота"
            if phone in {"Telegram", "TG"}
            else f"📞 {phone}"
        )

        keyboard = [[
            InlineKeyboardButton("✅ Подтвердить заказ",
                                 callback_data="confirm_order")
        ], [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]]

        text = (f"📋 *Проверьте данные заказа:*\n\n"
                f"🔹 Услуга: {service_name}\n")

        if problem_description:
            text += f"🔹 Проблема: {problem_description}\n"

        text += (f"🔹 Имя: {client_name}\n"
                 f"🔹 Связь: {phone_display}\n"
                 f"🔹 {has_photo}\n\n"
                 f"Всё верно?")

        if is_callback:
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown")
        else:
            await update.message.reply_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown")

        logger.info(f"Показано подтверждение заказа для {client_name}")
        return CONFIRM_ORDER

    except Exception as e:
        logger.error(f"Ошибка при показе подтверждения заказа: {e}")
        return ConversationHandler.END


async def confirm_order(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> int:
    """Подтверждение заказа"""
    try:
        await update.callback_query.answer()

        user = update.effective_user
        user_id = user.id

        # Добавляем/обновляем пользователя
        add_user(user_id=user_id,
                 username=user.username,
                 first_name=user.first_name,
                 last_name=user.last_name,
                 phone=context.user_data.get('client_phone'))

        # Создаем заказ
        problem_desc = context.user_data.get('problem_description')
        full_description = context.user_data.get('service_name', 'Услуга')
        if problem_desc:
            full_description = f"{full_description}: {problem_desc}"

        order_id = create_order(
            user_id=user_id,
            service_type=context.user_data.get('service', 'unknown'),
            description=full_description,
            photo_file_id=context.user_data.get('photo_file_id'),
            client_name=context.user_data.get('client_name'),
            client_phone=context.user_data.get('client_phone'))

        if not order_id:
            raise ValueError("Не удалось создать заказ")
        
        # Отслеживаем завершение заказа
        track_event(user_id, 'order_completed', str(order_id))

        # Формируем сообщение подтверждения
        if is_workday():
            today_hours = get_today_hours()
            confirmation_phrase = random.choice(
                CONFIRMATION_PHRASES_WORKDAY).format(hours=today_hours)
        else:
            confirmation_phrase = random.choice(CONFIRMATION_PHRASES_WEEKEND)

        formatted_order_id = format_order_id(order_id)

        # Отправляем подтверждение клиенту (ОДНО СООБЩЕНИЕ)
        await update.callback_query.edit_message_text(
            text=f"✅ *Заказ принят!*\n\n"
            f"📋 *Номер вашего заказа: {formatted_order_id}*\n\n"
            f"{confirmation_phrase}\n\n"
            f"📍 {WORKSHOP_ADDRESS}\n"
            f"📞 {WORKSHOP_PHONE}",
            parse_mode="Markdown")

        # Уведомляем администраторов
        await notify_admins(context, order_id, context.user_data, user_id)

        # Очищаем данные
        context.user_data.clear()

        logger.info(
            f"Заказ {order_id} успешно создан для пользователя {user_id}")
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при подтверждении заказа: {e}")
        await update.callback_query.edit_message_text(
            "❌ Произошла ошибка при создании заказа. Пожалуйста, попробуйте позже или свяжитесь с нами напрямую:\n\n"
            f"📞 {WORKSHOP_PHONE}")
        return ConversationHandler.END


async def cancel_order(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена заказа"""
    try:
        await update.callback_query.answer()
        
        # Отслеживаем отмену заказа
        track_event(update.effective_user.id, 'order_abandoned')
        
        context.user_data.clear()

        await update.callback_query.edit_message_text(
            text=
            "❌ Заказ отменён.\n\nВы можете оформить новый заказ в любое время.",
            reply_markup=get_main_menu())

        logger.info(f"Заказ отменен пользователем {update.effective_user.id}")
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при отмене заказа: {e}")
        return ConversationHandler.END


def get_admin_order_keyboard(order_id: int,
                             user_id: int) -> InlineKeyboardMarkup:
    """Создать клавиатуру управления заказом для админа"""
    # URL веб-админки
    web_admin_url = os.getenv('REPLIT_DEV_DOMAIN', '')
    if web_admin_url:
        web_admin_url = f"https://{web_admin_url}/admin/orders"
    else:
        web_admin_url = os.getenv('WEB_ADMIN_URL',
                                  'https://your-domain.com/admin')

    keyboard = [[
        InlineKeyboardButton("✅ В работу",
                             callback_data=f"status_in_progress_{order_id}"),
        InlineKeyboardButton("📦 Готов",
                             callback_data=f"status_completed_{order_id}")
    ],
                [
                    InlineKeyboardButton(
                        "📤 Выдан", callback_data=f"status_issued_{order_id}"),
                    InlineKeyboardButton(
                        "❌ Отменить",
                        callback_data=f"status_cancelled_{order_id}")
                ],
                [
                    InlineKeyboardButton("🌐 Веб-админка", url=web_admin_url),
                    InlineKeyboardButton("✉️ Написать",
                                         callback_data=f"contact_client_{order_id}")
                ]]
    return InlineKeyboardMarkup(keyboard)


async def notify_admins(context: ContextTypes.DEFAULT_TYPE,
                        order_id: int,
                        order_data: Dict[str, Any],
                        user_id: int = None):
    """Уведомить админов о новом заказе"""
    try:
        admins = get_admins() or []
        admin_ids = [admin.user_id for admin in admins if admin.user_id]

        # Добавляем основного администратора из переменных окружения
        env_admin_id = os.getenv('ADMIN_ID')
        if env_admin_id:
            try:
                admin_ids.append(int(env_admin_id))
            except ValueError:
                logger.warning(f"Неверный формат ADMIN_ID: {env_admin_id}")

        # Удаляем дубликаты
        admin_ids = list(set(admin_ids))

        if not admin_ids:
            logger.warning("Нет администраторов для уведомления")
            return

        # Формируем сообщение
        now = get_moscow_time()
        date_str = now.strftime("%d.%m.%Y %H:%M")
        formatted_order_id = format_order_id(order_id, now)

        service_key = order_data.get('service', 'unknown')
        service_name = SERVICE_NAMES.get(
            service_key, order_data.get('service_name', "❓ Другая услуга"))

        description = order_data.get('problem_description', '')
        description_text = f"◆ Описание: {description}\n" if description else ""

        message = (
            f"📋 *Новая заявка {formatted_order_id}*\n\n"
            f"◆ Услуга: {service_name}\n"
            f"◆ Клиент: {order_data.get('client_name', 'Не указано')}\n"
            f"◆ Телефон: {'Через бота' if order_data.get('client_phone') in {'Telegram', 'TG'} else order_data.get('client_phone', 'Не указан')}\n"
            f"{description_text}"
            f"◆ Дата: {date_str}\n"
            f"◆ Фото: {'✅ Есть' if order_data.get('photo_file_id') else '❌ Нет'}\n\n"
            f"_Заказ появится в работе после приёма вещи от клиента._\n"
            f"_Управление заказами: Админ → Все заказы_")

        # Отправляем уведомления всем администраторам (без кнопок)
        for admin_id in admin_ids:
            try:
                if order_data.get('photo_file_id'):
                    await context.bot.send_photo(
                        chat_id=admin_id,
                        photo=order_data['photo_file_id'],
                        caption=message,
                        parse_mode="Markdown")
                else:
                    await context.bot.send_message(chat_id=admin_id,
                                                   text=message,
                                                   parse_mode="Markdown")
                logger.info(
                    f"Уведомление отправлено администратору {admin_id}")
            except Exception as e:
                logger.error(
                    f"Не удалось отправить уведомление администратору {admin_id}: {e}"
                )

    except Exception as e:
        logger.error(f"Ошибка при уведомлении администраторов: {e}")


async def handle_order_status_change(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE):
    """Изменение статуса заказа админом"""
    try:
        query = update.callback_query
        await query.answer()

        data = query.data
        admin_user = update.effective_user
        admin_name = admin_user.username or admin_user.first_name or str(
            admin_user.id)

        # Извлекаем ID заказа и новый статус
        order_id = None
        status_text = ""
        new_status = ""
        status_map = {
            "in_progress": ("🔄 В работе", "status_in_progress_"),
            "completed": ("✅ Готов", "status_completed_"),
            "issued": ("📤 Выдан", "status_issued_"),
            "cancelled": ("❌ Отменён", "status_cancelled_")
        }

        for status, (text, prefix) in status_map.items():
            if data.startswith(prefix):
                order_id = int(data.replace(prefix, ""))
                status_text = text
                new_status = status
                break

        if not order_id:
            return

        # Обновляем статус в базе данных
        update_order_status(order_id, new_status)

        # Получаем информацию о заказе
        order = get_order(order_id)
        if not order:
            logger.error(f"Заказ {order_id} не найден")
            await query.edit_message_text(
                text=f"❌ Заказ {order_id} не найден в базе данных",
                parse_mode="Markdown")
            return

        # Уведомляем клиента об изменении статуса
        if new_status not in ("cancelled", "issued"):
            try:
                formatted_id = format_order_id(order_id, order.created_at)
                client_name = order.client_name or "Дорогой клиент"
                client_messages = {
                    "in_progress":
                    (f"Швейный HUB\n"
                     f"🔄 Статус заказа обновлён\n\n"
                     f"{client_name}, отличные новости! 🎉\n"
                     f"Ваш заказ {formatted_id} уже на столе у мастера и активно преображается! ✨\n\n"
                     f"🧵 Иголочка взяла ваш заказ на карандаш\n"
                     f"Я лично слежу за процессом и держу вас в курсе!\n\n"
                     f"⏳ Что дальше?\n"
                     f"Как только всё будет идеально — вам тут же придёт уведомление здесь.\n\n"
                     f"🔍 Хотите заглянуть «за кулисы»?\n"
                     f"Используйте меню бота ↓ или просто напишите «Статус» в любой момент.\n\n"
                     f"Иголочка на связи! 💫"),
                    "completed":
                    (f"Швейный HUB\n"
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
                     f"📍 Адрес:\n"
                     f"{WORKSHOP_ADDRESS}\n\n"
                     f"📞 Есть вопросы?\n"
                     f"Пишите в этот чат или звоните:\n"
                     f"{WORKSHOP_PHONE}\n\n"
                     f"Жду вас!\n"
                     f"Ваша Иголочка 🪡")
                }

                message = client_messages.get(
                    new_status,
                    f"{client_name}, статус заказа {formatted_id} изменён: {status_text} 🧵"
                )

                await context.bot.send_message(chat_id=order.user_id,
                                               text=message)
                logger.info(
                    f"Клиент {order.user_id} уведомлен об изменении статуса заказа {order_id}"
                )
            except Exception as e:
                logger.error(
                    f"Не удалось уведомить клиента об изменении статуса: {e}")

        # Определяем, куда вернуться администратору
        next_list = {
            "in_progress": "admin_orders_in_progress",
            "completed": "admin_orders_completed",
            "issued": "admin_orders_issued",
            "cancelled": "admin_back_menu"
        }.get(new_status, "admin_back_menu")

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ К списку заказов",
                                 callback_data=next_list)
        ]])

        formatted_id = format_order_id(order_id, order.created_at)
        new_text = f"✅ Заказ {formatted_id} обновлён\n\n{status_text}\n\n👤 Обработал: {admin_name}"

        # Обновляем сообщение у администратора
        if query.message.photo:
            await query.edit_message_caption(caption=new_text,
                                             reply_markup=keyboard,
                                             parse_mode="Markdown")
        else:
            await query.edit_message_text(text=new_text,
                                          reply_markup=keyboard,
                                          parse_mode="Markdown")

        logger.info(
            f"Статус заказа {order_id} изменен на {new_status} администратором {admin_user.id}"
        )

    except Exception as e:
        logger.error(f"Ошибка при изменении статуса заказа: {e}")
        try:
            await query.edit_message_text(
                text="❌ Произошла ошибка при изменении статуса заказа",
                parse_mode="Markdown")
        except:
            pass


def get_order_conversation_handler():
    """Создать и вернуть ConversationHandler для заказов"""
    from telegram.ext import MessageHandler, filters, CallbackQueryHandler

    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(order_start, pattern="^create_order$"),
            MessageHandler(filters.Regex(r'^(/order|Оформить заказ)$'),
                           order_start)
        ],
        states={
            SELECT_SERVICE: [
                CallbackQueryHandler(select_service,
                                     pattern="^(service_|back_menu)")
            ],
            SEND_PHOTO: [
                MessageHandler(filters.PHOTO, receive_photo),
                CallbackQueryHandler(skip_photo, pattern="^skip_photo$"),
                CallbackQueryHandler(cancel_order, pattern="^cancel_order$")
            ],
            ENTER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name),
                CallbackQueryHandler(use_tg_name, pattern="^use_tg_name$"),
                CallbackQueryHandler(cancel_order, pattern="^cancel_order$")
            ],
            ENTER_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_phone),
                CallbackQueryHandler(skip_phone, pattern="^skip_phone$"),
                CallbackQueryHandler(cancel_order, pattern="^cancel_order$")
            ],
            CONFIRM_ORDER: [
                CallbackQueryHandler(confirm_order, pattern="^confirm_order$"),
                CallbackQueryHandler(cancel_order, pattern="^cancel_order$")
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_order, pattern="^cancel_order$"),
            MessageHandler(filters.Regex(r'^(/cancel|Отмена)$'), cancel_order)
        ],
        allow_reentry=True,
        per_message=False)
