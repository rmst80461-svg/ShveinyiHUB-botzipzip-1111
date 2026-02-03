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


async def handle_message(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текстовых сообщений от пользователей"""
    try:
        if not update.message or not update.message.text:
            await handle_non_text_message(update, context)
            return

        user = update.effective_user
        user_id = user.id
        text = update.message.text.strip()

        # Проверяем режим администратора (например, для рассылки)
        if await handle_admin_mode(update, context, user_id, text):
            return

        # Обработка ввода срока готовности (для админов)
        from handlers.admin_orders import handle_ready_date_input
        if await handle_ready_date_input(update, context):
            return

        # Исключаем любых администраторов из обработки AI (GigaChat)
        if is_user_admin(user_id):
            # Проверяем кнопки админ-меню (Reply Keyboard)
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
                    "◀️ Выйти": lambda u, c: u.message.reply_text("Вы вышли из админ-меню", reply_markup=get_main_menu())
                }
                
                handler = handlers_map.get(text)
                if handler:
                    # Устанавливаем фильтр
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
            
            # Если это не кнопка, просто игнорируем (не шлем в AI)
            return

        # Добавляем/обновляем пользователя в базе
        add_user(user_id=user_id,
                 username=user.username,
                 first_name=user.first_name,
                 last_name=user.last_name)

        # Проверяем, не заблокирован ли пользователь
        if is_user_blocked(user_id):
            logger.warning(
                f"Заблокированный пользователь {user_id} пытался отправить сообщение"
            )
            await update.message.reply_text(
                "🚫 Ваш доступ к боту ограничен. Пожалуйста, свяжитесь с администратором."
            )
            return

        # Проверяем на спам
        is_spam, spam_reason = anti_spam.is_spam(user_id, text)
        if is_spam:
            logger.warning(f"Спам от {user_id}: {spam_reason}")
            await update.message.reply_text(
                f"⚠️ {spam_reason}\n\nПожалуйста, подождите немного перед следующим сообщением.",
                reply_markup=get_main_menu())
            return

        # Ограничиваем длину сообщения для AI
        if len(text) > MAX_MESSAGE_LENGTH:
            await update.message.reply_text(
                f"📝 Ваше сообщение слишком длинное ({len(text)} символов). "
                f"Пожалуйста, сократите его до {MAX_MESSAGE_LENGTH} символов.")
            return

        # Логируем полученное сообщение
        user_info = get_user_info(user_id)
        username_display = f"@{user_info.username}" if user_info and user_info.username else user_info.first_name if user_info else f"Пользователь {user_id}"
        logger.info(
            f"Сообщение от {username_display} (ID: {user_id}): {text[:100]}..."
        )

        # Показываем индикатор "печатает"
        try:
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        except Exception as e:
            logger.warning(f"Не удалось отправить ChatAction: {e}")

        # Получаем ответ от AI
        try:
            # Проверка на запрос отзыва
            review_keywords = ['отзыв', 'отзывы', 'как оставить отзыв', 'где оставить отзыв', 'написать отзыв', 'оставить отзыв', 'хочу оставить отзыв']
            if any(keyword in text.lower() for keyword in review_keywords):
                response = "Будем очень благодарны за ваш отзыв! Вы можете оставить его на Яндекс Картах по ссылке: https://yandex.ru/maps/org/shveynyy_hub/204285863268/"
                keyboard = get_ai_response_keyboard()
            else:
                response, needs_human = await get_ai_response(text, user_id)
                # Формируем клавиатуру ответа
                keyboard = get_ai_response_keyboard()

            # Отправляем ответ (без parse_mode чтобы избежать ошибок парсинга)
            try:
                await update.message.reply_text(
                    f"💭 {response}",
                    reply_markup=keyboard
                )
            except Exception as send_err:
                logger.warning(f"Ошибка отправки: {send_err}, пробуем без форматирования")
                await update.message.reply_text(
                    f"💭 {response}",
                    reply_markup=keyboard
                )

            # Логируем успешный ответ
            logger.info(f"AI ответил пользователю {user_id}")

        except Exception as e:
            logger.error(f"Ошибка при получении ответа от AI: {e}")
            await update.message.reply_text(
                "🤖 Извините, у меня возникли технические трудности. "
                "Пожалуйста, попробуйте позже или свяжитесь с нами напрямую:\n\n"
                "📞 +7 (968) 396-91-52\n"
                "📍 г. Москва, ул. Маршала Федоренко д.12, ТЦ \"Бусиново\"",
                reply_markup=get_main_menu())

    except Exception as e:
        logger.error(f"Критическая ошибка в обработке сообщения: {e}")
        await update.message.reply_text(
            "😔 Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже.")


async def handle_admin_mode(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            user_id: int, text: str) -> bool:
    """Обработка режима администратора (например, для рассылки)"""
    try:
        if not is_user_admin(user_id):
            return False

        # Проверяем специальные административные команды
        if text.startswith('/'):
            # Пропускаем команды для обработки в других хендлерах
            return False

        # Проверяем режим рассылки — обрабатывается в main.py через broadcast_preview
        if context.user_data.get('broadcast_mode'):
            return True  # Уже обработано в main.py, не вызываем GigaChat

        # Проверяем режим ответа пользователю
        if context.user_data.get('reply_mode'):
            target_user_id = context.user_data.get('reply_to_user')
            if target_user_id:
                try:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"📨 Ответ от администратора:\n\n{text}")
                    await update.message.reply_text(
                        f"✅ Ответ отправлен пользователю {target_user_id}")
                    context.user_data.pop('reply_mode', None)
                    context.user_data.pop('reply_to_user', None)
                except Exception as e:
                    logger.error(
                        f"Не удалось отправить ответ пользователю: {e}")
                    await update.message.reply_text(
                        f"❌ Не удалось отправить ответ: {e}")
                return True

        # Другие режимы администратора можно добавить здесь
        return False

    except Exception as e:
        logger.error(f"Ошибка в обработке режима администратора: {e}")
        return False


async def handle_non_text_message(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка не текстовых сообщений (фото, документы и т.д.)"""
    try:
        user_id = update.effective_user.id
        message = update.message

        if message.photo:
            await message.reply_text(
                "📸 Спасибо за фото! К сожалению, я пока не умею анализировать изображения.\n\n"
                "Пожалуйста, опишите вашу проблему текстом или свяжитесь с нами:\n"
                "📞 +7 (968) 396-91-52")

        elif message.document:
            await message.reply_text(
                "📎 Получен документ. Для обработки технических файлов (выкройки, схемы) "
                "пожалуйста, свяжитесь напрямую с мастером:\n\n"
                "📞 +7 (968) 396-91-52")

        elif message.voice or message.audio:
            await message.reply_text(
                "🎤 Я получил ваше голосовое сообщение. К сожалению, сейчас я работаю только с текстом.\n\n"
                "Пожалуйста, напишите ваш вопрос текстом или позвоните нам:\n"
                "📞 +7 (968) 396-91-52")

        elif message.sticker:
            # Можно просто проигнорировать или ответить шуткой
            if update.effective_user.is_bot:
                return
            await message.reply_text("😊 Спасибо за стикер!")

        elif message.contact or message.location:
            await message.reply_text(
                "📍 Спасибо за контактные данные! Я сохраню их для связи.\n\n"
                "Чем еще могу помочь?",
                reply_markup=get_main_menu())

    except Exception as e:
        logger.error(f"Ошибка при обработке не текстового сообщения: {e}")
        await update.message.reply_text(
            "Извините, у меня возникли проблемы с обработкой вашего сообщения. "
            "Попробуйте отправить текстовое сообщение.")


async def handle_callback_query(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка callback-запросов от inline-кнопок"""
    try:
        query = update.callback_query
        await query.answer()

        user_id = update.effective_user.id
        data = query.data

        logger.info(f"Callback от пользователя {user_id}: {data}")

        # Обработка различных callback-действий
        if data == 'contact_human':
            await query.edit_message_text(
                "👩‍💼 Хотите поговорить с живым специалистом?\n\n"
                "📞 Позвоните нам: +7 (968) 396-91-52\n"
                "📍 Приходите: г. Москва, ул. Маршала Федоренко д.12, ТЦ \"Бусиново\"\n\n"
                "Часы работы: Пн-Чт: 10:00-19:50, Пт: 10:00-19:00, Сб: 10:00-17:00, Вс: выходной",
                parse_mode="Markdown")

        elif data == 'rate_response':
            await query.edit_message_text(
                "⭐ Спасибо за оценку! Ваше мнение очень важно для нас.\n\n"
                "Можете оставить более подробный отзыв через команду /review",
                parse_mode="Markdown")

        elif data == 'new_question':
            await query.edit_message_text(
                "❓ Задайте ваш новый вопрос:\n\n"
                "Я постараюсь помочь максимально подробно!")

        elif data.startswith('client_already_brought_'):
            order_id = int(data.split('_')[-1])
            
            # Исправлено: используем сессию и закрываем её
            session = get_session()
            try:
                order = get_order(order_id, session)
                if order and order.user_id == user_id:
                    fid = format_order_id(int(order.id), order.created_at)
                    await query.edit_message_text(
                        f"✅ Спасибо! Я передала информацию мастеру. Заказ {fid} скоро будет обработан. 🪡"
                    )
                    # Уведомляем админа
                    admin_msg = (
                        f"🔔 *Внимание!* Клиент утверждает, что уже сдал вещь:\n\n"
                        f"📦 Заказ: *{fid}*\n"
                        f"👤 Клиент: {order.client_name or '—'}\n"
                        f"📅 Был создан: {order.created_at.strftime('%d.%m %H:%M')}\n\n"
                        f"Пожалуйста, проверьте и отметьте его как «Принят»."
                    )
                    for admin_id in get_admin_ids():
                        try:
                            await context.bot.send_message(chat_id=admin_id, text=admin_msg, parse_mode="Markdown")
                        except Exception as admin_err:
                            logger.error(f"Не удалось отправить уведомление админу {admin_id}: {admin_err}")
                else:
                    await query.edit_message_text("⚠️ Заказ не найден.")
            finally:
                session.close()

        elif data.startswith('client_bring_later_'):
            order_id = int(data.split('_')[-1])
            session = get_session()
            try:
                from utils.database import Order
                order = session.query(Order).filter(Order.id == order_id).first()
                if order:
                    # Сбрасываем флаг напоминания
                    order.client_reminded = False
                    order.last_reminder_date = datetime.utcnow()
                    session.commit()
                    
                    await query.edit_message_text(
                        "👌 Хорошо, мы забронировали место за вами. Ждем вас в удобное время! 🪡"
                    )
                else:
                    await query.edit_message_text("⚠️ Заказ не найден.")
            except Exception as e:
                logger.error(f"Ошибка при обработке 'принесу позже': {e}")
                await query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")
            finally:
                session.close()

        elif data.startswith('client_cancel_order_'):
            order_id = int(data.split('_')[-1])
            session = get_session()
            try:
                order = get_order(order_id, session)
                if order and order.user_id == user_id:
                    if delete_order(order_id, session):
                        await query.edit_message_text(
                            "✅ Ваш заказ успешно отменен и удален из базы. Ждем вас снова! 🪡"
                        )
                    else:
                        await query.edit_message_text("❌ Произошла ошибка при отмене заказа. Попробуйте позже.")
                else:
                    await query.edit_message_text("⚠️ Заказ не найден или у вас нет прав на его отмену.")
            finally:
                session.close()

        elif data.startswith('admin_'):
            # Административные действия
            if is_user_admin(user_id):
                await handle_admin_callback(query, context, data)
            else:
                await query.edit_message_text(
                    "❌ У вас нет прав для этого действия.")

    except BadRequest as e:
        if "Message is not modified" in str(e):
            # Игнорируем ошибку, если сообщение не изменилось
            pass
        else:
            logger.error(f"BadRequest в callback: {e}")
    except Exception as e:
        logger.error(f"Ошибка в обработке callback-запроса: {e}")
        try:
            await query.edit_message_text(
                "⚠️ Произошла ошибка. Попробуйте еще раз.")
        except:
            pass


async def handle_admin_callback(query, context, data: str):
    """Обработка административных callback-запросов"""
    try:
        if data == 'admin_broadcast':
            context.user_data['broadcast_mode'] = True
            await query.edit_message_text(
                "✉️ *Режим рассылки активирован*\n\n"
                "Введите сообщение для рассылки всем пользователей.\n\n"
                "Для отмены отправьте /cancel",
                parse_mode="Markdown")

        elif data == 'admin_stats':
            from utils.database import get_statistics
            stats = get_statistics()

            stats_text = ("📊 *Статистика бота:*\n\n"
                          f"👥 Пользователей: {stats.get('total_users', 0)}\n"
                          f"📦 Заказов: {stats.get('total_orders', 0)}\n"
                          f"🆕 Новых: {stats.get('new_orders', 0)}\n"
                          f"🔄 В работе: {stats.get('in_progress', 0)}\n"
                          f"✅ Готовых: {stats.get('completed', 0)}\n"
                          f"📤 Выданных: {stats.get('issued', 0)}\n"
                          f"🚫 Заблокировано: {stats.get('blocked_users', 0)}")
            await query.edit_message_text(stats_text, parse_mode="Markdown")

        elif data == 'admin_orders':
            await query.edit_message_text(
                "📦 *Управление заказами*\n\n"
                "Выберите действие:\n"
                "• Просмотр новых заказов\n"
                "• Заказы в работе\n"
                "• Готовые заказы\n"
                "• Поиск заказа\n\n"
                "Используйте веб-панель для полного управления.",
                parse_mode="Markdown")

        elif data == 'admin_back_menu':
            await query.edit_message_text(
                "🛠 *Панель администратора*\n\n"
                "Выберите раздел для управления:",
                reply_markup=get_admin_main_menu(),
                parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка в обработке административного callback: {e}")
        await query.edit_message_text(
            "❌ Произошла ошибка при выполнении действия.")


async def handle_inline_query(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка inline-запросов (если бот поддерживает inline режим)"""
    try:
        query = update.inline_query.query

        if not query or len(query.strip()) < 2:
            return

        from telegram import InlineQueryResultArticle, InputTextMessageContent

        results = [
            InlineQueryResultArticle(
                id='1',
                title="Швейный HUB",
                description="Нажмите чтобы открыть бота",
                input_message_content=InputTextMessageContent(
                    "🔍 Для использования бота перейдите в чат с @ваш_бот"))
        ]

        await update.inline_query.answer(results, cache_time=300)

    except Exception as e:
        logger.error(f"Ошибка в обработке inline-запроса: {e}")
