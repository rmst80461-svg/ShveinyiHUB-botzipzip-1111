FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN echo "=== Проверка установленных пакетов ===" && \
    pip show python-dotenv | grep -E "Name|Version" && \
    pip show python-telegram-bot | grep -E "Name|Version" && \
    pip show requests | grep -E "Name|Version" && \
    echo "=== Проверка python-dotenv ===" && \
    python -c 'import dotenv; print("✅ python-dotenv установлен")'

RUN pip cache purge || true

COPY . .

RUN mkdir -p /app/data && chmod 777 /app/data

RUN chown -R 1000:1000 /app/data || true

EXPOSE 8080

CMD ["python", "run_services.py"]
