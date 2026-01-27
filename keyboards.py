from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove


def get_persistent_menu() -> ReplyKeyboardMarkup:
    """Одна кнопка меню внизу экрана."""
    keyboard = [[KeyboardButton("☰ Меню")]]
    return ReplyKeyboardMarkup(keyboard,
                               resize_keyboard=True,
                               one_time_keyboard=False)


def remove_keyboard() -> ReplyKeyboardRemove:
    """Убрать клавиатуру."""
    return ReplyKeyboardRemove()


def get_main_menu() -> InlineKeyboardMarkup:
    """Главное меню бота."""
    buttons = [
        [InlineKeyboardButton("📋  Услуги и цены           ", callback_data="services")],
        [InlineKeyboardButton("➕  Создать заказ            ", callback_data="new_order")],
        [InlineKeyboardButton("🔍  Статус заказа            ", callback_data="check_status")],
        [InlineKeyboardButton("❓  Частые вопросы          ", callback_data="faq")],
        [InlineKeyboardButton("📍  Контакты                    ", callback_data="contacts")],
    ]
    return InlineKeyboardMarkup(buttons)


def get_prices_menu() -> InlineKeyboardMarkup:
    """Меню выбора категории цен."""
    buttons = [
        [InlineKeyboardButton("🧥  Ремонт пиджака          ", callback_data="price_jacket")],
        [InlineKeyboardButton("🎒  Изделия из кожи          ", callback_data="price_leather")],
        [InlineKeyboardButton("🪟  Пошив штор                  ", callback_data="price_curtains")],
        [InlineKeyboardButton("🧥  Ремонт куртки             ", callback_data="price_coat")],
        [InlineKeyboardButton("🐾  Шубы и дублёнки        ", callback_data="price_fur")],
        [InlineKeyboardButton("🧥  Плащ / пальто              ", callback_data="price_outerwear")],
        [InlineKeyboardButton("👖  Брюки / джинсы            ", callback_data="price_pants")],
        [InlineKeyboardButton("👗  Юбки / платья               ", callback_data="price_dress")],
        [InlineKeyboardButton("◀️  Назад в меню              ", callback_data="back_menu")],
    ]
    return InlineKeyboardMarkup(buttons)


def get_services_menu() -> InlineKeyboardMarkup:
    """Меню услуг для заказа."""
    buttons = [
        [InlineKeyboardButton("🧥  Ремонт пиджака          ", callback_data="service_jacket")],
        [InlineKeyboardButton("🎒  Изделия из кожи          ", callback_data="service_leather")],
        [InlineKeyboardButton("🪟  Пошив штор                  ", callback_data="service_curtains")],
        [InlineKeyboardButton("🧥  Ремонт куртки             ", callback_data="service_coat")],
        [InlineKeyboardButton("🐾  Шубы и дублёнки        ", callback_data="service_fur")],
        [InlineKeyboardButton("🧥  Плащ / пальто              ", callback_data="service_outerwear")],
        [InlineKeyboardButton("👖  Брюки / джинсы            ", callback_data="service_pants")],
        [InlineKeyboardButton("👗  Юбки / платья               ", callback_data="service_dress")],
        [InlineKeyboardButton("❓  Другое                           ", callback_data="service_other")],
        [InlineKeyboardButton("◀️  Назад в меню              ", callback_data="back_menu")],
    ]
    return InlineKeyboardMarkup(buttons)


def get_faq_menu() -> InlineKeyboardMarkup:
    """Меню FAQ."""
    buttons = [
        [InlineKeyboardButton("📋  Какие услуги?               ", callback_data="faq_services")],
        [InlineKeyboardButton("💰  Цены на ремонт           ", callback_data="faq_prices")],
        [InlineKeyboardButton("⏰  Сроки выполнения       ", callback_data="faq_timing")],
        [InlineKeyboardButton("📍  Адрес и график            ", callback_data="faq_location")],
        [InlineKeyboardButton("💳  Оплата и гарантия       ", callback_data="faq_payment")],
        [InlineKeyboardButton("📝  Как оформить заказ?  ", callback_data="faq_order")],
        [InlineKeyboardButton("❓  Другой вопрос              ", callback_data="faq_other")],
        [InlineKeyboardButton("◀️  Назад в меню              ", callback_data="back_menu")],
    ]
    return InlineKeyboardMarkup(buttons)


def get_back_button() -> InlineKeyboardMarkup:
    """Кнопка назад в меню."""
    buttons = [[
        InlineKeyboardButton("◀️  Главное меню               ", callback_data="back_menu")
    ]]
    return InlineKeyboardMarkup(buttons)


def get_ai_response_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для ответа AI."""
    buttons = [
        [InlineKeyboardButton("📝  Оформить заказ            ", callback_data="new_order")],
        [InlineKeyboardButton("◀️  В меню                          ", callback_data="back_menu")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_admin_main_menu() -> ReplyKeyboardMarkup:
    """Главное меню админа (Reply Keyboard)."""
    keyboard = [
        [KeyboardButton("📊 Все заказы"), KeyboardButton("📈 Статистика")],
        [KeyboardButton("👥 Пользователи"), KeyboardButton("📢 Рассылка")],
        [KeyboardButton("❌ Удалить спам"), KeyboardButton("◀️ Выйти")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_admin_inline_menu() -> InlineKeyboardMarkup:
    """Инлайн меню админа (старое для совместимости или доп. функций)."""
    buttons = [
        [InlineKeyboardButton("📦 Управление через веб", callback_data="open_web_admin")],
    ]
    return InlineKeyboardMarkup(buttons)


def get_admin_orders_submenu() -> InlineKeyboardMarkup:
    """Подменю управления заказами."""
    buttons = [
        [
            InlineKeyboardButton("🆕 Новые заказы",
                                 callback_data="admin_orders_new")
        ],
        [
            InlineKeyboardButton("🔄 В процессе",
                                 callback_data="admin_orders_in_progress")
        ],
        [
            InlineKeyboardButton("✅ Завершенные",
                                 callback_data="admin_orders_completed")
        ],
        [
            InlineKeyboardButton("📤 Выданные",
                                 callback_data="admin_orders_issued")
        ],
        [InlineKeyboardButton("◀️ Назад", callback_data="admin_back_menu")],
    ]
    return InlineKeyboardMarkup(buttons)


def get_admin_back_menu() -> InlineKeyboardMarkup:
    """Кнопка назад в админ-панель."""
    buttons = [[
        InlineKeyboardButton("◀️ В админ-панель",
                             callback_data="admin_back_menu")
    ]]
    return InlineKeyboardMarkup(buttons)


def get_admin_order_detail_keyboard(order_id: int,
                                    order_status: str) -> InlineKeyboardMarkup:
    """Клавиатура для детального просмотра заказа."""
    buttons = []

    # Кнопки изменения статуса в зависимости от текущего статуса
    if order_status == 'new':
        buttons.append([
            InlineKeyboardButton(
                "🔄 В работу", callback_data=f"status_in_progress_{order_id}"),
            InlineKeyboardButton("❌ Отменить",
                                 callback_data=f"status_cancelled_{order_id}")
        ])
    elif order_status == 'in_progress':
        buttons.append([
            InlineKeyboardButton("✅ Готов",
                                 callback_data=f"status_completed_{order_id}"),
            InlineKeyboardButton("❌ Отменить",
                                 callback_data=f"status_cancelled_{order_id}")
        ])
    elif order_status == 'completed':
        buttons.append([
            InlineKeyboardButton("📤 Выдан",
                                 callback_data=f"status_issued_{order_id}"),
            InlineKeyboardButton("🗑 Удалить",
                                 callback_data=f"status_deleted_{order_id}")
        ])
    else:
        # Для отмененных, выданных и т.д. даем возможность удалить
        buttons.append([
            InlineKeyboardButton("🗑 Удалить заказ",
                                 callback_data=f"status_deleted_{order_id}")
        ])

    # Кнопка для связи с клиентом
    buttons.append([
        InlineKeyboardButton("✉️ Написать клиенту",
                             callback_data=f"contact_client_{order_id}")
    ])

    # Кнопка назад (определяем, в какой список вернуться)
    back_data = {
        'new': 'admin_orders_new',
        'in_progress': 'admin_orders_in_progress',
        'completed': 'admin_orders_completed',
        'issued': 'admin_orders_issued'
    }.get(order_status, 'admin_back_menu')

    buttons.append(
        [InlineKeyboardButton("◀️ Назад к списку", callback_data=back_data)])

    return InlineKeyboardMarkup(buttons)


def get_admin_orders_menu() -> InlineKeyboardMarkup:
    """Меню управления заказами (старое название для совместимости)."""
    return get_admin_orders_submenu()
