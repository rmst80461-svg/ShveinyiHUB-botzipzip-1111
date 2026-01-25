import os
import subprocess
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_services():
    """Запуск бота и веб-панели параллельно"""
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Запуск веб-панели (Flask) на порту 3000 для Bothost
    logger.info("Запуск веб-админки на порту 3000...")
    webapp_process = subprocess.Popen(
        [sys.executable, "-m", "flask", "run", "--host=0.0.0.0", "--port=3000", "--no-debugger", "--no-reload"],
        env={**os.environ, "FLASK_APP": "webapp/app.py", "PORT": "3000"},
        cwd=base_dir
    )

    # 2. Запуск Telegram бота
    logger.info("Запуск Telegram бота...")
    time.sleep(5) 
    bot_process = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=base_dir
    )

    try:
        while True:
            if webapp_process.poll() is not None:
                logger.error("Процесс веб-панели завершился! Перезапуск...")
                webapp_process = subprocess.Popen(
                    [sys.executable, "-m", "flask", "run", "--host=0.0.0.0", "--port=3000"],
                    env={**os.environ, "FLASK_APP": "webapp/app.py", "PORT": "3000"},
                    cwd=base_dir
                )
            
            if bot_process.poll() is not None:
                logger.error("Процесс бота завершился! Перезапуск...")
                bot_process = subprocess.Popen(
                    [sys.executable, "main.py"],
                    cwd=base_dir
                )
                
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Остановка сервисов...")
        webapp_process.terminate()
        bot_process.terminate()

if __name__ == "__main__":
    run_services()
