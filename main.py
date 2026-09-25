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
    MessageHandler, ConversationHandler, filters, TypeHandler, ContextTypes
)

BOT_START_TIME = time.time()
LAST_UPDATE_TIME = time.time()
BOT_IS_RUNNING = False

class HealthHandler(BaseHTTPRequestHandler):
    """HTTP handler для поддержания работы на хостинге без падений"""
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        global LAST_UPDATE_TIME, BOT_IS_RUNNING
        if self.path in ['/', '/health', '/status']:
            uptime = int(time.time() - BOT_START_TIME)
            response = {
                "status": "alive" if BOT_IS_RUNNING else "starting",
                "uptime_seconds": uptime,
                "message": "Бот работает 24/7!"
            }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()

def start_health_server(port=8080):
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logging.info(f"✅ Health check сервер запущен на порту {port}")

from handlers import commands, messages, admin
from handlers.orders import (
    order_start, select_service, receive_photo, skip_photo,
    enter_description, skip_description, enter_name, enter_phone, 
    confirm_order, cancel_order, use_tg_name, skip_phone as skip_phone_handler,
    handle_order_status_change, SELECT_SERVICE, SEND_PHOTO, 
    ENTER_DESCRIPTION, ENTER_NAME, ENTER_PHONE, CONFIRM_ORDER
)
from handlers.reviews import get_review_conversation_handler, request_review
from keyboards import get_main_menu, get_prices_menu, get_services_menu, get_faq_menu, get_back_button
from utils.database import init_db, get_user_orders, add_user, get_orders_pending_feedback, mark_feedback_requested
from utils.anti_spam import anti_spam
from utils.prices import format_prices_text, import_prices_data

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

WORKSHOP_INFO = {
    "name": "Швейная мастерская",
    "address": "г. Москва, ул. Маршала Федоренко д.12, 1 этаж",
    "phone": "+7 (968) 396-91-52",
    "whatsapp": "+7 (968) 396-91-52"
}

# --- ОБРАБОТЧИКИ ИНЛАЙН-МЕНЮ КЛИЕНТА ---
async def callback_services(update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("💰 Выберите категорию услуг:", reply_markup=get_prices_menu())

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
        text = "🔍 У вас нет заказов.\n\nПозвоните нам: " + WORKSHOP_INFO['phone']
    else:
        from handlers.orders import format_order_id
        text = "🔍 *Ваши заказы:*\n\n"
        status_map = {'new': '🆕 Новый', 'in_progress': '🔄 В работе', 'completed': '✅ Готов', 'issued': '📤 Выдан', 'cancelled': '❌ Отменён'}
        for order in orders[:5]:
            status = status_map.get(str(order.status), str(order.status))
            desc = str(order.description) if order.description else "Услуга"
            fid = format_order_id(int(order.id), order.created_at)
            text += f"*{fid}* - {status}\n{desc}\n\n"
    await update.callback_query.edit_message_text(text=text, reply_markup=get_back_button(), parse_mode="Markdown")

async def callback_faq(update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("❓ Выберите интересующий вопрос:", reply_markup=get_faq_menu())

async def callback_faq_services(update, context):
    await update.callback_query.answer()
    text = "📋 *Какие услуги мы выполняем:*\n\n✂️ Подшив и укорачивание\n🔄 Замена молний и пуговиц\n📐 Ушивание и расширение\n🧥 Ремонт верхней одежды\n🎒 Ремонт кожаных\n🐾 Шубы и дублёнки\n🪟 Пошив штор"
    await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")

async def callback_faq_prices(update, context):
    await update.callback_query.answer()
    text = "💰 *Примерные цены:*\n\n👖 Укоротить джинсы — от 500р\n👖 С родным краем — от 900р\n👗 Укоротить юбку — от 800р\n🧥 Замена молнии — от 2000р\n🧥 Замена подкладки — от 3500р\n📐 Подгон по фигуре — от 1500р"
    await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")

async def callback_faq_timing(update, context):
    await update.callback_query.answer()
    text = "⏰ *Сроки:*\n\n⚡ Простой ремонт — 1-2 дня\n📦 Сложный ремонт — 3-7 дней\n🚀 Срочный ремонт — 24 часа (+50%)"
    await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")

async def callback_faq_location(update, context):
    await update.callback_query.answer()
    text = f"📍 *Адрес:*\n{WORKSHOP_INFO['address']}\n\n⏰ *График:*\nПн-Чт: 10:00-19:50\nПт: 10:00-19:00\nСб: 10:00-17:00\nВс: выходной\n\n📞 {WORKSHOP_INFO['phone']}"
    await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")

async def callback_faq_payment(update, context):
    await update.callback_query.answer()
    text = "💳 *Способы оплаты:*\n• Наличные\n• Перевод\n\n💵 *Предоплата:*\nНе требуется для обычного ремонта\n50% — для дорогой фурнитуры\n\n🛡️ *Гарантия:* 30 дней!"
    await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")

async def callback_faq_order(update, context):
    await update.callback_query.answer()
    text = "📝 *Как оформить:*\n1️⃣ Нажмите «Создать заказ»\n2️⃣ Выберите услугу\n3️⃣ Прикрепите фото\n4️⃣ Подтвердите\nМы свяжемся для уточнения!"
    await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")

async def callback_faq_other(update, context):
    await update.callback_query.answer()
    text = f"❓ *Другой вопрос?*\nОпишите проблему здесь в чате или позвоните: {WORKSHOP_INFO['phone']}"
    await update.callback_query.edit_message_text(text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")

async def callback_contacts(update, context):
    await update.callback_query.answer()
    text = f"📍 *Наши контакты:*\n\n📍 *Адрес:*\n{WORKSHOP_INFO['address']}\n\n📞 *Телефон:*\n{WORKSHOP_INFO['phone']}\n\n💬 *WhatsApp:*\n{WORKSHOP_INFO['whatsapp']}\n\n⏰ Пн-Чт: 10:00-19:50\nПт: 10:00-19:00\nСб: 10:00-17:00"
    await update.callback_query.edit_message_text(text=text, reply_markup=get_back_button(), parse_mode="Markdown")

async def callback_back(update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(text="✂️ *Швейный HUB — Главное меню*", reply_markup=get_main_menu(), parse_mode="Markdown")

async def callback_contact_master(update, context):
    await update.callback_query.answer()
    text = f"👩‍🔧 *Связаться с мастером*\n\n📞 *Позвоните:* {WORKSHOP_INFO['phone']}\n💬 *WhatsApp:* {WORKSHOP_INFO['whatsapp']}\n\n📍 *Или приходите:* {WORKSHOP_INFO['address']}"
    await update.callback_query.edit_message_text(text=text, reply_markup=get_back_button(), parse_mode="Markdown")

async def log_all_updates(update: Update, context):
    if update.callback_query:
        logger.info(f"📥 CALLBACK: {update.callback_query.data} from user {update.effective_user.id}")

def main():
    global BOT_IS_RUNNING
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен!")
        return

    start_health_server(int(os.getenv("PORT", 8080)))
    init_db()
    try: import_prices_data()
    except Exception: pass
    
    BOT_IS_RUNNING = True
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(TypeHandler(Update, log_all_updates), group=-1)

    # 1. ОБРАБОТЧИКИ ИНЛАЙН-КНОПОК КЛИЕНТА
    app.add_handler(CallbackQueryHandler(callback_services, pattern="^services$"))
    app.add_handler(CallbackQueryHandler(callback_check_status, pattern="^check_status$"))
    app.add_handler(CallbackQueryHandler(callback_faq, pattern="^faq$"))
    app.add_handler(CallbackQueryHandler(callback_contacts, pattern="^contacts$"))
    app.add_handler(CallbackQueryHandler(callback_back, pattern="^back_menu$"))
    app.add_handler(CallbackQueryHandler(callback_contact_master, pattern="^contact_master$"))

    for cat in ["jacket", "leather", "curtains", "coat", "fur", "outerwear", "pants", "dress"]:
        app.add_handler(CallbackQueryHandler(globals()[f"callback_price_{cat}"], pattern=f"^price_{cat}$"))
    for sub in ["services", "prices", "timing", "location", "payment", "order", "other"]:
        app.add_handler(CallbackQueryHandler(globals()[f"callback_faq_{sub}"], pattern=f"^faq_{sub}$"))

    # 2. ОБРАБОТЧИКИ АДМИНСКИХ КНОПОК
    app.add_handler(CallbackQueryHandler(admin.open_web_admin, pattern="^open_web_admin$"))
    app.add_handler(CallbackQueryHandler(admin.admin_view_order, pattern="^admin_view_"))
    app.add_handler(CallbackQueryHandler(admin.change_order_status, pattern="^status_"))
    app.add_handler(CallbackQueryHandler(admin.contact_client, pattern="^contact_client_"))
    app.add_handler(CallbackQueryHandler(mark_as_spam_callback, pattern="^mark_spam_"))
    app.add_handler(CallbackQueryHandler(admin.admin_menu_callback, pattern="^admin_"))

    # 3. CONVERSATION HANDLER ЗАКАЗОВ
    order_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(order_start, pattern="^new_order$"),
            CommandHandler("order", order_start)
        ],
        states={
            SELECT_SERVICE: [CallbackQueryHandler(select_service, pattern="^service_"), CallbackQueryHandler(cancel_order, pattern="^back_menu$")],
            SEND_PHOTO: [MessageHandler(filters.PHOTO, receive_photo), CallbackQueryHandler(skip_photo, pattern="^skip_photo$"), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")],
            ENTER_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_description), CallbackQueryHandler(skip_description, pattern="^skip_description$"), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")],
            ENTER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name), CallbackQueryHandler(use_tg_name, pattern="^use_tg_name$"), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")],
            ENTER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_phone), CallbackQueryHandler(skip_phone_handler, pattern="^skip_phone$"), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")],
            CONFIRM_ORDER: [CallbackQueryHandler(confirm_order, pattern="^confirm_order$"), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")]
        },
        fallbacks=[CommandHandler("cancel", cancel_order), CallbackQueryHandler(cancel_order, pattern="^cancel_order$")],
        allow_reentry=True,
        name="order_flow"
    )
    app.add_handler(order_conversation)
    app.add_handler(get_review_conversation_handler())

    # 4. КОМАНДЫ БОТА
    app.add_handler(CommandHandler("start", commands.start))
    app.add_handler(CommandHandler("help", commands.help_command))
    app.add_handler(CommandHandler("faq", commands.faq_command))
    app.add_handler(CommandHandler("status", commands.status_command))
    app.add_handler(CommandHandler("services", commands.services_command))
    app.add_handler(CommandHandler("contact", commands.contact_command))
    
    app.add_handler(CommandHandler("admin", admin.admin_panel_command))
    app.add_handler(CommandHandler("stats", admin.admin_stats))
    app.add_handler(CommandHandler("orders", admin.admin_orders))
    app.add_handler(CommandHandler("users", admin.admin_users))
    app.add_handler(CommandHandler("spam", admin.admin_spam))
    app.add_handler(CommandHandler("broadcast", admin.broadcast_start))
    app.add_handler(CommandHandler("setadmin", admin.set_admin_command))

    # 5. ГЛОБАЛЬНЫЕ ОБРАБОТЧИКИ ТЕКСТА И КОЛЛБЭКОВ
    app.add_handler(CallbackQueryHandler(messages.handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages.handle_message))

    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start", "🏠 Главное меню"),
            BotCommand("order", "➕ Оформить заказ"),
            BotCommand("services", "📋 Услуги и цены"),
            BotCommand("contact", "📞 Контакты"),
            BotCommand("help", "❓ Справка"),
        ])
        await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        
    app.post_init = post_init

    async def error_handler(update, context):
        logger.error(f"Exception while handling an update: {context.error}")

    app.add_error_handler(error_handler)
    
    # Запускаем поллинг, сбрасывая застрявшие апдейты
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

def run_with_restart():
    logger.info("⏳ Запуск...")
    max_retries = 10
    retry_count = 0
    conflict_retries = 0
    while retry_count < max_retries:
        try:
            main()
            break
        except KeyboardInterrupt:
            break
        except Exception as e:
            if 'conflict' in str(e).lower() or 'terminated by other' in str(e).lower():
                conflict_retries += 1
                time.sleep(60)
                continue
            retry_count += 1
            time.sleep(min(30, 5 * retry_count))

if __name__ == '__main__':
    run_with_restart()
