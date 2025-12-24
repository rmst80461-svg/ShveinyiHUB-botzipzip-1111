#!/usr/bin/env python3
import os
import logging
import asyncio
import time
import threading
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, MenuButtonCommands, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, ConversationHandler, filters
)

BOT_START_TIME = time.time()
LAST_UPDATE_TIME = time.time()
BOT_IS_RUNNING = False


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP handler для health check"""
    
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        global LAST_UPDATE_TIME, BOT_IS_RUNNING
        
        if self.path == '/' or self.path == '/health' or self.path == '/status':
            uptime = int(time.time() - BOT_START_TIME)
            response = {
                "status": "alive" if BOT_IS_RUNNING else "starting",
                "uptime_seconds": uptime,
                "last_update": LAST_UPDATE_TIME,
                "message": "Бот работает 24/7! ⚡"
            }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()


def start_health_server(port=8080):
    """Запуск health check сервера в отдельном потоке"""
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logging.info(f"✅ Health check сервер запущен на порту {port}")

from handlers import commands, messages, admin
from handlers.orders import (
    order_start, select_service, receive_photo, skip_photo,
    enter_name, enter_phone, confirm_order, cancel_order,
    use_tg_name, skip_phone as skip_phone_handler,
    handle_order_status_change,
    SELECT_SERVICE, SEND_PHOTO, ENTER_NAME, ENTER_PHONE, CONFIRM_ORDER
)
from handlers.reviews import get_review_conversation_handler, request_review
from keyboards import get_main_menu, get_prices_menu, get_services_menu, get_faq_menu, get_back_button, remove_keyboard
from utils.database import init_db, get_user_orders, add_user, get_orders_pending_feedback, mark_feedback_requested
from utils.knowledge_loader import knowledge
from utils.anti_spam import anti_spam
from utils.prices import format_prices_text, get_all_categories, import_prices_data

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

WORKSHOP_INFO = {
    "name": "Швейная мастерская",
    "address": "г.Москва ул.Маршала Федоренко д.12, 1 этаж",
    "phone": "+7 (968) 396-91-52",
    "whatsapp": "+7 (968) 396-91-52",
    "working_hours": {
        "пн": "10:00-19:50",
        "вт": "10:00-19:50",
        "ср": "10:00-19:50",
        "чт": "10:00-19:50",
        "пт": "10:00-19:00",
        "сб": "10:00-17:00",
        "вс": "Выходной"
    }
}


async def callback_services(update, context):
    """Кнопка Услуги и цены"""
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        text="💰 Выберите категорию услуг:",
        reply_markup=get_prices_menu()
    )


async def callback_price_category(update, context, category):
    """Показать цены для категории"""
    await update.callback_query.answer()
    prices_text = format_prices_text(category)
    
    if prices_text:
        await update.callback_query.edit_message_text(
            text=prices_text,
            reply_markup=get_prices_menu(),
            parse_mode="Markdown"
        )
    else:
        await update.callback_query.edit_message_text(
            text="Цены не найдены",
            reply_markup=get_prices_menu()
        )


async def callback_price_jacket(update, context):
    await callback_price_category(update, context, "jacket")

async def callback_price_leather(update, context):
    await callback_price_category(update, context, "leather")

async def callback_price_curtains(update, context):
    await callback_price_category(update, context, "curtains")

async def callback_price_coat(update, context):
    await callback_price_category(update, context, "coat")

async def callback_price_fur(update, context):
    await callback_price_category(update, context, "fur")

async def callback_price_outerwear(update, context):
    await callback_price_category(update, context, "outerwear")

async def callback_price_pants(update, context):
    await callback_price_category(update, context, "pants")

async def callback_price_dress(update, context):
    await callback_price_category(update, context, "dress")



async def callback_check_status(update, context):
    """Проверить статус заказа"""
    await update.callback_query.answer()
    user_id = update.effective_user.id
    orders = get_user_orders(user_id)
    
    if not orders:
        text = "🔍 У вас нет заказов.\n\nПозвоните нам: " + WORKSHOP_INFO['phone']
    else:
        text = "🔍 *Ваши заказы:*\n\n"
        status_map = {
            'new': '🆕 Новый',
            'in_progress': '🔄 В работе',
            'completed': '✅ Готов',
            'cancelled': '❌ Отменён'
        }
        for order in orders[:5]:
            status = status_map.get(str(order.status), str(order.status))
            desc = str(order.description) if order.description else 'Услуга'
            text += f"*#{int(order.id)}* - {status}\n{desc}\n\n"
    
    await update.callback_query.edit_message_text(
        text=text,
        reply_markup=get_back_button(),
        parse_mode="Markdown"
    )


async def callback_faq(update, context):
    """Кнопка FAQ"""
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        text="❓ Выберите интересующий вопрос:",
        reply_markup=get_faq_menu()
    )


async def callback_faq_services(update, context):
    """FAQ: Какие услуги"""
    await update.callback_query.answer()
    text = (
        "📋 *Какие услуги мы выполняем:*\n\n"
        "✂️ Подшив и укорачивание\n"
        "🔄 Замена молний и пуговиц\n"
        "📐 Ушивание и расширение по фигуре\n"
        "🧵 Штопка и реставрация\n"
        "🧥 Ремонт верхней одежды\n"
        "🎒 Ремонт кожаных изделий\n"
        "🐾 Ремонт шуб и дублёнок\n"
        "🪟 Пошив штор\n\n"
        "Если у вас особый случай — опишите его!"
    )
    await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")


async def callback_faq_prices(update, context):
    """FAQ: Цены"""
    await update.callback_query.answer()
    text = (
        "💰 *Примерные цены на популярные услуги:*\n\n"
        "👖 Укоротить джинсы — от 500 руб.\n"
        "👖 С родным краем — от 900 руб.\n"
        "👗 Укоротить юбку — от 800 руб.\n"
        "🧥 Замена молнии в куртке — от 2000 руб.\n"
        "🧥 Замена подкладки — от 3500 руб.\n"
        "📐 Подгон по фигуре — от 1500 руб.\n\n"
        "Полный прайс — в разделе «Услуги и цены»!"
    )
    await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")


async def callback_faq_timing(update, context):
    """FAQ: Сроки"""
    await update.callback_query.answer()
    text = (
        "⏰ *Сроки выполнения:*\n\n"
        "⚡ Простой ремонт — 1-2 дня\n"
        "(подшив, замена пуговицы)\n\n"
        "📦 Сложный ремонт — 3-7 дней\n"
        "(замена подкладки, молний)\n\n"
        "🚀 *Срочный ремонт* — за 24 часа\n"
        "Доплата +50% к стоимости\n\n"
        "Точный срок назовём при приёме заказа!"
    )
    await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")


async def callback_faq_location(update, context):
    """FAQ: Адрес и график"""
    await update.callback_query.answer()
    text = (
        f"📍 *Адрес:*\n{WORKSHOP_INFO['address']}\n\n"
        "🚇 Ориентир: м. Бабушкинская\n"
        "Вход с торца здания, 1 этаж\n\n"
        "⏰ *График работы:*\n"
        "Пн-Чт: 10:00-19:50\n"
        "Пт: 10:00-19:00\n"
        "Сб: 10:00-17:00\n"
        "Вс: выходной\n\n"
        f"📞 Телефон: {WORKSHOP_INFO['phone']}"
    )
    await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")


async def callback_faq_payment(update, context):
    """FAQ: Оплата и гарантия"""
    await update.callback_query.answer()
    text = (
        "💳 *Способы оплаты:*\n"
        "• Наличные\n"
        "• Карта\n"
        "• СБП / QR-код\n\n"
        "💵 *Предоплата:*\n"
        "Не требуется для обычного ремонта.\n"
        "50% — для дорогой фурнитуры.\n\n"
        "🛡️ *Гарантия:*\n"
        "30 дней на все виды ремонта!\n"
        "Если что-то разошлось — переделаем бесплатно."
    )
    await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")


async def callback_faq_order(update, context):
    """FAQ: Как оформить заказ"""
    await update.callback_query.answer()
    text = (
        "📝 *Как оформить заказ:*\n\n"
        "1️⃣ Нажмите «Создать заказ» в меню\n"
        "2️⃣ Выберите категорию услуги\n"
        "3️⃣ Прикрепите фото вещи\n"
        "4️⃣ Укажите имя и телефон\n"
        "5️⃣ Подтвердите заказ\n\n"
        "Мы свяжемся с вами для уточнения!\n\n"
        "Или приходите в мастерскую лично — "
        "мастер осмотрит вещь и назовёт точную цену."
    )
    await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")


async def callback_faq_other(update, context):
    """FAQ: Другое — описать проблему"""
    await update.callback_query.answer()
    text = (
        "❓ *У вас другой вопрос?*\n\n"
        "Опишите вашу проблему или вопрос прямо здесь в чате — "
        "я постараюсь помочь!\n\n"
        "Можете прислать фото вещи, и мы подскажем:\n"
        "• Возможен ли ремонт\n"
        "• Примерную стоимость\n"
        "• Сроки выполнения\n\n"
        f"Или позвоните нам: {WORKSHOP_INFO['phone']}"
    )
    await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")


async def callback_contacts(update, context):
    """Кнопка Контакты"""
    await update.callback_query.answer()
    hours_text = "Пн-Чт: 10:00-19:50\nПт: 10:00-19:00\nСб: 10:00-17:00\nВс: выходной"
    await update.callback_query.edit_message_text(
        text="📍 *Наши контакты:*\n\n"
        f"📍 *Адрес:*\n{WORKSHOP_INFO['address']}\n\n"
        f"📞 *Телефон:*\n{WORKSHOP_INFO['phone']}\n\n"
        f"💬 *WhatsApp:*\n{WORKSHOP_INFO['whatsapp']}\n\n"
        f"⏰ *График работы:*\n{hours_text}",
        reply_markup=get_back_button(),
        parse_mode="Markdown"
    )


async def callback_back(update, context):
    """Кнопка Назад"""
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        text="✂️ *Швейный HUB — Главное меню*",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )


async def callback_contact_master(update, context):
    """Кнопка Связаться с мастером"""
    await update.callback_query.answer()
    
    text = (
        "👩‍🔧 *Связаться с мастером*\n\n"
        "Для сложных вопросов и консультаций:\n\n"
        f"📞 *Позвоните:* {WORKSHOP_INFO['phone']}\n"
        f"💬 *WhatsApp:* {WORKSHOP_INFO['whatsapp']}\n\n"
        f"📍 *Или приходите к нам:*\n{WORKSHOP_INFO['address']}\n\n"
        "⏰ *График:*\n"
        "Пн-Чт: 10:00-19:50\n"
        "Пт: 10:00-19:00\n"
        "Сб: 10:00-17:00\n\n"
        "Мастер осмотрит вещь и назовёт точную цену!"
    )
    
    await update.callback_query.edit_message_text(
        text=text,
        reply_markup=get_back_button(),
        parse_mode="Markdown"
    )


LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "logo.jpg")

async def show_menu_with_logo(message, name):
    """Показать меню с логотипом"""
    caption = (
        f"✂️ *Швейный HUB*\n\n"
        f"Иголочка на связи! 🪡\n"
        f"Чем могу помочь, {name}?"
    )
    
    if os.path.exists(LOGO_PATH):
        with open(LOGO_PATH, 'rb') as photo:
            await message.reply_photo(
                photo=photo,
                caption=caption,
                parse_mode="Markdown"
            )
    else:
        await message.reply_text(caption, parse_mode="Markdown")
    
    await message.reply_text(
        "✂️ *Швейный HUB — Главное меню*",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

async def order_command(update, context):
    """Команда /order - начать оформление заказа (обрабатывается ConversationHandler)"""
    pass


async def services_command(update, context):
    """Команда /services - показать услуги и цены"""
    await update.message.reply_text(
        text="💰 Выберите категорию услуг:",
        reply_markup=get_prices_menu()
    )


async def contact_command(update, context):
    """Команда /contact - показать контакты"""
    text = (
        "📍 *Контакты мастерской*\n\n"
        "🏠 *Адрес:* г.Москва, ул.Маршала Федоренко д.12, 1 этаж\n\n"
        "📞 *Телефон:* +7 (968) 396-91-52\n"
        "💬 *WhatsApp:* +7 (968) 396-91-52\n\n"
        "⏰ *График работы:*\n"
        "Пн-Чт: 10:00-19:50\n"
        "Пт: 10:00-19:00\n"
        "Сб: 10:00-17:00\n"
        "Вс: выходной"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def menu_command(update, context):
    """Команда /menu"""
    user = update.effective_user
    name = user.first_name or "друг"
    await show_menu_with_logo(update.message, name)



async def log_all_updates(update: Update, context):
    """Логирование всех входящих обновлений для диагностики"""
    user_id = update.effective_user.id if update.effective_user else "unknown"
    if update.callback_query:
        logger.info(f"📥 CALLBACK RECEIVED: {update.callback_query.data} from user {user_id}")
    elif update.message:
        text = update.message.text[:50] if update.message.text else "[no text]"
        logger.info(f"📥 MESSAGE RECEIVED: {text} from user {user_id}")


def main() -> None:
    """Главная функция"""
    global BOT_IS_RUNNING
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен!")
        return
    
    start_health_server(8080)
    
    init_db()
    import_prices_data()
    logger.info("✅ База данных инициализирована")
    logger.info("💰 Цены загружены из базы данных")
    
    BOT_IS_RUNNING = True
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    from telegram.ext import TypeHandler
    app.add_handler(TypeHandler(Update, log_all_updates), group=-1)
    
    order_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(order_start, pattern="^new_order$"),
            CommandHandler("order", order_start)
        ],
        states={
            SELECT_SERVICE: [
                CallbackQueryHandler(select_service, pattern="^service_"),
                CallbackQueryHandler(cancel_order, pattern="^back_menu$")
            ],
            SEND_PHOTO: [
                MessageHandler(filters.PHOTO, receive_photo),
                CallbackQueryHandler(skip_photo, pattern="^skip_photo$"),
                CallbackQueryHandler(cancel_order, pattern="^cancel_order$")
            ],
            ENTER_NAME: [
                CallbackQueryHandler(use_tg_name, pattern="^use_tg_name$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name),
                CallbackQueryHandler(cancel_order, pattern="^cancel_order$")
            ],
            ENTER_PHONE: [
                CallbackQueryHandler(skip_phone_handler, pattern="^skip_phone$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_phone),
                CallbackQueryHandler(cancel_order, pattern="^cancel_order$")
            ],
            CONFIRM_ORDER: [
                CallbackQueryHandler(confirm_order, pattern="^confirm_order$"),
                CallbackQueryHandler(cancel_order, pattern="^cancel_order$")
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_order, pattern="^cancel_order$"),
            CommandHandler("cancel", lambda u, c: cancel_order(u, c))
        ],
        allow_reentry=True,
        per_message=False
    )
    
    app.add_handler(order_conversation)
    
    review_conversation = get_review_conversation_handler()
    app.add_handler(review_conversation)
    
    app.add_handler(CommandHandler("start", commands.start))
    app.add_handler(CommandHandler("help", commands.help_command))
    app.add_handler(CommandHandler("services", services_command))
    app.add_handler(CommandHandler("contact", contact_command))
    
    app.add_handler(CommandHandler("admin", admin.admin_menu))
    app.add_handler(CommandHandler("stats", admin.admin_stats))
    app.add_handler(CommandHandler("orders", admin.admin_orders))
    app.add_handler(CommandHandler("neworders", admin.admin_new_orders))
    app.add_handler(CommandHandler("users", admin.admin_users))
    app.add_handler(CommandHandler("spam", admin.admin_spam))
    app.add_handler(CommandHandler("broadcast", admin.broadcast_start))
    app.add_handler(CommandHandler("setadmin", admin.set_admin_command))
    
    app.add_handler(CallbackQueryHandler(admin.admin_menu_callback, pattern="^admin_orders_"))
    app.add_handler(CallbackQueryHandler(admin.admin_menu_callback, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin.admin_menu_callback, pattern="^admin_stats_today$"))
    app.add_handler(CallbackQueryHandler(admin.admin_menu_callback, pattern="^admin_stats_week$"))
    app.add_handler(CallbackQueryHandler(admin.admin_menu_callback, pattern="^admin_clients$"))
    app.add_handler(CallbackQueryHandler(admin.admin_menu_callback, pattern="^admin_back_menu$"))
    app.add_handler(CallbackQueryHandler(admin.open_web_admin, pattern="^open_web_admin$"))
    app.add_handler(CallbackQueryHandler(admin.admin_view_order, pattern="^admin_view_"))
    
    app.add_handler(CallbackQueryHandler(callback_services, pattern="^services$"))
    app.add_handler(CallbackQueryHandler(callback_check_status, pattern="^check_status$"))
    app.add_handler(CallbackQueryHandler(callback_faq, pattern="^faq$"))
    app.add_handler(CallbackQueryHandler(callback_contacts, pattern="^contacts$"))
    
    app.add_handler(CallbackQueryHandler(callback_price_jacket, pattern="^price_jacket$"))
    app.add_handler(CallbackQueryHandler(callback_price_leather, pattern="^price_leather$"))
    app.add_handler(CallbackQueryHandler(callback_price_curtains, pattern="^price_curtains$"))
    app.add_handler(CallbackQueryHandler(callback_price_coat, pattern="^price_coat$"))
    app.add_handler(CallbackQueryHandler(callback_price_fur, pattern="^price_fur$"))
    app.add_handler(CallbackQueryHandler(callback_price_outerwear, pattern="^price_outerwear$"))
    app.add_handler(CallbackQueryHandler(callback_price_pants, pattern="^price_pants$"))
    app.add_handler(CallbackQueryHandler(callback_price_dress, pattern="^price_dress$"))
    
    app.add_handler(CallbackQueryHandler(callback_faq_services, pattern="^faq_services$"))
    app.add_handler(CallbackQueryHandler(callback_faq_prices, pattern="^faq_prices$"))
    app.add_handler(CallbackQueryHandler(callback_faq_timing, pattern="^faq_timing$"))
    app.add_handler(CallbackQueryHandler(callback_faq_location, pattern="^faq_location$"))
    app.add_handler(CallbackQueryHandler(callback_faq_payment, pattern="^faq_payment$"))
    app.add_handler(CallbackQueryHandler(callback_faq_order, pattern="^faq_order$"))
    app.add_handler(CallbackQueryHandler(callback_faq_other, pattern="^faq_other$"))
    
    app.add_handler(CallbackQueryHandler(handle_order_status_change, pattern="^status_"))
    app.add_handler(CallbackQueryHandler(handle_order_status_change, pattern="^admin_open_"))
    
    app.add_handler(CallbackQueryHandler(callback_back, pattern="^back_menu$"))
    app.add_handler(CallbackQueryHandler(callback_contact_master, pattern="^contact_master$"))
    
    app.add_handler(CommandHandler("menu", menu_command))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages.handle_message))
    
    async def post_init(application):
        """Настройка кнопки меню"""
        await application.bot.set_my_commands([
            BotCommand("start", "🏠 Главное меню"),
            BotCommand("order", "➕ Оформить заказ"),
            BotCommand("services", "📋 Услуги и цены"),
            BotCommand("contact", "📞 Контакты"),
            BotCommand("help", "❓ Справка"),
        ])
        await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("✅ Кнопка меню настроена")
        
        import asyncio
        
        async def periodic_review_check():
            """Периодическая проверка отзывов каждый час"""
            await asyncio.sleep(60)  # первый запуск через 1 минуту
            while True:
                try:
                    orders = get_orders_pending_feedback()
                    for order in orders:
                        try:
                            user_id = int(order.user_id) if order.user_id else 0
                            order_id = int(order.id) if order.id else 0
                            await request_review(application, user_id, order_id)
                            mark_feedback_requested(order_id)
                            logger.info(f"Review request sent for order {order_id}")
                        except Exception as e:
                            logger.error(f"Failed to send review request for order {order_id}: {e}")
                except Exception as e:
                    logger.error(f"Error checking pending reviews: {e}")
                await asyncio.sleep(3600)  # каждый час
        
        asyncio.create_task(periodic_review_check())
        logger.info("✅ Фоновая задача для отзывов запущена")
    
    app.post_init = post_init
    
    logger.info("🤖 Бот запущен и готов к работе!")
    
    async def error_handler(update, context):
        """Глобальный обработчик ошибок"""
        logger.error(f"Exception while handling an update: {context.error}")
        try:
            admin_id = os.getenv('ADMIN_ID')
            if admin_id:
                await context.bot.send_message(
                    chat_id=int(admin_id),
                    text=f"⚠️ *Ошибка бота:*\n`{str(context.error)[:200]}`",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Failed to notify admin about error: {e}")
    
    app.add_error_handler(error_handler)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


def run_with_restart():
    """Запуск бота с автоматическим перезапуском при ошибках"""
    logger.info("⏳ Ожидание 15 секунд для завершения предыдущего экземпляра...")
    time.sleep(15)
    
    max_retries = 10
    retry_count = 0
    conflict_retries = 0
    max_conflict_retries = 10
    
    while retry_count < max_retries:
        try:
            main()
            break
        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем")
            break
        except Exception as e:
            error_str = str(e).lower()
            if 'conflict' in error_str or 'terminated by other' in error_str:
                conflict_retries += 1
                if conflict_retries >= max_conflict_retries:
                    logger.critical("⚠️ Конфликт не разрешён после 10 попыток. Остановка.")
                    break
                wait_time = 60
                logger.warning(f"⚠️ Конфликт с другим экземпляром. Попытка {conflict_retries}/{max_conflict_retries}. Ждём {wait_time} сек...")
                time.sleep(wait_time)
                continue
            
            retry_count += 1
            logger.error(f"Критическая ошибка #{retry_count}: {e}")
            if retry_count < max_retries:
                wait_time = min(30, 5 * retry_count)
                logger.info(f"Перезапуск через {wait_time} секунд...")
                time.sleep(wait_time)
            else:
                logger.critical("Достигнут лимит перезапусков. Бот остановлен.")


if __name__ == '__main__':
    run_with_restart()
