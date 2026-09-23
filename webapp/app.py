
STATUS_MESSAGES = {
    'accepted': '🧵 Ваш заказ #{order_id} принят в мастерскую!\n\nМы скоро начнем работу над вашей вещью.\n\nЕсли у вас есть вопросы, можете написать нам в чат или позвонить по телефону.\n\n📞 +7 (968) 396-91-52',
    'in_progress': '🧵 Отличные новости! Ваш заказ #{order_id} уже в работе!\n\nНаши мастера с любовью трудятся над вашим изделием.\n\nМы обязательно свяжемся с вами, если понадобится дополнительная информация.\n\n📍 г. Москва, ул. Маршала Федоренко д.12, ТЦ "Бусиново"',
    'completed': ('🎉 Ваш заказ #{order_id} выполнен!\n\n'
                  '<b>Забрать можно по адресу:</b> г. Москва, (МЦД/м. Ховрино) ул. Маршала Федоренко д.12, , ТЦ "Бусиново", 1 этаж\n\n'
                  '<b>График работы:</b>\nПн-Чт: 10:00-19:50\nПт: 10:00-19:00\nСб: 10:00-17:00\nВс: выходной\n\n'
                  '📞 +7 (968) 396-91-52\n\n---\n\n🙏 <b>Будем признательны за ваш отзыв!</b>\n\n'
                  '👉 <a href="https://yandex.ru/maps/org/shveyny_hub/1233246900/reviews/">Оставить отзыв на Яндекс.Картах</a>\n\nЖдём вас! 🪡'),
    'issued': '📤 Ваш заказ #{order_id} выдан!\n\nСпасибо, что выбрали нашу мастерскую. Будем рады видеть вас снова! 🪡',
    'cancelled': '😔 К сожалению, ваш заказ #{order_id} был отменён.\n\nЕсли у вас остались вопросы или вы хотите оформить новый заказ, мы всегда готовы помочь.\n\n📞 +7 (968) 396-91-52'
}

SERVICE_NAMES = {
    "jacket": "🧥 Ремонт пиджака",
    "leather": "🎒 Изделия из кожи",
    "curtains": "🪟 Пошив штор",
    "coat": "🧥 Ремонт куртки",
    "fur": "🐾 Шубы и дублёнки",
    "outerwear": "🧥 Плащ/пальто",
    "pants": "👖 Брюки/джинсы",
    "dress": "👗 Юбки/платья"
}

@app.route('/api/order/<int:order_id>/status', methods=['POST'])
@requires_auth
@csrf.exempt
def api_update_order_status(order_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request body'}), 400

    new_status = data.get('status')

    if new_status not in ['new', 'accepted', 'in_progress', 'completed', 'issued', 'cancelled']:
        return jsonify({'error': 'Invalid status'}), 400

    order = get_order(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404

    user_id = getattr(order, 'user_id', None)

    success = update_order_status(order_id, new_status)

    if success:
        if new_status in STATUS_MESSAGES and user_id:
            message = STATUS_MESSAGES[new_status].format(order_id=order_id)
            notification_sent = send_telegram_notification(user_id, message)
            logger.info(f"Status update notification for order {order_id}: sent={notification_sent}")

        return jsonify({'success': True, 'order_id': order_id, 'status': new_status})
    else:
        return jsonify({'error': 'Failed to update status'}), 500


@app.route('/api/orders/export-csv')
@requires_auth
@csrf.exempt
def api_export_csv():
    status = request.args.get('status', None)
    period = request.args.get('period', None)
    date_from = request.args.get('date_from', None)
    date_to = request.args.get('date_to', None)
    month_filter = request.args.get('month', None)
    year_filter = request.args.get('year', None)

    all_orders = get_all_orders(limit=1000)

    filtered = filter_orders(all_orders,
                             date_from=date_from,
                             date_to=date_to,
                             period=period,
                             month=month_filter,
                             year=year_filter)

    if status:
        filtered = [o for o in filtered if getattr(o, 'status', None) == status]

    STATUS_LABELS = {
        'new': 'Новый',
        'accepted': 'Принят',
        'in_progress': 'В работе',
        'completed': 'Готов',
        'issued': 'Выдан',
        'cancelled': 'Отменён'
    }

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['ID', 'Услуга', 'Клиент', 'Телефон', 'Статус', 'Дата создания'])

    for order in filtered:
        writer.writerow([
            getattr(order, 'id', ''),
            SERVICE_NAMES.get(getattr(order, 'service_type', None), getattr(order, 'service_type', '') or ''),
            getattr(order, 'client_name', '') or '',
            getattr(order, 'client_phone', '') or '',
            STATUS_LABELS.get(getattr(order, 'status', None), getattr(order, 'status', '')),
            order.created_at.strftime('%d.%m.%Y %H:%M') if getattr(order, 'created_at', None) else ''
        ])

    output.seek(0)
    filename = f"orders_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response
