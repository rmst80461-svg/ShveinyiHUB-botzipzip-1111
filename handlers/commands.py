import os
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from keyboards import (
    get_main_menu, 
    get_admin_main_menu, 
    get_faq_menu, 
    get_back_button
)
from handlers.admin import is_user_admin

logger = logging.getLogger(__name__)

WORKSHOP_ADDRESS = "г. Москва, (МЦД/м. Ховрино) ул. Маршала Федоренко д.12, ТЦ \"Бусиново\", 1 этаж"
WORKSHOP_PHONE = "+7 (968) 396-91-52"
HOURS = "Пн-Чт: 10:00-19:50, Пт: 10:00-19:00, Сб: 10:00-17:00, Вс: выходной"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGO_PATH = os.path.join(BASE_DIR, "assets", "logo.jpg")


def format_order_id(order_id: int, created_at: datetime) -> str:
    try:
        date_str = created_at.strftime("%d%m%y")
        return f"#{date_str}-{order_id:04d}"
    except (AttributeError, ValueError):
        return f"#{order_id:06d}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Главный обработчик команды /start"""
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if not message:
        return

    user = update.effective_user
    if not user:
        return

    name = user.first_name or "друг"
    user_id = user.id

    # Безопасное фоновое сохранение пользователя в БД
    try:
        from utils.database import add_user, track_event
        add_user(user_id, user.username or "", user.first_name or "", user.last_name or "")
        track_event(user_id, 'bot_started')
    except Exception as e:
        logger.warning(f"DB tracking skipped: {e}")

    # 1. Если зашел АДМИНИСТРАТОР -> показываем админ-панель
    if is_user_admin(user_id):
        try:
            from handlers.admin_panel.handlers import set_admin_commands
            await set_admin_commands(context.bot, user_id)
        except Exception:
            pass

        await message.reply_text(
            f"🛠 *Панель администратора*\n\nЗдравствуйте, {name}!\nВыберите раздел:",
            reply_markup=get_admin_main_menu(),
            parse_mode="Markdown"
        )
        return

    # 2. Если зашел КЛИЕНТ -> формируем приветствие и инлайн-клавиатуру
    current_hour = datetime.now().hour
    greeting = "Доброй ночи" if 0 <= current_hour < 6 else \
               "Доброе утро" if 6 <= current_hour < 12 else \
               "Добрый день" if 12 <= current_hour < 18 else "Добрый вечер"

    caption = (
        f"✂️ *Швейный HUB*\n\n"
        f"{greeting}, {name}! Я — *Иголочка*, ваш швейный помощник! 🪡\n"
        f"Выберите нужный пункт меню ниже:"
    )

    photo_sent = False
    if os.path.exists(LOGO_PATH):
        try:
            with open(LOGO_PATH, "rb") as photo:
                await message.reply_photo(photo=photo, caption=caption, parse_mode="Markdown")
                photo_sent = True
        except Exception as e:
            logger.warning(f"Не удалось отправить фото: {e}")

    if not photo_sent:
        try:
            await message.reply_text(caption, parse_mode="Markdown")
        except Exception:
            await message.reply_text(f"Швейный HUB. Добро пожаловать, {name}!")

    await message.reply_text(
        text="👇 *Главное меню мастерской:*",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    help_text = (
        "📖 *Справка по боту*\n\n"
        "📌 *Доступные команды:*\n"
        "/start — главное меню\n"
        "/order — оформить заказ\n"
        "/services — услуги и цены\n"
        "/faq — частые вопросы\n"
        "/status — статус заказа\n"
        "/contact — контакты\n\n"
        f"📞 *Телефон:* {WORKSHOP_PHONE}\n"
        f"📍 *Адрес:* {WORKSHOP_ADDRESS}"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def faq_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "❓ *Часто задаваемые вопросы:*\nВыберите тему:",
            reply_markup=get_faq_menu(),
            parse_mode="Markdown"
        )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user_id = update.effective_user.id
    try:
        from utils.database import get_user_orders
        orders = get_user_orders(user_id)
    except Exception:
        orders = []

    if not orders:
        text = f"🔍 *У вас пока нет заказов.*\n\nОформить заказ можно через команду /order или по телефону: {WORKSHOP_PHONE}"
    else:
        text = "🔍 *Ваши заказы:*\n\n"
        status_map = {
            'new': '🆕 Новый',
            'accepted': '⏳ Принят',
            'in_progress': '🔄 В работе',
            'completed': '✅ Готов',
            'issued': '📤 Выдан',
            'cancelled': '❌ Отменён',
            'spam': '🚫 Спам'
        }
        for o in orders[:5]:
            status = status_map.get(str(o.status), str(o.status))
            desc = str(o.description)[:40] if o.description else "Услуга"
            fid = format_order_id(int(o.id), o.created_at)
            text += f"*{fid}* — {status}\n_{desc}_\n\n"

    await update.message.reply_text(text=text, reply_markup=get_back_button(), parse_mode="Markdown")


async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    text = (
        f"📞 *Контакты мастерской*\n\n"
        f"📍 *Адрес:* {WORKSHOP_ADDRESS}\n"
        f"📱 *Телефон:* {WORKSHOP_PHONE}\n"
        f"⏰ *График:* {HOURS}\n\n"
        f"🗺 [Открыть на Яндекс.Картах](https://yandex.ru/maps/org/shveyny_hub/1233246900/)"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_back_button())


async def services_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        from keyboards import get_prices_menu
        await update.message.reply_text("💰 *Выберите категорию услуг:*", reply_markup=get_prices_menu(), parse_mode="Markdown")
