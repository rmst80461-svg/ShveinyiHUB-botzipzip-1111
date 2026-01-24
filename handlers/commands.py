import os
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from keyboards import get_main_menu, get_admin_main_menu, remove_keyboard, get_faq_menu, get_back_button
from utils.database import add_user, check_today_first_visit, get_user_orders, track_event
from handlers.admin_panel.handlers import set_admin_commands
from handlers.admin import is_user_admin

# Настройка логирования
logger = logging.getLogger(__name__)

# Константы
WORKSHOP_ADDRESS = "г. Москва, (МЦД/м. Ховрино) ул. Маршала Федоренко д.12, ТЦ \"Бусиново\", 1 этаж"
WORKSHOP_PHONE = "+7 (968) 396-91-52"
HOURS = "Пн-Чт: 10:00-19:50, Пт: 10:00-19:00, Сб: 10:00-17:00, Вс: выходной"

# Путь к логотипу - исправленный путь
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGO_PATH = os.path.join(BASE_DIR, "assets", "logo.jpg")


def format_order_id(order_id: int, created_at: datetime) -> str:
    """Форматирование ID заказа в читаемый вид"""
    try:
        date_str = created_at.strftime("%d%m%y")
        return f"#{date_str}-{order_id:04d}"
    except (AttributeError, ValueError):
        return f"#{order_id:06d}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /start с умным приветствием и заставкой"""
    if not update.message:
        return

    try:
        user = update.effective_user
        if not user:
            return
            
        name = user.first_name or "друг"

        # Добавляем пользователя в базу
        try:
            add_user(user.id, user.username or "", user.first_name or "", user.last_name or "")
        except Exception as e:
            logger.error(f"Error adding user {user.id} to DB: {e}")
        
        # Отслеживаем запуск бота
        track_event(user.id, 'bot_started')
            
        today_first_visit = check_today_first_visit(user.id)

        # Проверяем администратора
        user_is_admin = is_user_admin(user.id)

        if user_is_admin:
            caption = (
                f"🛠 *Панель администратора*\n\n"
                f"Добро пожаловать, {name}!\n"
                f"Используйте кнопки меню для управления:"
            )

            # Обновляем команды в боковом меню
            try:
                await set_admin_commands(context.bot, user.id)
            except Exception as e:
                logger.error(f"Error setting admin commands: {e}")

            await update.message.reply_text(
                caption,
                reply_markup=get_admin_main_menu(),
                parse_mode="Markdown"
            )
            return

        # Формируем приветствие в зависимости от времени суток
        current_hour = datetime.now().hour
        greeting = "Доброй ночи" if 0 <= current_hour < 6 else \
                  "Доброе утро" if 6 <= current_hour < 12 else \
                  "Добрый день" if 12 <= current_hour < 18 else "Добрый вечер"

        if today_first_visit:
            caption = (
                f"✨ _*весело подпрыгивая*_ ✨\n\n"
                f"{greeting}, {name}! Я — *Иголочка*, помощница «Швейного HUBа»! 🪡\n\n"
                f"Готова пронзить любую вашу швейную проблему своей экспертизой!\n"
                f"Расскажите — сострочим решение вместе, или воспользуйтесь нашим меню 👇"
            )
        else:
            caption = (
                f"{greeting}, {name}! 👀\n\n"
                f"Иголочка рада вас видеть снова!\n"
                f"Расскажите что случилось, или загляните в меню 👇"
            )

        # Анимация загрузки
        temp_msg = await update.message.reply_text("🪡", reply_markup=remove_keyboard())
        await temp_msg.delete()

        # Отправка фото с логотипом или текстом
        if os.path.exists(LOGO_PATH):
            try:
                with open(LOGO_PATH, 'rb') as photo:
                    await update.message.reply_photo(
                        photo=photo,
                        caption=caption,
                        parse_mode="Markdown"
                    )
            except Exception as e:
                logger.error(f"Не удалось отправить логотип: {e}")
                await update.message.reply_text(caption, parse_mode="Markdown")
        else:
            logger.warning(f"Файл логотипа не найден: {LOGO_PATH}")
            await update.message.reply_text(caption, parse_mode="Markdown")

        # Показываем основное меню для обычных пользователей
        await update.message.reply_text(
            "Выберите действие:",
            reply_markup=get_main_menu()
        )

    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")
        await update.message.reply_text(
            "😔 Произошла ошибка при запуске бота. Пожалуйста, попробуйте позже."
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /help"""
    try:
        help_text = (
            "📖 *Справка по боту*\n\n"
            "Используйте кнопку *Меню* слева от поля ввода для навигации.\n\n"
            "📌 *Доступные команды:*\n"
            "/start — главный экран\n"
            "/order — оформить заказ\n"
            "/services — услуги и цены\n"
            "/faq — часто задаваемые вопросы\n"
            "/status — проверить статус заказа\n"
            "/contact — контакты\n"
            "/help — эта справка\n\n"
            "📌 *Основные кнопки:*\n"
            "• Услуги и цены — просмотр всех услуг\n"
            "• Оформить заказ — начать оформление заказа\n"
            "• Мои заказы — просмотр ваших заказов\n"
            "• Задать вопрос — связь с поддержкой\n\n"
            f"📞 *Телефон:* {WORKSHOP_PHONE}\n"
            f"📍 *Адрес:* {WORKSHOP_ADDRESS}\n"
            f"⏰ *Часы работы:* {HOURS}"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка в команде /help: {e}")
        await update.message.reply_text("❌ Не удалось показать справку.")


async def faq_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /faq"""
    try:
        await update.message.reply_text(
            "❓ *Часто задаваемые вопросы*\n\n"
            "Выберите интересующий вопрос:",
            reply_markup=get_faq_menu(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /faq: {e}")
        await update.message.reply_text("❌ Не удалось загрузить FAQ.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /status - проверка статуса заказов"""
    try:
        user_id = update.effective_user.id
        orders = get_user_orders(user_id)

        if not orders:
            text = (
                "🔍 *У вас пока нет заказов*\n\n"
                "Чтобы оформить заказ, нажмите кнопку \"Оформить заказ\" "
                "или воспользуйтесь командой /order.\n\n"
                f"📞 Или позвоните нам: {WORKSHOP_PHONE}"
            )
        else:
            text = "🔍 *Ваши заказы:*\n\n"
            status_map = {
                'new': '🆕 Новый',
                'in_progress': '🔄 В работе',
                'completed': '✅ Готов',
                'issued': '📤 Выдан',
                'cancelled': '❌ Отменён'
            }

            for order in orders[:5]:  # Показываем последние 5 заказов
                status = status_map.get(str(order.status), str(order.status))
                desc = str(order.description)[:50] + "..." if len(str(order.description)) > 50 else str(order.description)
                formatted_id = format_order_id(int(order.id), order.created_at)
                text += f"*{formatted_id}* - {status}\n"
                text += f"📝 {desc}\n"
                text += f"📅 {order.created_at.strftime('%d.%m.%Y')}\n\n"

            if len(orders) > 5:
                text += f"... и еще {len(orders) - 5} заказов\n\n"

            text += "ℹ️ Для получения детальной информации о конкретном заказе свяжитесь с нами."

        await update.message.reply_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=get_back_button()
        )

    except Exception as e:
        logger.error(f"Ошибка в команде /status: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при получении статуса заказов. Попробуйте позже."
        )


async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /contact - контакты мастерской"""
    try:
        contact_text = (
            "📞 *Контакты Швейного HUBа*\n\n"
            f"*Телефон:* {WORKSHOP_PHONE}\n\n"
            f"*Адрес мастерской:*\n{WORKSHOP_ADDRESS}\n\n"
            f"*Часы работы:*\n{HOURS}\n\n"
            "*Как добраться:*\n"
            "🚇 МЦД/метро Ховрино — 10 мин пешком\n"
            "🚘 Бесплатная парковка у ТЦ\n\n"
            "📍 *Смотреть на карте:*\n"
            "https://yandex.ru/maps/org/shveyny_hub/1233246900/?ll=37.488843%2C55.881723&z=16.44"
        )

        # Попробуем отправить локацию
        try:
            # Координаты для ТЦ "Бусиново" (примерные)
            latitude = 55.870
            longitude = 37.492
            await update.message.reply_location(
                latitude=latitude,
                longitude=longitude
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить локацию: {e}")

        await update.message.reply_text(
            contact_text,
            parse_mode="Markdown",
            reply_markup=get_back_button()
        )

    except Exception as e:
        logger.error(f"Ошибка в команде /contact: {e}")
        await update.message.reply_text(
            f"📞 *Телефон:* {WORKSHOP_PHONE}\n"
            f"📍 *Адрес:* {WORKSHOP_ADDRESS}"
        )


async def services_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /services - услуги и цены"""
    try:
        from keyboards import get_services_menu

        await update.message.reply_text(
            "🪡 *Услуги и цены Швейного HUBа*\n\n"
            "Выберите категорию услуги для просмотра цен и подробностей:",
            reply_markup=get_services_menu(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка в команде /services: {e}")
        await update.message.reply_text(
            "❌ Не удалось загрузить список услуг. Попробуйте позже."
        )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /cancel - отмена текущего действия"""
    try:
        # Проверяем, есть ли активный ConversationHandler
        if context.user_data:
            context.user_data.clear()
            await update.message.reply_text(
                "✅ Текущее действие отменено.",
                reply_markup=get_main_menu()
            )
        else:
            await update.message.reply_text(
                "ℹ️ Нет активных действий для отмены.",
                reply_markup=get_main_menu()
            )
    except Exception as e:
        logger.error(f"Ошибка в команде /cancel: {e}")