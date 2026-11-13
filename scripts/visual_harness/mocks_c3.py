"""API simulada (datos FICTICIOS) del CRM C3. Variantes por ?v=: empty, error, many (muchas líneas), long (textos larguísimos), sent (cotización enviada)."""
from mocks import route

LONG = 'Propuesta económica integral para el congreso internacional de ingeniería, logística y transporte de carga pesada de la región andina 2027'
ST = ['borrador', 'enviada', 'negociada', 'aprobada', 'rechazada', 'vencida']


def _q(i, v):
    return {'id': i, 'number': 3000 + i, 'version': 1 + i % 2, 'parent_quote_id': None, 'account_id': 1, 'account_name': 'Asociación Colombiana de Ingenieros', 'contact_id': 11, 'contact_name': 'Camila Torres Quintero',
            'opportunity_id': None, 'title': LONG if v == 'long' and i % 2 else f'Cotización evento ejemplo {i}', 'stage': ST[i % 6], 'expired': i % 6 == 5, 'approval_status': 'pendiente', 'invoice_status': 'sin_facturar',
            'currency': 'USD' if i % 4 == 0 else 'COP', 'valid_until': '2026-12-15', 'event_start': '2027-03-15', 'terms_id': 1, 'template_id': 1, 'subtotal': '12500000.00', 'discount_total': '500000.00', 'tax_total': '2375000.00',
            'total': '14875000.00', 'has_pdf': False, 'sent_at': None, 'owner_staff_id': 7, 'owner_name': 'María Fernanda Rodríguez Valderrama', 'archived': False, 'created_at': '2026-11-01T10:00:00', 'updated_at': '2026-11-10T15:00:00'}


@route('GET', r'/api/crm/quotes/meta')
def c3_meta(v, q):
    return {'stages': ST, 'approvals': ['pendiente', 'aprobada', 'rechazada'], 'invoice_statuses': ['sin_facturar', 'facturada'], 'proforma_statuses': ['emitida', 'pagada'], 'currencies': ['COP', 'USD', 'EUR'],
            'terms': [{'id': 1, 'name': 'Condiciones generales', 'body': 'Anticipo del 50 % para reservar fecha.', 'position': 1, 'archived': False}], 'templates': [{'id': 1, 'kind': 'quote', 'name': 'Plantilla estándar', 'is_default': True}], 'is_admin': True}


@route('GET', r'/api/crm/quotes')
def c3_list(v, q):
    if v == 'error':
        return 500, {'detail': 'No se pudo cargar la lista.'}, {}
    items = [] if v == 'empty' else [_q(i, v) for i in range(1, 9)]
    return {'items': items, 'total': len(items), 'page': 1, 'size': 20}


@route('GET', r'/api/crm/quotes/(\d+)')
def c3_quote(v, q, qid):
    if v == 'error':
        return 500, {'detail': 'No se pudo abrir la cotización.'}, {}
    base = _q(int(qid), v)
    base['stage'] = 'enviada' if v == 'sent' else 'borrador'
    n = 40 if v == 'many' else 3
    lines = [{'id': k, 'position': k, 'product_id': None, 'name': (LONG if v == 'long' and k == 1 else f'Alquiler de equipos de registro, módulo {k}'), 'description': 'Incluye instalación y soporte.', 'qty': '2.00', 'unit_price': '1500000.00', 'discount_percent': '5.00', 'tax_percent': '19.00', 'line_total': '2850000.00'} for k in range(1, n + 1)]
    return {**base, 'terms_text': 'Anticipo del 50 % para reservar fecha.', 'meeting_notes': 'Pidieron ajustar el número de estaciones.', 'lines': lines,
            'versions': [{'id': 1, 'version': 1, 'stage': 'enviada'}, {'id': 2, 'version': 2, 'stage': 'borrador'}]}


@route('GET', r'/api/crm/quotes/(\d+)/history')
def c3_hist(v, q, qid):
    return [{'field': 'stage', 'old': 'borrador', 'new': 'enviada', 'source': 'edit', 'at': '2026-11-09T11:00:00'}, {'field': 'total', 'old': '12000000', 'new': '14875000', 'source': 'edit', 'at': '2026-11-08T09:30:00'}]


@route('GET', r'/api/crm/accounts/(\d+)/contacts')
def c3_contacts(v, q, aid):
    return [{'id': 11, 'account_id': 1, 'full_name': 'Camila Torres Quintero', 'is_primary': True}, {'id': 12, 'account_id': 1, 'full_name': 'Pedro Inventado Gómez', 'is_primary': False}]


@route('GET', r'/api/crm/products')
def c3_products(v, q):
    if v == 'empty':
        return {'items': [], 'total': 0, 'page': 1, 'size': 20}
    items = [{'id': i, 'sku': f'EQ-{i:03d}', 'name': 'Escarapela impresa a color con cordón' if i % 3 else LONG, 'description': 'Incluye diseño.', 'category': 'Equipos', 'cost': '8000.00', 'price': '15000.00', 'currency': 'COP', 'tax_percent': '19.00', 'active': i % 4 != 0, 'updated_at': '2026-11-10T15:00:00'} for i in range(1, 8)]
    return {'items': items, 'total': len(items), 'page': 1, 'size': 20}


@route('GET', r'/api/crm/terms')
def c3_terms(v, q):
    return {'items': [{'id': 1, 'name': 'Condiciones generales', 'body': 'Anticipo del 50 %.', 'position': 1, 'archived': False}, {'id': 2, 'name': 'Condiciones de patrocinio', 'body': 'Pago a 30 días.', 'position': 2, 'archived': True}]}


@route('GET', r'/api/crm/doc-templates')
def c3_templates(v, q):
    return {'items': [{'id': 1, 'kind': 'quote', 'name': 'Plantilla estándar', 'header_text': 'Golden Eventos', 'greeting_text': 'Cordial saludo', 'footer_text': 'Gracias', 'is_default': True, 'archived': False},
                      {'id': 2, 'kind': 'proforma', 'name': 'Proforma estándar', 'header_text': '', 'greeting_text': '', 'footer_text': '', 'is_default': True, 'archived': False}]}


@route('GET', r'/api/crm/filters')
def c3_filters(v, q):
    return {'items': [{'id': 1, 'scope': 'cotizaciones', 'name': 'Enviadas', 'filters': {'stage': 'enviada'}, 'shared': False, 'mine': True}]}


@route('GET', r'/api/crm/search')
def c3_search(v, q):
    if v == 'empty':
        return {'accounts': [], 'contacts': [], 'opportunities': [], 'quotes': [], 'leads': []}
    return {'accounts': [{'id': 1, 'code': 1001, 'name': 'Asociación Colombiana de Ingenieros', 'status': 'cliente'}], 'contacts': [{'id': 11, 'account_id': 1, 'name': 'Camila Torres Quintero', 'job_title': 'Directora'}],
            'opportunities': [{'id': 1, 'code': 4001, 'name': 'Congreso 2027', 'outcome': 'open'}], 'quotes': [{'id': 1, 'number': 3001, 'version': 1, 'title': 'Cotización evento ejemplo', 'stage': 'enviada'}], 'leads': []}
