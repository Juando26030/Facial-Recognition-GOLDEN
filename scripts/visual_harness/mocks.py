"""API simulada con datos FICTICIOS. handle(method, path, query, body, referer) -> (code, data, headers) | None."""
import re
from urllib.parse import urlparse, parse_qs

ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile('^' + pattern + '$'), fn))
        return fn
    return deco


def variant(v):
    return v


def handle(method, path, q, body, referer):
    v = variant(referer)
    for m, rx, fn in ROUTES:
        if m in (method, '*'):
            mt = rx.match(path)
            if mt:
                r = fn(v, q, *mt.groups())
                if isinstance(r, tuple):
                    return r
                return 200, r, {}
    if method != 'GET':
        return 200, {'ok': True}, {}
    return None


# ------- comunes -------
@route('GET', r'/api/notifications')
def notifs(v, q):
    if q.get('unread'):
        return {'items': [], 'unread': 0 if v == 'empty' else 3}
    return {'items': [], 'unread': 0}


@route('GET', r'/api/ops/version-check')
def vcheck(v, q):
    return {'update_available': False}


@route('GET', r'/api/ops/update-status')
def ustatus(v, q):
    return {'running': False}


# ------- turnos -------
NAMES = ['Ana María Gómez Restrepo', 'Luis Pérez', 'Juan Sebastián Castañeda Villamizar', 'Sofía Díaz', 'Carlos Andrés Rodríguez', 'Valentina Ospina', 'Mateo López', 'Daniela Fernández Arango']


@route('GET', r'/api/events/\d+/queue')
def queue(v, q):
    if v == 'empty':
        return {'mode': 'arrival', 'total': 0, 'lanes': [{'letter': 'A', 'name': 'A', 'serving': None, 'waiting': 0}], 'listing': {'waiting': [], 'skipped': [], 'called': []}}
    lanes = [{'letter': 'A', 'name': 'Acreditación general', 'serving': {'label': 'A-017', 'desk': 'Mesa 2'}, 'waiting': 23},
             {'letter': 'B', 'name': 'B', 'serving': {'label': 'B-004', 'desk': ''}, 'waiting': 5},
             {'letter': 'C', 'name': 'Prensa e invitados especiales', 'serving': None, 'waiting': 0}]
    waiting = [{'id': i, 'lane': 'A' if i % 3 else 'B', 'label': ('A' if i % 3 else 'B') + '-%03d' % (18 + i), 'name': NAMES[i % len(NAMES)], 'user_id': str(1000000000 + i * 7919)} for i in range(14)]
    skipped = [{'id': 99, 'lane': 'A', 'label': 'A-009', 'name': 'Pedro Pablo Montoya'}]
    return {'mode': 'manual' if v == 'manual' else 'form', 'total': 128, 'lanes': lanes, 'listing': {'waiting': waiting, 'skipped': skipped, 'called': []}}


@route('GET', r'/api/events/\d+/queue/tv')
def queue_tv(v, q):
    if v == 'empty':
        return {'lanes': [{'letter': 'A', 'name': 'A', 'serving': None}], 'recent': []}
    return {'lanes': [{'letter': 'A', 'name': 'Acreditación general', 'serving': {'label': 'A-017', 'desk': 'Mesa 2', 'seq': 17}},
                      {'letter': 'B', 'name': 'B', 'serving': {'label': 'B-004', 'desk': 'Mesa 5', 'seq': 4}},
                      {'letter': 'C', 'name': 'Prensa', 'serving': None}],
            'recent': [{'label': 'A-016', 'desk': 'Mesa 1'}, {'label': 'B-003', 'desk': 'Mesa 5'}, {'label': 'A-015', 'desk': 'Mesa 2'}, {'label': 'A-014', 'desk': ''}]}


@route('GET', r'/turno/\d+/([^/]+)/state')
def turno_state(v, q, tok):
    if tok == 'tokcalled':
        return {'label': 'A-017', 'your_turn': True, 'desk': 'Mesa 2', 'name': 'Ana María', 'status': 'called'}
    if tok == 'tokskipped':
        return {'label': 'A-009', 'your_turn': False, 'status': 'skipped'}
    return {'label': 'A-023', 'your_turn': False, 'ahead': 6, 'serving': 'A-017', 'name': 'Ana María', 'status': 'waiting'}


@route('GET', r'/api/events/\d+/tv')
def tv(v, q):
    if v == 'empty':
        return {'registered': 0, 'expected': 850, 'percent': 0, 'recent': [], 'updated_at': '10:42 a. m.'}
    rec = [{'name': n.split()[0] + ' ' + n.split()[-1][0] + '.', 'at': '10:%02d a. m.' % (41 - i), 'entity': ['Bancolombia S.A.', 'Universidad Nacional de Colombia — Facultad de Ingeniería', '', 'Ecopetrol'][i % 4]} for i, n in enumerate(NAMES)]
    return {'registered': 612, 'expected': 850, 'percent': 72, 'recent': rec, 'updated_at': '10:42 a. m.'}


# ------- autorregistro, expositores, contactos -------
@route('GET', r'/api/events/\d+/selfreg/form')
def selfreg_form(v, q):
    if v == 'closed':
        return {'available': False, 'reason': 'closed'}
    return {'available': True, 'fields': [
        {'key': 'id', 'label': 'Número de documento', 'type': 'text', 'required': True},
        {'key': 'first_name', 'label': 'Nombres', 'type': 'text', 'required': True},
        {'key': 'last_name', 'label': 'Apellidos', 'type': 'text', 'required': True},
        {'key': 'email', 'label': 'Correo electrónico', 'type': 'email', 'required': False, 'help': 'Te enviamos tu escarapela digital.'},
        {'key': 'opt_1', 'label': 'Tipo de asistente', 'type': 'select', 'required': True, 'options': ['Asistente', 'Ponente', 'Prensa']},
        {'key': 'consent', 'label': 'Acepto el tratamiento de mis datos personales para mi acreditación en este evento', 'type': 'consent', 'required': True}]}


@route('GET', r'/api/events/\d+/exhibitors')
def exhibitors(v, q):
    if v == 'empty':
        return []
    return [{'id': 1, 'name': 'Industrias Metalmecánicas del Pacífico Ltda.', 'contact_name': 'Jorge Iván Salazar', 'leads': 37, 'active': True},
            {'id': 2, 'name': 'Café Sol', 'contact_name': '', 'leads': 0, 'active': False},
            {'id': 3, 'name': 'Software Andino', 'contact_name': 'Paula Moreno', 'leads': 112, 'active': True}]


@route('GET', r'/contacto/([^/]+)/data')
def contact_data(v, q, tok):
    return {'text': 'Al aceptar, autorizas a Acme S.A.S. a entregar tu nombre, empresa, cargo, teléfono y correo a los expositores del evento que escaneen tu código. '
                    'Puedes retirar la autorización en cualquier momento desde esta página.\n\nResponsable: Acme S.A.S. — privacidad@ejemplo.test',
            'minor': v == 'minor', 'sharing': v == 'sharing', 'needs_adult': True, 'adult_text': 'Confirmo que soy mayor de 18 años', 'card_path': '/tarjeta/abc123'}


@route('GET', r'/tarjeta/([^/]+)/data')
def card_data(v, q, tok):
    if tok == 'tk-gone':
        return 404, {'detail': 'no'}, {}
    return {'name': 'Ana María Gómez Restrepo', 'company': 'Universidad Nacional de Colombia', 'title': 'Directora de Investigación', 'phone': '+57 300 000 0000', 'email': 'ana.gomez@ejemplo.test'}


@route('GET', r'/expositor/([^/]+)/data')
def expo_data(v, q, tok):
    leads = [] if v == 'empty' else [{'first_name': n.split()[0], 'last_name': ' '.join(n.split()[1:]), 'company': ['Bancolombia S.A.', 'Universidad Nacional de Colombia', ''][i % 3], 'title': ['Gerente de compras', '', 'Analista'][i % 3], 'card': 'c%d' % i} for i, n in enumerate(NAMES[:6])]
    return {'count': len(leads), 'leads': leads, 'card_path': '/tarjeta/expo999'}


@route('POST', r'/expositor/([^/]+)/scan')
def expo_scan(v, q, tok):
    return {'status': 'new', 'person': {'first_name': 'Ana María', 'last_name': 'Gómez Restrepo', 'company': 'Universidad Nacional de Colombia', 'title': 'Directora', 'phone': '+57 300 000 0000', 'email': 'ana@ejemplo.test'}, 'card': 'c1'}


# ------- registro -------
def people(v):
    if v == 'empty':
        return []
    rows = []
    ents = ['Bancolombia S.A.', 'Universidad Nacional de Colombia — Facultad de Ingeniería', '', 'Ecopetrol', 'Alcaldía Mayor de Bogotá D.C.']
    tipos = ['Asistente', 'Ponente internacional invitado', '', 'Prensa', 'VIP']
    ids = ['0000349220', '1020304050', '79876543', '0012345678', 'PRUEBA', '52123456', 'AB123456', '1000000001', '98765', '1144556677', '0000000123', '39123456']
    for i, cid in enumerate(ids):
        n = NAMES[i % len(NAMES)].split()
        rows.append({'id': cid, 'first_name': ' '.join(n[:2]) if len(n) > 2 else n[0], 'last_name': ' '.join(n[2:]) if len(n) > 2 else n[-1],
                     'opt_1': tipos[i % 5], 'entity': ents[i % 5], 'status': 'Registrado' if i % 3 == 0 else 'No registrado',
                     'origin': ['base', 'manual', 'autoregistro', 'base'][i % 4]})
    rows[1]['recent_at'] = 4102444800000
    return rows


@route('GET', r'/api/users/changes')
def changes(v, q):
    return {'cursor': 'c1', 'users': [], 'total': len(people(v)), 'flags': {}}


@route('GET', r'/api/users')
def users(v, q):
    p = people(v)
    off = int(q.get('offset', 0) or 0)
    lim = int(q.get('limit', 500) or 500)
    return 200, p[off:off + lim], {'X-Total-Count': str(len(p))}


@route('GET', r'/api/events/\d+/incomplete-registrations')
def incomplete(v, q):
    return {'people': [], 'count': 0}


# ------- panel: servidor local, sincronización, inventario, cobros, gastos -------
EVS = [('Congreso Nacional de Innovación, Tecnología Aplicada y Transformación Digital 2026', 'CNIT26', 'en_proceso', '2026-11-12', 'Asociación Colombiana de Ingenieros de Sistemas'),
       ('Feria Pyme', 'FPY26', 'creado', '2026-12-03', 'Acme'), ('Foro de Salud Pública del Pacífico', 'FSP26', 'finalizado', '2026-10-01', 'Acme'),
       ('Lanzamiento Producto X', 'LPX', 'en_proceso', '2026-11-09', 'Bancolombia S.A.')]


@route('GET', r'/api/session/idle')
def idle(v, q):
    return {'remaining': 1800}


@route('GET', r'/api/local/cloud-events')
def cloud_events(v, q):
    if v == 'empty':
        return {'node_name': 'Portátil Sala 3', 'configured': True, 'events': []}
    evs = []
    for i, (n, c, s, d, t) in enumerate(EVS):
        evs.append({'id': i + 1, 'name': n, 'event_code': c, 'status': s, 'start_date': d, 'end_date': '2026-11-14' if i == 0 else d, 'tenant_name': t,
                    'downloaded': i == 1, 'local_event_id': 9 if i == 1 else None, 'leased_elsewhere': i == 2, 'local': {'node_name': 'Equipo Medellín'} if i == 2 else None})
    return {'node_name': 'Portátil Sala 3', 'configured': True, 'offline': v == 'offline', 'error': 'No hay conexión con la nube.', 'events': evs}


@route('GET', r'/api/node-sync/status')
def ns_status(v, q):
    evs = [] if v == 'empty' else [
        {'id': 1, 'name': EVS[0][0], 'code': 'CNIT26', 'package_at': '2026-11-08T10:00:00', 'last_upload_at': '2026-11-09T14:30:00', 'pending': {'total': 12, 'persons': 3, 'logs': 9}, 'error': '', 'local_only': {}},
        {'id': 2, 'name': 'Feria Pyme', 'code': 'FPY26', 'package_at': '2026-11-07T10:00:00', 'last_upload_at': None, 'pending': {'total': 0, 'persons': 0, 'logs': 0}, 'error': 'La nube rechazó la subida: el evento ya no está asignado a este servidor.', 'local_only': {'formularios': 2}}]
    return {'configured': True, 'version': {'configured': True, 'status': 'igual'}, 'events': evs, 'pending_total': 12, 'interval_minutes': 5}


@route('GET', r'/api/nodes')
def nodes(v, q):
    if v == 'empty':
        return {'nodes': []}
    return {'nodes': [{'id': 1, 'name': 'Portátil Sala 3', 'revoked': False, 'created_at': '2026-11-01T10:00:00', 'created_by_name': 'María Fernanda Rodríguez', 'last_seen_at': '2026-11-09T14:30:00', 'last_version': '2026.11.9'},
                      {'id': 2, 'name': 'Equipo Medellín (bodega)', 'revoked': True, 'created_at': '2026-10-01T10:00:00', 'created_by_name': '', 'last_seen_at': None, 'last_version': ''}]}


@route('GET', r'/api/inventory/events')
def inv_events(v, q):
    if v == 'empty':
        return {'events': []}
    return {'events': [{'id': i + 1, 'name': n, 'code': c, 'status': s, 'start_date': d} for i, (n, c, s, d, t) in enumerate(EVS)]}


CATS = [{'id': 1, 'name': 'Escarapelas y cordones'}, {'id': 2, 'name': 'Equipos'}]
PRODS = [{'id': 1, 'name': 'Escarapela PVC 62 × 100 mm', 'unit': 'unidades', 'sku': 'ESC-62', 'category_id': 1, 'category_name': 'Escarapelas y cordones', 'fields': [{'key': 'color', 'label': 'Color', 'kind': 'text'}]},
         {'id': 2, 'name': 'Cordón sublimado con logo del cliente', 'unit': 'unidades', 'sku': '', 'category_id': 1, 'category_name': 'Escarapelas y cordones', 'fields': []},
         {'id': 3, 'name': 'Impresora Brother QL-800', 'unit': 'equipos', 'sku': 'IMP-QL800', 'category_id': 2, 'category_name': 'Equipos', 'fields': []},
         {'id': 4, 'name': 'Tableta para registro', 'unit': 'equipos', 'sku': 'TAB-01', 'category_id': 2, 'category_name': 'Equipos', 'fields': []}]


@route('GET', r'/api/inventory/catalog')
def catalog(v, q):
    return {'categories': [dict(c, archived=False, products=2) for c in CATS], 'units': ['unidades', 'equipos'], 'products': [dict(p, archived=False, active=True) for p in PRODS]}


@route('GET', r'/api/events/\d+/inventory-plan')
def inv_plan(v, q):
    lines = [dict(p, archived=False, assigned=[850, 850, 4, 6][i], out=[850, 850, 4, 6][i], returned=[0, 0, 4, 5][i], consumed=[612, 600, 0, 0][i], notes='', attrs={}) for i, p in enumerate(PRODS)]
    return {'lines': lines, 'can_edit_plan': True, 'can_edit_movement': True, 'status': 'en_proceso', 'draft': False,
            'balance': {'ok': True, 'balanced': False, 'errors': [], 'warnings': [{'message': 'Tableta para registro: falta 1 por volver o consumir.'}]},
            'totals': {'assigned': 1710, 'out': 1710, 'returned': 9, 'consumed': 1212, 'pending': 489}, 'warnings': ['El evento empieza en 3 días: el inventario se suele asignar con 5 días de anticipación.']}


@route('GET', r'/api/payment-accounts')
def pay_accounts(v, q):
    if v == 'empty':
        return {'accounts': [], 'encryption_ready': True}
    return {'encryption_ready': True, 'accounts': [
        {'id': 1, 'name': 'Fundación Educativa del Caribe Colombiano', 'env': 'prod', 'active': True, 'holder': 'Fundación Educativa del Caribe', 'public_key_masked': 'pub_prod_••••3f9a', 'forms': 3, 'has_private': True, 'keys_readable': True, 'webhook_url': 'https://app.ejemplo.test/api/wompi/webhook/acct/1f0c2b7e-9d1a-4a4b-8a6e-3c1d2e3f4a5b'},
        {'id': 2, 'name': 'Club Deportivo', 'env': 'test', 'active': False, 'holder': '', 'public_key_masked': 'pub_test_••••11aa', 'forms': 0, 'has_private': False, 'keys_readable': False, 'webhook_url': 'https://app.ejemplo.test/api/wompi/webhook/acct/2'}]}


@route('GET', r'/api/payment-accounts-forms')
def pay_forms(v, q):
    if v == 'empty':
        return {'forms': []}
    return {'forms': [{'id': 10, 'name': 'Inscripción general con pago anticipado', 'event': EVS[0][0], 'event_id': 1, 'payment_account_id': 1, 'url': 'https://app.ejemplo.test/f/abc'},
                      {'id': 11, 'name': 'Taller', 'event': 'Feria Pyme', 'event_id': 2, 'payment_account_id': None, 'url': 'https://app.ejemplo.test/f/def'}]}


MONTHS = ['2026-06', '2026-07', '2026-08', '2026-09', '2026-10', '2026-11']


@route('GET', r'/api/gastos/infra/summary')
def gx_summary(v, q):
    import random
    random.seed(3)
    G = ['google', 'neon', 'microsoft', 'cloudflare', 'otros']
    series = {g: [0 if v == 'empty' else random.randint(50, 900) * 1000 for _ in MONTHS] for g in G}
    totals = [sum(series[g][i] for g in G) for i in range(len(MONTHS))]
    events = [] if v == 'empty' else [{'name': n, 'code': c, 'total': 400000 - i * 60000, 'fixed': 250000, 'variable': 150000 - i * 60000 if i < 3 else 0, 'share': 0.2, 'persons': 800 - i * 100} for i, (n, c, s, d, t) in enumerate(EVS)]
    return {'months': MONTHS, 'series': series, 'totals': totals, 'group_labels': {'google': 'Google Cloud', 'neon': 'Neon', 'microsoft': 'Microsoft 365', 'cloudflare': 'Cloudflare', 'otros': 'Otros'},
            'events': events, 'unassigned': 120000, 'unassigned_months': ['2026-06'], 'grand_total': sum(totals), 'monthly_avg': sum(totals) // 6, 'avg_per_event': 280000,
            'basis_labels': {'persons': 'Por personas registradas', 'days': 'Por días de evento', 'equal': 'Partes iguales'}, 'basis': 'persons', 'gcp_export_configured': False,
            'formula': 'costo del mes × (personas del evento ÷ personas de todos los eventos del mes)', 'trm_default': 4100, 'neon_configured': False}


@route('GET', r'/api/gastos/infra/costs')
def gx_costs(v, q):
    if v == 'empty':
        return {'costs': []}
    return {'costs': [{'id': i, 'month': MONTHS[i % 6], 'provider_label': ['Google Cloud', 'Neon', 'Microsoft 365'][i % 3], 'concept': ['Cloud Run y Cloud Storage', 'Plan Scale', 'Licencias Business Basic'][i % 3],
                       'note': 'Factura 123' if i == 1 else '', 'kind': 'fixed' if i % 2 else 'variable', 'currency': 'USD' if i % 3 == 1 else 'COP', 'amount': 69, 'trm': 4100, 'amount_cop': 282900 + i * 1000,
                       'source': 'gcp_export' if i % 3 == 0 else 'manual', 'has_attachment': i == 1} for i in range(6)]}


@route('GET', r'/api/gastos/eventos/filtros')
def ge_filtros(v, q):
    return {'clients': [{'id': 'acme', 'name': 'Acme'}], 'commercials': [{'id': 3, 'name': 'Laura Gómez'}], 'defaults': {'low_threshold': 2, 'overdue_days': 15, 'survey_wait_days': 7}}


@route('GET', r'/api/gastos/eventos/panel')
def ge_panel(v, q):
    st = {'n': 8, 'mean': 6.2, 'median': 5, 'p90': 12}
    grp = [{'name': 'Laura Gómez', 'events': 5, 'avg': 2.6, 'nps': 40, 'bill': st, 'close': st}, {'name': 'Andrés Salazar Montoya', 'events': 3, 'avg': 2.1, 'nps': -10, 'bill': st, 'close': st}]
    ev = [{'event_id': 1, 'name': EVS[0][0], 'client': 'Acme', 'avg': 2.8, 'nps_score': 10, 'reason': 'Calidad baja', 'days_waiting': 9, 'link_opened': True, 'commercial': 'Laura Gómez', 'has_base': False}]
    return {'range': {'from': '2026-06-01', 'to': '2026-11-30'}, 'events_total': 8, 'summary_text': '8 eventos entregados entre el 1 de junio y el 30 de noviembre de 2026; 6 respondieron la encuesta.',
            'kpis': {'nps': {'value': 33, 'promoters': 3, 'passives': 2, 'detractors': 1}, 'avg_quality': 2.45, 'responses': 6, 'response_rate_pct': 75, 'eligible': 8,
                     'next_event': {'pct_yes': 50, 'yes': 3, 'answered': 6}, 'converted': {'converted': 1}, 'bill_median_days': 5, 'close_median_days': 3},
            'satisfaction': {'questions': [{'label': 'Experiencia con el servicio del registro', 'avg': 2.6}, {'label': 'Presentación y atención del personal', 'avg': 2.8}, {'label': 'Tiempos de espera', 'avg': 2.1}],
                             'nps_distribution': [0, 0, 0, 1, 0, 0, 0, 1, 1, 2, 1], 'monthly': [{'month': m[5:], 'avg': 2 + i * 0.1, 'nps': -20 + i * 10} for i, m in enumerate(MONTHS)],
                             'best': ev, 'worst': ev, 'by_commercial': grp, 'by_coordinator': grp, 'by_client': grp, 'by_city': grp,
                             'comments': [{'text': 'Muy buena atención del equipo de registro, la fila avanzó rápido.', 'client': 'Acme', 'event': 'Feria Pyme', 'date': '03/11/2026'}]},
            'alerts': {'low_satisfaction': ev, 'pending_surveys': ev, 'declining_clients': [{'client': 'Acme', 'previous_avg': 2.8, 'last_avg': 2.1, 'drop': 0.7}]},
            'times': {'summary': {'close_days': st, 'base_days': st, 'bill_after_final_days': st, 'bill_after_end_days': st}, 'monthly': [{'month': m[5:], 'bill': {'mean': 5 + i}, 'close': {'mean': 3 + i / 2}} for i, m in enumerate(MONTHS)],
                      'overdue': ev, 'by_commercial': grp, 'by_client': grp}}


# ------- eventos y ventana de edición -------
def ev_obj(i):
    n, c, s, d, t = EVS[i % len(EVS)]
    return {'id': 42 + i, 'name': n, 'event_code': c, 'status': 'finalizado' if i == 0 else s, 'start_date': d, 'end_date': d, 'tenant_name': t, 'tenant_id': 'acme', 'city': 'Bogotá D.C.', 'country': 'CO',
            'location': 'Centro de Convenciones Ágora', 'address': 'Calle 24 # 38-47', 'commercial_name': 'Laura Gómez', 'coordinator_name': 'Andrés Salazar Montoya', 'state_name': 'Facturado' if i == 0 else '',
            'billed': i == 0, 'billed_by_name': 'Laura Gómez', 'billed_at': '2026-11-08T15:00:00', 'archived': False, 'super_event_name': 'Gira Nacional 2026' if i == 1 else '',
            'final_db_uploaded': i == 0, 'final_db_name': 'base_final_CNIT26.xlsx', 'final_db_uploaded_by_name': 'Andrés Salazar', 'final_db_uploaded_at': '2026-11-08T10:00:00',
            'report_uploaded': False, 'local': {'leased': i == 0, 'node_name': 'Portátil Sala 3', 'since': '2026-11-07T08:00:00', 'last_upload_at': '2026-11-09T14:30:00'}, 'extra': {}, 'state_id': 3 if i == 0 else None,
            'coordinator_staff_id': 5, 'commercial_staff_id': 3, 'commercial_name_x': ''}


@route('GET', r'/api/events/search')
def ev_search(v, q):
    import time; time.sleep(0.4)
    return [] if v == 'empty' else [ev_obj(i) for i in range(4)]


@route('GET', r'/api/events/(\d+)')
def ev_one(v, q, eid):
    return ev_obj(int(eid) - 42)


@route('GET', r'/api/staff/coordinators')
def coords(v, q):
    return [{'id': 5, 'full_name': 'Andrés Salazar Montoya', 'username': 'asalazar'}]


@route('GET', r'/api/staff/commercials')
def comms(v, q):
    return [{'id': 3, 'full_name': 'Laura Gómez', 'username': 'lgomez'}]


@route('GET', r'/api/event-states')
def states(v, q):
    return {'can_set_billed': True, 'states': [{'id': 1, 'name': 'Creado', 'base_status': 'creado', 'is_active': True, 'billing': False}, {'id': 2, 'name': 'Finalizado', 'base_status': 'finalizado', 'is_active': True, 'billing': False},
                                               {'id': 3, 'name': 'Facturado', 'base_status': 'finalizado', 'is_active': True, 'billing': True}]}


@route('GET', r'/api/super-events')
def supers(v, q):
    return [{'id': 1, 'name': 'Gira Nacional 2026', 'archived': False}]


@route('GET', r'/api/events/\d+/public-link')
def plink(v, q):
    return {'ok': True, 'slug': 'congreso-innovacion-2026', 'base': 'https://golden-eventos.com', 'clean_enabled': True, 'forms': [{'id': 10, 'name': 'Inscripción general', 'slug': 'inscripcion', 'is_primary': True}]}


@route('GET', r'/api/events/\d+/delivery')
def delivery(v, q):
    return {'eligible': True, 'link': 'https://golden-eventos.com/entrega/Zx81kQ_r2Lp0aN9cVb7', 'has_final_db': True, 'final_db_name': 'base_final_CNIT26.xlsx', 'survey_done': False,
            'last_opened_at': '2026-11-09T10:15:00', 'recipient': 'contacto@acme-ejemplo.test', 'public_url_ready': True}


@route('GET', r'/api/events/\d+/change-history')
def history(v, q):
    items = [{'changed_at_local': '09/11/2026 10:%02d a. m.' % (40 - i), 'changed_by': ['Laura Gómez', 'Andrés Salazar Montoya', None][i % 3], 'field_label': ['Estado', 'Ciudad', 'Notas internas del evento', 'Fecha de inicio'][i % 4],
              'source': ['state', 'edit', 'edit', 'import'][i % 4], 'old_value': ['Finalizado', 'Medellín', None, '2026-11-10'][i % 4], 'new_value': ['Facturado', 'Bogotá D.C.', 'Llevar 2 impresoras extra y 1 tableta de respaldo', '2026-11-12'][i % 4]} for i in range(10)]
    return {'items': items, 'total': 23, 'page': 1, 'per_page': 10, 'fields': [{'key': 'status', 'label': 'Estado'}, {'key': 'city', 'label': 'Ciudad'}]}




@route('GET', r'/api/colors')
def colors(v, q):
    return []


@route('GET', r'/api/system-alerts')
def alerts(v, q):
    return {'settings': {'enabled': True, 'per_action': 50, 'window_count': 200, 'window_minutes': 10},
            'recipients': [] if v == 'empty' else [{'id': 1, 'kind': 'email', 'email': 'seguridad@golden-ejemplo.test', 'label': '', 'role': '', 'active': True},
                                                   {'id': 2, 'kind': 'staff', 'email': 'maria.rodriguez@golden-ejemplo.test', 'label': 'María Fernanda Rodríguez Valderrama', 'role': 'super_admin', 'active': False}],
            'staff_options': [{'id': 7, 'label': 'Laura Gómez', 'role': 'comercial', 'has_email': True}],
            'recent': [] if v == 'empty' else [{'title': 'Borrado masivo: 312 personas del evento CNIT26', 'created_at': '2026-11-09T09:12:00', 'actor': 'Andrés Salazar Montoya (coordinador)', 'body': 'Una sola acción borró 312 registros de «Personas».'}]}


@route('GET', r'/api/events/\d+/queue/config')
def qconf(v, q):
    return {'enabled': True, 'mode': 'form', 'lanes': [{'letter': 'A', 'name': 'Acreditación general'}, {'letter': 'B', 'name': ''}], 'show_name': True, 'require_registered': False}


import json as _json, os as _os
try:
    _TPL = _json.load(open(_os.path.join(_os.path.dirname(__file__), 'tpl.json')))
except OSError:      # tpl.json no se versiona: sin él la pantalla de plantilla del evento no se simula, el resto sí
    _TPL = {}


@route('GET', r'/api/event-template')
def evtpl2(v, q):
    return dict(_TPL, people={})


@route('GET', r'/api/tenants')
def tenants(v, q):
    return [{'id': 'acme', 'name': 'Acme'}, {'id': 'acis', 'name': 'Asociación Colombiana de Ingenieros de Sistemas y Telecomunicaciones'}]


@route('GET', r'/api/cities')
def cities(v, q):
    return ['Bogotá D.C.', 'Medellín', 'Cali']


@route('GET', r'/api/my-events')
def my_events(v, q):
    return [] if v == 'empty' else [{'id': 42, 'name': EVS[0][0], 'event_code': 'CNIT26', 'status': 'en_proceso', 'tenant_name': EVS[0][4], 'start_date': '2026-11-12'}]


@route('GET', r'/api/inventory/overview')
def inv_overview(v, q):
    day = q.get('day') or '2026-11-11'
    prods = [dict(p, stock=[2000, 3000, 12, 20][i], in_use=[850, 850, 4, 25][i] if day.endswith('11') else 0) for i, p in enumerate(PRODS)]
    for p in prods:
        p['available'] = p['stock'] - p['in_use']
    return {'categories': CATS, 'products': prods, 'today': '2026-11-11', 'day': day, 'can_manage': True, 'can_edit_catalog': True}


@route('GET', r'/api/inventory/calendar')
def inv_calendar(v, q):
    import datetime as dt
    a = dt.date.fromisoformat(q.get('start') or '2026-10-26'); b = dt.date.fromisoformat(q.get('end') or '2026-12-06')
    def L(pid, n, name, unit): return {'product_id': pid, 'name': name, 'unit': unit, 'assigned': n, 'out': 0, 'returned': 0, 'pending_return': 0}
    evs = [
        {'id': 1, 'name': 'Momento de Encuentro Colaboradores 2026', 'code': 'FSJ-0011', 'status': 'en_proceso', 'event_start': '2026-11-10', 'event_end': '2026-11-12', 'start': '2026-11-09', 'end': '2026-11-12', 'has_inventory': True,
         'event_type_id': 1, 'event_type_name': 'Capacitación', 'event_type_color': '#2a6df4', 'lines': [L(1, 850, 'Escarapela PVC 62 × 100 mm', 'unidades'), L(2, 850, 'Cordón sublimado', 'unidades'), L(3, 4, 'Impresora Brother QL-800', 'equipos')]},
        {'id': 2, 'name': 'Feria Empresarial Cali', 'code': 'FEC-0007', 'status': 'creado', 'event_start': '2026-11-11', 'event_end': '2026-11-14', 'start': '2026-11-11', 'end': '2026-11-14', 'has_inventory': True,
         'event_type_id': 2, 'event_type_name': 'Feria', 'event_type_color': '#e8a317', 'lines': [L(4, 25, 'Tableta para registro', 'equipos'), L(3, 6, 'Impresora Brother QL-800', 'equipos')]},
        {'id': 3, 'name': 'Congreso Nacional de Logística', 'code': 'CNL-0003', 'status': 'creado', 'event_start': '2026-11-11', 'event_end': '2026-11-11', 'start': '2026-11-11', 'end': '2026-11-11', 'has_inventory': False,
         'event_type_id': None, 'event_type_name': None, 'event_type_color': None, 'lines': []},
        {'id': 4, 'name': 'Fin de año Bavaria', 'code': 'BAV-0021', 'status': 'creado', 'event_start': '2026-11-27', 'event_end': '2026-11-28', 'start': '2026-11-26', 'end': '2026-11-28', 'has_inventory': True,
         'event_type_id': 1, 'event_type_name': 'Capacitación', 'event_type_color': '#2a6df4', 'lines': [L(1, 400, 'Escarapela PVC 62 × 100 mm', 'unidades')]},
    ]
    daily = {}
    d = a
    while d <= b:
        iso = d.isoformat()
        for e in evs:
            if e['start'] <= iso <= e['end']:
                for l in e['lines']:
                    daily.setdefault(iso, {}); daily[iso][str(l['product_id'])] = daily[iso].get(str(l['product_id']), 0) + l['assigned']
        d += dt.timedelta(days=1)
    prods = [dict(p, stock=[2000, 3000, 8, 20][i]) for i, p in enumerate(PRODS)]
    return {'start': a.isoformat(), 'end': b.isoformat(), 'events': evs, 'products': prods, 'daily': daily, 'can_assign': True}


@route('GET', r'/api/events/42/forms$')
def forms_list(v, q):
    base = {'public_state': 'pruebas', 'use_schedule': False, 'submissions': 0, 'test_submissions': 0, 'preregistered': 0, 'capacity': None, 'archived': False,
            'public_url': 'https://app.golden-eventos.com/f/acreditaciones'}
    return [dict(base, id=1, name='ACREDITACIONES VASSAR MONTAJE', slug='acreditaciones'),
            dict(base, id=2, name='Inscripción general del Congreso Nacional de Innovación', slug='inscripcion-general', public_state='activo', submissions=1280, test_submissions=3, preregistered=42, capacity=2000)]


@route('GET', r'/api/events/42/staff-users$')
def temp_users(v, q):
    return [{'id': 1, 'username': '1023456789', 'full_name': 'Ana María Rodríguez', 'role': 'digitador', 'is_active': True, 'has_email': True, 'client_temp': False},
            {'id': 2, 'username': 'cli-k7m2xq', 'full_name': 'Carlos Pérez (Cliente)', 'role': 'digitador', 'is_active': True, 'has_email': False, 'client_temp': True}]


@route('GET', r'/api/staff/assignable')
def staff_assignable(v, q):
    return []


@route('GET', r'/api/events/42/staff-users/login-state')
def login_state(v, q):
    return {'can_manage': True, 'event_in_progress': True, 'accounts': [{'id': 1, 'locked': False, 'login_pending': True, 'req': 'r1'}]}


@route('GET', r'/api/events/42/pledge.*')
def pledge_any(v, q):
    return {}


# ------- CRM (C1b-2) -------
CRM_OWNERS = [{'id': 7, 'name': 'María Fernanda Rodríguez Valderrama'}, {'id': 8, 'name': 'Andrés Ochoa'}, {'id': 9, 'name': 'Laura Páez'}]


def _crm_account(i, v=''):
    names = ['Asociación Colombiana de Ingenieros de Sistemas y Telecomunicaciones', 'Distribuidora Andina S.A.S.', 'Fundación Horizonte', 'Corferias', 'Constructora Bolívar Ltda.',
             'Café Sierra Nevada', 'Universidad del Norte', 'Seguros Pacífico', 'Banco Mercantil', 'Logística Express']
    return {'id': i, 'code': 51000 + i, 'name': names[(i - 1) % len(names)], 'status': ['activo', 'activo', 'inactivo', 'masivo'][i % 4], 'city': ['Bogotá', 'Medellín', 'Cali', None][i % 4],
            'owner_staff_id': [7, 8, 9, None][i % 4], 'is_client': i % 3 == 0, 'tenant_id': 'acme' if i % 3 == 0 else None, 'archived': v == 'archived',
            'primary_contact': ['Camila Torres Quintero', None, 'Juan Pablo Rojas', 'Ana María Villegas de la Torre'][i % 4], 'updated_at': '2026-11-10T15:00:00'}


@route('GET', r'/api/crm/meta')
def crm_meta(v, q):
    return {'statuses': ['activo', 'inactivo', 'masivo'], 'owners': CRM_OWNERS, 'cities': ['Bogotá', 'Cali', 'Medellín'], 'payment_terms': ['Contado', '30 días', '60 días']}


@route('GET', r'/api/crm/accounts')
def crm_list(v, q):
    if v == 'error':
        return 500, {'detail': 'No se pudo cargar la lista.'}, {}
    if v == 'empty' or q.get('q') == 'zzz':
        return {'items': [], 'total': 0, 'page': 1, 'size': 20}
    items = [_crm_account(i, v) for i in range(1, 21)]
    return {'items': items, 'total': 1243, 'page': int(q.get('page') or 1), 'size': 20}


@route('GET', r'/api/crm/accounts/(\d+)')
def crm_get(v, q, i):
    if v == 'missing':
        return 404, {'detail': 'Cuenta no encontrada.'}, {}
    if v == 'error':
        return 500, {'detail': 'No se pudo cargar la ficha.'}, {}
    a = _crm_account(int(i), 'archived' if v == 'archived' else '')
    a['is_client'] = v == 'client'
    a.update({'nit': '900123456-7', 'email': 'contabilidad@ejemplo.test', 'phone': '601 555 1234', 'billing_address': 'Carrera 15 # 88-64, Oficina 502', 'billing_city': 'Bogotá',
              'billing_state': 'Cundinamarca', 'billing_country': 'Colombia', 'shipping_address': None, 'shipping_city': None, 'shipping_country': None,
              'billing_contact_name': 'Tesorería', 'billing_contact_phone': '601 555 9876', 'payment_term': '30 días', 'billing_close': 'Día 25', 'description': 'Cliente de congresos anuales.',
              'payment_days': 30, 'agency_percent': '10.00', 'created_at': '2024-03-02T10:00:00'})
    return a


@route('PUT', r'/api/crm/accounts/(\d+)')
def crm_put(v, q, i):
    if v == 'conflict':
        return 409, {'detail': 'Alguien más modificó esta cuenta mientras la editabas.'}, {}
    return crm_get('', q, i)


@route('POST', r'/api/crm/accounts')
def crm_create(v, q):
    return crm_get('', q, '1')


_CRM_CONTACTS = [
    {'id': 11, 'account_id': 1, 'first_name': 'Camila', 'last_name': 'Torres Quintero', 'full_name': 'Camila Torres Quintero', 'job_title': 'Directora de eventos', 'email': 'camila.torres@ejemplo.test',
     'phone': '601 555 1234', 'mobile': '300 123 4567', 'is_primary': True, 'notes': 'Prefiere que la llamen por la mañana.', 'archived': False, 'updated_at': '2026-11-10T15:00:00'},
    {'id': 12, 'account_id': 1, 'first_name': 'Juan Pablo', 'last_name': 'Rojas', 'full_name': 'Juan Pablo Rojas', 'job_title': None, 'email': 'jprojas@ejemplo.test', 'phone': None,
     'mobile': '310 999 8888', 'is_primary': False, 'notes': None, 'archived': False, 'updated_at': '2026-11-10T15:00:00'},
]


@route('GET', r'/api/crm/accounts/\d+/contacts')
def crm_contacts(v, q):
    if v == 'cerror':
        return 500, {'detail': 'No se pudieron cargar los contactos.'}, {}
    if q.get('archived'):
        return []
    return [] if v == 'cempty' else _CRM_CONTACTS


@route('GET', r'/api/crm/contacts/\d+/erase-preview')
def crm_preview(v, q):
    review = {'description': True, 'general_notes': 2} if v != 'clean' else {'description': False, 'general_notes': 0}
    return {'counts': {'contacts': 1, 'notes': 2, 'changes': 4, 'account_history': 3, 'account_fields': 2, 'tenant_fields': 3, 'review': review}}


@route('POST', r'/api/crm/contacts/\d+/erase')
def crm_erase(v, q):
    return crm_preview(v, q)['counts'] and {'message': 'Datos del contacto suprimidos', 'counts': crm_preview(v, q)['counts']}


@route('GET', r'/api/crm/accounts/\d+/notes')
def crm_notes(v, q):
    if v == 'nempty':
        return []
    return [{'id': 1, 'contact_id': 11, 'kind': 'note', 'body': 'Pidió cotización para el congreso de 2027.\nQuedamos en llamar el lunes.', 'author': 'María Fernanda Rodríguez Valderrama', 'created_at': '2026-11-09T14:00:00'},
            {'id': 2, 'contact_id': None, 'kind': 'note', 'body': 'Cuenta con crédito a 30 días.', 'author': 'Andrés Ochoa', 'created_at': '2026-11-02T09:30:00'}]


@route('GET', r'/api/crm/accounts/\d+/history')
def crm_history(v, q):
    return [{'entity': 'account', 'entity_id': 1, 'contact': None, 'field': 'payment_term', 'old': '30 días', 'new': '60 días', 'by': 'Andrés Ochoa', 'source': 'edit', 'at': '2026-11-10T15:00:00'},
            {'entity': 'contact', 'entity_id': 11, 'contact': 'Camila Torres Quintero', 'field': 'is_primary', 'old': 'False', 'new': 'True', 'by': 'Laura Páez', 'source': 'edit', 'at': '2026-11-09T11:00:00'},
            {'entity': 'account', 'entity_id': 1, 'contact': None, 'field': 'name', 'old': None, 'new': 'Asociación Colombiana de Ingenieros', 'by': None, 'source': 'import', 'at': '2026-10-01T08:00:00'}]
