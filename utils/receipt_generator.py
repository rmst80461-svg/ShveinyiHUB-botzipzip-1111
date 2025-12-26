import os
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

RECEIPTS_DIR = Path(__file__).parent.parent / "receipts"
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

RECEIPTS_DIR.mkdir(exist_ok=True)

SERVICE_NAMES = {
    "knitwear": "🧵 Ремонт трикотажа",
    "leather": "🎒 Кожаные изделия",
    "fur": "🐾 Меховые изделия",
    "outerwear": "🧥 Верхняя одежда",
    "fitting": "📏 Подгонка по фигуре",
    "small_repair": "🔘 Мелкий ремонт",
    "artistic": "✂️ Художественная штопка",
    "urgent": "🚀 Срочные услуги"
}

def get_service_display_name(service_type: str) -> str:
    return SERVICE_NAMES.get(service_type, service_type or "Услуга")

def generate_receipt_html(order_id: int, client_name: str, client_phone: str, 
                         service_type: str, price: str = "По прайсу") -> str:
    template_path = TEMPLATES_DIR / "receipt.html"
    
    if not template_path.exists():
        logger.error(f"Receipt template not found: {template_path}")
        return None
    
    with open(template_path, 'r', encoding='utf-8') as f:
        html = f.read()
    
    now = datetime.now()
    date_str = now.strftime("%d.%m.%Y")
    
    service_name = get_service_display_name(service_type)
    
    phone_display = client_phone if client_phone else "Через Telegram"
    
    html = html.replace("{{ORDER_ID}}", str(order_id))
    html = html.replace("{{DATE}}", date_str)
    html = html.replace("{{CLIENT_NAME}}", client_name or "Клиент")
    html = html.replace("{{CLIENT_PHONE}}", phone_display)
    html = html.replace("{{SERVICE_NAME}}", service_name)
    html = html.replace("{{PRICE}}", price)
    
    return html

def generate_receipt_image(order_id: int, client_name: str, client_phone: str,
                          service_type: str, price: str = "По прайсу") -> str:
    try:
        from html2image import Html2Image
        
        html_content = generate_receipt_html(order_id, client_name, client_phone, 
                                            service_type, price)
        if not html_content:
            return None
        
        output_path = RECEIPTS_DIR / f"receipt_{order_id}.png"
        
        hti = Html2Image(
            output_path=str(RECEIPTS_DIR),
            size=(440, 680),
            custom_flags=['--no-sandbox', '--disable-gpu', '--disable-software-rasterizer']
        )
        
        hti.screenshot(
            html_str=html_content,
            save_as=f"receipt_{order_id}.png"
        )
        
        if output_path.exists():
            logger.info(f"Receipt image generated: {output_path}")
            return str(output_path)
        else:
            logger.error("Receipt image was not created")
            return None
            
    except ImportError:
        logger.error("html2image not installed")
        return None
    except Exception as e:
        logger.error(f"Error generating receipt image: {e}")
        return None

def generate_receipt_text(order_id: int, client_name: str, client_phone: str,
                         service_type: str) -> str:
    now = datetime.now()
    date_str = now.strftime("%d.%m.%Y %H:%M")
    service_name = get_service_display_name(service_type)
    phone_display = client_phone if client_phone else "📲 Через Telegram"
    
    return f"""
╔══════════════════════════════════╗
║      ✂️ ШВЕЙНЫЙ HUB              ║
║      КВИТАНЦИЯ О ПРИЁМЕ          ║
╠══════════════════════════════════╣
║  Заказ № {order_id:<24}║
║  Дата: {date_str:<25}║
╠══════════════════════════════════╣
║  👤 Клиент: {client_name or 'Не указано':<21}║
║  📞 Тел: {phone_display:<23}║
╠══════════════════════════════════╣
║  🧵 Услуга:                      ║
║  {service_name:<33}║
╠══════════════════════════════════╣
║  📅 О готовности сообщим         ║
║     дополнительно                ║
╠══════════════════════════════════╣
║  📍 г. Москва                    ║
║  (МЦД/м. Ховрино)                ║
║  ул. Маршала Федоренко, д. 12    ║
║  ТЦ "Бусиново", 1 этаж           ║
║  📞 +7 (968) 396-91-52           ║
║  Пн-Чт 10-19:50 | Пт 10-19       ║
║  Сб 10-17 | Вс выходной          ║
╚══════════════════════════════════╝

💾 Сохраните для получения заказа
"""

async def send_receipt_to_client(bot, chat_id: int, order_id: int, 
                                client_name: str, client_phone: str,
                                service_type: str):
    image_sent = False
    
    try:
        receipt_path = generate_receipt_image(order_id, client_name, client_phone, service_type)
        
        if receipt_path and os.path.exists(receipt_path):
            try:
                with open(receipt_path, 'rb') as photo:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=photo,
                        caption=f"📋 Квитанция о приёме заказа №{order_id}\n\n"
                               f"Сохраните для получения заказа!"
                    )
                logger.info(f"Receipt image sent to {chat_id} for order {order_id}")
                image_sent = True
                return True
            except Exception as img_send_err:
                logger.warning(f"Failed to send receipt image, falling back to text: {img_send_err}")
                image_sent = False
    except Exception as gen_err:
        logger.warning(f"Image generation failed, falling back to text: {gen_err}")
        image_sent = False
    
    if not image_sent:
        try:
            receipt_text = generate_receipt_text(order_id, client_name, client_phone, service_type)
            await bot.send_message(
                chat_id=chat_id,
                text=receipt_text
            )
            logger.info(f"Receipt text sent to {chat_id} for order {order_id} (fallback)")
            return True
        except Exception as text_err:
            logger.error(f"Failed to send receipt text: {text_err}")
            return False
    
    return False
