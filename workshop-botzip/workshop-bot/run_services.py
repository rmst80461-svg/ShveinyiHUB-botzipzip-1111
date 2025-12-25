        #!/usr/bin/env python3
rt subprocess
import sys
rt os
ignal
import time
import threading

        BOT_PROCESS = None
        WEB_PROCESS = None
        SHOULD_EXIT = False

        def signal_handler(sig, frame):
            global SHOULD_EXIT
            print("\n" + "="*50)
            print("=== Получена команда завершения ===")
            print("="*50)
            SHOULD_EXIT = True
            terminate_all()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        def terminate_all():
            """Завершить все процессы"""
            global BOT_PROCESS, WEB_PROCESS
            if BOT_PROCESS and BOT_PROCESS.poll() is None:
                BOT_PROCESS.terminate()
                try:
                    BOT_PROCESS.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    BOT_PROCESS.kill()
            if WEB_PROCESS and WEB_PROCESS.poll() is None:
                WEB_PROCESS.terminate()
                try:
                    WEB_PROCESS.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    WEB_PROCESS.kill()

        def run_service(service_name, command, restart_delay=5):
            """Запускать сервис с автоматическим перезапуском"""
            while not SHOULD_EXIT:
                try:
                    print(f"\n📱 Запуск {service_name}...")
                    process = subprocess.Popen(
                        command,
                        shell=True,
                        cwd=os.path.join(os.path.dirname(__file__), '.'),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        universal_newlines=True,
                        bufsize=1
                    )
                    print(f"✓ {service_name} запущен (PID: {process.pid})")

                    # Ждём завершения процесса
                    while not SHOULD_EXIT:
                        ret = process.poll()
                        if ret is not None:
                            if ret == 0:
                                print(f"⚠️ {service_name} завершился нормально (код {ret})")
                            else:
                                print(f"⚠️ {service_name} завершился с ошибкой (код {ret})")
                            break
                        time.sleep(1)

                    if not SHOULD_EXIT:
                        print(f"🔄 Перезапуск {service_name} через {restart_delay}с...")
                        time.sleep(restart_delay)
                except Exception as e:
                    print(f"✗ Ошибка при запуске {service_name}: {e}")
                    if not SHOULD_EXIT:
                        time.sleep(restart_delay)

        if __name__ == "__main__":
            print("="*50)
            print("🚀 ЗАПУСК ПРИЛОЖЕНИЯ ShveinyiHUB")
            print("="*50)

            # Запускаем сервисы в отдельных потоках
            print("\n🌐 Запуск Web Interface...")
            web_thread = threading.Thread(
                target=run_service,
                args=("Web Interface", "python -m gunicorn --bind 0.0.0.0:5000 --timeout 120 --workers 2 --keep-alive 75 webapp:app"),
                daemon=False
            )
            web_thread.start()

            time.sleep(2)  # Задержка перед запуском бота

            print("\n📱 Запуск Telegram Bot...")
            bot_thread = threading.Thread(
                target=run_service,
                args=("Telegram Bot", "python main.py"),
                daemon=False
            )
            bot_thread.start()

            print("\n" + "="*50)
            print("✅ ВСЕ СЕРВИСЫ ЗАПУЩЕНЫ")
            print("="*50)
            print("📱 Telegram Bot: работает")
            print("🌐 Web Interface: http://0.0.0.0:5000")
            print(f"✓ ADMIN_ID: {os.getenv('ADMIN_ID', 'не установлен')}")
            print("\nДля остановки нажмите Ctrl+C")
            print("="*50 + "\n")

            # Ждём завершения
            try:
                while not SHOULD_EXIT:
                    time.sleep(1)
            except KeyboardInterrupt:
                signal_handler(None, None)

            # Ждём завершения потоков
            web_thread.join(timeout=10)
            bot_thread.join(timeout=10)

            print("\n" + "="*50)
            print("Приложение завершено")
            print("="*50)
            # Никогда не выходим с кодом 0, чтобы Cloud Run перезапустил контейнер
            sys.exit(1)