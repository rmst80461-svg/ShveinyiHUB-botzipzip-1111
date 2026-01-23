#!/usr/bin/env python3
"""
Запуск бота через Webhook (вместо polling)

Переменные окружения:
- BOT_TOKEN: токен бота
- WEBHOOK_URL: публичный URL вашего сервера (например: https://your-domain.bothost.ru)
- WEBHOOK_SECRET: секретный токен для проверки запросов (опционально)
- PORT: порт веб-сервера (по умолчанию 5000)

Использование:
1. Установите WEBHOOK_URL в переменные окружения
2. Запустите: python run_webhook.py
"""

import os
import sys
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv(override=True)

from flask import Flask, request, jsonify
from telegram import Update, MenuButtonCommands, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters
)

from handlers import commands, messages, admin
from handlers.commands import faq_command, status_command
from handlers.orders import (
    order_start, select_service, receive_photo, skip_photo,
    enter_description, skip_description, enter_name, enter_phone,
    confirm_order, cancel_order, use_tg_name, skip_phone as skip_phone_handler,
    handle_order_status_change, SELECT_SERVICE, SEND_PHOTO, ENTER_DESCRIPTION,
    ENTER_NAME, ENTER_PHONE, CONFIRM_ORDER
)
from handlers.reviews import get_review_conversation_handler
from keyboards import get_main_menu, get_admin_main_menu
from utils.database import init_db
from utils.prices import import_prices_data
from handlers.admin_panel.handlers import (
    set_admin_commands, show_admin_stats, show_spam_candidates, mark_as_spam_callback
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
PORT = int(os.getenv("PORT", 5000))

try:
    from webapp.app import app
except ImportError:
    app = Flask(__name__)
    logger.warning("webapp.app not found, using minimal Flask app")

application = None


def get_admin_ids():
    """Получить список ID администраторов"""
    admin_ids_str = os.getenv("ADMIN_IDS", "")
    admin_id_str = os.getenv("ADMIN_ID", "")
    
    ids = set()
    for s in [admin_ids_str, admin_id_str]:
        for part in s.split(","):
            part = part.strip()
            if part.isdigit():
                ids.add(int(part))
    return ids


def is_admin(user_id):
    return user_id in get_admin_ids()


async def start_command(update, context):
    user = update.effective_user
    if is_admin(user.id):
        await update.message.reply_text(
            f"👋 Привет, администратор!\n\n"
            "Выберите действие:",
            reply_markup=get_admin_main_menu()
        )
    else:
        await update.message.reply_text(
            f"👋 Добро пожаловать в *Швейный HUB*!\n\n"
            "🧵 Мы занимаемся ремонтом и пошивом одежды.\n"
            "Выберите действие:",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )


def setup_handlers(app_bot):
    """Настройка всех обработчиков бота"""
    
    order_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(order_start, pattern="^new_order$"),
            CallbackQueryHandler(order_start, pattern="^order_category_"),
        ],
        states={
            SELECT_SERVICE: [
                CallbackQueryHandler(select_service, pattern="^order_category_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_service),
            ],
            SEND_PHOTO: [
                MessageHandler(filters.PHOTO, receive_photo),
                CallbackQueryHandler(skip_photo, pattern="^skip_photo$"),
            ],
            ENTER_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_description),
                CallbackQueryHandler(skip_description, pattern="^skip_description$"),
            ],
            ENTER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name),
                CallbackQueryHandler(use_tg_name, pattern="^use_tg_name$"),
            ],
            ENTER_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_phone),
                MessageHandler(filters.CONTACT, enter_phone),
                CallbackQueryHandler(skip_phone_handler, pattern="^skip_phone$"),
            ],
            CONFIRM_ORDER: [
                CallbackQueryHandler(confirm_order, pattern="^confirm_order$"),
                CallbackQueryHandler(cancel_order, pattern="^cancel_order$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_order, pattern="^cancel_order$"),
            CommandHandler("cancel", cancel_order),
        ],
        per_message=False,
        per_chat=True,
        per_user=True,
    )
    app_bot.add_handler(order_conv)
    
    review_conv = get_review_conversation_handler()
    app_bot.add_handler(review_conv)
    
    app_bot.add_handler(CommandHandler("start", start_command))
    app_bot.add_handler(CommandHandler("help", commands.help_command))
    app_bot.add_handler(CommandHandler("faq", faq_command))
    app_bot.add_handler(CommandHandler("status", status_command))
    app_bot.add_handler(CommandHandler("contact", commands.contact_command))
    app_bot.add_handler(CommandHandler("admin", admin.admin_command))
    
    app_bot.add_handler(CallbackQueryHandler(admin.admin_callback, pattern="^admin_"))
    app_bot.add_handler(CallbackQueryHandler(show_admin_stats, pattern="^admin_stats$"))
    app_bot.add_handler(CallbackQueryHandler(show_spam_candidates, pattern="^spam_candidates$"))
    app_bot.add_handler(CallbackQueryHandler(mark_as_spam_callback, pattern="^mark_spam_"))
    
    app_bot.add_handler(CallbackQueryHandler(handle_order_status_change, pattern="^admin_open_"))
    
    app_bot.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, messages.handle_message)
    )
    
    async def error_handler(update, context):
        logger.error(f"Exception: {context.error}")
        try:
            admin_ids = get_admin_ids()
            if admin_ids:
                admin_id = list(admin_ids)[0]
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"⚠️ *Ошибка:*\n`{str(context.error)[:200]}`",
                    parse_mode="Markdown"
                )
        except:
            pass
    
    app_bot.add_error_handler(error_handler)


async def setup_webhook():
    """Настройка webhook"""
    global application
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return None
    
    if not WEBHOOK_URL:
        logger.error("WEBHOOK_URL not set! Example: https://your-domain.bothost.ru")
        return None
    
    application = Application.builder().token(BOT_TOKEN).build()
    setup_handlers(application)
    
    await application.initialize()
    
    webhook_url = f"{WEBHOOK_URL.rstrip('/')}/webhook/{BOT_TOKEN}"
    
    await application.bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None,
        drop_pending_updates=True
    )
    
    logger.info(f"Webhook установлен: {webhook_url}")
    
    return application


@app.route(f"/webhook/<token>", methods=["POST"])
def webhook_handler(token):
    """Обработчик webhook запросов от Telegram"""
    global application
    
    if token != BOT_TOKEN:
        logger.warning("Invalid token in webhook request")
        return jsonify({"error": "Invalid token"}), 403
    
    if WEBHOOK_SECRET:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if secret != WEBHOOK_SECRET:
            logger.warning("Invalid secret token")
            return jsonify({"error": "Invalid secret"}), 403
    
    if application is None:
        logger.error("Application not initialized")
        return jsonify({"error": "Not ready"}), 503
    
    try:
        update = Update.de_json(request.get_json(), application.bot)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(application.process_update(update))
        loop.close()
        
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/webhook/status", methods=["GET"])
def webhook_status():
    """Проверка статуса webhook"""
    return jsonify({
        "status": "running",
        "webhook_url": WEBHOOK_URL,
        "bot_ready": application is not None
    })


def run_webhook_server():
    """Запуск сервера с webhook"""
    
    init_db()
    import_prices_data()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup_webhook())
    
    logger.info(f"🚀 Запуск webhook сервера на порту {PORT}")
    logger.info(f"📡 Webhook URL: {WEBHOOK_URL}/webhook/{BOT_TOKEN[:10]}...")
    
    app.run(host="0.0.0.0", port=PORT, debug=False)


if __name__ == "__main__":
    run_webhook_server()
