#!/usr/bin/env python3
import os
import logging
import asyncio
import time
import threading
import json
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, MenuButtonCommands, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, ConversationHandler, filters, TypeHandler, ContextTypes
)

BOT_START_TIME = time.time()
BOT_IS_RUNNING = False

class HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
    def do_GET(self):
        global BOT_IS_RUNNING
        if self.path in ['/', '/health', '/status']:
            uptime = int(time.time() - BOT_START_TIME)
            response = {"status": "alive" if BOT_IS_RUNNING else "starting", "uptime": uptime}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()

def start_health_server(port):
    try:
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logging.info(f"✅ Health check сервер запущен на порту {port}")
    except Exception as e:
        logging.error(f"❌ Ошибка Health-сервера: {e}")

# --- Импорты хэндлеров ---
from handlers import commands, messages, admin
from handlers.commands import faq_command, status_command
from handlers.orders import (
    order_start, select_service, receive_photo, skip_photo,
    enter_description, skip_description, enter_name, enter_phone, 
    confirm_order, cancel_order, use_tg_name, skip_phone as skip_phone_handler,
    handle_order_status_change, SELECT_SERVICE, SEND_PHOTO, 
    ENTER_DESCRIPTION, ENTER_NAME, ENTER_PHONE, CONFIRM_ORDER
)
from handlers.reviews import get_review_conversation_handler
from keyboards import get_main_menu, get_prices_menu, get_faq_menu, get_back_button
from utils.database import init_db, get_user_orders
from utils.prices import format_prices_text, import_prices_data
from handlers.admin_panel.handlers import show_spam_candidates, mark_as_spam_callback

WORKSHOP_INFO = {
    "name": "Швейная мастерская",
    "address": "г. Москва, ул. Маршала Федоренко д.12, 1 этаж",
    "phone": "+7 (968) 396-91-52",
    "whatsapp": "+7 (968) 396-91-52"
}

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

async def callback_service_category(update, context):
    await update.callback_query.answer()
    category = update.callback_query.data.removeprefix("service_")
    if category == "other":
        await update.callback_query.edit_message_text(text="❓ Опишите, какая услуга вам нужна.", reply_markup=get_back_button())
        return
    prices_text = format_prices_text(category)
    await update.callback_query.edit_message_text(text=prices_text or "Для этой категории цены пока не добавлены.", reply_markup=get_back_button(), parse_mode="Markdown" if prices_text else None)

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

async def log_all_updates(update: Update, context):
    if update.callback_query:
        logging.info(f"📥 CALLBACK: {update.callback_query.data} from user {update.effective_user.id}")


def main():
    global BOT_IS_RUNNING
    load_dotenv()
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    logger = logging.getLogger(__name__)

    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не установлен!")
        return

    port = int(os.getenv("PORT", 8080))
    start_health_server(port)

    # === 1. ПРИНУДИТЕЛЬНОЕ УДАЛЕНИЕ ВЕБХУКА ===
    try:
        logger.info("⏳ Очистка фантомного вебхука Telegram...")
        resp = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=false", timeout=10)
        logger.info(f"✅ Webhook успешно сброшен: {resp.text}")
    except Exception as e:
        logger.warning(f"⚠️ Ошибка очистки Webhook: {e}")

    # === 2. ИНИЦИАЛИЗАЦИЯ БД ===
    init_db()
    try: 
        import_prices_data()
    except Exception as e: 
        logger.error(f"❌ Ошибка импорта цен: {e}")

    # === 3. ЗАПУСК БОТА ===
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(TypeHandler(Update, log_all_updates), group=-1)

    app.add_handler(CallbackQueryHandler(callback_services, pattern="^services$"))
    app.add_handler(CallbackQueryHandler(callback_check_status, pattern="^check_status$"))
    app.add_handler(CallbackQueryHandler(callback_faq, pattern="^faq$"))
    app.add_handler(CallbackQueryHandler(callback_contacts, pattern="^contacts$"))
    app.add_handler(CallbackQueryHandler(callback_back, pattern="^back_menu$"))

    for cat in ["jacket", "leather", "curtains", "coat", "fur", "outerwear", "pants", "dress"]:
        app.add_handler(CallbackQueryHandler(globals()[f"callback_price_{cat}"], pattern=f"^price_{cat}$"))
    for sub in ["services", "prices", "timing", "location", "payment", "order", "other"]:
        app.add_handler(CallbackQueryHandler(globals()[f"callback_faq_{sub}"], pattern=f"^faq_{sub}$"))
    app.add_handler(CallbackQueryHandler(callback_service_category, pattern="^service_"))

    app.add_handler(CallbackQueryHandler(admin.open_web_admin, pattern="^open_web_admin$"))
    app.add_handler(CallbackQueryHandler(admin.admin_view_order, pattern="^admin_view_"))
    app.add_handler(CallbackQueryHandler(admin.change_order_status, pattern="^status_"))
    app.add_handler(CallbackQueryHandler(admin.contact_client, pattern="^contact_client_"))
    app.add_handler(CallbackQueryHandler(mark_as_spam_callback, pattern="^mark_spam_"))
    app.add_handler(CallbackQueryHandler(admin.admin_menu_callback, pattern="^admin_"))

    order_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(order_start, pattern="^new_order$"), CommandHandler("order", order_start)],
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

    app.add_handler(CommandHandler("start", commands.start))
    app.add_handler(CommandHandler("menu", commands.start))
    app.add_handler(CommandHandler("help", commands.help_command))
    app.add_handler(CommandHandler("faq", commands.faq_command))
    app.add_handler(CommandHandler("status", commands.status_command))
    app.add_handler(CommandHandler("services", commands.services_command))
    app.add_handler(CommandHandler("contact", commands.contact_command))
    
    from handlers.admin import (
        admin_orders as admin_orders_list, admin_stats as admin_stats_info, 
        admin_users as admin_users_list, admin_spam as admin_spam_logs, 
        broadcast_start as admin_broadcast_start, admin_panel_command as admin_panel_cmd
    )
    app.add_handler(CommandHandler("admin", admin_panel_cmd))
    app.add_handler(CommandHandler("stats", admin_stats_info))
    app.add_handler(CommandHandler("orders", admin_orders_list))
    app.add_handler(CommandHandler("users", admin_users_list))
    app.add_handler(CommandHandler("spam", admin_spam_logs))
    app.add_handler(CommandHandler("broadcast", admin_broadcast_start))

    admin_btn_pattern = filters.Regex("^(📋 Сегодня в работе|⏳ Приняты, ждут|✅ Готовы к выдаче|📊 Все заказы|📈 Статистика|👥 Пользователи|📢 Рассылка)$")
    app.add_handler(MessageHandler(filters.TEXT & admin_btn_pattern, admin.admin_menu_callback))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^❌ Удалить спам$"), show_spam_candidates))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^◀️ Выйти$"), commands.start))

    async def admin_search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        from handlers.admin_orders import handle_search_input
        if update.effective_user and admin.is_user_admin(update.effective_user.id):
            if context.user_data.get("search_mode"):
                if await handle_search_input(update, context): 
                    return
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, admin_search_handler), group=2)

    from handlers.admin_orders import orders_callback_handler
    app.add_handler(CallbackQueryHandler(orders_callback_handler, pattern="^olist_"))
    app.add_handler(CallbackQueryHandler(orders_callback_handler, pattern="^odetail_"))
    app.add_handler(CallbackQueryHandler(orders_callback_handler, pattern="^ostatus_"))
    app.add_handler(CallbackQueryHandler(orders_callback_handler, pattern="^odelete_"))
    app.add_handler(CallbackQueryHandler(orders_callback_handler, pattern="^osearch"))
    app.add_handler(CallbackQueryHandler(orders_callback_handler, pattern="^orders_page_info$"))
    app.add_handler(CallbackQueryHandler(orders_callback_handler, pattern="^skip_"))

    app.add_handler(CallbackQueryHandler(messages.handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages.handle_message))

    async def post_init(application):
        try:
            logger.info("⏳ Настройка команд меню...")
            await application.bot.set_my_commands([
                BotCommand("start", "🏠 Главное меню"),
                BotCommand("order", "➕ Оформить заказ"),
                BotCommand("services", "📋 Услуги и цены"),
                BotCommand("contact", "📞 Контакты"),
                BotCommand("help", "❓ Справка"),
            ])
            await application.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
            logger.info("✅ Команды меню успешно настроены!")
        except Exception as e:
            logger.error(f"❌ Ошибка при настройке меню: {e}")
        
        global BOT_IS_RUNNING
        BOT_IS_RUNNING = True
        logger.info("🤖 БОТ УСПЕШНО ЗАПУЩЕН И ГОТОВ ПРИНИМАТЬ СООБЩЕНИЯ!")

    app.post_init = post_init

    async def error_handler(update, context):
        logger.error(f"❌ Ошибка при обработке обновления: {context.error}", exc_info=True)

    app.add_error_handler(error_handler)
    
    logger.info("⏳ Включение Polling...")
    # Здесь специально убран drop_pending_updates, чтобы бот не "глотал" ваши нажатия
    app.run_polling(allowed_updates=Update.ALL_TYPES)

def run_with_restart():
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.info("⏳ Запуск скрипта...")
    
    while True:
        try:
            main()
            break
        except KeyboardInterrupt:
            logger.info("Остановка бота вручную.")
            break
        except Exception as e:
            logger.error(f"🔴 Критическая ошибка бота: {e}", exc_info=True)
            logger.info("⏳ Перезапуск через 10 секунд...")
            time.sleep(10)

if __name__ == '__main__':
    run_with_restart()
