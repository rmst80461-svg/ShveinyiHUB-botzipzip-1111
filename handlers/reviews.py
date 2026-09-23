"""
Обработчик отзывов с 5-звездочной системой
"""

import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters

from utils.database import (create_review, has_review, get_order,
                            get_average_rating, get_user_reviews,
                            update_review_status, get_admins, get_review_stats,
                            get_recent_reviews)
from keyboards import get_main_menu, get_admin_main_menu
from handlers.admin import is_user_admin
from handlers.orders import format_order_id

logger = logging.getLogger(__name__)

# Константы для ConversationHandler
SELECT_RATING, ENTER_COMMENT, ADMIN_REVIEW_ACTION = range(3)

# Ограничения
MAX_COMMENT_LENGTH = 1000
MIN_COMMENT_LENGTH = 10

# URL для отзывов на Яндекс.Карты
YANDEX_REVIEWS_URL = "https://yandex.ru/maps/org/shveyny_hub/1233246900?si=qazrp3fnzwhkjgancr36aquutw"

# Паттерны для фильтрации нецензурной лексики (расширенный список)
PROFANITY_PATTERNS = [
    r'\b(бля|блять|блядь|блядина|ёб|еб|ебан|ебать|ебло|ебуч|пизд|пизда|пиздец|хуй|хуя|хуе|хуи|сука|сучк|мудак|мудил|дебил|долбо|залуп|говн|срать|сран|жоп|ёпт|нах)\w*',
    r'\b(fuck|shit|bitch|asshole|dick|pussy|cunt|motherfucker|damn|ass)\w*',
    r'(б+л+я+|п+и+з+д+|х+у+й+|е+б+а+|с+у+к+а+)',
    r'(f+u+c+k+|s+h+i+t+|b+i+t+c+h+)',
]

# Маппинг для декодирования leetspeak
LEETSPEAK_MAP = {
    '0': 'о',
    '@': 'а',
    '3': 'е',
    '1': 'и',
    '4': 'а',
    '5': 's',
    '$': 's',
    '6': 'б',
    '8': 'в',
    '!': 'i',
    '7': 't',
    '9': 'g',
    '&': 'и'
}


def normalize_text(text: str) -> str:
    """Нормализация текста: удаление обфускации и приведение к нижнему регистру"""
    if not text:
        return ""

    result = text.lower()

    # Замена leetspeak символов
    for char, replacement in LEETSPEAK_MAP.items():
        result = result.replace(char, replacement)

    # Удаление специальных символов
    result = re.sub(r'[._\-*#~^<>]+', '', result)

    # Удаление повторяющихся символов (более 3 раз)
    result = re.sub(r'(.)\1{3,}', r'\1\1', result)

    return result


def contains_profanity(text: str) -> bool:
    """Проверка текста на наличие нецензурной лексики"""
    if not text or len(text.strip()) == 0:
        return False

    if len(text) > MAX_COMMENT_LENGTH:
        return True

    normalized = normalize_text(text)

    for pattern in PROFANITY_PATTERNS:
        try:
            if re.search(pattern, normalized, re.IGNORECASE):
                logger.info(
                    f"Обнаружена нецензурная лексика в тексте: {text[:50]}...")
                return True
        except re.error as e:
            logger.error(f"Ошибка в регулярном выражении {pattern}: {e}")
            continue

    return False


def get_stars_keyboard(order_id: int,
                       for_admin: bool = False) -> InlineKeyboardMarkup:
    """Создание клавиатуры с 5-звездочной оценкой"""
    buttons = []
    for i in range(1, 6):
        stars = "⭐" * i
        if for_admin:
            callback_data = f"admin_review_rate:{order_id}:{i}"
        else:
            callback_data = f"review_rate:{order_id}:{i}"
        buttons.append(InlineKeyboardButton(stars,
                                            callback_data=callback_data))

    keyboard = [
        buttons[:3],
        buttons[3:],
    ]

    if not for_admin:
        keyboard.append([
            InlineKeyboardButton("📝 Оставить отзыв на Яндексе",
                                 url=YANDEX_REVIEWS_URL)
        ])

    return InlineKeyboardMarkup(keyboard)


async def request_review(bot_or_context, user_id: int, order_id: int) -> bool:
    """Отправить запрос на отзыв пользователю"""
    try:
        order = get_order(order_id)
        if not order:
            logger.warning(f"Заказ {order_id} не найден при запросе отзыва")
            return False

        # Проверяем, не оставлял ли уже пользователь отзыв на этот заказ
        if has_review(order_id):
            logger.info(
                f"Пользователь {user_id} уже оставил отзыв на заказ {order_id}"
            )
            return False

        # Получаем имя клиента и форматируем номер заказа
        client_name = order.client_name or "Дорогой клиент"
        formatted_id = format_order_id(order_id, order.created_at)

        text = (f"🪡 Ваше мнение очень важно!\n\n"
                f"Привет, {client_name}! Это Иголочка.\n"
                f"Надеюсь, обновлённая вещь из заказа {formatted_id} радует вас! ✨\n\n"
                f"Чтобы другие тоже могли найти нас и доверить свою одежду, "
                f"помогите, пожалуйста, оставить отзыв на Яндекс Картах. "
                f"Для нас это лучшая поддержка!\n\n"
                f"Оставить отзыв можно тут:\n"
                f"📍 {YANDEX_REVIEWS_URL}\n\n"
                f"Спасибо, что помогаете нам расти!\n"
                f"Ваша мастерская «Швейный HUB» 🧵")

        # Получаем бота из контекста или приложения
        if hasattr(bot_or_context, 'bot'):
            bot = bot_or_context.bot
        else:
            bot = bot_or_context

        # Отправляем запрос на отзыв (только ссылка на Яндекс)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📝 Оставить отзыв на Яндексе", url=YANDEX_REVIEWS_URL)
        ]])
        await bot.send_message(chat_id=user_id,
                               text=text,
                               reply_markup=keyboard,
                               parse_mode="Markdown")

        logger.info(
            f"Запрос на отзыв отправлен пользователю {user_id} для заказа {order_id}"
        )
        return True

    except Exception as e:
        logger.error(f"Ошибка при отправке запроса на отзыв: {e}")
        return False


async def handle_rating(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка callback с оценкой звёздами"""
    try:
        query = update.callback_query
        if not query:
            return ConversationHandler.END

        await query.answer()

        data_parts = query.data.split(":")
        if len(data_parts) != 3:
            logger.error(f"Некорректный callback data: {query.data}")
            if query.message:
                await query.edit_message_text(
                    "Произошла ошибка. Пожалуйста, попробуйте еще раз.",
                    reply_markup=get_main_menu())
            return ConversationHandler.END

        try:
            order_id = int(data_parts[1])
            rating = int(data_parts[2])
        except (ValueError, IndexError) as e:
            logger.error(f"Ошибка при парсинге callback data: {e}")
            return ConversationHandler.END

        # Проверяем корректность рейтинга
        if not (1 <= rating <= 5):
            logger.error(f"Некорректный рейтинг: {rating}")
            return ConversationHandler.END

        # Проверяем, существует ли заказ
        order = get_order(order_id)
        if not order:
            logger.error(f"Заказ {order_id} не найден")
            if query.message:
                await query.edit_message_text(
                    "❌ Заказ не найден. Пожалуйста, свяжитесь с администратором.",
                    reply_markup=get_main_menu())
            return ConversationHandler.END

        # Проверяем, не оставлял ли уже пользователь отзыв на этот заказ
        if has_review(order_id):
            if query.message:
                await query.edit_message_text(
                    "✅ Вы уже оставили отзыв на этот заказ. Спасибо!",
                    reply_markup=get_main_menu())
            return ConversationHandler.END

        # Сохраняем данные в context.user_data
        context.user_data['review_order_id'] = order_id
        context.user_data['review_rating'] = rating

        # Формируем строку со звёздами
        stars = "⭐" * rating

        # Клавиатура для следующего шага
        keyboard = [[
            InlineKeyboardButton("⏭ Пропустить комментарий",
                                 callback_data="review_skip_comment")
        ],
                    [
                        InlineKeyboardButton("📝 Оставить отзыв на Яндексе",
                                             url=YANDEX_REVIEWS_URL)
                    ],
                    [
                        InlineKeyboardButton("❌ Отменить",
                                             callback_data="review_cancel")
                    ]]

        if query.message:
            await query.edit_message_text(
                f"Отлично! Ваша оценка: {stars}\n\n"
                f"📝 *Хотите добавить комментарий?*\n\n"
                f"Напишите, что понравилось или что можно улучшить.\n"
                f"*Минимальная длина:* {MIN_COMMENT_LENGTH} символов\n"
                f"*Максимальная длина:* {MAX_COMMENT_LENGTH} символов\n\n"
                f"Или нажмите «Пропустить комментарий» чтобы отправить только оценку.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown")

        return ENTER_COMMENT

    except Exception as e:
        logger.error(f"Ошибка при обработке оценки: {e}")
        return ConversationHandler.END


async def handle_comment(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка текстового комментария"""
    try:
        if not update.message or not update.message.text:
            return ENTER_COMMENT

        comment = update.message.text.strip()
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "Пользователь"

        # Получаем данные из context
        order_id = context.user_data.get('review_order_id')
        rating = context.user_data.get('review_rating')

        if not order_id or not rating:
            logger.error(
                f"Отсутствуют данные отзыва для пользователя {user_id}")
            await update.message.reply_text(
                "❌ Произошла ошибка. Пожалуйста, начните оценку заново.",
                reply_markup=get_main_menu())
            return ConversationHandler.END

        # Проверяем длину комментария
        if len(comment) < MIN_COMMENT_LENGTH:
            await update.message.reply_text(
                f"❌ Комментарий слишком короткий. "
                f"Пожалуйста, напишите хотя бы {MIN_COMMENT_LENGTH} символов.",
                reply_markup=get_main_menu())
            return ENTER_COMMENT

        if len(comment) > MAX_COMMENT_LENGTH:
            await update.message.reply_text(
                f"❌ Комментарий слишком длинный. "
                f"Пожалуйста, сократите его до {MAX_COMMENT_LENGTH} символов.",
                reply_markup=get_main_menu())
            return ENTER_COMMENT

        # Проверяем на нецензурную лексику
        is_approved = True
        rejected_reason = None

        if contains_profanity(comment):
            is_approved = False
            rejected_reason = 'profanity'

            logger.warning(
                f"Обнаружена нецензурная лексика в отзыве от пользователя {user_id}"
            )

            await update.message.reply_text(
                "⚠️ *К сожалению, ваш комментарий содержит недопустимые выражения.*\n\n"
                "Пожалуйста, перефразируйте комментарий или отправьте только оценку.\n\n"
                "Напишите новый комментарий или используйте команду /skip для пропуска.",
                parse_mode="Markdown")
            return ENTER_COMMENT

        # Создаем отзыв в базе данных
        review_id = create_review(order_id=order_id,
                                  user_id=user_id,
                                  rating=rating,
                                  comment=comment,
                                  is_approved=is_approved,
                                  rejected_reason=rejected_reason)

        if review_id:
            stars = "⭐" * rating

            if is_approved:
                # Уведомляем администраторов о новом отзыве
                await notify_admins_about_review(context, review_id, order_id,
                                                 rating, comment, user_name)

                message = (
                    f"✅ *Спасибо за отзыв!*\n\n"
                    f"Ваша оценка: {stars}\n"
                    f"Комментарий: {comment[:200]}{'...' if len(comment) > 200 else ''}\n\n"
                    f"Мы ценим ваше мнение и постоянно работаем над улучшением качества услуг! 💜\n\n"
                    f"📝 Вы также можете оставить отзыв на Яндексе:")
            else:
                message = (f"✅ *Спасибо за оценку!*\n\n"
                           f"Ваша оценка: {stars}\n"
                           f"Ваш комментарий будет проверен модератором.\n\n"
                           f"Мы ценим ваше мнение! 💜")

            keyboard = [[
                InlineKeyboardButton("📝 Оставить отзыв на Яндексе",
                                     url=YANDEX_REVIEWS_URL)
            ], [
                InlineKeyboardButton("🏠 В главное меню", callback_data="menu")
            ]]

            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown")

            logger.info(
                f"Отзыв {review_id} создан для заказа {order_id} пользователем {user_id}"
            )
        else:
            await update.message.reply_text(
                "❌ Произошла ошибка при сохранении отзыва. Попробуйте позже.",
                reply_markup=get_main_menu())

        # Очищаем данные
        context.user_data.pop('review_order_id', None)
        context.user_data.pop('review_rating', None)

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при обработке комментария: {e}")
        return ConversationHandler.END


async def skip_comment(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пропустить комментарий и сохранить только оценку"""
    try:
        query = update.callback_query
        if not query:
            return ConversationHandler.END

        await query.answer()

        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "Пользователь"

        order_id = context.user_data.get('review_order_id')
        rating = context.user_data.get('review_rating')

        if not order_id or not rating:
            logger.error(
                f"Отсутствуют данные отзыва для пользователя {user_id}")
            if query.message:
                await query.edit_message_text(
                    "❌ Произошла ошибка. Пожалуйста, начните оценку заново.",
                    reply_markup=get_main_menu())
            return ConversationHandler.END

        # Создаем отзыв только с оценкой
        review_id = create_review(order_id=order_id,
                                  user_id=user_id,
                                  rating=rating,
                                  comment=None,
                                  is_approved=True)

        if review_id:
            stars = "⭐" * rating

            # Уведомляем администраторов
            await notify_admins_about_review(context, review_id, order_id,
                                             rating, None, user_name)

            message = (
                f"✅ *Спасибо за оценку!*\n\n"
                f"Ваша оценка: {stars}\n\n"
                f"Мы ценим ваше мнение! 💜\n\n"
                f"📝 Вы также можете оставить развёрнутый отзыв на Яндексе:")

            keyboard = [[
                InlineKeyboardButton("📝 Оставить отзыв на Яндексе",
                                     url=YANDEX_REVIEWS_URL)
            ], [
                InlineKeyboardButton("🏠 В главное меню", callback_data="menu")
            ]]

            if query.message:
                await query.edit_message_text(
                    message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown")

            logger.info(
                f"Отзыв {review_id} (только оценка) создан для заказа {order_id}"
            )
        else:
            if query.message:
                await query.edit_message_text(
                    "❌ Произошла ошибка при сохранении оценки. Попробуйте позже.",
                    reply_markup=get_main_menu())

        # Очищаем данные
        context.user_data.pop('review_order_id', None)
        context.user_data.pop('review_rating', None)

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при пропуске комментария: {e}")
        return ConversationHandler.END


async def cancel_review(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена оставления отзыва"""
    try:
        # Очищаем данные
        context.user_data.pop('review_order_id', None)
        context.user_data.pop('review_rating', None)

        if update.callback_query:
            await update.callback_query.answer()
            if update.callback_query.message:
                await update.callback_query.edit_message_text(
                    "❌ Оценка отменена.\n\nВы можете оставить отзыв позже.",
                    reply_markup=get_main_menu())
        elif update.message:
            await update.message.reply_text(
                "❌ Оценка отменена.\n\nВы можете оставить отзыв позже.",
                reply_markup=get_main_menu())

        logger.info(
            f"Оставление отзыва отменено пользователем {update.effective_user.id}"
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при отмене отзыва: {e}")
        return ConversationHandler.END


async def notify_admins_about_review(context: ContextTypes.DEFAULT_TYPE,
                                     review_id: int, order_id: int,
                                     rating: int, comment: Optional[str],
                                     user_name: str) -> bool:
    """Уведомить администраторов о новом отзыве"""
    try:
        import os

        admins = get_admins() or []
        admin_ids: List[int] = [
            admin.user_id for admin in admins if admin.user_id
        ]

        # Добавляем основного администратора из переменных окружения
        env_admin_id = os.getenv('ADMIN_ID')
        if env_admin_id:
            try:
                admin_ids.append(int(env_admin_id))
            except ValueError:
                logger.warning(f"Неверный формат ADMIN_ID: {env_admin_id}")

        # Удаляем дубликаты
        admin_ids = list(set(admin_ids))

        if not admin_ids:
            logger.warning(
                "Нет администраторов для уведомления о новом отзыве")
            return False

        # Формируем сообщение
        stars = "⭐" * rating
        comment_text = f"💬 {comment[:200]}..." if comment else "📝 Без комментария"

        message = (f"📝 *Новый отзыв!*\n\n"
                   f"◆ Заказ: #{order_id}\n"
                   f"◆ Пользователь: {user_name}\n"
                   f"◆ Оценка: {stars} ({rating}/5)\n"
                   f"◆ Комментарий: {comment_text}\n\n"
                   f"◆ ID отзыва: {review_id}")

        # Создаем клавиатуру для администратора
        keyboard = [[
            InlineKeyboardButton(
                "✅ Одобрить",
                callback_data=f"admin_review_approve:{review_id}"),
            InlineKeyboardButton(
                "❌ Отклонить",
                callback_data=f"admin_review_reject:{review_id}")
        ],
                    [
                        InlineKeyboardButton(
                            "📊 Статистика отзывов",
                            callback_data="admin_review_stats")
                    ]]

        # Отправляем уведомления всем администраторам
        for admin_id in admin_ids:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown")
                logger.info(
                    f"Уведомление о новом отзыве отправлено администратору {admin_id}"
                )
            except Exception as e:
                logger.error(
                    f"Не удалось отправить уведомление администратору {admin_id}: {e}"
                )

        return True

    except Exception as e:
        logger.error(f"Ошибка при уведомлении администраторов об отзыве: {e}")
        return False


async def show_review_stats(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику отзывов (для администраторов)"""
    try:
        query = update.callback_query
        if not query:
            return

        await query.answer()

        user_id = update.effective_user.id

        if not is_user_admin(user_id):
            if query.message:
                await query.edit_message_text(
                    "❌ У вас нет прав для просмотра статистики отзывов.",
                    reply_markup=get_main_menu())
            return

        # Получаем статистику
        stats = get_review_stats()

        if not stats or stats.get('total_reviews', 0) == 0:
            if query.message:
                await query.edit_message_text(
                    "📊 *Статистика отзывов*\n\n"
                    "Пока нет отзывов.",
                    parse_mode="Markdown",
                    reply_markup=get_admin_main_menu())
            return

        # Формируем сообщение со статистикой
        avg_rating = stats.get('average_rating', 0)
        total_reviews = stats.get('total_reviews', 0)
        approved_reviews = stats.get('approved_reviews', 0)
        pending_reviews = stats.get('pending_reviews', 0)

        # Получаем распределение по оценкам
        rating_distribution = stats.get('rating_distribution', {})

        stats_text = (f"📊 *Статистика отзывов*\n\n"
                      f"⭐ *Средний рейтинг:* {avg_rating:.1f}/5.0\n"
                      f"📈 *Всего отзывов:* {total_reviews}\n"
                      f"✅ *Одобрено:* {approved_reviews}\n"
                      f"⏳ *На модерации:* {pending_reviews}\n\n")

        # Добавляем распределение по оценкам
        if rating_distribution:
            stats_text += "*Распределение оценок:*\n"
            for rating in range(5, 0, -1):
                count = rating_distribution.get(str(rating), 0)
                stars = "⭐" * rating
                percentage = (count / total_reviews *
                              100) if total_reviews > 0 else 0
                bar = "▓" * int(
                    percentage / 10) + "░" * (10 - int(percentage / 10))
                stats_text += f"{stars}: {count} ({percentage:.1f}%) {bar}\n"

        # Получаем последние отзывы
        recent_reviews = get_recent_reviews(limit=5)
        if recent_reviews:
            stats_text += "\n*Последние отзывы:*\n"
            for review in recent_reviews:
                stars = "⭐" * review.rating
                status = "✅" if review.is_approved else "⏳"
                created_at = review.created_at.strftime('%d.%m.%Y') if hasattr(
                    review.created_at, 'strftime') else str(review.created_at)
                stats_text += f"{status} {stars} - {created_at}\n"

        keyboard = [[
            InlineKeyboardButton("📋 Список отзывов",
                                 callback_data="admin_review_list")
        ], [InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")]]

        if query.message:
            await query.edit_message_text(
                stats_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка при показе статистики отзывов: {e}")
        if update.callback_query and update.callback_query.message:
            await update.callback_query.edit_message_text(
                "❌ Произошла ошибка при получении статистики.",
                parse_mode="Markdown")


async def show_review_list(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    """Показать последние отзывы администратору."""
    query = update.callback_query
    if not query:
        return

    await query.answer()
    if not is_user_admin(update.effective_user.id):
        await query.edit_message_text(
            "❌ У вас нет прав для просмотра отзывов.",
            reply_markup=get_main_menu())
        return

    reviews = get_recent_reviews(limit=20)
    if not reviews:
        text = "📋 *Отзывы*\n\nПока нет отзывов."
    else:
        lines = ["📋 *Последние отзывы:*\n"]
        for review in reviews:
            stars = "⭐" * max(1, min(5, int(review.rating or 0)))
            status = "одобрен" if review.is_approved else (
                "отклонён" if review.rejected_reason else "на модерации")
            created_at = (
                review.created_at.strftime("%d.%m.%Y")
                if hasattr(review.created_at, "strftime")
                else str(review.created_at)
            )
            comment = (review.comment or "Без комментария").replace("\n", " ")
            lines.append(
                f"{stars} {created_at} — {status}\n"
                f"{comment[:160]}\n"
            )
        text = "\n".join(lines)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика отзывов",
                              callback_data="admin_review_stats")],
        [InlineKeyboardButton("◀️ В админ-панель",
                              callback_data="admin_back_menu")],
    ])
    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode="Markdown")


async def handle_admin_review_action(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий администратора с отзывами"""
    try:
        query = update.callback_query
        if not query:
            return

        await query.answer()

        user_id = update.effective_user.id

        if not is_user_admin(user_id):
            if query.message:
                await query.edit_message_text(
                    "❌ У вас нет прав для выполнения этого действия.",
                    reply_markup=get_main_menu())
            return

        data_parts = query.data.split(":")
        if len(data_parts) < 2:
            logger.error(f"Некорректный callback data: {query.data}")
            return

        action = data_parts[0]

        try:
            review_id = int(data_parts[1])
        except ValueError:
            logger.error(f"Ошибка при парсинге review_id: {data_parts[1]}")
            return

        # Обработка различных действий
        success = False
        action_text = ""

        if action == "admin_review_approve":
            success = update_review_status(review_id, is_approved=True)
            action_text = "одобрен"
        elif action == "admin_review_reject":
            success = update_review_status(review_id,
                                           is_approved=False,
                                           rejected_reason="rejected_by_admin")
            action_text = "отклонён"
        else:
            logger.error(f"Неизвестное действие: {action}")
            return

        if success:
            # Обновляем сообщение у администратора
            if query.message:
                original_text = query.message.text or ""
                new_text = original_text + f"\n\n✅ Отзыв {action_text} администратором"

                keyboard = [[
                    InlineKeyboardButton("📊 Статистика отзывов",
                                         callback_data="admin_review_stats")
                ],
                            [
                                InlineKeyboardButton(
                                    "◀️ Назад",
                                    callback_data="admin_back_menu")
                            ]]

                # Проверяем есть ли в сообщении фото/видео
                if query.message.photo:
                    await query.edit_message_caption(
                        caption=new_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown")
                else:
                    await query.edit_message_text(
                        text=new_text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown")

            logger.info(
                f"Отзыв {review_id} {action_text} администратором {user_id}")
        else:
            await query.answer("❌ Не удалось обновить статус отзыва",
                               show_alert=True)

    except Exception as e:
        logger.error(
            f"Ошибка при обработке действия администратора с отзывом: {e}")


async def request_review_command(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """Команда для запроса отзыва от администратора"""
    try:
        user_id = update.effective_user.id

        if not is_user_admin(user_id):
            await update.message.reply_text(
                "❌ У вас нет прав для выполнения этой команды.")
            return

        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                "Использование: /request_review <user_id> <order_id>\n\n"
                "Пример: /request_review 123456789 42")
            return

        try:
            target_user_id = int(context.args[0])
            order_id = int(context.args[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат команды.\n\n"
                "Использование: /request_review <user_id> <order_id>\n"
                "user_id и order_id должны быть числами.")
            return

        # Запрашиваем отзыв
        success = await request_review(context.bot, target_user_id, order_id)

        if success:
            await update.message.reply_text(
                f"✅ Запрос на отзыв отправлен пользователю {target_user_id} для заказа {order_id}"
            )
        else:
            await update.message.reply_text(
                f"⚠️ Не удалось отправить запрос на отзыв. "
                f"Проверьте корректность user_id и order_id.")

    except Exception as e:
        logger.error(f"Ошибка в команде request_review: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при отправке запроса на отзыв.")


def get_review_conversation_handler() -> ConversationHandler:
    """✅ ИСПРАВЛЕННО: Создать и вернуть ConversationHandler для отзывов с per_message=False"""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_rating,
                                 pattern=r"^review_rate:\d+:\d+$")
        ],
        states={
            ENTER_COMMENT: [
                CallbackQueryHandler(skip_comment,
                                     pattern=r"^review_skip_comment$"),
                CallbackQueryHandler(cancel_review,
                                     pattern=r"^review_cancel$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               handle_comment),
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_review, pattern=r"^review_cancel$"),
            MessageHandler(filters.Regex(r'^(/cancel|Отмена)$'),
                           cancel_review),
            MessageHandler(filters.Regex(r'^/skip$'), skip_comment),
        ],
        per_message=False,  # ✅ ИСПРАВЛЕНО: было False, теперь True
        allow_reentry=True)


def get_admin_review_handlers() -> List[CallbackQueryHandler]:
    """Получить обработчики для административных действий с отзывами"""
    return [
        CallbackQueryHandler(show_review_list,
                             pattern=r"^admin_review_list$"),
        CallbackQueryHandler(show_review_stats,
                             pattern=r"^admin_review_stats$"),
        CallbackQueryHandler(handle_admin_review_action,
                             pattern=r"^admin_review_(approve|reject):\d+$"),
    ]
