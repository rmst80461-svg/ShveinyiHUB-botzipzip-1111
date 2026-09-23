"""
Полнофункциональный обработчик админ-панели для бота.

Реализовано:
- команды: /admin, /stats, /orders, /neworders, /users, /spam, /broadcast, /setadmin
- callback-обработчики админ-меню: admin_menu_callback, admin_view_order,
  change_order_status, contact_client, open_web_admin
- интеграция с utils.database и keyboards
- безопасные проверки прав (ENV ADMIN_ID + флаг is_admin из БД)
"""
import os
import logging
import asyncio
from typing import List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# Локальные зависимости (должны существовать в проекте)
from utils.database import (
    get_statistics,
    get_all_orders,
    get_all_users,
    get_spam_logs,
    set_admin,
    is_admin,
    get_orders_by_status,
    get_order,
    update_order_status,
    get_admins,
)
from keyboards import (
    get_admin_main_menu,
    get_admin_orders_submenu,
    get_admin_back_menu,
    get_admin_order_detail_keyboard,
)

logger = logging.getLogger(__name__)

# Конфигурация - поддержка нескольких админов через запятую
def get_env_admin_ids() -> List[int]:
    """Получить список админов из переменных окружения (ADMIN_IDS или ADMIN_ID)"""
    admin_ids = []
    # Сначала проверяем ADMIN_IDS (множественные)
    env_ids = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID") or ""
    for id_str in env_ids.replace(" ", "").split(","):
        if id_str:
            try:
                admin_ids.append(int(id_str))
            except ValueError:
                pass
    return admin_ids

ENV_ADMIN_IDS = get_env_admin_ids()
# Для обратной совместимости
ENV_ADMIN_ID = ENV_ADMIN_IDS[0] if ENV_ADMIN_IDS else 0

WEB_ADMIN_URL = os.getenv("WEB_ADMIN_URL") or f"https://{os.getenv('REPLIT_DEV_DOMAIN')}" or ""


def _get_web_admin_orders_url() -> str:
    """Сформировать URL веб-админки для страницы заказов"""
    if WEB_ADMIN_URL:
        # Убираем /admin/orders и оставляем просто /orders, так как в app.py роут /orders
        return f"{WEB_ADMIN_URL.rstrip('/')}/orders"
    return ""


def get_admin_ids() -> List[int]:
    """Вернуть список admin ids (ENV + БД)"""
    ids = list(ENV_ADMIN_IDS)  # Копируем список из ENV
    try:
        db_admins = get_admins() if callable(get_admins) else []
        for a in db_admins:
            try:
                uid = int(a.user_id)
                if uid not in ids:
                    ids.append(uid)
            except Exception:
                pass
    except Exception:
        logger.debug("get_admins not available or failed")
    return ids


def is_user_admin(user_id: int) -> bool:
    """Проверка прав администратора: ENV_ADMIN_IDS или is_admin из БД"""
    if not user_id:
        return False
    
    # Принудительно приводим к int для надежности сравнения
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return False
    
    # Прямая проверка ID из переменных окружения (наивысший приоритет)
    env_ids = str(os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID") or "")
    
    # ЛОГИРОВАНИЕ ДЛЯ ОТЛАДКИ
    logging.info(f"Checking admin access for {user_id}. Raw ENV ADMIN_IDS: '{env_ids}'")
    
    admin_ids = []
    # Обработка разных разделителей (запятая, точка с запятой, пробел)
    clean_env_ids = env_ids.replace(";", ",").replace(" ", ",")
    for id_str in clean_env_ids.split(","):
        if id_str.strip():
            try:
                admin_ids.append(int(id_str.strip()))
            except ValueError:
                pass
                
    if user_id in admin_ids:
        logging.info(f"User {user_id} found in ENV_ADMIN_IDS")
        return True
        
    try:
        from utils.database import is_admin as db_is_admin
        res = bool(db_is_admin(user_id))
        if res:
            logging.info(f"User {user_id} is admin in DB")
        return res
    except Exception as e:
        logging.error(f"Error checking admin status in DB for {user_id}: {e}")
        return False


# ---------------- Команды ----------------


async def admin_panel_command(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    """/admin — показать главное админ-меню"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return

    try:
        stats = get_statistics()
    except Exception:
        stats = {}
    text = "📋 *Админ-панель*\n\nВыберите раздел для управления:"
    await update.effective_message.reply_text(
        text, reply_markup=get_admin_main_menu(), parse_mode="Markdown")


def get_admin_stats():
    """Возвращает статистику для админ-панели в формате, необходимом для callback меню"""
    try:
        stats = get_statistics()
        # Преобразуем статистику в формат, ожидаемый в messages.py
        return {
            'users': stats.get('total_users', 0),
            'orders': stats.get('total_orders', 0),
            'messages': stats.get('total_orders', 0),  # используем количество заказов как приближенное значение
            'reviews': 0,  # в текущей базе данных нет отдельного поля для отзывов
            'active_sessions': 0  # в текущей реализации нет подсчета активных сессий
        }
    except Exception:
        logger.exception("Ошибка при получении статистики")
        return {
            'users': 0,
            'orders': 0,
            'messages': 0,
            'reviews': 0,
            'active_sessions': 0
        }


async def admin_stats(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats — показать статистику"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        await update.effective_message.reply_text("⛔ У вас нет доступа.")
        return

    try:
        from utils.database import get_statistics
        stats = get_statistics()
        text = ("📊 *Статистика бота*\n\n"
                f"👥 Пользователей: {stats.get('total_users', 0)}\n"
                f"📦 Всего заказов: {stats.get('total_orders', 0)}\n"
                f"🆕 Новых: {stats.get('new_orders', 0)}\n"
                f"🔄 В работе: {stats.get('in_progress', 0)}\n"
                f"✅ Выполнено: {stats.get('completed', 0)}\n"
                f"📤 Выдано: {stats.get('issued', 0)}\n"
                f"🚫 Заблокировано: {stats.get('blocked_users', 0)}\n"
                f"🛑 Спам-записей: {stats.get('spam_count', 0)}")
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats"),
            InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")
        ]])
        
        # Проверка: если вызвана как команда (update.message) или как callback (update.callback_query)
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await update.effective_message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    except Exception:
        logger.exception("Ошибка при формировании статистики")
        error_text = "❌ Ошибка при получении статистики."
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(error_text)
        else:
            await update.effective_message.reply_text(error_text)


async def admin_orders(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    """/orders — вывести заказы с пагинацией (новая система)"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ У вас нет доступа.")
        return

    # Получаем фильтр
    status_filter = context.user_data.get('admin_orders_filter', 'all')
    
    # ПЕРЕХВАТЫВАЕМ ТЕКСТОВУЮ КНОПКУ "Все заказы" В ЛЮБОМ ВИДЕ
    status_str = str(status_filter).lower()
    if "все заказы" in status_str or "📊" in status_str or not status_filter:
        status_filter = "all"
    
    # УДАЛЯЕМ ВСЕ ЭМОДЗИ И ЛИШНИЕ СИМВОЛЫ ИЗ ТЕКСТА КНОПКИ ДЛЯ ОСТАЛЬНЫХ
    normalized_filter = status_str
    for emoji in ["📊", "📦", "📋", "⏳", "✅", "📤"]:
        normalized_filter = normalized_filter.replace(emoji, "")
    normalized_filter = normalized_filter.strip()
    
    if "сегодня в работе" in normalized_filter:
        status_filter = "in_progress"
    elif "приняты" in normalized_filter:
        status_filter = "accepted"
    elif "готовы к выдаче" in normalized_filter:
        status_filter = "completed"
    elif status_filter != "all":
        # Если это уже системный статус (new, etc), оставляем как есть
        status_filter = normalized_filter
        
    context.user_data.pop('admin_orders_filter', None)
    
    # Окончательная проверка на валидность
    valid_statuses = ['all', 'new', 'accepted', 'in_progress', 'completed', 'issued', 'cancelled', 'spam']
    if status_filter not in valid_statuses:
        status_filter = 'all'
    
    logger.info(f"Admin orders requested. Original: {status_filter}, Normalized: {status_filter}")
    
    from handlers.admin_orders import show_orders_list
    await show_orders_list(update, context, status=status_filter, page=0)


async def admin_new_orders(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """/neworders — показать новые заказы"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ У вас нет доступа.")
        return

    try:
        orders = get_orders_by_status("new")
        if not orders:
            await update.effective_message.reply_text("✅ Новых заказов нет.")
            return
        from handlers.orders import format_order_id
        text = f"🆕 *Новые заказы ({len(orders)}):*\n\n"
        for order in orders[:20]:
            formatted = format_order_id(order.id, order.created_at)
            text += f"*{formatted}* — {order.client_name or '—'} | 📞 {order.client_phone or '—'}\n"
        await update.effective_message.reply_text(text, parse_mode="Markdown")
    except Exception:
        logger.exception("Ошибка при получении новых заказов")
        if update.effective_message:
            await update.effective_message.reply_text("❌ Ошибка при получении новых заказов.")


async def admin_users(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> None:
    """/users — список пользователей"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ У вас нет доступа.")
        return

    try:
        users = get_all_users()
        if not users:
            if hasattr(update, 'callback_query') and update.callback_query:
                await update.callback_query.edit_message_text("👥 Пользователей нет.")
            else:
                await update.effective_message.reply_text("👥 Пользователей нет.")
            return
        text = f"👥 *Пользователи ({len(users)}):*\n\n"
        for u in users[:50]:
            name = u.first_name or u.username or f"ID: {u.user_id}"
            line = f"• {name}"
            if u.phone:
                line += f" ({u.phone})"
            text += line + "\n"
        
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown")
        else:
            await update.effective_message.reply_text(text, parse_mode="Markdown")
    except Exception:
        logger.exception("Ошибка при получении пользователей")
        error_text = "❌ Ошибка при получении пользователей."
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(error_text)
        else:
            await update.effective_message.reply_text(error_text)


async def admin_spam(update: Update,
                     context: ContextTypes.DEFAULT_TYPE) -> None:
    """/spam — показать журнал спама"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ У вас нет доступа.")
        return

    try:
        logs = get_spam_logs(limit=50)
        if not logs:
            await update.effective_message.reply_text("🛑 Записей спама нет.")
            return
        text = "🛑 *Последние спам-записи:*\n\n"
        for l in logs[:50]:
            text += f"👤 {l.user_id} • {l.reason}\n{(l.message[:120] + '...') if l.message else ''}\n\n"
        await update.effective_message.reply_text(text, parse_mode="Markdown")
    except Exception:
        logger.exception("Ошибка при получении spam logs")
        if update.effective_message:
            await update.effective_message.reply_text("❌ Ошибка при получении журнала спама.")


# ---------------- Рассылка ----------------


async def broadcast_start(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запустить режим рассылки (следующий текст — рассылка)"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if update.message:
            await update.message.reply_text("⛔ У вас нет доступа.")
        return
    
    context.user_data["broadcast_mode"] = True
    context.user_data["broadcast_text"] = None
    
    text = (
        "📣 *Режим рассылки*\n\n"
        "Введите текст сообщения для всех пользователей бота.\n\n"
        "💡 Можно использовать Markdown для оформления."
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")]
    ])
    
    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard, parse_mode="Markdown")


async def broadcast_preview(update: Update,
                            context: ContextTypes.DEFAULT_TYPE,
                            message_text: str) -> None:
    """Показать предпросмотр рассылки перед отправкой"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        return
    
    context.user_data["broadcast_text"] = message_text
    context.user_data["broadcast_mode"] = False
    
    try:
        users = get_all_users()
        user_count = len(users)
    except:
        user_count = "?"
    
    preview_text = (
        "📋 *Предпросмотр рассылки*\n"
        "━━━━━━━━━━━━━━━\n\n"
        f"{message_text}\n\n"
        "━━━━━━━━━━━━━━━\n"
        f"👥 Получателей: {user_count}"
    )
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Отправить", callback_data="broadcast_confirm"),
            InlineKeyboardButton("✏️ Редактировать", callback_data="broadcast_edit")
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")]
    ])
    
    await update.message.reply_text(preview_text, reply_markup=keyboard, parse_mode="Markdown")


async def broadcast_cancel(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отменить рассылку и вернуться в админ-меню"""
    query = update.callback_query
    await query.answer("Рассылка отменена")
    
    context.user_data["broadcast_mode"] = False
    context.user_data["broadcast_text"] = None
    
    try:
        await query.message.delete()
    except:
        pass
    
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="❌ Рассылка отменена.",
        reply_markup=get_admin_main_menu(),
        parse_mode="Markdown"
    )


async def broadcast_edit(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """Редактировать текст рассылки"""
    query = update.callback_query
    await query.answer()
    
    context.user_data["broadcast_mode"] = True
    
    old_text = context.user_data.get("broadcast_text", "")
    
    text = (
        "✏️ *Редактирование рассылки*\n\n"
        f"Текущий текст:\n_{old_text[:200]}{'...' if len(old_text) > 200 else ''}_\n\n"
        "Введите новый текст:"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="broadcast_cancel")]
    ])
    
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def broadcast_confirm(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтвердить и отправить рассылку"""
    query = update.callback_query
    await query.answer("Запускаю рассылку...")
    
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        return
    
    message_text = context.user_data.get("broadcast_text")
    if not message_text:
        await query.edit_message_text("❌ Текст рассылки не найден. Начните заново.")
        return
    
    context.user_data["broadcast_text"] = None
    
    try:
        users = get_all_users()
    except Exception:
        logger.exception("Ошибка при получении списка пользователей")
        await query.edit_message_text("❌ Не удалось получить список пользователей.")
        return
    
    await query.edit_message_text(f"📤 Запускаю рассылку {len(users)} пользователям...")
    
    sent = 0
    failed = 0
    delay = float(os.getenv("BROADCAST_DELAY", "0.05"))
    
    for u in users:
        try:
            await context.bot.send_message(
                chat_id=int(u.user_id),
                text=message_text,
                parse_mode="Markdown"
            )
            sent += 1
            if delay:
                await asyncio.sleep(delay)
        except Exception:
            failed += 1
    
    await context.bot.send_message(
        chat_id=user_id,
        text=f"✅ *Рассылка завершена*\n\n📨 Отправлено: {sent}\n❌ Ошибок: {failed}",
        parse_mode="Markdown"
    )


async def broadcast_send(update: Update,
                         context: ContextTypes.DEFAULT_TYPE,
                         message_text: Optional[str] = None) -> None:
    """Отправить рассылку всем пользователям"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        return

    if not message_text:
        if context.args:
            message_text = " ".join(context.args)
        elif update.message and update.message.text:
            message_text = update.message.text
        else:
            await update.message.reply_text("❌ Нет текста для рассылки.")
            return

    if message_text == "/cancel":
        context.user_data["broadcast_mode"] = False
        await update.message.reply_text("❌ Рассылка отменена.")
        return

    # Выключаем режим рассылки после получения сообщения
    context.user_data["broadcast_mode"] = False

    try:
        users = get_all_users()
    except Exception:
        logger.exception("Ошибка при получении списка пользователей")
        await update.message.reply_text(
            "❌ Не удалось получить список пользователей.")
        return

    sent = 0
    failed = 0
    delay = float(os.getenv("BROADCAST_DELAY", "0.05"))

    status_msg = await update.message.reply_text(
        f"📤 Запускаю рассылку {len(users)} пользователям...")
    
    for u in users:
        try:
            await context.bot.send_message(chat_id=int(u.user_id),
                                           text=message_text,
                                           parse_mode="Markdown")
            sent += 1
            if delay:
                await asyncio.sleep(delay)
            
            if sent % 10 == 0:
                try:
                    await status_msg.edit_text(f"📤 Отправлено: {sent} / {len(users)}...")
                except: pass
        except Exception:
            failed += 1
            
    await update.message.reply_text(
        f"✅ Рассылка завершена.\nОтправлено: {sent}\nОшибок: {failed}.")


# ---------------- Управление правами ----------------


async def set_admin_command(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setadmin <user_id> — назначить пользователя админом"""
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("⛔ У вас нет доступа.")
        return

    if not context.args:
        await update.effective_message.reply_text("Использование: /setadmin <user_id>")
        return

    try:
        new_admin_id = int(context.args[0])
        ok = set_admin(new_admin_id, True)
        if ok:
            await update.effective_message.reply_text(
                f"✅ Пользователь {new_admin_id} назначен админом.")
        else:
            await update.effective_message.reply_text(
                "❌ Не удалось назначить администратора.")
    except Exception:
        logger.exception("Ошибка в set_admin_command")
        if update.effective_message:
            await update.effective_message.reply_text(
                "❌ Ошибка при назначении администратора.")


# ---------------- Callback-обработчики ----------------


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Главный обработчик callback для админ-панели (вызывается из хендлера сообщений)"""
    return await admin_menu_callback(update, context)

async def admin_menu_callback(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка callback'ов из админ-меню"""
    # Безопасное получение query
    query = getattr(update, 'callback_query', None)
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        if query:
            await query.answer("⛔ Нет доступа", show_alert=True)
        return

    data = getattr(query, 'data', "")

    # Напоминания о зависших заказах
    try:
        from utils.database import get_session, Order
        from datetime import datetime, timedelta
        session = get_session()
        
        # 1. Заказы, которые не принесли (статус 'new' более 3 дней)
        three_days_ago = datetime.utcnow() - timedelta(days=3)
        not_brought_orders = session.query(Order).filter(
            Order.status == 'new',
            Order.created_at <= three_days_ago
        ).all()
        
        if not_brought_orders:
            from handlers.orders import format_order_id
            text = f"⏳ *{len(not_brought_orders)} новых заказов не принесли (более 3 дней):*\n\n"
            for o in not_brought_orders:
                fid = format_order_id(int(o.id), o.created_at)
                text += f"• {fid} {o.client_name or '—'} — создан {o.created_at.strftime('%d.%m')}\n"
            text += "\n_Рекомендуется уточнить у клиента или отменить._"
            
            # Проверяем наличие бота перед отправкой
            bot = context.bot if context and hasattr(context, 'bot') else None
            if bot:
                for admin_id in get_admin_ids():
                    try:
                        await bot.send_message(chat_id=admin_id, text=text, parse_mode="Markdown")
                    except Exception as e:
                        logger.error(f"Failed to send stuck order reminder to admin {admin_id}: {e}")

        # 2. Заказы, принятые но не в работе (статус 'accepted' более 5 дней)
        five_days_ago = datetime.utcnow() - timedelta(days=5)
        stuck_orders = session.query(Order).filter(
            Order.status == 'accepted',
            Order.accepted_at <= five_days_ago
        ).all()
        
        if stuck_orders:
            text = f"⚠️ *{len(stuck_orders)} заказа «Приняты» но не в работе (более 5 дней):*\n\n"
            for o in stuck_orders:
                from handlers.orders import format_order_id
                fid = format_order_id(int(o.id), o.created_at)
                # Безопасное сравнение дат
                is_overdue = False
                if o.ready_date:
                    try:
                        current_date = datetime.now().strftime("%d.%m")
                        if current_date > str(o.ready_date):
                            is_overdue = True
                    except: pass
                overdue_label = " (ПРОСРОЧЕН!)" if is_overdue else ""
                text += f"• {fid} {o.client_name or '—'} — принят {o.accepted_at.strftime('%d.%m')}, срок {o.ready_date or 'Н/Д'}{overdue_label}\n"
            
            bot = context.bot if context and hasattr(context, 'bot') else None
            if bot:
                for admin_id in get_admin_ids():
                    try:
                        await bot.send_message(chat_id=admin_id, text=text, parse_mode="Markdown")
                    except Exception as e:
                        logger.error(f"Failed to send stuck accepted reminder to admin {admin_id}: {e}")
    except Exception as e:
        logger.error(f"Error in stuck orders check: {e}")
    finally:
        session.close()
    if data == "📊 Все заказы" or (update.message and update.message.text == "📊 Все заказы"):
        await admin_orders(update, context)
        return

    if data == "📈 Статистика" or (update.message and update.message.text == "📈 Статистика"):
        await admin_stats(update, context)
        return

    if data == "👥 Пользователи" or (update.message and update.message.text == "👥 Пользователи"):
        await admin_users(update, context)
        return

    # Новые фильтры "Что делать сегодня"
    if update.message and update.message.text == "📋 Сегодня в работе":
        from handlers.admin_orders import show_orders_list
        await show_orders_list(update, context, status="in_progress", page=0)
        return

    if update.message and update.message.text == "⏳ Приняты, ждут":
        from handlers.admin_orders import show_orders_list
        await show_orders_list(update, context, status="accepted", page=0)
        return

    if update.message and update.message.text == "✅ Готовы к выдаче":
        from handlers.admin_orders import show_orders_list
        await show_orders_list(update, context, status="completed", page=0)
        return

    if data == "📢 Рассылка" or (update.message and update.message.text == "📢 Рассылка") or data == "broadcast_menu":
        # Проверяем, не является ли это вызовом через MessageHandler (кнопка меню)
        if update.message and update.message.text == "📢 Рассылка":
            # Если мы НЕ в режиме рассылки, то переходим в него
            if not context.user_data.get("broadcast_mode"):
                await broadcast_start(update, context)
            return
        
        # Для callback_query всегда вызываем старт
        await broadcast_start(update, context)
        return
    
    if data == "admin_orders_menu":
        from handlers.admin_orders import show_orders_list
        await show_orders_list(update, context, status="new", page=0)
        return

    if data == "admin_back_menu":
        try:
            await query.message.delete()
        except:
            pass
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="📋 *Админ-панель*\n\nВыберите раздел:",
            reply_markup=get_admin_main_menu(),
            parse_mode="Markdown")
        return

    if data == "admin_stats":
        await admin_stats(update, context)
        return

    if data == "admin_clients":
        await admin_users(update, context)
        return

    if data == "open_web_admin":
        url = _get_web_admin_orders_url() or "Веб-панель недоступна"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 Открыть веб-админку", url=url)
        ], [InlineKeyboardButton("◀️ Назад",
                                 callback_data="admin_back_menu")]])
        await query.edit_message_text(f"🌐 Веб-панель: {url}",
                                      reply_markup=keyboard,
                                      parse_mode="Markdown")
        return

    status_map = {
        "admin_orders_new": ("new", "🆕 Новые заказы"),
        "admin_orders_in_progress": ("in_progress", "🔄 Заказы в работе"),
        "admin_orders_completed": ("completed", "✅ Готовые заказы"),
        "admin_orders_issued": ("issued", "📤 Выданные заказы"),
    }
    if data in status_map:
        status, title = status_map[data]
        try:
            orders = get_orders_by_status(status)
            if not orders:
                await query.edit_message_text(
                    f"{title}\n\n📭 Заказов нет",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("◀️ Назад",
                                             callback_data="admin_back_menu")
                    ]]),
                    parse_mode="Markdown")
                return
            from handlers.orders import format_order_id, SERVICE_NAMES
            text = f"📋 *{title}* — {len(orders)} шт.\n\n"
            keyboard = []
            for order in orders[:20]:
                formatted = format_order_id(int(order.id), order.created_at)
                phone = order.client_phone or "📲 TG"
                # Используем SERVICE_NAMES для перевода названия услуги
                service_display = SERVICE_NAMES.get(order.service_type, order.service_type or '—')
                text += f"📦 {formatted} — {order.client_name or 'Аноним'}\n🛠 _{service_display}_\n📞 {phone}\n\n"
                keyboard.append([
                    InlineKeyboardButton(
                        f"📦 {formatted}",
                        callback_data=f"admin_view_{order.id}")
                ])
            keyboard.append([
                InlineKeyboardButton("◀️ Назад",
                                     callback_data="admin_back_menu")
            ])
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown")
        except Exception:
            logger.exception("Ошибка получения заказов по статусу")
            await query.edit_message_text(
                "❌ Ошибка при получении заказов.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад",
                                         callback_data="admin_back_menu")
                ]]))
        return

    if data.startswith("admin_view_"):
        await admin_view_order(update, context)
        return

    if data.startswith("status_"):
        await change_order_status(update, context)
        return

    if data.startswith("contact_client_"):
        await contact_client(update, context)
        return

    if data.startswith("status_deleted_"):
        try:
            order_id = int(data.replace("status_deleted_", ""))
            from utils.database import delete_order
            if delete_order(order_id):
                await query.answer("✅ Заказ удален")
                await query.message.edit_text(f"🗑 Заказ #{order_id} был удален из базы данных.")
            else:
                await query.answer("❌ Ошибка при удалении", show_alert=True)
        except Exception as e:
            logger.error(f"Error deleting order: {e}")
            await query.answer("❌ Ошибка", show_alert=True)
        return

    await query.answer("Неизвестное действие.", show_alert=True)


async def admin_view_order(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """Просмотр заказа с кнопками управления"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    try:
        order_id = int(query.data.replace("admin_view_", ""))
    except Exception:
        await query.answer("❌ Неверный ID заказа", show_alert=True)
        return

    order = get_order(order_id)
    if not order:
        await query.answer("❌ Заказ не найден", show_alert=True)
        return

    from handlers.orders import format_order_id, WORKSHOP_ADDRESS, WORKSHOP_PHONE, SERVICE_NAMES
    formatted = format_order_id(order.id, order.created_at)
    
    # Перевод услуги на русский
    service_display = SERVICE_NAMES.get(order.service_type, order.service_type or '—')
    
    status_emoji = {
        "new": "🆕",
        "in_progress": "🔄",
        "completed": "✅",
        "cancelled": "❌",
        "issued": "📤",
        "spam": "🚫",
    }.get(str(order.status), "❓")
    
    status_text_display = {
        "new": "Новый",
        "in_progress": "В работе",
        "completed": "Готов",
        "issued": "Выдан",
        "cancelled": "Отменён",
        "spam": "Спам"
    }.get(str(order.status), str(order.status))

    # Кнопки детального управления (В работу, Выполнен, Удалить)
    keyboard = get_admin_order_detail_keyboard(order.id, order.status)
    
    phone_display = order.client_phone if order.client_phone and order.client_phone != "Telegram" else "📲 Telegram"

    text = (
        f"📦 *Заказ {formatted}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 *Статус:* {status_emoji} {status_text_display}\n"
        f"🏷 *Услуга:* {service_display}\n"
        f"👤 *Клиент:* {order.client_name or 'Аноним'}\n"
        f"📞 *Телефон:* {phone_display}\n"
        f"📝 *Описание:* {order.description or 'Нет описания'}\n"
        f"📅 *Дата:* {order.created_at.strftime('%d.%m.%Y %H:%M') if order.created_at else 'Н/Д'}\n"
    )
    
    try:
        # Пытаемся удалить сообщение со списком или старое сообщение заказа
        try:
            await query.message.delete()
        except Exception:
            pass

        if order.photo_file_id:
            await context.bot.send_photo(
                chat_id=user_id,
                photo=order.photo_file_id,
                caption=text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error in admin_view_order display: {e}")
        # Если удаление не сработало или возникла ошибка, пробуем просто редактировать текст (если это не фото-сообщение)
        try:
            await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard, parse_mode="Markdown")
    return

    # Кнопки детального управления (В работу, Выполнен, Удалить)
    keyboard = get_admin_order_detail_keyboard(order.id, order.status)
    
    text = (
        f"📦 *Заказ {formatted}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 *Статус:* {status_emoji} {status_text_display}\n"
        f"🏷 *Услуга:* {order.service_type or '—'}\n"
        f"👤 *Клиент:* {order.client_name or 'Аноним'}\n"
        f"📞 *Телефон:* {order.client_phone or '—'}\n"
        f"📝 *Описание:* {order.description or 'Нет описания'}\n"
        f"📅 *Дата:* {order.created_at.strftime('%d.%m.%Y %H:%M') if order.created_at else 'Н/Д'}\n"
    )
    try:
        if getattr(query.message, "photo", None) or order.photo_file_id:
            try:
                await query.message.delete()
            except Exception:
                pass
            if order.photo_file_id:
                await context.bot.send_photo(chat_id=query.message.chat_id,
                                             photo=order.photo_file_id,
                                             caption=text,
                                             reply_markup=keyboard,
                                             parse_mode="Markdown")
            else:
                await context.bot.send_message(chat_id=query.message.chat_id,
                                               text=text,
                                               reply_markup=keyboard,
                                               parse_mode="Markdown")
        else:
            await query.edit_message_text(text,
                                          reply_markup=keyboard,
                                          parse_mode="Markdown")
    except Exception:
        logger.exception("Ошибка при отображении заказа админом")
        await query.edit_message_text(text,
                                      reply_markup=keyboard,
                                      parse_mode="Markdown")


async def change_order_status(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    """Изменение статуса заказа админом"""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if not is_user_admin(user.id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    data = query.data or ""
    parts = data.split("_")
    if len(parts) < 3:
        await query.answer("❌ Неверный формат данных", show_alert=True)
        return

    try:
        new_status = parts[1] if parts[0] == "status" else parts[1]
        order_id = int(parts[-1])
    except Exception:
        await query.answer("❌ Неверный ID заказа", show_alert=True)
        return

    mapping = {
        "in": "in_progress",
        "inprogress": "in_progress",
        "in_progress": "in_progress",
        "completed": "completed",
        "issued": "issued",
        "cancelled": "cancelled",
        "cancel": "cancelled",
    }
    new_status_norm = mapping.get(new_status, new_status)

    try:
        updated = update_order_status(order_id, new_status_norm)
    except Exception:
        logger.exception("Ошибка при обновлении статуса заказа в БД")
        await query.answer("❌ Ошибка при обновлении статуса", show_alert=True)
        return

    if not updated:
        await query.answer("❌ Заказ не найден или не обновлён",
                           show_alert=True)
        return

    order = get_order(order_id)
    try:
        from handlers.orders import format_order_id
        formatted = format_order_id(
            order.id, order.created_at) if order else f"#{order_id}"
        client_msgs = {
            "in_progress": f"✂️ Ваша вещь в работе.\nЗаказ: {formatted}",
            "completed":
            f"🎉 Заказ готов!\nЗаказ: {formatted}\nПриходите за выдачей.",
            "issued": f"📤 Заказ выдан.\nЗаказ: {formatted}",
            "cancelled": f"❌ Заказ отменён.\nЗаказ: {formatted}",
            "new": f"🆕 Ваш заказ зарегистрирован: {formatted}"
        }
        client_text = client_msgs.get(
            new_status_norm, f"📦 Статус заказа обновлён: {new_status_norm}")
        if order and getattr(order, "user_id", None):
            try:
                await context.bot.send_message(chat_id=order.user_id,
                                               text=client_text)
            except Exception:
                logger.warning(
                    f"Не удалось уведомить пользователя {order.user_id}")
    except Exception:
        logger.exception(
            "Ошибка при уведомлении клиента после изменения статуса")

    try:
        status_text_map = {
            "in_progress": "🔄 В работе",
            "completed": "✅ Готов",
            "issued": "📤 Выдан",
            "cancelled": "❌ Отменён",
            "new": "🆕 Новый"
        }
        status_text = status_text_map.get(new_status_norm, new_status_norm)
        admin_name = user.username or user.first_name or str(user.id)
        formatted_id = f"#{order_id}"
        try:
            from handlers.orders import format_order_id
            if order:
                formatted_id = format_order_id(order.id, order.created_at)
        except Exception:
            pass
        new_text = f"✅ Заказ {formatted_id} обновлён\n\n{status_text}\n\n👤 Обновил: @{admin_name}"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ К списку заказов",
                                 callback_data="admin_orders_menu")
        ]])
        if query.message and getattr(query.message, "photo", None):
            try:
                await query.message.edit_caption(caption=new_text,
                                                 reply_markup=keyboard)
            except Exception:
                await query.edit_message_text(text=new_text,
                                              reply_markup=keyboard)
        else:
            await query.edit_message_text(text=new_text, reply_markup=keyboard)
    except Exception:
        logger.exception(
            "Ошибка при обновлении сообщения админа после смены статуса")


async def contact_client(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запустить отправку следующего сообщения клиенту через бота."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    try:
        order_id = int(query.data.replace("contact_client_", ""))
    except Exception:
        await query.answer("❌ Неверный ID заказа", show_alert=True)
        return

    order = get_order(order_id)
    if not order:
        await query.answer("❌ Заказ не найден", show_alert=True)
        return

    if not order.user_id:
        await query.answer("❌ У заказа нет Telegram-пользователя", show_alert=True)
        return

    context.user_data["reply_mode"] = True
    context.user_data["reply_to_user"] = order.user_id
    phone = order.client_phone or "Не указан"
    buttons = [[
        InlineKeyboardButton("❌ Отмена", callback_data="reply_cancel")
    ], [
        InlineKeyboardButton("◀️ Назад",
                             callback_data=f"admin_view_{order_id}")
    ])
    await query.edit_message_text(
        f"✉️ *Ответ клиенту через бота*\n\n"
        f"👤 {order.client_name or 'Не указано'}\n"
        f"📞 {phone}\n\n"
        f"Введите следующим сообщением текст для клиента.\n"
        f"Сообщение будет отправлено от имени бота.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons))


async def open_web_admin(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """Открытие веб-админки"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_user_admin(user_id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    url = _get_web_admin_orders_url()
    if not url:
        await query.answer("❌ Веб-панель не настроена", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🌐 Открыть веб-админку", url=url)],
         [InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")]])
    await query.edit_message_text(f"🌐 *Веб-панель администратора*\n\n{url}",
                                  reply_markup=keyboard,
                                  parse_mode="Markdown")


# ---------------- Вспомогательные функции ----------------


def get_admin_menu_keyboard(
        stats: Optional[dict] = None) -> InlineKeyboardMarkup:
    """Клавиатура админ-меню (с метриками)"""
    if stats is None:
        try:
            stats = get_statistics()
        except Exception:
            stats = {}
    new_count = stats.get("new_orders", 0)
    in_progress = stats.get("in_progress", 0)
    completed = stats.get("completed", 0)
    issued = stats.get("issued", 0)
    keyboard = [
        [
            InlineKeyboardButton(f"🆕 Новые ({new_count})",
                                 callback_data="admin_orders_new"),
            InlineKeyboardButton(f"🔄 В работе ({in_progress})",
                                 callback_data="admin_orders_in_progress")
        ],
        [
            InlineKeyboardButton(f"✅ Готовые ({completed})",
                                 callback_data="admin_orders_completed"),
            InlineKeyboardButton(f"📤 Выданные ({issued})",
                                 callback_data="admin_orders_issued")
        ],
        [
            InlineKeyboardButton("👥 Клиенты", callback_data="admin_clients"),
            InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton("🌐 Веб-админка",
                                 callback_data="open_web_admin"),
            InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
