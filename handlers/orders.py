import os
import logging
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from keyboards import get_services_menu, get_main_menu, get_admin_main_menu
from utils.database import create_order, get_admins, add_user, get_order, update_order_status, track_event
try:
    from utils.knowledge_loader import knowledge
except ImportError:
    knowledge = None
from handlers.admin import is_user_admin

logger = logging.getLogger(__name__)

# Константы для состояний ConversationHandler
SELECT_SERVICE, SEND_PHOTO, ENTER_DESCRIPTION, ENTER_NAME, ENTER_PHONE, CONFIRM_ORDER = range(6)

# Контактная информация
WORKSHOP_PHONE = "+7 (968) 396-91-52"
WORKSHOP_ADDRESS = "г. Москва, (МЦД/м. Ховрино) ул. Маршала Федоренко д.12, ТЦ \"Бусиново\", 1 этаж"

# Часы работы (0=Пн, 6=Вс)
WORK_HOURS = {
    0: "10:00-19:50",
    1: "10:00-19:50",
    2: "10:00-19:50",
    3: "10:00-19:50",
    4: "10:00-19:00",
    5: "10:00-17:00",
    6: None
}

MOSCOW_TZ = timezone(timedelta(hours=3))

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
    "dress": "👗 Юбки/платья",
    "other": "❓ Другое"
}

def get_moscow_time(dt: Optional[datetime] = None) -> datetime:
    if dt is None:
        return datetime.now(MOSCOW_TZ)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).astimezone(MOSCOW_TZ)
    return dt.astimezone(MOSCOW_TZ)

def get_today_hours() -> Optional[str]:
    weekday = get_moscow_time().weekday()
    hours = WORK_HOURS.get(weekday)
    if hours:
        return f"с {hours.replace('-', ' до ')}"
    return None

def is_workday() -> bool:
    return WORK_HOURS.get(get_moscow_time().weekday()) is not None

def format_order_id(order_id: int, created_at: Optional[datetime] = None) -> str:
    date_obj = get_moscow_time(created_at)
    day = date_obj.strftime('%d')
    month = date_obj.strftime('%m')
    year = date_obj.strftime('%y')
    return f"{day}-{month}.{year}-#{order_id}"

def get_user_display_name(user) -> str:
    if user.first_name:
        return user.first_name
    if user.username:
        return f"@{user.username}"
    return f"Пользователь {user.id}"

async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user = update.effective_user
        user_id = user.id

        if is_user_admin(user_id):
            text = ("⚠️ *Администраторы не создают заказы через бота*\n\n"
                    "Используйте веб-панель для управления заказами.")
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(text=text, reply_markup=get_admin_main_menu(), parse_mode="Markdown")
            else:
                await update.message.reply_text(text=text, reply_markup=get_admin_main_menu(), parse_mode="Markdown")
            return ConversationHandler.END

        context.user_data.clear()
        
        try:
            track_event(user_id, 'order_started')
        except Exception:
            pass

        text = "➕ *Оформление заказа*\n\nВыберите категорию услуги:"
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text=text, reply_markup=get_services_menu(), parse_mode="Markdown")
        else:
            await update.message.reply_text(text=text, reply_markup=get_services_menu(), parse_mode="Markdown")

        return SELECT_SERVICE

    except Exception as e:
        logger.error(f"Ошибка в начале оформления заказа: {e}")
        if update.callback_query:
            await update.callback_query.edit_message_text("❌ Произошла ошибка. Пожалуйста, попробуйте позже.")
        else:
            await update.message.reply_text("❌ Произошла ошибка. Пожалуйста, попробуйте позже.")
        return ConversationHandler.END


async def select_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()

        if query.data == "back_menu":
            await query.edit_message_text(text="🏠 Возврат в главное меню", reply_markup=get_main_menu())
            return ConversationHandler.END

        service = query.data.replace("service_", "")
        context.user_data['service'] = service
        context.user_data['service_name'] = SERVICE_NAMES.get(service, service)
        
        try:
            track_event(update.effective_user.id, 'order_category_selected', service)
        except Exception: pass

        if service == "other":
            keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]]
            await query.edit_message_text(
                text="❓ *Вы выбрали: Другое*\n\n📝 *Шаг 1/5*: Опишите, что именно вам нужно сделать?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            context.user_data['other_description_mode'] = True
            return ENTER_DESCRIPTION

        service_info = ""
        try:
            if knowledge and hasattr(knowledge, 'get_category_prices'):
                prices = knowledge.get_category_prices(service)
                if prices:
                    service_info = f"\n{prices}\n"
        except Exception:
            pass

        keyboard = [
            [InlineKeyboardButton("⏭ Пропустить фото", callback_data="skip_photo")], 
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
        ]

        await query.edit_message_text(
            text=f"✅ Вы выбрали: *{SERVICE_NAMES.get(service, service)}*\n{service_info}\n📸 *Шаг 1/5*: Отправьте фото вашей вещи\n(или нажмите 'Пропустить')",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return SEND_PHOTO

    except Exception as e:
        logger.error(f"Ошибка при выборе услуги: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка. Начните заново с команды /order")
        return ConversationHandler.END


async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        if update.message and update.message.photo:
            photo = update.message.photo[-1]
            context.user_data['photo_file_id'] = photo.file_id
            
            try: track_event(update.effective_user.id, 'order_photo_added')
            except Exception: pass

            if context.user_data.get('service') == 'other' and context.user_data.get('problem_description'):
                user_name = get_user_display_name(update.effective_user)
                context.user_data['suggested_name'] = user_name
                keyboard = [
                    [InlineKeyboardButton(f"✅ Да, я {user_name}", callback_data="use_tg_name")], 
                    [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
                ]
                await update.message.reply_text(
                    text=f"📸 Фото получено!\n\n👤 *Шаг 3/5*: Как к вам обращаться?\n\nОбращаться к вам *{user_name}*?\nИли напишите другое имя:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                return ENTER_NAME

            keyboard = [
                [InlineKeyboardButton("⏭ Пропустить описание", callback_data="skip_description")],
                [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
            ]
            await update.message.reply_text(
                text="📸 Фото получено!\n\n📝 *Шаг 2/5*: Кратко опишите проблему\n(например: 'подшить брюки' или 'замена молнии'):",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return ENTER_DESCRIPTION

        await update.message.reply_text("Пожалуйста, отправьте фото или нажмите 'Пропустить'.")
        return SEND_PHOTO

    except Exception as e:
        logger.error(f"Ошибка при получении фото: {e}")
        return SEND_PHOTO


async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        await update.callback_query.answer()
        context.user_data['photo_file_id'] = None
        
        try: track_event(update.effective_user.id, 'order_photo_skipped')
        except Exception: pass

        if context.user_data.get('service') == 'other' and context.user_data.get('problem_description'):
            user_name = get_user_display_name(update.effective_user)
            context.user_data['suggested_name'] = user_name
            keyboard = [
                [InlineKeyboardButton(f"✅ Да, я {user_name}", callback_data="use_tg_name")], 
                [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
            ]
            await update.callback_query.edit_message_text(
                text=f"👤 *Шаг 3/5*: Как к вам обращаться?\n\nОбращаться к вам *{user_name}*?\nИли напишите другое имя:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return ENTER_NAME

        keyboard = [
            [InlineKeyboardButton("⏭ Пропустить описание", callback_data="skip_description")], 
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
        ]
        await update.callback_query.edit_message_text(
            text="📝 *Шаг 2/5*: Кратко опишите проблему\n(например: 'подшить брюки' или 'замена молнии'):",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return ENTER_DESCRIPTION

    except Exception as e:
        logger.error(f"Ошибка при пропуске фото: {e}")
        return ConversationHandler.END


async def enter_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        description = update.message.text.strip()
        context.user_data['problem_description'] = description
        
        try: track_event(update.effective_user.id, 'order_description_added')
        except Exception: pass

        if context.user_data.get('other_description_mode'):
            context.user_data['other_description_mode'] = False
            keyboard = [
                [InlineKeyboardButton("⏭ Пропустить фото", callback_data="skip_photo")], 
                [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
            ]
            await update.message.reply_text(
                text=f"✅ Описание сохранено!\n\n📸 *Шаг 2/5*: Отправьте фото вашей вещи\n(или нажмите 'Пропустить')",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return SEND_PHOTO

        user_name = get_user_display_name(update.effective_user)
        context.user_data['suggested_name'] = user_name
        keyboard = [
            [InlineKeyboardButton(f"✅ Да, я {user_name}", callback_data="use_tg_name")], 
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
        ]
        await update.message.reply_text(
            text=f"👤 *Шаг 3/5*: Как к вам обращаться?\n\nОбращаться к вам *{user_name}*?\nИли напишите другое имя:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return ENTER_NAME

    except Exception as e:
        logger.error(f"Ошибка при вводе описания: {e}")
        return ENTER_DESCRIPTION


async def skip_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        await update.callback_query.answer()
        context.user_data['problem_description'] = None

        user_name = get_user_display_name(update.effective_user)
        context.user_data['suggested_name'] = user_name

        keyboard = [
            [InlineKeyboardButton(f"✅ Да, я {user_name}", callback_data="use_tg_name")], 
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
        ]
        await update.callback_query.edit_message_text(
            text=f"👤 *Шаг 3/5*: Как к вам обращаться?\n\nОбращаться к вам *{user_name}*?\nИли напишите другое имя:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return ENTER_NAME

    except Exception as e:
        logger.error(f"Ошибка при пропуске описания: {e}")
        return ConversationHandler.END


async def use_tg_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        await update.callback_query.answer()
        name = context.user_data.get('suggested_name', get_user_display_name(update.effective_user))
        context.user_data['client_name'] = name
        
        keyboard = [
            [InlineKeyboardButton("⏭ Пропустить (уведомлю сюда)", callback_data="skip_phone")], 
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
        ]
        await update.callback_query.edit_message_text(
            text=f"Отлично, {name}! 👋\n\n📞 *Шаг 4/5*: Укажите номер телефона\n\nВведите номер для SMS\nили нажмите «Пропустить» — пришлём уведомление сюда",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return ENTER_PHONE

    except Exception as e:
        logger.error(f"Ошибка при использовании имени из Telegram: {e}")
        return ConversationHandler.END


async def enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        name = update.message.text.strip()
        if len(name) < 2 or len(name) > 50:
            await update.message.reply_text("❌ Пожалуйста, введите корректное имя (2-50 символов).")
            return ENTER_NAME

        context.user_data['client_name'] = name
        keyboard = [
            [InlineKeyboardButton("⏭ Пропустить (уведомлю сюда)", callback_data="skip_phone")], 
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
        ]
        await update.message.reply_text(
            text=f"Приятно познакомиться, {name}! 👋\n\n📞 *Шаг 4/5*: Укажите номер телефона\n\nВведите номер для SMS\nили нажмите «Пропустить»",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return ENTER_PHONE

    except Exception as e:
        logger.error(f"Ошибка при вводе имени: {e}")
        return ENTER_NAME


async def skip_phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await skip_phone(update, context)


async def skip_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        if update.callback_query:
            await update.callback_query.answer()
        context.user_data['client_phone'] = "Telegram"
        return await show_confirmation(update, context, is_callback=True if update.callback_query else False)
    except Exception as e:
        logger.error(f"Ошибка при пропуске телефона: {e}")
        return ConversationHandler.END


async def enter_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        phone = update.message.text.strip()
        digits = ''.join(filter(str.isdigit, phone))

        if len(digits) < 10 or len(digits) > 15:
            keyboard = [
                [InlineKeyboardButton("⏭ Пропустить (уведомлю сюда)", callback_data="skip_phone")],
                [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
            ]
            await update.message.reply_text(
                "❌ Неверный формат номера.\nВведите номер (например: +7 999 123 45 67) или нажмите «Пропустить»",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return ENTER_PHONE

        if digits.startswith('7') or digits.startswith('8'):
            formatted_phone = f"+7 {digits[1:4]} {digits[4:7]} {digits[7:9]} {digits[9:]}"
        else:
            formatted_phone = phone

        context.user_data['client_phone'] = formatted_phone
        return await show_confirmation(update, context, is_callback=False)

    except Exception as e:
        logger.error(f"Ошибка при вводе телефона: {e}")
        return ENTER_PHONE


async def show_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback: bool) -> int:
    try:
        service_name = context.user_data.get('service_name', 'Услуга')
        problem_description = context.user_data.get('problem_description')
        client_name = context.user_data.get('client_name', 'Клиент')
        phone = context.user_data.get('client_phone', 'Telegram')
        has_photo = "✅ Фото прикреплено" if context.user_data.get('photo_file_id') else "❌ Без фото"

        phone_display = "📲 Telegram" if phone == "Telegram" else f"📞 {phone}"
        keyboard = [
            [InlineKeyboardButton("✅ Подтвердить заказ", callback_data="confirm_order")], 
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_order")]
        ]

        text = f"📋 *Проверьте данные заказа:*\n\n🔹 Услуга: {service_name}\n"
        if problem_description:
            text += f"🔹 Проблема: {problem_description}\n"
        text += f"🔹 Имя: {client_name}\n🔹 Связь: {phone_display}\n🔹 {has_photo}\n\nВсё верно?"

        if is_callback:
            await update.callback_query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await update.message.reply_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        return CONFIRM_ORDER
    except Exception as e:
        logger.error(f"Ошибка при показе подтверждения заказа: {e}")
        return ConversationHandler.END


async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        await update.callback_query.answer()
        user = update.effective_user
        user_id = user.id

        add_user(user_id=user_id, username=user.username, first_name=user.first_name, last_name=user.last_name, phone=context.user_data.get('client_phone'))

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
            client_phone=context.user_data.get('client_phone')
        )

        if not order_id:
            raise ValueError("Не удалось создать заказ")

        if is_workday():
            confirmation_phrase = random.choice(CONFIRMATION_PHRASES_WORKDAY).format(hours=get_today_hours())
        else:
            confirmation_phrase = random.choice(CONFIRMATION_PHRASES_WEEKEND)

        formatted_order_id = format_order_id(order_id)

        await update.callback_query.edit_message_text(
            text=f"✅ *Заказ принят!*\n\n📋 *Номер вашего заказа: {formatted_order_id}*\n\n{confirmation_phrase}\n\n📍 {WORKSHOP_ADDRESS}\n📞 {WORKSHOP_PHONE}",
            parse_mode="Markdown"
        )

        await notify_admins(context, order_id, context.user_data, user_id)
        context.user_data.clear()
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при подтверждении заказа: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка. Пожалуйста, свяжитесь с нами напрямую.")
        return ConversationHandler.END


async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        await update.callback_query.answer()
        context.user_data.clear()
        await update.callback_query.edit_message_text(text="❌ Заказ отменён.\n\nВы можете оформить новый заказ в любое время.", reply_markup=get_main_menu())
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка при отмене заказа: {e}")
        return ConversationHandler.END


def get_admin_order_keyboard(order_id: int, user_id: int) -> InlineKeyboardMarkup:
    web_admin_url = os.getenv('WEB_ADMIN_URL', 'https://your-domain.com/admin')
    keyboard = [
        [
            InlineKeyboardButton("✅ В работу", callback_data=f"status_in_progress_{order_id}"),
            InlineKeyboardButton("📦 Готов", callback_data=f"status_completed_{order_id}")
        ],
        [
            InlineKeyboardButton("📤 Выдан", callback_data=f"status_issued_{order_id}"),
            InlineKeyboardButton("❌ Отменить", callback_data=f"status_cancelled_{order_id}")
        ],
        [
            InlineKeyboardButton("🌐 Веб-админка", url=web_admin_url),
            InlineKeyboardButton("✉️ Написать", url=f"tg://user?id={user_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def notify_admins(context: ContextTypes.DEFAULT_TYPE, order_id: int, order_data: Dict[str, Any], user_id: int = None):
    try:
        admins = get_admins() or []
        admin_ids = [admin.user_id for admin in admins if admin.user_id]

        env_admin_id = os.getenv('ADMIN_ID')
        if env_admin_id:
            try:
                admin_ids.append(int(env_admin_id))
            except ValueError:
                pass

        admin_ids = list(set(admin_ids))

        if not admin_ids:
            return

        now = get_moscow_time()
        date_str = now.strftime("%d.%m.%Y %H:%M")
        formatted_order_id = format_order_id(order_id, now)

        service_key = order_data.get('service', 'unknown')
        service_name = SERVICE_NAMES.get(service_key, order_data.get('service_name', service_key))
        description = order_data.get('problem_description', '')
        description_text = f"◆ Описание: {description}\n" if description else ""

        message = (
            f"📋 *Новая заявка {formatted_order_id}*\n\n"
            f"◆ Услуга: {service_name}\n"
            f"◆ Клиент: {order_data.get('client_name', 'Не указано')}\n"
            f"◆ Телефон: {order_data.get('client_phone', 'Не указан')}\n"
            f"{description_text}"
            f"◆ Дата: {date_str}\n"
            f"◆ Фото: {'✅ Есть' if order_data.get('photo_file_id') else '❌ Нет'}\n\n"
            f"_Заказ появится в работе после приёма вещи от клиента._"
        )

        for admin_id in admin_ids:
            try:
                if order_data.get('photo_file_id'):
                    await context.bot.send_photo(chat_id=admin_id, photo=order_data['photo_file_id'], caption=message, parse_mode="Markdown")
                else:
                    await context.bot.send_message(chat_id=admin_id, text=message, parse_mode="Markdown")
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Ошибка при уведомлении администраторов: {e}")


async def handle_order_status_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Данная функция теперь обрабатывается напрямую из handlers.admin_view_order
    pass

def get_order_conversation_handler():
    from telegram.ext import MessageHandler, filters, CallbackQueryHandler
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(order_start, pattern="^create_order$"),
            MessageHandler(filters.Regex(r'^(/order|Оформить заказ)$'), order_start)
        ],
        states={
            SELECT_SERVICE: [CallbackQueryHandler(select_service, pattern="^(service_|back_menu)")],
            SEND_PHOTO: [MessageHandler(filters.PHOTO, receive_photo), CallbackQueryHandler(skip_photo, pattern="^skip_photo$"), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")],
            ENTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name), CallbackQueryHandler(use_tg_name, pattern="^use_tg_name$"), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")],
            ENTER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_phone), CallbackQueryHandler(skip_phone, pattern="^skip_phone$"), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")],
            CONFIRM_ORDER: [CallbackQueryHandler(confirm_order, pattern="^confirm_order$"), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_order, pattern="^cancel_order$"),
            MessageHandler(filters.Regex(r'^(/cancel|Отмена)$'), cancel_order)
        ],
        allow_reentry=True,
        per_message=False
    )
