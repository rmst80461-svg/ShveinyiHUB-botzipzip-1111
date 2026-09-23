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

        return

    add_user(user_id=user_id,
             username=user.username,
             first_name=user.first_name,
             last_name=user.last_name)

    if is_user_blocked(user_id):
        logger.warning(
            f"Заблокированный пользователь {user_id} пытался отправить сообщение"
        )
        await update.message.reply_text(
            "🚫 Ваш доступ к боту ограничен. Пожалуйста, свяжитесь с администратором."
        )
        return

    is_spam, spam_reason = anti_spam.is_spam(user_id, text)
    if is_spam:
        logger.warning(f"Спам от {user_id}: {spam_reason}")
        await update.message.reply_text(
            f"⚠️ {spam_reason}\n\nПожалуйста, подождите немного перед следующим сообщением.",
            reply_markup=get_main_menu())
        return

    if len(text) > MAX_MESSAGE_LENGTH:
        await update.message.reply_text(
            f"📝 Ваше сообщение слишком длинное ({len(text)} символов). "
            f"Пожалуйста, сократите его до {MAX_MESSAGE_LENGTH} символов.")
        return

    user_info = get_user_info(user_id)
    username = getattr(user_info, 'username', None) if user_info else None
    first_name = getattr(user_info, 'first_name', None) if user_info else None
    if username:
        username_display = f"@{username}"
    elif first_name:
        username_display = first_name
    else:
        username_display = f"Пользователь {user_id}"
    logger.info(
        f"Сообщение от {username_display} (ID: {user_id}): {text[:100]}..."
    )

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except Exception as e:
        logger.warning(f"Не удалось отправить ChatAction: {e}")

    try:
        review_keywords = ['отзыв', 'отзывы', 'как оставить отзыв', 'где оставить отзыв', 'написать отзыв', 'оставить отзыв']
        if any(keyword in text.lower() for keyword in review_keywords):
            response = "Будем очень благодарны за ваш отзыв! Вы можете оставить его на Яндекс Картах по ссылке: https://yandex.ru/maps/org/shveyny_hub/1233246900/reviews/"
            keyboard = get_ai_response_keyboard()
        else:
            response, needs_human = await get_ai_response(text, user_id)
            keyboard = get_ai_response_keyboard()

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
