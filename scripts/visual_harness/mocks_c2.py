"""API simulada (datos FICTICIOS) del CRM C2/C1c. Variantes por ?v= de la página: empty, error, many (columna con más de 50), long (nombres larguísimos)."""
from mocks import route, CRM_OWNERS

STAGES = [(1, 'Prospecto', 10, 'open'), (2, 'Calificado', 25, 'open'), (3, 'Propuesta', 50, 'open'), (4, 'Cotización enviada', 65, 'open'), (5, 'Negociación', 80, 'open'), (6, 'Ganada', 100, 'won'), (7, 'Perdida', 0, 'lost')]
LONG = 'Congreso internacional de ingeniería, logística y transporte de carga pesada para la región andina 2027'
ACC = ['Asociación Colombiana de Ingenieros', 'Hotel Ejemplo SAS', 'Cámara Ficticia de Comercio', 'Constructora Norte Ltda']


def _stage(i, n, p, k):
    return {'id': i, 'name': n, 'position': i, 'probability': p, 'kind': k, 'archived': False}


def _pipes():
    return [{'id': 1, 'name': 'Eventos', 'is_default': True, 'archived': False, 'stages': [_stage(*s) for s in STAGES]},
            {'id': 2, 'name': 'Patrocinios con un nombre de embudo bastante largo', 'is_default': False, 'archived': False, 'stages': [_stage(11, 'Nuevo', 10, 'open'), _stage(12, 'Ganada', 100, 'won'), _stage(13, 'Perdida', 0, 'lost')]}]


def _card(i, stage, v):
    return {'id': i, 'code': 4000 + i, 'name': (LONG if v == 'long' and i % 3 == 0 else f'Evento ejemplo {i}'), 'account_id': 1 + i % 4, 'account_name': ACC[i % 4],
            'amount': str(1500000 * (i % 5 + 1)), 'currency': 'USD' if i % 4 == 0 else 'COP', 'probability': 10 + 10 * (i % 7), 'expected_close': '2027-03-15', 'owner_staff_id': 7, 'owner_name': CRM_OWNERS[i % 3]['name'],
            'outcome': 'open', 'stage_id': stage, 'next_activity_at': None if i % 3 == 0 else '2026-11-15T14:00:00', 'no_next_activity': i % 3 == 0, 'stage_entered_at': '2026-11-01T10:00:00', 'archived': False, 'updated_at': '2026-11-10T15:00:00'}


@route('GET', r'/api/crm/pipeline/meta')
def c2_meta(v, q):
    return {'activity_kinds': [{'key': 'call', 'label': 'Llamada'}, {'key': 'task', 'label': 'Tarea'}, {'key': 'meeting', 'label': 'Reunión'}, {'key': 'note', 'label': 'Nota'}],
            'results': [{'key': 'quote_sent', 'label': 'Cotización enviada'}, {'key': 'other', 'label': 'Otro'}], 'currencies': ['COP', 'USD'],
            'lead_statuses': ['nuevo', 'contactado', 'calificado', 'convertido', 'descartado'], 'pipelines': _pipes(), 'is_admin': True}


@route('GET', r'/api/crm/pipelines')
def c2_pipes(v, q):
    return {'pipelines': _pipes()}


@route('GET', r'/api/crm/opportunities/board')
def c2_board(v, q):
    if v == 'error':
        return 500, {'detail': 'No se pudo cargar el tablero.'}, {}
    cols = []
    for sid, name, prob, kind in STAGES:
        n = 0 if (v == 'empty' or sid in (6, 7) and v != 'many') else (57 if (v == 'many' and sid == 2) else [3, 2, 4, 5, 1][sid - 1] if sid < 6 else 0)
        cards = [_card(sid * 100 + k, sid, v) for k in range(min(n, 50))]
        cols.append({**_stage(sid, name, prob, kind), 'count': n, 'totals': [] if not n else [{'currency': 'COP', 'amount': str(n * 3000000), 'weighted': str(int(n * 3000000 * prob / 100))}, {'currency': 'USD', 'amount': str(n * 900), 'weighted': str(int(n * 900 * prob / 100))}],
                     'cards': cards, 'offset': 0, 'has_more': n > 50})
    return {'pipeline': {'id': 1, 'name': 'Eventos'}, 'columns': cols, 'closed_days': 90, 'page_size': 50}


@route('GET', r'/api/crm/opportunities')
def c2_list(v, q):
    items = [] if v == 'empty' else [{**_card(i, 1 + i % 5, v), 'stage_name': STAGES[i % 5][1]} for i in range(1, 9)]
    return {'items': items, 'total': len(items), 'page': 1, 'size': 20}


@route('GET', r'/api/crm/opportunities/(\d+)')
def c2_opp(v, q, oid):
    c = _card(int(oid), 4, v)
    return {**c, 'pipeline_id': 1, 'stage_name': 'Cotización enviada', 'stage_kind': 'open', 'opp_type': 'Congreso', 'source': 'Referido', 'next_step': 'Enviar la propuesta ajustada', 'description': 'Evento de tres días con 400 asistentes.',
            'primary_contact_id': 11, 'primary_contact': 'Camila Torres Quintero', 'event_start': '2027-03-15', 'city': 'Bogotá', 'closed_at': None, 'lost_reason': None, 'event_id': None, 'own_probability': None,
            'created_at': '2026-10-01T08:00:00', 'account_is_client': True}


@route('GET', r'/api/crm/opportunities/(\d+)/history')
def c2_hist(v, q, oid):
    return [{'field': 'stage', 'old': 'Calificado', 'new': 'Cotización enviada', 'by': 'Andrés Ochoa', 'source': 'edit', 'at': '2026-11-09T11:00:00'}]


@route('GET', r'/api/crm/activities')
def c2_acts(v, q):
    return {'items': [], 'total': 0, 'page': 1, 'size': 20}


@route('GET', r'/api/crm/leads')
def c2_leads(v, q):
    if v == 'error':
        return 500, {'detail': 'No se pudo cargar la lista.'}, {}
    items = [] if v == 'empty' else [{'id': i, 'full_name': ['Lucía Ficticia', 'Pedro Inventado Gómez de la Torre', 'Sin nombre'][i % 3], 'company_name': ACC[i % 4], 'email': f'lead{i}@ejemplo.test', 'phone': '3000000000',
                                         'source': 'web', 'status': ['nuevo', 'contactado', 'calificado', 'convertido'][i % 4], 'owner_staff_id': 7, 'owner_name': CRM_OWNERS[i % 3]['name'], 'archived': False,
                                         'converted_account_id': None, 'converted_contact_id': None, 'converted_opportunity_id': None, 'created_at': '2026-11-01T10:00:00', 'updated_at': '2026-11-10T15:00:00'} for i in range(1, 8)]
    return {'items': items, 'total': len(items), 'page': 1, 'size': 20}


@route('GET', r'/api/crm/import/runs')
def c2_runs(v, q):
    if v == 'empty':
        return {'items': [], 'apply_enabled': False}
    return {'apply_enabled': v != 'blocked', 'items': [
        {'id': 2, 'mode': 'dry_run', 'status': 'done', 'files': {}, 'error': None, 'created_at': '2026-11-12T14:00:00', 'finished_at': '2026-11-12T14:01:00',
         'counts': {'accounts': {'counts': {'read': 120, 'created': 112, 'skipped_existing': 3, 'rejected': 5}, 'rejected': [{'row': 14, 'reason': 'Fila sin nombre.'}, {'row': 33, 'reason': 'El campo name es demasiado largo (máximo 200 caracteres).'}]},
                    'contacts': {'counts': {'read': 300, 'created': 280, 'skipped_existing': 0, 'rejected': 20}, 'rejected': []}, 'pairs': {'seguro': 40, 'dudoso': 12, 'sin_pareja': 8}}},
        {'id': 1, 'mode': 'sample', 'status': 'failed', 'files': {}, 'counts': {}, 'error': 'Al archivo le falta la columna obligatoria: nombre.', 'created_at': '2026-11-12T13:00:00', 'finished_at': None}]}


@route('GET', r'/api/crm/import/runs/(\d+)/pairs')
def c2_pairs(v, q, rid):
    return {'items': [{'id': 1, 'tenant_name': 'Hotel Ejemplo SAS', 'suitecrm_name': 'HOTEL EJEMPLO', 'suitecrm_code': 5001, 'score': 100, 'bucket': 'seguro', 'decision': 'pending'},
                      {'id': 2, 'tenant_name': 'Constructora Norte', 'suitecrm_name': 'Constructora Nortes', 'suitecrm_code': 5002, 'score': 88, 'bucket': 'dudoso', 'decision': 'pending'},
                      {'id': 3, 'tenant_name': 'Empresa Sola', 'suitecrm_name': None, 'suitecrm_code': None, 'score': 20, 'bucket': 'sin_pareja', 'decision': 'pending'}]}
