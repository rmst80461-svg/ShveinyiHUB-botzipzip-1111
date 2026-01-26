import os
import sys
import time
import logging
import subprocess

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_services():
    """Запуск бота и веб-панели параллельно"""
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    port = os.environ.get('PORT', '8080')
    
    # 1. Запуск веб-панели через gunicorn
    logger.info(f"Запуск веб-админки на порту {port} через gunicorn...")
    webapp_process = subprocess.Popen(
        [
            sys.executable, "-m", "gunicorn",
            "--bind", f"0.0.0.0:{port}",
            "--workers", "2",
            "--timeout", "120",
            "--access-logfile", "-",
            "--error-logfile", "-",
            "webapp.app:app"
        ],
        cwd=base_dir,
        env={**os.environ, "PORT": port}
    )

    # 2. Запуск Telegram бота
    logger.info("Запуск Telegram бота...")
    bot_process = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=base_dir,
        env={**os.environ, "SKIP_FLASK": "1"}
    )

    try:
        while True:
            if webapp_process.poll() is not None:
                logger.error("Процесс веб-панели завершился! Перезапуск...")
                webapp_process = subprocess.Popen(
                    [
                        sys.executable, "-m", "gunicorn",
                        "--bind", f"0.0.0.0:{port}",
                        "--workers", "2",
                        "--timeout", "120",
                        "--access-logfile", "-",
                        "--error-logfile", "-",
                        "webapp.app:app"
                    ],
                    cwd=base_dir,
                    env={**os.environ, "PORT": port}
                )
            
            if bot_process.poll() is not None:
                logger.error("Процесс бота завершился! Перезапуск...")
                bot_process = subprocess.Popen(
                    [sys.executable, "main.py"],
                    cwd=base_dir,
                    env={**os.environ, "SKIP_FLASK": "1"}
                )
                
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Остановка сервисов...")
        webapp_process.terminate()
        bot_process.terminate()

if __name__ == "__main__":
    run_services()
