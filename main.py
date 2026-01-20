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
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

load_dotenv()

from telegram import Update, MenuButtonCommands, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, filters, TypeHandler

from handlers import commands, messages, admin
from handlers.commands import faq_command, status_command
from handlers.orders import order_start, select_service, receive_photo, skip_photo, enter_name, enter_phone, confirm_order, cancel_order, use_tg_name, skip_phone as skip_phone_handler, handle_order_status_change, SELECT_SERVICE, SEND_PHOTO, ENTER_NAME, ENTER_PHONE, CONFIRM_ORDER
from handlers.reviews import get_review_conversation_handler, request_review
from keyboards import get_main_menu, get_prices_menu, get_faq_menu, get_back_button, get_admin_main_menu
from utils.database import init_db, get_user_orders, get_orders_pending_feedback, mark_feedback_requested
from utils.prices import format_prices_text, import_prices_data

_lock = None
logger = logging.getLogger(__name__)


def create_lock():
    global _lock
    if os.getenv("DISABLE_INSTANCE_LOCK", "0") == "1":
        logger.info("Instance lock disabled")
        return None
    lock_port = int(os.getenv("LOCK_PORT", "48975"))
    lockfile_path = os.getenv("LOCKFILE_PATH", "/tmp/poslednya_v1.lock")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", lock_port))
        s.listen(1)
        s.setblocking(False)
        _lock = {"type": "socket", "obj": s, "port": lock_port}
        logging.info(f"Instance locked on 127.0.0.1:{lock_port}")
        return _lock
    except OSError:
        pass
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(lockfile_path, flags, 0o644)
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        _lock = {"type": "file", "path": lockfile_path}
        logging.info(f"Instance locked via pidfile {lockfile_path}")
        return _lock
    except FileExistsError:
        try:
            with open(lockfile_path, "r") as f:
                existing_pid = int(f.read().strip() or 0)
        except:
            existing_pid = None
        if existing_pid:
            try:
                os.kill(existing_pid, 0)
                print(f"Another instance running (pid {existing_pid})")
                sys.exit(1)
            except:
                try:
                    os.remove(lockfile_path)
                    fd = os.open(lockfile_path,
                                 os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                    with os.fdopen(fd, "w") as f:
                        f.write(str(os.getpid()))
                    _lock = {"type": "file", "path": lockfile_path}
                    return _lock
                except:
                    sys.exit(1)


def release_lock():
    global _lock
    try:
        if not _lock:
            return
        if isinstance(_lock, dict) and _lock.get("type") == "socket":
            _lock["obj"].close()
        elif isinstance(_lock, dict) and _lock.get("type") == "file":
            path = _lock.get("path")
            if path and os.path.exists(path):
                os.remove(path)
    except Exception:
        pass
    finally:
        _lock = None


atexit.register(release_lock)

BOT_START_TIME = time.time()
LAST_UPDATE_TIME = time.time()
BOT_IS_RUNNING = False


class HealthHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        return

    def do_GET(self):
        global LAST_UPDATE_TIME, BOT_IS_RUNNING
        if self.path in ("/", "/health", "/status"):
            uptime = int(time.time() - BOT_START_TIME)
            response = {
                "status": "alive" if BOT_IS_RUNNING else "starting",
                "uptime_seconds": uptime,
                "last_update": LAST_UPDATE_TIME,
                "message": "Бот работает 24/7!"
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()


def start_health_server(port=8080):
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logging.info(f"Health check на порту {port}")
    except Exception as e:
        logging.warning(f"Health server: {e}")


WORKSHOP_INFO = {
    "name": "Швейная мастерская",
    "address":
    "г. Москва, (МЦД/м. Ховрино) ул. Маршала Федоренко д.12, , ТЦ \"Бусиново\", 1 этаж",
    "phone": "+7 (968) 396-91-52",
    "whatsapp": "+7 (968) 396-91-52"
}


async def callback_services(update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        text="💰 Выберите категорию услуг:", reply_markup=get_prices_menu())


async def callback_price_category(update, context, category):
    await update.callback_query.answer()
    prices_text = format_prices_text(category)
    if prices_text:
        await update.callback_query.edit_message_text(
            text=prices_text,
            reply_markup=get_prices_menu(),
            parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(
            text="Цены не найдены", reply_markup=get_prices_menu())


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
    await update.callback_query.answer()
    user_id = update.effective_user.id
    orders = get_user_orders(user_id)
    if not orders:
        text = "🔍 У вас нет заказов.\n\nПозвоните нам: " + WORKSHOP_INFO[
            "phone"]
    else:
        from handlers.orders import format_order_id
        text = "🔍 *Ваши заказы:*\n\n"
        status_map = {
            "new": "🆕 Новый",
            "in_progress": "🔄 В работе",
            "completed": "✅ Готов",
            "issued": "📤 Выдан",
            "cancelled": "❌ Отменён"
        }
        for order in orders[:5]:
            status = status_map.get(str(order.status), str(order.status))
            desc = str(order.description) if order.description else "Услуга"
            formatted_id = format_order_id(int(order.id), order.created_at)
            text += f"*{formatted_id}* - {status}\n{desc}\n\n"
    await update.callback_query.edit_message_text(
        text=text, reply_markup=get_back_button(), parse_mode="Markdown")


async def callback_faq(update, context):
    await update.callback_query.answer()
    try:
        await update.callback_query.edit_message_text(
            text="❓ Выберите интересующий вопрос:",
            reply_markup=get_faq_menu())
    except:
        pass


async def callback_faq_services(update, context):
    await update.callback_query.answer()
    text = "📋 *Какие услуги мы выполняем:*\n\n✂️ Подшив и укорачивание\n🔄 Замена молний и пуговиц\n📐 Ушивание и расширение\n🧵 Штопка и реставрация\n🧥 Ремонт верхней одежды\n🎒 Ремонт кожаных изделий\n🐾 Ремонт шуб и дублёнок\n🪟 Пошив штор"
    try:
        await update.callback_query.edit_message_text(
            text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")
    except:
        pass


async def callback_faq_prices(update, context):
    await update.callback_query.answer()
    text = "💰 *Примерные цены:*\n\n👖 Укоротить джинсы — от 500р\n👖 С родным краем — от 900р\n👗 Укоротить юбку — от 800р\n🧥 Замена молнии — от 2000р\n🧥 Замена подкладки — от 3500р\n📐 Подгон по фигуре — от 1500р"
    try:
        await update.callback_query.edit_message_text(
            text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")
    except:
        pass


async def callback_faq_timing(update, context):
    await update.callback_query.answer()
    text = "⏰ *Сроки:*\n\n⚡ Простой ремонт — 1-2 дня\n📦 Сложный ремонт — 3-7 дней\n🚀 Срочный ремонт — 24 часа (+50%)"
    try:
        await update.callback_query.edit_message_text(
            text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")
    except:
        pass


async def callback_faq_location(update, context):
    await update.callback_query.answer()
    text = f"📍 *Адрес:*\n{WORKSHOP_INFO['address']}\n\n⏰ *График:*\nПн-Чт: 10:00-19:50\nПт: 10:00-19:00\nСб: 10:00-17:00\nВс: выходной\n\n📞 {WORKSHOP_INFO['phone']}"
    try:
        await update.callback_query.edit_message_text(
            text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")
    except:
        pass


async def callback_faq_payment(update, context):
    await update.callback_query.answer()
    text = "💳 *Способы оплаты:*\n• Наличные\n• Перевод по номеру\n\n💵 *Предоплата:*\nНе требуется для обычного ремонта\n50% — для дорогой фурнитуры\n\n🛡️ *Гарантия:*\n30 дней на все виды!"
    try:
        await update.callback_query.edit_message_text(
            text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")
    except:
        pass


async def callback_faq_order(update, context):
    await update.callback_query.answer()
    text = "📝 *Как оформить:*\n\n1️⃣ Создать заказ\n2️⃣ Выберите услугу\n3️⃣ Фото вещи\n4️⃣ Имя и телефон\n5️⃣ Подтвердите\n\nМы свяжемся для уточнения!"
    try:
        await update.callback_query.edit_message_text(
            text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")
    except:
        pass


async def callback_faq_other(update, context):
    await update.callback_query.answer()
    text = f"❓ *Другой вопрос?*\n\nОпишите здесь в чате или позвоните: {WORKSHOP_INFO['phone']}"
    try:
        await update.callback_query.edit_message_text(
            text=text, reply_markup=get_faq_menu(), parse_mode="Markdown")
    except:
        pass


async def callback_contacts(update, context):
    await update.callback_query.answer()
    hours_text = "Пн-Чт: 10:00-19:50\nПт: 10:00-19:00\nСб: 10:00-17:00\nВс: выходной"
    await update.callback_query.edit_message_text(
        text=
        f"📍 *Наши контакты:*\n\n📍 *Адрес:*\n{WORKSHOP_INFO['address']}\n\n📞 *Телефон:*\n{WORKSHOP_INFO['phone']}\n\n💬 *WhatsApp:*\n{WORKSHOP_INFO['whatsapp']}\n\n⏰ *График:*\n{hours_text}",
        reply_markup=get_back_button(),
        parse_mode="Markdown")


async def callback_back(update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        text="✂️ *Швейный HUB — Главное меню*",
        reply_markup=get_main_menu(),
        parse_mode="Markdown")


async def callback_contact_master(update, context):
    await update.callback_query.answer()
    text = f"👩‍🔧 *Связаться с мастером*\n\n📞 *Позвоните:* {WORKSHOP_INFO['phone']}\n💬 *WhatsApp:* {WORKSHOP_INFO['whatsapp']}\n\n📍 *Адрес:*\n{WORKSHOP_INFO['address']}\n\n⏰ Пн-Чт: 10:00-19:50\nПт: 10:00-19:00\nСб: 10:00-17:00"
    await update.callback_query.edit_message_text(
        text=text, reply_markup=get_back_button(), parse_mode="Markdown")


LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "logo.jpg")


async def show_menu_with_logo(message, name):
    caption = f"✂️ *Швейный HUB*\n\nИголочка на связи! 🪡\nЧем могу помочь, {name}?"
    if os.path.exists(LOGO_PATH):
        with open(LOGO_PATH, "rb") as photo:
            await message.reply_photo(photo=photo,
                                      caption=caption,
                                      parse_mode="Markdown")
    else:
        await message.reply_text(caption, parse_mode="Markdown")
    await message.reply_text("✂️ *Швейный HUB — Главное меню*",
                             reply_markup=get_main_menu(),
                             parse_mode="Markdown")


async def order_command(update, context):
    await order_start(update, context)


async def services_command(update, context):
    await update.message.reply_text(text="💰 Выберите категорию услуг:",
                                    reply_markup=get_prices_menu())


async def contact_command(update, context):
    text = f"📍 *Контакты мастерской*\n\n🏠 *Адрес:* {WORKSHOP_INFO['address']}\n\n📞 *Телефон:* {WORKSHOP_INFO['phone']}\n💬 *WhatsApp:* {WORKSHOP_INFO['whatsapp']}\n\n⏰ *График:*\nПн-Чт: 10:00-19:50\nПт: 10:00-19:00\nСб: 10:00-17:00\nВс: выходной"
    await update.message.reply_text(text, parse_mode="Markdown")


async def menu_command(update, context):
    user = update.effective_user
    name = user.first_name or "друг"
    await show_menu_with_logo(update.message, name)


async def admin_panel_command(update, context):
    user_id = update.effective_user.id
    from handlers.admin import is_user_admin
    if not is_user_admin(user_id):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    text = "📋 *Админ-панель*\n\nВыберите раздел для управления:"
    await update.message.reply_text(text,
                                    reply_markup=get_admin_main_menu(),
                                    parse_mode="Markdown")


async def log_all_updates(update: Update, context):
    global LAST_UPDATE_TIME
    LAST_UPDATE_TIME = time.time()
    user_id = update.effective_user.id if update.effective_user else "unknown"
    if update.callback_query:
        logger.info(f"📥 CALLBACK: {update.callback_query.data} from {user_id}")
    elif update.message:
        text = update.message.text[:50] if update.message.text else "[no text]"
        logger.info(f"📥 MESSAGE: {text} from {user_id}")


create_lock()

BOT_TOKEN = os.getenv("BOT_TOKEN")
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    global BOT_IS_RUNNING

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не установлен!")
        return

    start_health_server(int(os.getenv("PORT", "8080")))

    init_db()
    try:
        import_prices_data()
    except Exception:
        logger.warning("Не удалось загрузить цены")
    logger.info("База данных инициализирована")

    BOT_IS_RUNNING = True

    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start", "🏠 Главное меню"),
            BotCommand("order", "➕ Оформить заказ"),
            BotCommand("faq", "❓ FAQ"),
            BotCommand("status", "🔍 Статус заказа"),
            BotCommand("services", "📋 Услуги и цены"),
            BotCommand("contact", "📞 Контакты"),
            BotCommand("help", "❓ Справка"),
        ])
        await application.bot.set_chat_menu_button(
            menu_button=MenuButtonCommands())
        logger.info("Кнопка меню настроена")

        async def periodic_review_check():
            await asyncio.sleep(60)
            while True:
                try:
                    orders = get_orders_pending_feedback()
                    for order in orders:
                        try:
                            user_id = int(
                                order.user_id) if order.user_id else 0
                            order_id = int(order.id) if order.id else 0
                            await request_review(application, user_id,
                                                 order_id)
                            mark_feedback_requested(order_id)
                            logger.info(
                                f"Review request sent for order {order_id}")
                        except Exception as e:
                            logger.error(f"Failed review request: {e}")
                except Exception as e:
                    logger.error(f"Error checking reviews: {e}")
                await asyncio.sleep(3600)

        try:
            application.create_task(periodic_review_check())
            logger.info("Фоновая задача для отзывов запущена")
        except Exception as e:
            logger.error(f"Не удалось запустить фоновую задачу: {e}")

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

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
                CallbackQueryHandler(skip_phone_handler,
                                     pattern="^skip_phone$"),
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
        per_message=False)
    app.add_handler(order_conversation)
    review_conversation = get_review_conversation_handler()
    app.add_handler(review_conversation)

    app.add_handler(CommandHandler("start", commands.start))
    app.add_handler(CommandHandler("help", commands.help_command))
    app.add_handler(CommandHandler("faq", faq_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("services", services_command))
    app.add_handler(CommandHandler("contact", contact_command))

    app.add_handler(CommandHandler("admin", admin_panel_command))
    app.add_handler(CommandHandler("stats", admin.admin_stats))
    app.add_handler(CommandHandler("orders", admin.admin_orders))
    app.add_handler(CommandHandler("neworders", admin.admin_new_orders))
    app.add_handler(CommandHandler("users", admin.admin_users))
    app.add_handler(CommandHandler("spam", admin.admin_spam))
    app.add_handler(CommandHandler("broadcast", admin.broadcast_start))
    app.add_handler(CommandHandler("setadmin", admin.set_admin_command))

    app.add_handler(
        CallbackQueryHandler(admin.admin_menu_callback, pattern="^admin_"))
    app.add_handler(
        CallbackQueryHandler(admin.open_web_admin, pattern="^open_web_admin$"))
    app.add_handler(
        CallbackQueryHandler(admin.admin_view_order, pattern="^admin_view_"))
    app.add_handler(
        CallbackQueryHandler(admin.change_order_status, pattern="^status_"))
    app.add_handler(
        CallbackQueryHandler(admin.contact_client, pattern="^contact_client_"))

    app.add_handler(
        CallbackQueryHandler(callback_services, pattern="^services$"))
    app.add_handler(
        CallbackQueryHandler(callback_check_status, pattern="^check_status$"))
    app.add_handler(CallbackQueryHandler(callback_faq, pattern="^faq$"))
    app.add_handler(
        CallbackQueryHandler(callback_contacts, pattern="^contacts$"))

    app.add_handler(
        CallbackQueryHandler(callback_price_jacket, pattern="^price_jacket$"))
    app.add_handler(
        CallbackQueryHandler(callback_price_leather,
                             pattern="^price_leather$"))
    app.add_handler(
        CallbackQueryHandler(callback_price_curtains,
                             pattern="^price_curtains$"))
    app.add_handler(
        CallbackQueryHandler(callback_price_coat, pattern="^price_coat$"))
    app.add_handler(
        CallbackQueryHandler(callback_price_fur, pattern="^price_fur$"))
    app.add_handler(
        CallbackQueryHandler(callback_price_outerwear,
                             pattern="^price_outerwear$"))
    app.add_handler(
        CallbackQueryHandler(callback_price_pants, pattern="^price_pants$"))
    app.add_handler(
        CallbackQueryHandler(callback_price_dress, pattern="^price_dress$"))

    app.add_handler(
        CallbackQueryHandler(callback_faq_services, pattern="^faq_services$"))
    app.add_handler(
        CallbackQueryHandler(callback_faq_prices, pattern="^faq_prices$"))
    app.add_handler(
        CallbackQueryHandler(callback_faq_timing, pattern="^faq_timing$"))
    app.add_handler(
        CallbackQueryHandler(callback_faq_location, pattern="^faq_location$"))
    app.add_handler(
        CallbackQueryHandler(callback_faq_payment, pattern="^faq_payment$"))
    app.add_handler(
        CallbackQueryHandler(callback_faq_order, pattern="^faq_order$"))
    app.add_handler(
        CallbackQueryHandler(callback_faq_other, pattern="^faq_other$"))

    app.add_handler(
        CallbackQueryHandler(handle_order_status_change,
                             pattern="^admin_open_"))
    app.add_handler(CallbackQueryHandler(callback_back, pattern="^back_menu$"))
    app.add_handler(
        CallbackQueryHandler(callback_contact_master,
                             pattern="^contact_master$"))
    app.add_handler(CommandHandler("menu", menu_command))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND,
                       messages.handle_message))

    async def error_handler(update, context):
        logger.error(f"Exception: {context.error}")
        try:
            admin_id = os.getenv("ADMIN_ID")
            if admin_id:
                await context.bot.send_message(
                    chat_id=int(admin_id),
                    text=f"⚠️ *Ошибка:*\n`{str(context.error)[:200]}`",
                    parse_mode="Markdown")
        except:
            pass

    app.add_error_handler(error_handler)

    logger.info("🤖 Бот запущен и готов к работе!")
    app.run_polling(drop_pending_updates=True)


def run_with_restart():
    logger.info("⏳ Ожидание 15 секунд...")
    time.sleep(15)

    max_retries = 10
    retry_count = 0

    while retry_count < max_retries:
        try:
            main()
            break
        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем")
            break
        except Exception as e:
            retry_count += 1
            logger.error(f"Критическая ошибка #{retry_count}: {e}")
            if retry_count < max_retries:
                wait_time = min(30, 5 * retry_count)
                logger.info(f"Перезапуск через {wait_time} сек...")
                time.sleep(wait_time)
            else:
                logger.critical("Достигнут лимит перезапусков.")


if __name__ == "__main__":
    run_with_restart()
