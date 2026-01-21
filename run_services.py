import os
import subprocess
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_services():
    """Запуск бота и веб-панели параллельно"""
    
    # Путь к текущей директории
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Запуск инициализации БД (если нужно)
    # try:
    #    logger.info("Инициализация базы данных...")
    #    subprocess.run([sys.executable, "init_db.py"], check=True)
    # except Exception as e:
    #    logger.error(f"Ошибка при инициализации БД: {e}")

    # 2. Запуск веб-панели (Flask)
    # Используем gunicorn для продакшена или flask run для дева
    # Using port 5001 to avoid conflict with other services
    logger.info("Запуск веб-админки на порту 5001...")
    webapp_process = subprocess.Popen(
        [sys.executable, "-m", "flask", "run", "--host=0.0.0.0", "--port=5001"],
        env={**os.environ, "FLASK_APP": "webapp/app.py", "PORT": "5001"},
        cwd=base_dir
    )

    # 3. Запуск Telegram бота
    logger.info("Запуск Telegram бота...")
    time.sleep(20)  # Максимальная пауза для гарантированного закрытия старых соединений
    bot_process = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=base_dir
    )

    try:
        # Держим скрипт запущенным, пока работают процессы
        while True:
            if webapp_process.poll() is not None:
                logger.error("Процесс веб-панели завершился! Перезапуск...")
                webapp_process = subprocess.Popen(
                    [sys.executable, "-m", "flask", "run", "--host=0.0.0.0", "--port=5001"],
                    env={**os.environ, "FLASK_APP": "webapp/app.py", "PORT": "5001"},
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
