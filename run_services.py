import os
import sys
import time
import logging
import threading
import subprocess

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def run_webapp():
    """Запуск веб-панели Flask напрямую"""
    from webapp.app import app
    port = int(os.environ.get('PORT', 3000))
    logger.info(f"Запуск веб-админки на порту {port}...")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def run_bot():
    """Запуск Telegram бота"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    logger.info("Запуск Telegram бота...")
    
    while True:
        try:
            process = subprocess.Popen(
                [sys.executable, "main.py"],
                cwd=base_dir
            )
            process.wait()
            logger.error("Процесс бота завершился! Перезапуск через 5 секунд...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Ошибка запуска бота: {e}")
            time.sleep(5)

def run_services():
    """Запуск бота и веб-панели параллельно"""
    
    # Запуск веб-панели в отдельном потоке
    webapp_thread = threading.Thread(target=run_webapp, daemon=True)
    webapp_thread.start()
    
    # Небольшая пауза перед запуском бота
    time.sleep(3)
    
    # Запуск бота (в основном потоке)
    run_bot()

if __name__ == "__main__":
    run_services()
