#!/usr/bin/env python3
"""
Run only the web admin panel (without Telegram bot).
Use this when the bot is deployed on a separate server (e.g., Bothost).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.database import init_db
init_db()

from webapp.app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting web admin panel on port {port}...")
    print("Bot is NOT started - use this when bot runs on external server")
    app.run(host="0.0.0.0", port=port, debug=False)
