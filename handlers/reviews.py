"""
Обработчик отзывов с 5-звездочной системой
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters
from utils.database import create_review, has_review, get_order, get_average_rating
from keyboards import get_main_menu
import logging
import re

logger = logging.getLogger(__name__)

YANDEX_REVIEWS_URL = "https://yandex.ru/maps/org/shveyny_hub/1233246900?si=qazrp3fnzwhkjgancr36aquutw"

ENTER_COMMENT = 0

MAX_COMMENT_LENGTH = 1000

PROFANITY_PATTERNS = [
    r'\b(бля|блять|блядь|блядина|ёб|еб|ебан|ебать|ебло|ебуч|пизд|пизда|пиздец|хуй|хуя|хуе|хуи|сука|сучк|мудак|мудил|дебил|долбо|залуп|говн|срать|сран|жоп|ёпт|нах)\w*',
    r'\b(fuck|shit|bitch|asshole|dick|pussy)\w*',
    r'(б+л+я+|п+и+з+д+|х+у+й+|е+б+а+|с+у+к+а+)',
    r'(f+u+c+k+|s+h+i+t+)',
]

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
    """Normalize text by removing obfuscation"""
    result = text.lower()
    for char, replacement in LEETSPEAK_MAP.items():
        result = result.replace(char, replacement)
    result = re.sub(r'[._\-*#]+', '', result)
    result = re.sub(r'(.)\1{3,}', r'\1\1', result)
    return result


def contains_profanity(text: str) -> bool:
    """Check if text contains profanity"""
    if not text:
        return False
    if len(text) > MAX_COMMENT_LENGTH:
        return True
    normalized = normalize_text(text)
    for pattern in PROFANITY_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            return True
    return False


def get_stars_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Create 5-star rating keyboard"""
    buttons = []
    for i in range(1, 6):
        stars = "⭐" * i
        buttons.append(
            InlineKeyboardButton(stars,
                                 callback_data=f"review_rate:{order_id}:{i}"))

    keyboard = [
        buttons[:3], buttons[3:],
        [
            InlineKeyboardButton("📝 Оставить отзыв на Яндексе",
                                 url=YANDEX_REVIEWS_URL)
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def request_review(app_or_context, user_id: int, order_id: int):
    """Send review request to user"""
    try:
        order = get_order(order_id)
        if not order:
            return

        if has_review(order_id):
            return

        avg_rating = get_average_rating()
        rating_text = f"⭐ {avg_rating}" if avg_rating > 0 else ""

        text = (f"🧵 *Как прошёл ремонт?*\n\n"
                f"Привет! Это Иголочка! 🪡\n"
                f"Недавно вы были у нас в мастерской (заказ #{order_id}).\n\n"
                f"Расскажите, всё ли понравилось?\n"
                f"Нажмите на звёздочки для оценки:\n\n"
                f"{rating_text}")

        bot = getattr(app_or_context, 'bot', None)
        if bot is None:
            bot = app_or_context

        await bot.send_message(chat_id=user_id,
                               text=text,
                               reply_markup=get_stars_keyboard(order_id),
                               parse_mode="Markdown")
        logger.info(
            f"Review request sent to user {user_id} for order {order_id}")
    except Exception as e:
        logger.error(f"Error sending review request: {e}")


async def handle_rating(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle star rating callback"""
    query = update.callback_query
    await query.answer()

    data = query.data.split(":")
    if len(data) != 3:
        return ConversationHandler.END

    _, order_id, rating = data
    order_id = int(order_id)
    rating = int(rating)

    if has_review(order_id):
        await query.edit_message_text(
            "✅ Вы уже оставили отзыв на этот заказ. Спасибо!",
            reply_markup=get_main_menu())
        return ConversationHandler.END

    context.user_data['review_order_id'] = order_id
    context.user_data['review_rating'] = rating

    stars = "⭐" * rating

    keyboard = [[
        InlineKeyboardButton("⏭ Пропустить",
                             callback_data="review_skip_comment")
    ], [InlineKeyboardButton("📝 Яндекс отзывы", url=YANDEX_REVIEWS_URL)]]

    await query.edit_message_text(
        f"Отлично! Ваша оценка: {stars}\n\n"
        f"Хотите добавить комментарий?\n"
        f"Напишите, что понравилось или что можно улучшить.\n\n"
        f"Или нажмите «Пропустить» чтобы отправить только оценку.",
        reply_markup=InlineKeyboardMarkup(keyboard))

    return ENTER_COMMENT


async def handle_comment(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle text comment"""
    comment = update.message.text
    user_id = update.effective_user.id

    order_id = context.user_data.get('review_order_id')
    rating = context.user_data.get('review_rating')

    if not order_id or not rating:
        await update.message.reply_text(
            "Произошла ошибка. Пожалуйста, начните оценку заново.",
            reply_markup=get_main_menu())
        return ConversationHandler.END

    is_approved = True
    rejected_reason = None

    if contains_profanity(comment):
        is_approved = False
        rejected_reason = 'profanity'

        await update.message.reply_text(
            "⚠️ К сожалению, ваш отзыв содержит недопустимые выражения.\n"
            "Пожалуйста, перефразируйте комментарий или отправьте только оценку.\n\n"
            "Напишите новый комментарий или нажмите /skip чтобы пропустить.",
            reply_markup=get_main_menu())
        return ENTER_COMMENT

    review_id = create_review(order_id=order_id,
                              user_id=user_id,
                              rating=rating,
                              comment=comment,
                              is_approved=is_approved,
                              rejected_reason=rejected_reason)

    if review_id:
        stars = "⭐" * rating
        await update.message.reply_text(
            f"✅ Спасибо за отзыв!\n\n"
            f"Ваша оценка: {stars}\n"
            f"Комментарий: {comment[:100]}...\n\n"
            f"Мы ценим ваше мнение! 💜\n\n"
            f"📝 Вы также можете оставить отзыв на Яндексе:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 Яндекс отзывы", url=YANDEX_REVIEWS_URL)
            ], [InlineKeyboardButton("🏠 В меню", callback_data="menu")]]))
    else:
        await update.message.reply_text(
            "Произошла ошибка при сохранении отзыва. Попробуйте позже.",
            reply_markup=get_main_menu())

    context.user_data.pop('review_order_id', None)
    context.user_data.pop('review_rating', None)

    return ConversationHandler.END


async def skip_comment(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> int:
    """Skip comment and save rating only"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    order_id = context.user_data.get('review_order_id')
    rating = context.user_data.get('review_rating')

    if not order_id or not rating:
        await query.edit_message_text(
            "Произошла ошибка. Пожалуйста, начните оценку заново.",
            reply_markup=get_main_menu())
        return ConversationHandler.END

    review_id = create_review(order_id=order_id,
                              user_id=user_id,
                              rating=rating,
                              comment=None,
                              is_approved=True)

    if review_id:
        stars = "⭐" * rating
        await query.edit_message_text(
            f"✅ Спасибо за оценку!\n\n"
            f"Ваша оценка: {stars}\n\n"
            f"Мы ценим ваше мнение! 💜\n\n"
            f"📝 Вы также можете оставить развёрнутый отзыв на Яндексе:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 Яндекс отзывы", url=YANDEX_REVIEWS_URL)
            ], [InlineKeyboardButton("🏠 В меню", callback_data="menu")]]))
    else:
        await query.edit_message_text(
            "Произошла ошибка при сохранении оценки. Попробуйте позже.",
            reply_markup=get_main_menu())

    context.user_data.pop('review_order_id', None)
    context.user_data.pop('review_rating', None)

    return ConversationHandler.END


async def cancel_review(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel review"""
    context.user_data.pop('review_order_id', None)
    context.user_data.pop('review_rating', None)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Оценка отменена. Вы можете оставить отзыв позже.",
            reply_markup=get_main_menu())
    else:
        await update.message.reply_text(
            "Оценка отменена. Вы можете оставить отзыв позже.",
            reply_markup=get_main_menu())

    return ConversationHandler.END


def get_review_conversation_handler():
    """Create review conversation handler"""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_rating,
                                 pattern=r"^review_rate:\d+:\d+$")
        ],
        states={
            ENTER_COMMENT: [
                CallbackQueryHandler(skip_comment,
                                     pattern=r"^review_skip_comment$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND,
                               handle_comment),
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_review, pattern=r"^cancel$"),
        ],
        per_message=False)
