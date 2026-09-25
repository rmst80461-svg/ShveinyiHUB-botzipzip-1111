import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatAction
from telegram.error import BadRequest
from utils.gigachat_api import get_ai_response
from utils.anti_spam import anti_spam
from utils.database import add_user, is_user_blocked, get_user_info, get_order, get_session, delete_order
from keyboards import get_main_menu, get_ai_response_keyboard, get_admin_main_menu
from handlers.admin import is_user_admin, get_admin_ids
from handlers.orders import format_order_id

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 1000

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текстовых сообщений от пользователей (включая админ-кнопки)"""
    try:
        if not update.message or not update.message.text:
            await handle_non_text_message(update, context)
            return

        user = update.effective_user
        user_id = user.id
        text = update.message.text.strip()

        if await handle_admin_mode(update, context, user_id, text):
            return

        try:
            from handlers.admin_orders import handle_ready_date_input
            if await handle_ready_date_input(update, context):
                return
        except ImportError:
            pass

        # === 1. МАРШРУТИЗАЦИЯ АДМИН-КНОПОК ===
        if is_user_admin(user_id):
            admin_buttons = [
                "📋 Сегодня в работе", "⏳ Приняты, ждут", 
                "✅ Готовы к выдаче", "📊 Все заказы", 
                "📈 Статистика", "👥 Пользователи", 
                "📢 Рассылка", "❌ Удалить спам", "◀️ Выйти"
            ]
            
            if text in admin_buttons:
                from handlers.admin import admin_stats, admin_orders, admin_users, admin_spam, broadcast_start
                
                handlers_map = {
                    "📊 Все заказы": admin_orders,
                    "📈 Статистика": admin_stats,
                    "👥 Пользователи": admin_users,
                    "❌ Удалить спам": admin_spam,
                    "📢 Рассылка": broadcast_start,
                    "📋 Сегодня в работе": admin_orders,
                    "⏳ Приняты, ждут": admin_orders,
                    "✅ Готовы к выдаче": admin_orders,
                }
                
                if text == "◀️ Выйти":
                    await update.message.reply_text("Вы вышли из админ-меню.", reply_markup=get_main_menu())
                    return
                
                handler = handlers_map.get(text)
                if handler:
                    text_lower = text.lower()
                    if "все заказы" in text_lower or "📊" in text_lower:
                        context.user_data['admin_orders_filter'] = 'all'
                    elif "сегодня в работе" in text_lower:
                        context.user_data['admin_orders_filter'] = 'in_progress'
                    elif "приняты" in text_lower:
                        context.user_data['admin_orders_filter'] = 'accepted'
                    elif "готовы к выдаче" in text_lower:
                        context.user_data['admin_orders_filter'] = 'completed'
                        
                    await handler(update, context)
                return

        # === 2. ЛОГИКА ОБЫЧНОГО ПОЛЬЗОВАТЕЛЯ (БД, АНТИСПАМ, AI) ===
        add_user(user_id=user_id, username=user.username, first_name=user.first_name, last_name=user.last_name)

        if is_user_blocked(user_id):
            await update.message.reply_text("🚫 Ваш доступ к боту ограничен.")
            return

        is_spam, spam_reason = anti_spam.is_spam(user_id, text)
        if is_spam:
            await update.message.reply_text(f"⚠️ {spam_reason}\n\nПожалуйста, подождите немного.", reply_markup=get_main_menu())
            return

        if len(text) > MAX_MESSAGE_LENGTH:
            await update.message.reply_text(f"📝 Сообщение слишком длинное. Сократите до {MAX_MESSAGE_LENGTH} символов.")
            return

        try:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        except Exception:
            pass

        review_keywords = ['отзыв', 'отзывы', 'как оставить отзыв', 'где оставить отзыв', 'написать отзыв', 'оставить отзыв']
        if any(keyword in text.lower() for keyword in review_keywords):
            response = "Будем очень благодарны за ваш отзыв! Вы можете оставить его на Яндекс Картах: https://yandex.ru/maps/org/shveynyy_hub/1233246900/"
            keyboard = get_ai_response_keyboard()
        else:
            response, needs_human = await get_ai_response(text, user_id)
            keyboard = get_ai_response_keyboard()

        try:
            await update.message.reply_text(f"💭 {response}", reply_markup=keyboard)
        except Exception:
            await update.message.reply_text(f"💭 {response}", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        await update.message.reply_text("😔 Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже.")

async def handle_admin_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str) -> bool:
    try:
        if not is_user_admin(user_id):
            return False
        if text.startswith('/'):
            return False
        if context.user_data.get('broadcast_mode'):
            return True 
        if context.user_data.get('reply_mode'):
            target_user_id = context.user_data.get('reply_to_user')
            if target_user_id:
                try:
                    await context.bot.send_message(chat_id=target_user_id, text=f"📨 Ответ от администратора:\n\n{text}")
                    await update.message.reply_text(f"✅ Ответ отправлен пользователю {target_user_id}")
                    context.user_data.pop('reply_mode', None)
                    context.user_data.pop('reply_to_user', None)
                except Exception as e:
                    await update.message.reply_text(f"❌ Не удалось отправить ответ: {e}")
                return True
        return False
    except Exception:
        return False

async def handle_non_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        message = update.message
        if message.photo:
            await message.reply_text("📸 Спасибо за фото! К сожалению, я пока не умею анализировать изображения. Опишите проблему текстом или позвоните: +7 (968) 396-91-52")
        elif message.document:
            await message.reply_text("📎 Получен документ. Для обработки технических файлов свяжитесь напрямую с мастером: +7 (968) 396-91-52")
        elif message.voice or message.audio:
            await message.reply_text("🎤 Я получил голосовое сообщение. К сожалению, сейчас я работаю только с текстом. Напишите вопрос текстом или позвоните: +7 (968) 396-91-52")
        elif message.sticker:
            if update.effective_user.is_bot: return
            await message.reply_text("😊 Спасибо за стикер!")
        elif message.contact or message.location:
            await message.reply_text("📍 Контактные данные получены. Чем могу помочь?", reply_markup=get_main_menu())
    except Exception:
        await update.message.reply_text("Извините, у меня возникли проблемы с обработкой. Попробуйте отправить текстовое сообщение.")

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка специфичных callback-запросов, которые не пойманы в main.py"""
    try:
        query = update.callback_query
        user_id = update.effective_user.id
        data = query.data

        if data == 'contact_human':
            await query.answer()
            await query.edit_message_text(
                "👩‍💼 Хотите поговорить с живым специалистом?\n\n"
                "📞 Позвоните нам: +7 (968) 396-91-52\n"
                "📍 Приходите: г. Москва, ул. Маршала Федоренко д.12, ТЦ \"Бусиново\"\n\n"
                "Часы работы: Пн-Чт: 10:00-19:50, Пт: 10:00-19:00, Сб: 10:00-17:00, Вс: выходной",
                parse_mode="Markdown")

        elif data == 'rate_response':
            await query.answer()
            await query.edit_message_text("⭐ Спасибо за оценку! Ваше мнение очень важно для нас.\nМожете оставить отзыв через команду /review", parse_mode="Markdown")

        elif data == 'new_question':
            await query.answer()
            await query.edit_message_text("❓ Задайте ваш новый вопрос:\n\nЯ постараюсь помочь максимально подробно!")

        elif data.startswith('client_already_brought_'):
            await query.answer()
            order_id = int(data.split('_')[-1])
            session = get_session()
            try:
                order = get_order(order_id, session)
                if order and order.user_id == user_id:
                    fid = format_order_id(int(order.id), order.created_at)
                    await query.edit_message_text(f"✅ Спасибо! Заказ {fid} скоро будет обработан. 🪡")
                    admin_msg = f"🔔 *Внимание!* Клиент утверждает, что уже сдал вещь:\n\n📦 Заказ: *{fid}*\n👤 Клиент: {order.client_name}\nПожалуйста, проверьте."
                    for admin_id in get_admin_ids():
                        try: await context.bot.send_message(chat_id=admin_id, text=admin_msg, parse_mode="Markdown")
                        except Exception: pass
                else:
                    await query.edit_message_text("⚠️ Заказ не найден.")
            finally:
                session.close()

        elif data.startswith('client_bring_later_'):
            await query.answer()
            order_id = int(data.split('_')[-1])
            session = get_session()
            try:
                from utils.database import Order
                order = session.query(Order).filter(Order.id == order_id).first()
                if order:
                    order.client_reminded = False
                    order.last_reminder_date = datetime.utcnow()
                    session.commit()
                    await query.edit_message_text("👌 Хорошо, мы забронировали место за вами. Ждем вас в удобное время! 🪡")
                else:
                    await query.edit_message_text("⚠️ Заказ не найден.")
            finally:
                session.close()

        elif data.startswith('client_cancel_order_'):
            await query.answer()
            order_id = int(data.split('_')[-1])
            session = get_session()
            try:
                order = get_order(order_id, session)
                if order and order.user_id == user_id:
                    if delete_order(order_id, session):
                        await query.edit_message_text("✅ Ваш заказ успешно отменен и удален из базы. Ждем вас снова! 🪡")
                    else:
                        await query.edit_message_text("❌ Произошла ошибка при отмене заказа. Попробуйте позже.")
                else:
                    await query.edit_message_text("⚠️ Заказ не найден или у вас нет прав на его отмену.")
            finally:
                session.close()
                
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.error(f"BadRequest в callback: {e}")
    except Exception as e:
        logger.error(f"Ошибка в обработке callback-запроса: {e}")
