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

Preferred communication style: Simple, everyday language.

## Recent Changes (January 2026)
- New paginated order management system (8 orders per page)
- Filter by status: New, In Progress, Completed, Issued  
- Search by order ID or client name
- Quick status change without leaving the page
- New callback patterns: `olist_`, `odetail_`, `ostatus_`, `odelete_`, `osearch_`
- New file: `handlers/admin_orders.py` — пагинация и поиск заказов

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
- Adaptive prompts based on user context and question complexity

### Database Layer
- **SQLAlchemy ORM** with support for both SQLite and PostgreSQL
- Primary tables: Orders, Users, Reviews, SpamLog, Category, Price
- Environment variable `DATABASE_URL` controls database connection
- Default: SQLite for development, Postgres-ready for production

### Web Admin Panel
- **Flask 3.0** with Jinja2 templates
- HTTP Basic Authentication with password hashing (Werkzeug)
- CSRF protection via Flask-WTF (exempted for API endpoints)
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

### Health Check Server
- Built-in HTTP server on port 8080 for uptime monitoring
- Returns JSON status for deployment health checks

## External Dependencies

### APIs & Services
- **Telegram Bot API** - Core bot functionality (requires `BOT_TOKEN`)
- **GigaChat API** - AI responses (requires `GIGACHAT_CREDENTIALS`)

### Python Packages
- `python-telegram-bot` - Telegram integration
- `gigachat` - Sber AI client
- `sqlalchemy` + `psycopg2-binary` - Database ORM and PostgreSQL driver
- `flask` + `flask-wtf` - Web admin interface
- `python-dotenv` - Environment configuration
- `gunicorn` - Production WSGI server
- `requests` - HTTP client for notifications

### Environment Variables
| Variable | Purpose |
|----------|---------|
| `BOT_TOKEN` | Telegram bot token |
| `GIGACHAT_CREDENTIALS` | GigaChat API credentials |
| `DATABASE_URL` | Database connection string |
| `ADMIN_ID` | Telegram user ID for admin access |
| `ADMIN_PASSWORD` | Web admin panel password |
| `FLASK_SECRET_KEY` | Flask session encryption |

### File Structure
- `/handlers/` - Telegram command and message handlers
- `/utils/` - Database, AI, anti-spam, caching utilities
- `/webapp/` - Flask admin application
- `/templates/` - HTML templates for web interface
- `/data/knowledge_base/` - Text files with service information