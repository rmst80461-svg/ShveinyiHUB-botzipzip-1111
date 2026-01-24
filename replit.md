# Швейный HUB - Telegram Bot for Sewing Workshop

## Overview

This is a production-ready Telegram bot for a sewing workshop ("Швейная мастерская") called "Швейный HUB". The bot handles customer orders, provides service information and pricing, integrates with GigaChat AI for natural language responses, and includes a Flask-based admin panel for order management.

**Core Purpose:**
- Accept and track sewing/repair orders from customers
- Provide automated responses about services, pricing, and FAQ
- AI-powered conversational support using GigaChat (Sber AI)
- Admin web interface for order and user management
- Anti-spam protection system

## User Preferences

Preferred communication style: Simple, everyday language (Russian).

## Recent Changes (January 2026)

### Analytics Feature (January 24, 2026)
- **Таблица Events**: Новая таблица для отслеживания действий пользователей
- **Воронка конверсии**: Визуализация пути от запуска бота до заказа
- **Страница аналитики** в веб-админке (/analytics):
  - Метрики: новые пользователи, вернувшиеся, конверсия
  - Воронка оформления заказа по шагам
  - Статистика отказов на каждом шаге
  - График заказов и активности по дням (Chart.js)
- **Отслеживаемые события**:
  - `bot_started` - запуск бота
  - `order_started` - начало оформления
  - `order_category_selected` - выбор категории
  - `order_description_added` - добавление описания
  - `order_photo_added` / `order_photo_skipped` - фото
  - `order_name_added` - ввод имени
  - `order_phone_added` / `order_phone_skipped` - телефон
  - `order_completed` - заказ оформлен
  - `order_abandoned` - отмена заказа

### Latest Fixes (January 24, 2026)
- **Ссылка на карту в контактах**: Добавлена ссылка на Яндекс Карты в меню "Контакты"
- **GigaChat промпт обновлён**: Инструкции для отзывов и маршрутов с автоматической ссылкой
- **Авторизация веб-админки исправлена**: 
  - Постоянный ключ сессии (не сбрасывается при перезапуске)
  - Сессия на 7 дней
  - Не слетает при переключении вкладок

### Client Notifications (January 23, 2026)
- **Персонализированные уведомления** с именем клиента и номером заказа
- **"В работе"**: Подробное сообщение с описанием процесса от Иголочки
- **"Готов к выдаче"**: Полная информация с часами работы, адресом, контактами
- **Отзывы только на Яндекс**: Убраны внутренние звёзды, собираем отзывы только на Яндекс Картах
- Подпись: "Ваша мастерская «Швейный HUB»"

### Deployment Architecture
- **Bothost.ru**: Runs bot + web panel together (`run_services.py`)
- **Replit**: Development environment, can run web panel separately (`run_webapp.py`)
- PWA support added - web panel can be installed as mobile app
- Procfile: `web: python run_services.py`

### Order System Updates
- Category "Другое" (Other) with custom description flow
- Paginated order management (8 orders per page)
- Filter by status: New, In Progress, Completed, Issued
- Search by order ID or client name
- Quick status change without leaving the page

### Bug Fixes
- Fixed "Inline keyboard expected" error in admin navigation
- Fixed GigaChat being called during broadcast message input
- Resolved polling conflict between Replit and Bothost

## Deployment Configuration

### Bothost.ru (Production)
```
Procfile: web: python run_services.py
```
- Runs both Telegram bot and web admin panel
- Requires Basic plan (99₽/month) or higher for web access
- Environment variables: BOT_TOKEN, GIGACHAT_CREDENTIALS, DATABASE_URL, ADMIN_ID

### Replit (Development/Alternative)
```
Workflow: python run_webapp.py (web panel only)
```
- Use when bot runs on external server
- Avoids polling conflict

### Key Files
| File | Purpose |
|------|---------|
| `run_services.py` | Runs bot + web panel together |
| `run_webapp.py` | Runs only web panel (no bot) |
| `main.py` | Telegram bot only |

## System Architecture

### Bot Framework
- **python-telegram-bot v20.7** - Modern async Telegram bot framework
- Uses conversation handlers for multi-step order creation flow
- Inline keyboards for navigation, persistent reply keyboard for menu access
- Dual-role interface: regular users see customer menu, admins see management panel

### AI Integration
- **GigaChat (Sber)** - Russian language AI model for natural conversations
- Response caching system to reduce API calls and costs
- Fallback to knowledge base when AI is unavailable
- Broadcast mode bypasses AI processing

### Database Layer
- **SQLAlchemy ORM** with support for both SQLite and PostgreSQL
- Primary tables: Orders, Users, Reviews, SpamLog, Category, Price
- Environment variable `DATABASE_URL` controls database connection
- Default: SQLite for development, Postgres-ready for production

### Web Admin Panel
- **Flask 3.0** with Jinja2 templates
- HTTP Basic Authentication with password hashing (Werkzeug)
- CSRF protection via Flask-WTF (exempted for API endpoints)
- PWA support (manifest.json, icons) for mobile installation
- Features: order management, user listing, spam logs, review moderation, statistics dashboard, CSV export

### Anti-Spam System
- Rate limiting (5 messages per minute default)
- Blacklist/whitelist word detection
- Automatic muting for spammers
- Profanity filter for reviews with leetspeak normalization

### Knowledge Base
- Text files in `data/knowledge_base/` directory
- Categories: pricing, FAQ, contacts, services, policies
- Used for AI context and fallback responses

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `BOT_TOKEN` | Telegram bot token |
| `GIGACHAT_CREDENTIALS` | GigaChat API credentials |
| `DATABASE_URL` | Database connection string |
| `ADMIN_ID` or `ADMIN_IDS` | Telegram user ID(s) for admin access (comma-separated for multiple) |
| `ADMIN_PASSWORD` | Web admin panel password |
| `FLASK_SECRET_KEY` | Flask session encryption |

## File Structure
```
├── main.py                 # Telegram bot entry point
├── run_services.py         # Bot + Web panel launcher
├── run_webapp.py           # Web panel only launcher
├── Procfile                # Bothost deployment config
├── keyboards.py            # Telegram keyboard layouts
├── handlers/               # Telegram command handlers
│   ├── admin.py            # Admin panel handlers
│   ├── admin_orders.py     # Order management with pagination
│   ├── orders.py           # Order creation flow
│   └── messages.py         # Message processing
├── utils/                  # Utilities
│   ├── database.py         # SQLAlchemy models
│   ├── gigachat_utils.py   # AI integration
│   └── anti_spam.py        # Spam protection
├── webapp/                 # Flask admin application
│   ├── app.py              # Flask routes
│   ├── templates/          # HTML templates
│   └── static/             # CSS, JS, PWA assets
└── data/knowledge_base/    # Service information files
```
