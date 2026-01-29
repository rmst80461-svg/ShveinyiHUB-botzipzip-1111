#!/usr/bin/env python3
import os
import sys
import time
import asyncio
import threading
import json
import socket
import atexit
import logging
import subprocess
from dotenv import load_dotenv

# --- АВТОЗАПУСК ДЛЯ BOTHOST ---
# Загружаем .env принудительно для работы на любом хостинге
def force_load_env():
    possible_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'),
        os.path.join(os.getcwd(), '.env'),
        '.env'
    ]
    for path in possible_paths:
        if os.path.exists(path):
            load_dotenv(path, override=True)
            # Если python-dotenv не справился, читаем вручную
            try:
                with open(path, 'r') as f:
                    for line in f:
                        if '=' in line and not line.startswith('#'):
                            k, v = line.split('=', 1)
                            key = k.strip()
                            value = v.strip().strip('"').strip("'")
                            # Сохраняем в окружение
                            os.environ[key] = value
                            # Специальная обработка для ADMIN_ID/ADMIN_IDS, чтобы они были доступны глобально
                            if key in ["ADMIN_ID", "ADMIN_IDS"]:
                                logging.info(f"Loaded {key} from .env")
            except: pass
            return True
    return False

# Принудительно загружаем переменные окружения ДО всего остального
force_load_env()

# ЛОГИРОВАНИЕ (настройка до импортов)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO)
logger = logging.getLogger(__name__)

# Проверка токена
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not os.getenv("SKIP_FLASK"):
    import subprocess as _sp
    import sys as _sys
    _startup_logger = logging.getLogger("startup")
    _startup_logger.info("Перенаправление на run_services.py...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.execvp(_sys.executable, [_sys.executable, os.path.join(base_dir, "run_services.py")])

# --- ИМПОРТ ВЕБ-АДМИНКИ ---
try:
    from webapp.app import app
except ImportError:
    from flask import Flask
    app = Flask(__name__)
    @app.route('/')
    def index(): return "Ошибка импорта webapp.app."

from telegram import Update, MenuButtonCommands, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
                          MessageHandler, ConversationHandler, filters, TypeHandler, ContextTypes)

from handlers import commands, messages, admin
from handlers.commands import faq_command, status_command
from handlers.orders import (order_start, select_service, receive_photo, skip_photo, 
                             enter_description, skip_description, enter_name, enter_phone, 
                             confirm_order, cancel_order, use_tg_name, skip_phone as skip_phone_handler, 
                             handle_order_status_change, SELECT_SERVICE, SEND_PHOTO, 
                             ENTER_DESCRIPTION, ENTER_NAME, ENTER_PHONE, CONFIRM_ORDER)
from handlers.reviews import get_review_conversation_handler, request_review
from keyboards import (get_main_menu, get_prices_menu, get_faq_menu,
                       get_back_button, get_admin_main_menu)
from utils.database import (init_db, get_user_orders, get_orders_pending_feedback, mark_feedback_requested)
from utils.prices import format_prices_text, import_prices_data

_lock = None

# --- БЛОКИРОВКА ПОВТОРНОГО ЗАПУСКА ---
def create_lock():
    global _lock
    if os.getenv("DISABLE_INSTANCE_LOCK", "0") == "1": return None
    lock_port = int(os.getenv("LOCK_PORT", "48975"))
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", lock_port))
        s.listen(1)
        s.setblocking(False)
        _lock = {"type": "socket", "obj": s, "port": lock_port}
        return _lock
    except OSError: pass
    return None

def release_lock():
    global _lock
    try:
        if isinstance(_lock, dict) and _lock.get("type") == "socket": _lock["obj"].close()
    except Exception: pass
    finally: _lock = None

atexit.register(release_lock)

from handlers.admin_panel.handlers import set_admin_commands, show_admin_stats, show_spam_candidates, mark_as_spam_callback

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ---
BOT_START_TIME = time.time()
WORKSHOP_INFO = {
    "name": "Швейная мастерская",
    "address": "г. Москва, (МЦД/м. Ховрино) ул. Маршала Федоренко д.12, , ТЦ \"Бусиново\", 1 этаж",
    "phone": "+7 (968) 396-91-52",
    "whatsapp": "+7 (968) 396-91-52"
}

# --- CALLBACK ФУНКЦИИ ---
async def callback_services(update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(text="💰 Выберите категорию услуг:", reply_markup=get_prices_menu())

async def callback_price_category(update, context, category):
    await update.callback_query.answer()
    prices_text = format_prices_text(category)
    if prices_text:
        await update.callback_query.edit_message_text(text=prices_text, reply_markup=get_prices_menu(), parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(text="Цены не найдены", reply_markup=get_prices_menu())

async def callback_price_jacket(update, context): await callback_price_category(update, context, "jacket")
async def callback_price_leather(update, context): await callback_price_category(update, context, "leather")
async def callback_price_curtains(update, context): await callback_price_category(update, context, "curtains")
async def callback_price_coat(update, context): await callback_price_category(update, context, "coat")
async def callback_price_fur(update, context): await callback_price_category(update, context, "fur")
async def callback_price_outerwear(update, context): await callback_price_category(update, context, "outerwear")
async def callback_price_pants(update, context): await callback_price_category(update, context, "pants")
async def callback_price_dress(update, context): await callback_price_category(update, context, "dress")

async def callback_check_status(update, context):
    await update.callback_query.answer()
    user_id = update.effective_user.id
    orders = get_user_orders(user_id)
    if not orders:
        text = "🔍 У вас нет заказов.\n\nПозвоните нам: " + WORKSHOP_INFO["phone"]
    else:
        from handlers.orders import format_order_id
        text = "🔍 *Ваши заказы:*\n\n"
        status_map = {"new": "🆕 Новый", "in_progress": "🔄 В работе", "completed": "✅ Готов", "issued": "📤 Выдан", "cancelled": "❌ Отменён"}
        for order in orders[:5]:
            status = status_map.get(str(order.status), str(order.status))
            desc = str(order.description) if order.description else "Услуга"
            formatted_id = format_order_id(int(order.id), order.created_at)
            text += f"*{formatted_id}* - {status}\n{desc}\n\n"
    await update.callback_query.edit_message_text(text=text, reply_markup=get_back_button(), parse_mode="Markdown")

async def callback_faq(update, context):
    await update.callback_query.answer()
    try: await update.callback_query.edit_message_text(text="❓ Выберите интересующий вопрос:", reply_markup=get_faq_menu())
    except: pass

async def callback_faq_services(update, context):
    await update.callback_query.answer()
    text = "📋 *Какие услуги мы выполняем:*\n\n✂️ Подшив и укорачивание\n🔄 Замена молний и пуговиц\n📐 Ушивание и расширение\n🧥 Ремонт верхней одежды\n🎒 Ремонт кожаных изделий\n🐾 Ремонт шуб и дублёнок\n🪟 Пошив штор"
    try: await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")
    except: pass

async def callback_faq_prices(update, context):
    await update.callback_query.answer()
    text = "💰 *Примерные цены:*\n\n👖 Укоротить джинсы — от 500р\n👖 С родным краем — от 900р\n👗 Укоротить юбку — от 800р\n🧥 Замена молнии — от 2000р\n🧥 Замена подкладки — от 3500р\n📐 Подгон по фигуре — от 1500р"
    try: await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")
    except: pass

async def callback_faq_timing(update, context):
    await update.callback_query.answer()
    text = "⏰ *Сроки:*\n\n⚡ Простой ремонт — 1-2 дня\n📦 Сложный ремонт — 3-7 дней\n🚀 Срочный ремонт — 24 часа (+50%)"
    try: await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")
    except: pass

async def callback_faq_location(update, context):
    await update.callback_query.answer()
    text = f"📍 *Адрес:*\n{WORKSHOP_INFO['address']}\n\n⏰ *График:*\nПн-Чт: 10:00-19:50\nПт: 10:00-19:00\nСб: 10:00-17:00\nВс: выходной\n\n📞 {WORKSHOP_INFO['phone']}"
    try: await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")
    except: pass

async def callback_faq_payment(update, context):
    await update.callback_query.answer()
    text = "💳 *Способы оплаты:*\n• Наличные\n• Перевод по номеру\n\n💵 *Предоплата:*\nНе требуется для обычного ремонта\n50% — для дорогой фурнитуры\n\n🛡️ *Гарантия:*\n30 дней на все виды!"
    try: await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")
    except: pass

async def callback_faq_order(update, context):
    await update.callback_query.answer()
    text = "📝 *Как оформить:*\n\n1️⃣ Создать заказ\n2️⃣ Выберите услугу\n3️⃣ Фото вещи\n4️⃣ Имя и телефон\n5️⃣ Подтвердите\n\nМы свяжемся для уточнения!"
    try: await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")
    except: pass

async def callback_faq_other(update, context):
    await update.callback_query.answer()
    text = f"❓ *Другой вопрос?*\n\nОпишите здесь в чате или позвоните: {WORKSHOP_INFO['phone']}"
    try: await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")
    except: pass

async def callback_contacts(update, context):
    await update.callback_query.answer()
    hours_text = "Пн-Чт: 10:00-19:50\nПт: 10:00-19:00\nСб: 10:00-17:00\nВс: выходной"
    map_link = "https://yandex.ru/maps/org/shveyny_hub/1233246900/"
    text = (f"📍 <b>Наши контакты:</b>\n\n📍 <b>Адрес:</b>\n{WORKSHOP_INFO['address']}\n\n"
            f"🗺 <b>Смотреть на карте:</b>\n{map_link}\n\n📞 <b>Телефон:</b>\n{WORKSHOP_INFO['phone']}\n\n"
            f"💬 <b>WhatsApp:</b>\n{WORKSHOP_INFO['whatsapp']}\n\n⏰ <b>График:</b>\n{hours_text}")
    await update.callback_query.edit_message_text(text=text, reply_markup=get_back_button(), parse_mode="HTML")

async def callback_back(update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(text="✂️ *Швейный HUB — Главное меню*", reply_markup=get_main_menu(), parse_mode="Markdown")

async def callback_contact_master(update, context):
    await update.callback_query.answer()
    text = f"👩‍🔧 *Связаться с мастером*\n\n📞 *Позвоните:* {WORKSHOP_INFO['phone']}\n💬 *WhatsApp:* {WORKSHOP_INFO['whatsapp']}\n\n📍 *Адрес:*\n{WORKSHOP_INFO['address']}\n\n⏰ Пн-Чт: 10:00-19:50\nПт: 10:00-19:00\nСб: 10:00-17:00"
    await update.callback_query.edit_message_text(text=text, reply_markup=get_back_button(), parse_mode="Markdown")

LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "logo.jpg")

async def show_menu_with_logo(message, name):
    caption = f"✂️ *Швейный HUB*\n\nИголочка на связи! 🪡\nЧем могу помочь, {name}?"
    if os.path.exists(LOGO_PATH):
        with open(LOGO_PATH, "rb") as photo:
            await message.reply_photo(photo=photo, caption=caption, parse_mode="Markdown")
    else:
        await message.reply_text(caption, parse_mode="Markdown")
    await message.reply_text("✂️ *Швейный HUB — Главное меню*", reply_markup=get_main_menu(), parse_mode="Markdown")

async def order_command(update, context): await order_start(update, context)
async def services_command(update, context):
    if update.message: await update.message.reply_text(text="💰 Выберите категорию услуг:", reply_markup=get_prices_menu())

async def contact_command(update, context):
    text = f"📍 *Контакты мастерской*\n\n🏠 *Адрес:* {WORKSHOP_INFO['address']}\n\n📞 *Телефон:* {WORKSHOP_INFO['phone']}\n💬 *WhatsApp:* {WORKSHOP_INFO['whatsapp']}\n\n⏰ *График:*\nПн-Чт: 10:00-19:50\nПт: 10:00-19:00\nСб: 10:00-17:00\nВс: выходной"
    if update.message: await update.message.reply_text(text, parse_mode="Markdown")

async def menu_command(update, context):
    user = update.effective_user
    name = user.first_name or "друг"
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if message: await show_menu_with_logo(message, name)

async def admin_panel_command(update, context):
    user_id = update.effective_user.id
    from handlers.admin import is_user_admin
    if not is_user_admin(user_id):
        if update.message: await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    # Принудительно устанавливаем команды админа при входе в панель
    try:
        from handlers.admin_panel.handlers import set_admin_commands
        await set_admin_commands(context.bot, user_id)
    except: pass
    
    text = "📋 *Админ-панель*\n\nВыберите раздел для управления:"
    if update.message: await update.message.reply_text(text, reply_markup=get_admin_main_menu(), parse_mode="Markdown")

async def log_all_updates(update: Update, context):
    user_id = update.effective_user.id if update.effective_user else "unknown"
    if update.callback_query: logger.info(f"📥 CALLBACK: {update.callback_query.data} from {user_id}")
    elif update.message:
        text = update.message.text[:50] if update.message.text else "[no text]"
        logger.info(f"📥 MESSAGE: {text} from {user_id}")

# --- ГЛАВНАЯ ФУНКЦИЯ ---
def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN не установлен!")
        return
    create_lock()
    logger.info("⏳ Ожидание 5 секунд перед запуском бота...")
    time.sleep(5)
    try:
        import requests
        requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=true", timeout=10)
        logger.info("✅ Webhook сброшен")
    except Exception as e: logger.warning(f"Не удалось сбросить webhook: {e}")

    if not os.getenv("SKIP_FLASK") and not os.getenv("SKIP_BOT") and (token or os.getenv("REPLIT_SLUG")):
        def run_flask():
            try:
                # Пытаемся взять порт из PORT (Bothost) или FLASK_PORT или дефолтный 8080
                # Bothost ожидает, что приложение слушает порт из переменной PORT
                port = int(os.getenv("PORT") or os.getenv("FLASK_PORT") or "8080")
                logger.info(f"Запуск Flask на порту {port}")
                app.run(host="0.0.0.0", port=port, use_reloader=False, threaded=True)
            except Exception as e: logger.error(f"Ошибка при запуске Flask: {e}")
        threading.Thread(target=run_flask, daemon=True).start()
        time.sleep(3)

    init_db()
    try: import_prices_data()
    except Exception: logger.warning("Не удалось загрузить цены")

    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start", "🏠 Главное меню"), BotCommand("order", "➕ Оформить заказ"),
            BotCommand("faq", "❓ FAQ"), BotCommand("status", "🔍 Статус заказа"),
            BotCommand("services", "📋 Услуги и цены"), BotCommand("contact", "📞 Контакты"), BotCommand("help", "❓ Справка")
        ])
        await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        async def periodic_review_check():
            await asyncio.sleep(60)
            while True:
                try:
                    orders = get_orders_pending_feedback()
                    for order in orders:
                        try:
                            user_id = int(order.user_id) if order.user_id else 0
                            order_id = int(order.id) if order.id else 0
                            await request_review(application, user_id, order_id)
                            mark_feedback_requested(order_id)
                        except Exception as e: logger.error(f"Failed review request: {e}")
                    from handlers.admin import get_admin_ids
                    from utils.database import get_session, Order
                    from datetime import datetime, timedelta
                    session = get_session()
                    five_days_ago = datetime.utcnow() - timedelta(days=5)
                    stuck_orders = session.query(Order).filter(Order.status == 'accepted', Order.accepted_at <= five_days_ago).all()
                    if stuck_orders:
                        admin_ids = get_admin_ids()
                        text = f"⚠️ *{len(stuck_orders)} заказа «Приняты» но не в работе:*\n\n"
                        for o in stuck_orders:
                            from handlers.orders import format_order_id
                            fid = format_order_id(o.id, o.created_at)
                            text += f"• {fid} {o.client_name or '—'} — принят {o.accepted_at.strftime('%d.%m') if o.accepted_at else 'Н/Д'}, срок {o.ready_date or 'Н/Д'}\n"
                        for admin_id in admin_ids:
                            try: await application.bot.send_message(chat_id=admin_id, text=text, parse_mode="Markdown")
                            except: pass
                    three_days_ago = datetime.utcnow() - timedelta(days=3)
                    pending_clients = session.query(Order).filter(Order.status == 'new', Order.client_reminded == False, Order.created_at <= three_days_ago).all()
                    for o in pending_clients:
                        try:
                            from handlers.orders import format_order_id
                            fid = format_order_id(int(o.id), o.created_at)
                            client_msg = (f"🧵 *Швейный HUB*\n\nЗдравствуйте, {o.client_name or 'дорогой клиент'}! 😊\n"
                                          f"Вы оформили заказ *{fid}* 3 дня назад, но мы его еще не получили.\n\n"
                                          f"📍 Мы очень ждем вас и вашу вещь в нашей мастерской!\n\nПожалуйста, выберите действие:")
                            keyboard = InlineKeyboardMarkup([
                                [InlineKeyboardButton("✅ Я уже сдал вещь", callback_data=f"client_already_brought_{o.id}")],
                                [InlineKeyboardButton("🕒 Принесу позже", callback_data=f"client_bring_later_{o.id}")],
                                [InlineKeyboardButton("❌ Отменить заказ", callback_data=f"client_cancel_order_{o.id}")]
                            ])
                            await application.bot.send_message(chat_id=o.user_id, text=client_msg, reply_markup=keyboard, parse_mode="Markdown")
                            o.client_reminded = True
                            session.commit()
                        except Exception as e: logger.error(f"Failed to remind client {o.user_id}: {e}")
                    session.close()
                except Exception as e: logger.error(f"Error in periodic check: {e}")
                await asyncio.sleep(3600)
        try: application.create_task(periodic_review_check())
        except Exception as e: logger.error(f"Не удалось запустить фоновую задачу: {e}")

    app_bot = ApplicationBuilder().token(token).post_init(post_init).build()
    app_bot.add_handler(TypeHandler(Update, log_all_updates), group=-1)

    order_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(order_start, pattern="^new_order$"), CommandHandler("order", order_start)],
        states={
            SELECT_SERVICE: [CallbackQueryHandler(select_service, pattern="^service_"), CallbackQueryHandler(cancel_order, pattern="^back_menu$")],
            SEND_PHOTO: [MessageHandler(filters.PHOTO, receive_photo), CallbackQueryHandler(skip_photo, pattern="^skip_photo$"), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")],
            ENTER_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_description), CallbackQueryHandler(skip_description, pattern="^skip_description$"), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")],
            ENTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name), CallbackQueryHandler(use_tg_name, pattern="^use_tg_name$"), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")],
            ENTER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_phone), MessageHandler(filters.CONTACT, enter_phone), CallbackQueryHandler(skip_phone_handler, pattern="^skip_phone$"), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")],
            CONFIRM_ORDER: [CallbackQueryHandler(confirm_order, pattern="^confirm_order$"), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")]
        },
        fallbacks=[CommandHandler("cancel", cancel_order)],
        name="order_flow", persistent=False)
    app_bot.add_handler(order_conversation)
    app_bot.add_handler(get_review_conversation_handler())

    app_bot.add_handler(CommandHandler("start", commands.start))
    app_bot.add_handler(CommandHandler("faq", faq_command))
    app_bot.add_handler(CommandHandler("status", status_command))
    app_bot.add_handler(CommandHandler("services", services_command))
    app_bot.add_handler(CommandHandler("contact", contact_command))
    app_bot.add_handler(CommandHandler("menu", menu_command))

    from handlers.admin import admin_orders as admin_orders_list, admin_stats as admin_stats_info, admin_users as admin_users_list, admin_spam as admin_spam_logs, broadcast_start as admin_broadcast_start, admin_panel_command as admin_panel_cmd
    from handlers.admin_panel.handlers import show_spam_candidates, mark_as_spam_callback
    
    app_bot.add_handler(CommandHandler("admin", admin_panel_cmd))
    app_bot.add_handler(CommandHandler("stats", admin_stats_info))
    app_bot.add_handler(CommandHandler("orders", admin_orders_list))
    app_bot.add_handler(CommandHandler("users", admin_users_list))
    app_bot.add_handler(CommandHandler("spam", admin_spam_logs))
    app_bot.add_handler(CommandHandler("broadcast", admin_broadcast_start))

    app_bot.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📈 Статистика$"), admin_stats_info))
    app_bot.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📊 Все заказы$"), admin_orders_list))
    app_bot.add_handler(MessageHandler(filters.TEXT & filters.Regex("^❌ Удалить спам$"), show_spam_candidates))
    app_bot.add_handler(MessageHandler(filters.TEXT & filters.Regex("^👥 Пользователи$"), admin_users_list))
    app_bot.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📢 Рассылка$"), admin_broadcast_start))
    app_bot.add_handler(MessageHandler(filters.TEXT & filters.Regex("^◀️ Выйти$"), commands.start))

    app_bot.add_handler(CallbackQueryHandler(mark_as_spam_callback, pattern="^mark_spam_"))

    from handlers.admin_orders import orders_callback_handler, handle_search_input
    app_bot.add_handler(CallbackQueryHandler(orders_callback_handler, pattern="^olist_"))
    app_bot.add_handler(CallbackQueryHandler(orders_callback_handler, pattern="^odetail_"))
    app_bot.add_handler(CallbackQueryHandler(orders_callback_handler, pattern="^ostatus_"))
    app_bot.add_handler(CallbackQueryHandler(orders_callback_handler, pattern="^odelete_"))
    app_bot.add_handler(CallbackQueryHandler(orders_callback_handler, pattern="^osearch"))
    app_bot.add_handler(CallbackQueryHandler(orders_callback_handler, pattern="^orders_page_info$"))

    async def admin_search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        from handlers.admin import is_user_admin
        if update.effective_user and is_user_admin(update.effective_user.id):
            if context.user_data.get("search_mode"):
                if await handle_search_input(update, context): return
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, admin_search_handler), group=2)

    app_bot.add_handler(CallbackQueryHandler(admin.admin_menu_callback, pattern="^admin_"))
    app_bot.add_handler(CallbackQueryHandler(admin.open_web_admin, pattern="^open_web_admin$"))
    app_bot.add_handler(CallbackQueryHandler(admin.admin_view_order, pattern="^admin_view_"))
    app_bot.add_handler(CallbackQueryHandler(admin.change_order_status, pattern="^status_"))
    app_bot.add_handler(CallbackQueryHandler(admin.contact_client, pattern="^contact_client_"))
    app_bot.add_handler(CallbackQueryHandler(callback_services, pattern="^services$"))
    app_bot.add_handler(CallbackQueryHandler(callback_check_status, pattern="^check_status$"))
    app_bot.add_handler(CallbackQueryHandler(callback_faq, pattern="^faq$"))
    app_bot.add_handler(CallbackQueryHandler(callback_contacts, pattern="^contacts$"))
    app_bot.add_handler(CallbackQueryHandler(callback_back, pattern="^back_menu$"))
    app_bot.add_handler(CallbackQueryHandler(callback_contact_master, pattern="^contact_master$"))
    app_bot.add_handler(CallbackQueryHandler(handle_order_status_change, pattern="^admin_open_"))

    for cat in ["jacket", "leather", "curtains", "coat", "fur", "outerwear", "pants", "dress"]:
        app_bot.add_handler(CallbackQueryHandler(globals()[f"callback_price_{cat}"], pattern=f"^price_{cat}$"))
    for sub in ["services", "prices", "timing", "location", "payment", "order", "other"]:
        app_bot.add_handler(CallbackQueryHandler(globals()[f"callback_faq_{sub}"], pattern=f"^faq_{sub}$"))

    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages.handle_message))

    async def error_handler(update, context):
        from telegram.error import BadRequest
        if isinstance(context.error, BadRequest) and "Message is not modified" in str(context.error): return
        logger.error(f"Exception: {context.error}")
        try:
            admin_id = os.getenv("ADMIN_ID")
            if admin_id: await context.bot.send_message(chat_id=admin_id, text=f"❌ Ошибка бота:\n{context.error}")
        except: pass

    app_bot.add_error_handler(error_handler)
    logger.info("Бот запущен...")
    app_bot.run_polling(drop_pending_updates=True)

if __name__ == "__main__": main()
