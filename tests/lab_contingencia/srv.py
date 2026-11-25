# ruff: noqa
"""Laboratorio de contingencia: sirve la pantalla REAL de Registro (plantilla + JS del repo) con un servidor de mentira (personas inventadas), para manejarla con Chrome sin pantalla.
Sin base de datos ni FastAPI. Ver LEEME.md. Uso: python3 tests/lab_contingencia/srv.py [puerto]"""
import json, os, re, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import jinja2

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
EV = 7
FIELDS = [
    {"key": "first_name", "label": "Nombres", "field_type": "text", "required": True, "visible": True, "position": 1},
    {"key": "last_name", "label": "Apellidos", "field_type": "text", "required": False, "visible": True, "position": 2},
    {"key": "id", "label": "Cédula", "field_type": "text", "required": True, "visible": True, "position": 3},
    {"key": "role", "label": "Cargo", "field_type": "text", "required": False, "visible": True, "position": 4},
    {"key": "entity", "label": "Entidad", "field_type": "text", "required": False, "visible": True, "position": 5},
    {"key": "phone", "label": "Teléfono", "field_type": "text", "required": False, "visible": True, "position": 6},
    {"key": "email", "label": "Correo Electrónico", "field_type": "text", "required": False, "visible": True, "position": 7},
    {"key": "opt_1", "label": "Tipo de Asistente", "field_type": "text", "required": False, "visible": True, "position": 8},
]
STATE = {}
def reset():
    STATE.clear()
    STATE.update(users=[
        {"id": "10002020", "first_name": "Juan davis", "last_name": "Ramirez", "role": "", "entity": "Golden Logisticas", "phone": "", "email": "", "opt_1": "", "status": "No registrado", "origin": "base", "categories": [], "extra_fields": {}},
        {"id": "10003030", "first_name": "Tester2", "last_name": "Dos", "role": "", "entity": "", "phone": "", "email": "", "opt_1": "", "status": "No registrado", "origin": "base", "categories": [], "extra_fields": {}},
        {"id": "10004040", "first_name": "Tester1", "last_name": "Uno", "role": "", "entity": "", "phone": "", "email": "", "opt_1": "", "status": "Registrado", "origin": "base", "categories": [], "extra_fields": {}},
    ], log=[], down=False, role='super_admin',
    areas=[{"id": 1, "name": "Salón", "allow_reentry": True, "is_group": False, "parent_id": None, "inside": 0, "max_capacity": None}, {"id": 2, "name": "Almuerzo", "allow_reentry": False, "is_group": False, "parent_id": None, "inside": 0, "max_capacity": None}],
    presence={"1": [], "2": []}, items=[{"id": 5, "name": "Camiseta", "initial_qty": 10, "delivered": 0, "available": 10, "is_group": False, "parent_id": None, "allow_repeat_delivery": False, "max_per_person": 1, "active": True}], deliveries=[])
reset()

class Soft(jinja2.ChainableUndefined):
    def __call__(self, *a, **k): return Soft()
    def __iter__(self): return iter(())
    def __bool__(self): return False
env = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.join(ROOT, 'templates')), undefined=Soft, autoescape=True)
env.globals['url_for'] = lambda name, path='', **k: f'/static/{path}'
env.filters.setdefault('tojson', lambda v: jinja2.utils.htmlsafe_json_dumps(v))

def page(name):
    event = dict(id=EV, name='Evento de laboratorio', status='en_proceso', facial_enabled=False, auto_print_badge=False, auto_register=False, directory_page_size=50, reprint_disabled=False, areas_enabled=True, inventory_enabled=True, areas_autoscan=True, inventory_autoscan=False)
    ctx = dict(event=event, dependents_cfg_json='null', optional_labels_json='{}', reg_card_fields_json='[]', person_form_json='null', autoprint_rules=False, event_id=EV, event_name='Evento de laboratorio', event_status='en_proceso', staff_role=STATE['role'], staff_username='lab', contingency_enabled=True,
               field_configs_json=json.dumps(FIELDS), field_configs=FIELDS, auto_register=False, auto_print=False, print_offline_json=json.dumps({"per_category": False, "categories": [], "labels": {}, "code": False}),
               can_register=True, event_in_progress=True, static_version='lab')
    return env.get_template(name).render(**ctx)

import hashlib
SALT = 'ab' * 16
def fp(c): return hashlib.sha256(f'{SALT}:{c}'.encode()).hexdigest()[:16]

class Quiet(ThreadingHTTPServer):
    def handle_error(self, request, client_address): pass          # el navegador cortó la conexión (pasa al simular la caída de red)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body, ctype='application/json', extra=None):
        b = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(code); self.send_header('Content-Type', ctype + ('; charset=utf-8' if 'json' in ctype or 'html' in ctype or 'javascript' in ctype or 'css' in ctype else ''))
        self.send_header('Content-Length', str(len(b))); self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)
    def body(self):
        n = int(self.headers.get('Content-Length') or 0); raw = self.rfile.read(n) if n else b''
        try: return json.loads(raw or b'{}')
        except Exception: return {}
    def user(self, uid): return next((u for u in STATE['users'] if u['id'] == uid), None)
    def do_GET(self): self.route('GET')
    def do_POST(self): self.route('POST')
    def do_PATCH(self): self.route('PATCH')
    def do_PUT(self): self.route('PUT')
    def do_DELETE(self): self.route('DELETE')
    def route(self, m):
        u = urlparse(self.path); p = u.path; q = parse_qs(u.query)
        if p == '/__lab/state': return self.send(200, STATE)
        if p == '/__lab/reset': reset(); return self.send(200, {})
        if p == '/__lab/down': STATE['down'] = q.get('v', ['1'])[0] == '1'; return self.send(200, {})
        if p == '/__lab/role': STATE['role'] = q.get('v', ['super_admin'])[0]; return self.send(200, {})
        if STATE['down']:                                                   # «sin red»: se corta la conexión sin responder
            try: self.connection.shutdown(2)
            except Exception: pass
            return
        if p.startswith('/static/'):
            f = os.path.join(ROOT, p.lstrip('/'))
            if not os.path.isfile(f): return self.send(404, 'no', 'text/plain')
            ct = {'js': 'application/javascript', 'css': 'text/css', 'svg': 'image/svg+xml', 'png': 'image/png', 'woff2': 'font/woff2', 'json': 'application/json'}.get(f.rsplit('.', 1)[-1], 'application/octet-stream')
            return self.send(200, open(f, 'rb').read(), ct)
        if p == '/kiosk/sw.js': return self.send(200, open(os.path.join(ROOT, 'static/js/kiosk-sw.js'), encoding='utf8').read().replace('__BUILD__', 'lab'), 'application/javascript', {'Service-Worker-Allowed': '/kiosk/'})
        m2 = re.match(r'^/kiosk/\d+/(registro|areas|inventario)$', p)
        if m2: return self.send(200, page(f'kiosk_{m2.group(1)}.html'), 'text/html')
        if re.match(r'^/kiosk/\d+/escarapela/imprimir/', p): return self.send(200, '<html><body>ventana de impresión (laboratorio)\n    const USER_ID = "x";\n    const USER_IDS = ["x"];\n</body></html>', 'text/html')
        if p in ('/health', '/api/ping-auth'): return self.send(200, {"ok": True})
        if m != 'GET': STATE['log'].append({"m": m, "p": p, "body": self.body() if m != 'DELETE' else None, "op": self.headers.get('X-Op-Id')})
        last = STATE['log'][-1] if (m != 'GET' and STATE['log']) else None
        if p == '/api/users' and m == 'GET': return self.send(200, STATE['users'])
        if p == '/api/users/changes': return self.send(200, {"users": [], "total": len(STATE['users']), "cursor": "c1"})
        if p.endswith('/local-roster'):
            return self.send(200, {"v": "v" + str(len(STATE['log'])), "generated_at": "2026-11-25T00:00:00", "max_age_s": 86400, "event": {"id": EV, "status": "en_proceso", "auto_register": False}, "salt": SALT, "count": len(STATE['users']),
                                   "people": [{"h": fp(x['id']), "n": (x['first_name'] + ' ' + x['last_name']).strip(), "c": x['categories'], "s": x['status']} for x in STATE['users']]})
        mm = re.match(r'^/api/users/([^/]+)$', p)
        if mm and m == 'PATCH':
            x = self.user(mm.group(1))
            if not x: return self.send(404, {"detail": "No existe"})
            b = last['body']; [x.__setitem__(k, v) for k, v in b.items() if k in x and k not in ('id', 'status')]; return self.send(200, {"message": "ok"})
        if mm and m == 'DELETE':
            STATE['users'] = [x for x in STATE['users'] if x['id'] != mm.group(1)]; return self.send(200, {"message": "ok"})
        mm = re.match(r'^/api/users/([^/]+)/cedula$', p)
        if mm and m == 'PUT':
            x = self.user(mm.group(1))
            if not x: return self.send(404, {"detail": "No existe"})
            x['id'] = last['body']['new_id']; return self.send(200, {"message": "ok"})
        mm = re.match(r'^/api/events/\d+/users/([^/]+)/status$', p)
        if mm and m == 'PATCH':
            x = self.user(mm.group(1))
            if not x: return self.send(404, {"detail": "No existe"})
            x['status'] = 'Registrado' if last['body'].get('status') == 'registrado' else 'No registrado'; return self.send(200, {"status": x['status']})
        if p.endswith('/access-logs/sync') and m == 'POST':
            out = []
            for r in last['body'].get('records', []):
                x = next((y for y in STATE['users'] if fp(y['id']) == r.get('h')), None)
                if x: x['status'] = 'Registrado'
                out.append({"client_id": r.get('client_id'), "result": "ok" if x else "not_found"})
            return self.send(200, {"results": out})
        if p.endswith('/outbox/sync') and m == 'POST':
            out = []
            for o in last['body'].get('ops', []):
                f = o.get('fields') or {}
                if o.get('type', 'create_person') == 'create_person' and not self.user(f.get('id')):
                    STATE['users'].append({"id": f.get('id'), "first_name": f.get('first_name', ''), "last_name": f.get('last_name', ''), "role": f.get('role', ''), "entity": f.get('entity', ''), "phone": f.get('phone', ''), "email": f.get('email', ''), "opt_1": f.get('opt_1', ''), "status": "Registrado", "origin": "manual", "categories": [], "extra_fields": {}})
                out.append({"op_id": o.get('op_id'), "result": "ok"})
            return self.send(200, {"results": out})
        if p.endswith('/areas') and m == 'GET': return self.send(200, STATE['areas'])
        mm = re.match(r'^/api/events/\d+/areas/(\d+)/presence$', p)
        if mm: return self.send(200, STATE['presence'].get(mm.group(1), []))
        mm = re.match(r'^/api/events/\d+/areas/(\d+)/movement$', p)
        if mm and m == 'POST':
            b = last['body']; x = self.user(b.get('cedula')); ar = next(a for a in STATE['areas'] if str(a['id']) == mm.group(1)); rows = STATE['presence'][mm.group(1)]
            if not x: return self.send(200, {"result": "NOT_FOUND"})
            prev = next((r for r in rows if r['id'] == x['id']), None); d = b.get('direction') or 'auto'
            if d == 'auto': d = 'out' if prev and prev['direction'] == 'in' else 'in'
            if d == 'in' and prev and not ar['allow_reentry']: return self.send(200, {"result": "ALREADY_ENTERED", "details": "YA había entrado", "data": x, "area": ar['name'], "direction": "in"})
            STATE['presence'][mm.group(1)] = [{"id": x['id'], "name": x['first_name'], "direction": d, "time": b.get('client_time') or "2026-11-25T12:00:00"}] + [r for r in rows if r['id'] != x['id']]
            ar['inside'] += 1 if d == 'in' else -1
            return self.send(200, {"result": "OK", "direction": d, "area": ar['name'], "data": x, "time": b.get('client_time') or "2026-11-25T12:00:00"})
        if p.endswith('/inventory') and m == 'GET': return self.send(200, STATE['items'])
        if p.endswith('/inventory/deliveries'): return self.send(200, STATE['deliveries'])
        if p.endswith('/inventory/deliver') and m == 'POST':
            b = last['body']; x = self.user(b.get('cedula')); out = []
            for ln in b.get('items', []):
                it = next(i for i in STATE['items'] if i['id'] == ln['item_id'])
                if any(dv['user_id'] == x['id'] and dv['item_id'] == it['id'] for dv in STATE['deliveries']): return self.send(400, {"detail": "Ya recibió ese ítem"})
                it['available'] -= ln['qty']; it['delivered'] += ln['qty']; out.append({"qty": ln['qty'], "name": it['name']})
                STATE['deliveries'].insert(0, {"time": "2026-11-25T12:00:00", "user_id": x['id'], "batch_id": "b", "name": x['first_name'], "item": it['name'], "item_id": it['id'], "qty": ln['qty']})
            return self.send(200, {"message": "ok", "delivered": out, "data": x})
        if m == 'GET': return self.send(200, [] if p.endswith(('/history', '/print-jobs')) else {})
        return self.send(200, {})

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    Quiet(('127.0.0.1', port), H).serve_forever()
