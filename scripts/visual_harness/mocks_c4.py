"""API simulada (datos FICTICIOS) del CRM C4. Variantes por ?v=: empty, error, many, long (textos larguísimos), comercial (sin selector de responsable)."""
from mocks import route

LONG = 'Congreso internacional de ingeniería, logística y transporte de carga pesada para la región andina 2027'


def _act(i, v, due):
    return {'id': i, 'kind': ['call', 'task', 'meeting'][i % 3], 'kind_label': ['Llamada', 'Tarea', 'Reunión'][i % 3], 'subject': LONG if v == 'long' and i % 2 else f'Seguimiento ejemplo {i}', 'due_at': due, 'remind_at': None,
            'account_id': 1, 'account_name': 'Asociación Colombiana de Ingenieros', 'opportunity_id': 1 if i % 2 else None, 'opportunity_name': 'Congreso 2027' if i % 2 else None, 'lead_id': None, 'contact_id': None, 'updated_at': '2026-11-10T15:00:00'}


@route('GET', r'/api/crm/today')
def c4_today(v, q):
    if v == 'error':
        return 500, {'detail': 'No se pudo cargar tu día.'}, {}
    if v == 'empty':
        return {'today': '2026-11-12', 'overdue': [], 'due_today': [], 'reminders': [], 'no_next_activity': [], 'no_next_activity_more': False, 'closing_soon': [], 'quotes_expiring': [], 'close_soon_days': 14, 'quote_soon_days': 7}
    n = 40 if v == 'many' else 3
    opp = lambda i: {'id': i, 'code': 4000 + i, 'name': LONG if v == 'long' else f'Evento ejemplo {i}', 'amount': str(2500000 * i), 'currency': 'COP' if i % 2 else 'USD', 'expected_close': '2026-11-20', 'account_name': 'Hotel Ejemplo SAS'}
    return {'today': '2026-11-12', 'overdue': [_act(i, v, '2026-11-09T10:00:00') for i in range(1, n)], 'due_today': [_act(i, v, '2026-11-12T15:30:00') for i in range(10, 10 + n)], 'reminders': [_act(30, v, '2026-11-18T09:00:00')],
            'no_next_activity': [opp(i) for i in range(1, 4)], 'no_next_activity_more': v == 'many', 'closing_soon': [opp(5), opp(6)],
            'quotes_expiring': [{'id': 1, 'number': 3001, 'version': 2, 'title': 'Cotización evento ejemplo', 'stage': 'enviada', 'valid_until': '2026-11-15', 'total': '14875000.00', 'currency': 'COP', 'account_name': 'Cámara Ficticia de Comercio'}],
            'close_soon_days': 14, 'quote_soon_days': 7}


@route('GET', r'/api/crm/dashboards')
def c4_dash(v, q):
    if v == 'error':
        return 500, {'detail': 'No se pudieron cargar los tableros.'}, {}
    stages = [] if v == 'empty' else [{'stage_id': i, 'name': n, 'count': c, 'totals': [{'currency': 'COP', 'amount': str(c * 3000000), 'weighted': str(c * 900000)}, {'currency': 'USD', 'amount': str(c * 900), 'weighted': str(c * 300)}]}
                                      for i, (n, c) in enumerate([('Prospecto', 12), ('Calificado', 8), ('Propuesta de valor', 5), ('Cotización enviada', 3), ('Negociación', 2)], 1)]
    d = {'days': 90, 'day_options': [30, 90, 365], 'scope': 'all' if v != 'comercial' else 'me', 'pipeline_id': 1, 'stages': stages,
         'closed': {'won': {'count': 0 if v == 'empty' else 7, 'totals': [] if v == 'empty' else [{'currency': 'COP', 'amount': '85000000.00'}, {'currency': 'USD', 'amount': '12000.00'}]}, 'lost': {'count': 0 if v == 'empty' else 4, 'totals': [] if v == 'empty' else [{'currency': 'COP', 'amount': '20000000.00'}]}},
         'win_rate': None if v == 'empty' else 64, 'activities': {'pending': 0 if v == 'empty' else 23, 'overdue': 0 if v == 'empty' else 5, 'done_by_kind': [] if v == 'empty' else [{'kind': 'call', 'label': 'Llamada', 'count': 41}, {'kind': 'meeting', 'label': 'Reunión', 'count': 12}, {'kind': 'task', 'label': 'Tarea', 'count': 30}]},
         'quotes': [] if v == 'empty' else [{'stage': 'borrador', 'count': 6, 'totals': [{'currency': 'COP', 'amount': '30000000.00'}]}, {'stage': 'enviada', 'count': 9, 'totals': [{'currency': 'COP', 'amount': '120000000.00'}, {'currency': 'USD', 'amount': '8000.00'}]}, {'stage': 'aprobada', 'count': 3, 'totals': [{'currency': 'COP', 'amount': '45000000.00'}]}],
         'by_owner': [] if v in ('empty', 'comercial') else [{'owner_id': 7, 'name': 'María Fernanda Rodríguez Valderrama', 'count': 14, 'totals': [{'currency': 'COP', 'amount': '40000000.00', 'weighted': '15000000.00'}]}, {'owner_id': 8, 'name': 'Andrés Ochoa', 'count': 9, 'totals': [{'currency': 'COP', 'amount': '22000000.00', 'weighted': '9000000.00'}, {'currency': 'USD', 'amount': '5000.00', 'weighted': '2500.00'}]}]}
    return d
