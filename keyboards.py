from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove


def get_persistent_menu() -> ReplyKeyboardMarkup:
    """Одна кнопка меню внизу экрана."""
    keyboard = [[KeyboardButton("☰ Меню")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


def remove_keyboard() -> ReplyKeyboardRemove:
    """Убрать клавиатуру."""
    return ReplyKeyboardRemove()


def get_main_menu() -> InlineKeyboardMarkup:
    """Главное меню бота."""
    buttons = [
        [InlineKeyboardButton("📋 Услуги и цены", callback_data="services")],
        [InlineKeyboardButton("➕ Создать заказ", callback_data="new_order")],
        [InlineKeyboardButton("🔍 Статус заказа", callback_data="check_status")],
        [InlineKeyboardButton("❓ FAQ", callback_data="faq")],
        [InlineKeyboardButton("📍 Контакты", callback_data="contacts")],
    ]
    return InlineKeyboardMarkup(buttons)


def get_prices_menu() -> InlineKeyboardMarkup:
    """Меню выбора категории цен."""
    buttons = [
        [InlineKeyboardButton("🧥 Ремонт пиджака", callback_data="price_jacket")],
        [InlineKeyboardButton("🎒 Изделия из кожи", callback_data="price_leather")],
        [InlineKeyboardButton("🪟 Пошив штор", callback_data="price_curtains")],
        [InlineKeyboardButton("🧥 Ремонт куртки", callback_data="price_coat")],
        [InlineKeyboardButton("🐾 Шубы и дублёнки", callback_data="price_fur")],
        [InlineKeyboardButton("🧥 Плащ/пальто", callback_data="price_outerwear")],
        [InlineKeyboardButton("👖 Брюки/джинсы", callback_data="price_pants")],
        [InlineKeyboardButton("👗 Юбки/платья", callback_data="price_dress")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_menu")],
    ]
    return InlineKeyboardMarkup(buttons)


def get_services_menu() -> InlineKeyboardMarkup:
    """Меню услуг для заказа."""
    buttons = [
        [InlineKeyboardButton("🧥 Ремонт пиджака", callback_data="service_jacket")],
        [InlineKeyboardButton("🎒 Изделия из кожи", callback_data="service_leather")],
        [InlineKeyboardButton("🪟 Пошив штор", callback_data="service_curtains")],
        [InlineKeyboardButton("🧥 Ремонт куртки", callback_data="service_coat")],
        [InlineKeyboardButton("🐾 Шубы и дублёнки", callback_data="service_fur")],
        [InlineKeyboardButton("🧥 Плащ/пальто", callback_data="service_outerwear")],
        [InlineKeyboardButton("👖 Брюки/джинсы", callback_data="service_pants")],
        [InlineKeyboardButton("👗 Юбки/платья", callback_data="service_dress")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_menu")],
    ]
    return InlineKeyboardMarkup(buttons)


def get_faq_menu() -> InlineKeyboardMarkup:
    """Меню FAQ."""
    buttons = [
        [InlineKeyboardButton("📋 Какие услуги?", callback_data="faq_services")],
        [InlineKeyboardButton("💰 Цены на ремонт", callback_data="faq_prices")],
        [InlineKeyboardButton("⏰ Сроки выполнения", callback_data="faq_timing")],
        [InlineKeyboardButton("📍 Адрес и график", callback_data="faq_location")],
        [InlineKeyboardButton("💳 Оплата и гарантия", callback_data="faq_payment")],
        [InlineKeyboardButton("📝 Как оформить заказ?", callback_data="faq_order")],
        [InlineKeyboardButton("❓ Другое", callback_data="faq_other")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_menu")],
    ]
    return InlineKeyboardMarkup(buttons)


def get_back_button() -> InlineKeyboardMarkup:
    """Кнопка назад в меню."""
    buttons = [[InlineKeyboardButton("◀️ Главное меню", callback_data="back_menu")]]
    return InlineKeyboardMarkup(buttons)


def get_ai_response_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для ответа AI."""
    buttons = [
        [InlineKeyboardButton("📝 Оформить заказ", callback_data="new_order")],
        [InlineKeyboardButton("◀️ В меню", callback_data="back_menu")]
    ]
    return InlineKeyboardMarkup(buttons)


def get_admin_main_menu() -> InlineKeyboardMarkup:
    """Главное меню админа."""
    buttons = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("📦 Управление заказами", callback_data="admin_orders")],
        [InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton("◀️ Выйти из админки", callback_data="back_menu")],
    ]
    return InlineKeyboardMarkup(buttons)
