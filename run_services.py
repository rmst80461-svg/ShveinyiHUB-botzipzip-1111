#!/usr/bin/env python3
import os
import sys
import time
import logging
import subprocess

# Настройка логирования для вывода в консоль
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

def run_services():
    """Запуск бота и веб-панели параллельно"""
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    port = os.environ.get('PORT', '8080')
    
    # Принудительно выключаем буферизацию для всех дочерних процессов
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    # 1. Запуск веб-панели через Flask
    logger.info(f"Запуск веб-админки на порту {port}...")
    webapp_process = subprocess.Popen(
        [
            sys.executable, "-u", "-c",
            f"import os; from webapp.app import app; port = int(os.environ.get('PORT', {port})); print(f'Starting web admin panel on port {{port}}...'); app.run(host='0.0.0.0', port=port, debug=False, threaded=True)"
        ],
        cwd=base_dir,
        env={**env, "SKIP_BOT": "1", "FLASK_ENV": "production"}
    )
    
    # Даём Flask время на запуск
    time.sleep(5)

    # 2. Запуск Telegram бота
    logger.info("Запуск Telegram бота...")
    
    # Принудительно передаем все переменные окружения, включая те, что считали из .env
    bot_env = {**os.environ, "SKIP_FLASK": "1", "SKIP_BOT": "0", "PYTHONUNBUFFERED": "1", "FLASK_ENV": "production"}
    
    bot_process = subprocess.Popen(
        [sys.executable, "-u", "main.py"],
        cwd=base_dir,
        env=bot_env
    )
    
    # Даем боту время на запуск и логирование
    time.sleep(5)

    try:
        while True:
            # Проверка состояния процессов
            if webapp_process.poll() is not None:
                logger.error("Процесс веб-панели завершился! Перезапуск...")
                webapp_process = subprocess.Popen(
                    [sys.executable, "-u", "-c", f"from webapp.app import app; app.run(host='0.0.0.0', port={port})"],
                    cwd=base_dir,
                    env={**env, "SKIP_BOT": "1"}
                )
            
            if bot_process.poll() is not None:
                logger.error("Процесс бота завершился! Перезапуск...")
                bot_process = subprocess.Popen(
                    [sys.executable, "-u", "main.py"],
                    cwd=base_dir,
                    env={**env, "SKIP_FLASK": "1"}
                )
                
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Остановка сервисов...")
        webapp_process.terminate()
        bot_process.terminate()

if __name__ == "__main__":
    run_services()
