import os
import json
import re

class KnowledgeLoader:
    """Загрузчик знаний из файлов"""
    
    def __init__(self):
        self.prices = {}
        self.prices_by_category = {}
        self.faq = {}
        self.load_all()
    
    def load_all(self):
        """Загрузить все данные"""
        self.load_prices()
        self.load_faq()
    
    def load_prices(self):
        """Загрузить цены из файла"""
        prices_file = "workshop-bot/data/knowledge_base/Цены на услуги.txt"
        if os.path.exists(prices_file):
            with open(prices_file, 'r', encoding='utf-8') as f:
                content = f.read()
                self.prices = {
                    "raw": content,
                    "formatted": self._format_prices(content)
                }
                self.prices_by_category = self._parse_prices_by_category(content)
    
    def _parse_prices_by_category(self, content):
        """Разбить цены на категории"""
        categories = {}
        current_category = None
        lines = content.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Проверяем, это ли заголовок категории
            # Заголовок: короткая строка, заканчивается на какое-то русское слово
            is_category = (
                len(line) < 80 and
                not re.search(r'\d+', line) and  # Нет цифр
                any(keyword in line.lower() for keyword in [
                    'ремонт', 'работа', 'подгонка', 'мелкий', 
                    'художественная', 'срочные'
                ])
            )
            
            if is_category:
                current_category = line
                categories[current_category] = []
            elif current_category and line and re.search(r'\d+', line):
                # Это услуга (содержит цифры - цены)
                categories[current_category].append(line)
        
        return categories
    
    def _format_prices(self, content):
        """Форматировать цены для вывода"""
        lines = content.strip().split('\n')
        formatted = "💰 *ПРАЙС-ЛИСТ УСЛУГ*\n\n"
        
        current_category = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Если это заголовок категории
            is_category = (
                len(line) < 80 and
                not re.search(r'\d+', line) and
                any(keyword in line.lower() for keyword in [
                    'ремонт', 'работа', 'подгонка', 'мелкий',
                    'художественная', 'срочные'
                ])
            )
            
            if is_category:
                current_category = line
                formatted += f"\n📌 *{current_category}*\n"
            elif re.search(r'\d+', line):
                formatted += f"• {line}\n"
        
        return formatted
    
    def _parse_faq(self, content):
        """Парсить FAQ из markdown"""
        lines = content.split('\n')
        faq_dict = {}
        current_question = None
        current_answer = ""
        
        for line in lines:
            if line.startswith('**') and line.endswith('**'):
                if current_question:
                    faq_dict[current_question] = current_answer.strip()
                current_question = line.replace('**', '').strip()
                current_answer = ""
            elif current_question and line.strip():
                current_answer += line + "\n"
        
        if current_question:
            faq_dict[current_question] = current_answer.strip()
        
        return faq_dict
    
    def load_faq(self):
        """Загрузить FAQ из файла"""
        faq_file = "workshop-bot/data/knowledge_base/Ответы на вопросы.md"
        if os.path.exists(faq_file):
            with open(faq_file, 'r', encoding='utf-8') as f:
                content = f.read()
                self.faq = {
                    "raw": content,
                    "parsed": self._parse_faq(content)
                }
    
    def get_prices(self):
        """Получить форматированные цены"""
        return self.prices.get('formatted', 'Цены не загружены')
    
    def get_price_raw(self):
        """Получить сырые цены"""
        return self.prices.get('raw', '')
    
    def get_prices_by_category(self):
        """Получить цены разделённые по категориям"""
        return self.prices_by_category
    
    def get_category_prices(self, category_key):
        """Получить цены для конкретной категории"""
        categories = self.prices_by_category
        
        category_map = {
            "tricot": "Ремонт трикотажа",
            "leather": "Ремонт кожаных изделий",
            "fur": "Ремонт меховых изделий",
            "outerwear": "Работа с верхней одеждой (куртки, пальто, пуховики)",
            "fitting": "Подгонка по фигуре",
            "small": "Мелкий ремонт",
            "darn": "Художественная штопка",
            "urgent": "Срочные услуги"
        }
        
        category_name = category_map.get(category_key)
        if not category_name:
            return None
        
        prices = categories.get(category_name, [])
        if not prices:
            return None
        
        text = f"💰 *{category_name}*\n\n"
        for price in prices:
            text += f"• {price}\n"
        
        return text
    
    def get_faq_answers(self):
        """Получить все ответы FAQ"""
        return self.faq.get('parsed', {})
    
    def get_answer(self, question_key):
        """Получить ответ по вопросу"""
        faq = self.faq.get('parsed', {})
        for q, answer in faq.items():
            if question_key.lower() in q.lower():
                return answer
        return None
    
    def get_all_knowledge(self):
        """Получить всё знание для GigaChat"""
        prices = self.get_price_raw()
        faq_text = "\n\n".join([f"В: {q}\nО: {a}" for q, a in self.faq.get('parsed', {}).items()])
        return f"ПРАЙС-ЛИСТ:\n{prices}\n\nFAQ:\n{faq_text}"

    def search_knowledge(self, query: str) -> str:
        """
        Поиск ответа в базе знаний по ключевым словам.
        Используется как фоллбэк при недоступности GigaChat.
        """
        query_lower = query.lower()
        results = []
        
        # Ключевые слова для поиска
        keywords = {
            'цен': ('prices', 'Информация о ценах'),
            'прайс': ('prices', 'Прайс-лист'),
            'стоим': ('prices', 'Стоимость услуг'),
            'сколько': ('prices', 'Цены на услуги'),
            'адрес': ('contacts', 'Контакты'),
            'где': ('contacts', 'Как нас найти'),
            'находит': ('contacts', 'Адрес мастерской'),
            'метро': ('contacts', 'Как добраться'),
            'телефон': ('contacts', 'Контакты'),
            'whatsapp': ('contacts', 'Контакты'),
            'график': ('schedule', 'График работы'),
            'работает': ('schedule', 'Режим работы'),
            'время': ('schedule', 'Часы работы'),
            'выходн': ('schedule', 'График работы'),
            'срок': ('timing', 'Сроки выполнения'),
            'долго': ('timing', 'Время выполнения'),
            'быстро': ('timing', 'Сроки'),
            'срочн': ('urgent', 'Срочные услуги'),
            'оплат': ('payment', 'Способы оплаты'),
            'картой': ('payment', 'Оплата'),
            'наличн': ('payment', 'Оплата'),
            'гарант': ('warranty', 'Гарантия'),
            'услуг': ('services', 'Наши услуги'),
            'ремонт': ('services', 'Услуги ремонта'),
            'подгонк': ('services', 'Подгонка одежды'),
            'укорот': ('services', 'Подгонка одежды'),
            'штопк': ('services', 'Художественная штопка'),
        }
        
        matched_category = None
        for keyword, (category, description) in keywords.items():
            if keyword in query_lower:
                matched_category = category
                break
        
        if matched_category == 'prices':
            return self._get_prices_fallback()
        elif matched_category == 'contacts':
            return self._get_contacts_fallback()
        elif matched_category == 'schedule':
            return self._get_schedule_fallback()
        elif matched_category in ('timing', 'urgent'):
            return self._get_timing_fallback()
        elif matched_category == 'payment':
            return self._get_payment_fallback()
        elif matched_category == 'warranty':
            return self._get_warranty_fallback()
        elif matched_category == 'services':
            return self._get_services_fallback()
        
        # Поиск в FAQ
        faq_answer = self._search_faq(query_lower)
        if faq_answer:
            return faq_answer
        
        return None
    
    def _search_faq(self, query: str) -> str:
        """Поиск в FAQ по ключевым словам"""
        faq = self.faq.get('parsed', {})
        for question, answer in faq.items():
            if any(word in question.lower() for word in query.split() if len(word) > 3):
                return answer
        return None
    
    def _get_prices_fallback(self) -> str:
        """Краткая информация о ценах"""
        return (
            "💰 Наши цены зависят от вида работы:\n\n"
            "• Мелкий ремонт — от 100₽\n"
            "• Подгонка брюк/джинсов — от 300₽\n"
            "• Ремонт курток — от 500₽\n"
            "• Ремонт кожи — от 700₽\n"
            "• Художественная штопка — от 500₽\n\n"
            "Для точной оценки пришлите фото изделия или посетите нас!\n"
            "📍 м. Ховрино, ТЦ \"Бусиново\""
        )
    
    def _get_contacts_fallback(self) -> str:
        """Контактная информация"""
        return (
            "📍 *Как нас найти:*\n\n"
            "🏠 Адрес: г. Москва, м. Ховрино,\n"
            "м. Ховрино, ТЦ \"Бусиново\", 1 этаж\n\n"
            "📞 Телефон: +7 (968) 396-91-52\n"
            "💬 WhatsApp: +7 (968) 396-91-52"
        )
    
    def _get_schedule_fallback(self) -> str:
        """График работы"""
        return (
            "⏰ *График работы:*\n\n"
            "Пн-Чт: 10:00 - 19:50\n"
            "Пт: 10:00 - 19:00\n"
            "Сб: 10:00 - 17:00\n"
            "Вс: Выходной"
        )
    
    def _get_timing_fallback(self) -> str:
        """Сроки выполнения"""
        return (
            "⏱ *Сроки выполнения:*\n\n"
            "• Мелкий ремонт — от 1 часа\n"
            "• Подгонка одежды — 1-3 дня\n"
            "• Сложный ремонт — 3-7 дней\n\n"
            "🚀 Есть срочные услуги (доплата 50-100%)"
        )
    
    def _get_payment_fallback(self) -> str:
        """Оплата"""
        return (
            "💳 *Способы оплаты:*\n\n"
            "• Наличные\n"
            "• Карта (перевод на карту)\n"
            "• СБП\n\n"
            "Оплата при получении готового изделия."
        )
    
    def _get_warranty_fallback(self) -> str:
        """Гарантия"""
        return (
            "✅ *Гарантия качества:*\n\n"
            "Мы даём гарантию на все виды работ.\n"
            "Если вас что-то не устроит — исправим бесплатно!"
        )
    
    def _get_services_fallback(self) -> str:
        """Услуги"""
        return (
            "🧵 *Наши услуги:*\n\n"
            "• Ремонт трикотажа\n"
            "• Ремонт кожаных изделий\n"
            "• Ремонт меховых изделий\n"
            "• Ремонт верхней одежды\n"
            "• Подгонка по фигуре\n"
            "• Мелкий ремонт\n"
            "• Художественная штопка\n"
            "• Срочные услуги\n\n"
            "Для оценки отправьте фото изделия!"
        )


# Глобальный экземпляр
knowledge = KnowledgeLoader()
