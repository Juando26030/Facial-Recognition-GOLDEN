"""Arnés visual: renderiza plantillas de /tmp/vis con jinja2 y datos FICTICIOS, sirve /static y simula la API.
Uso: python3 server.py [puerto]. Página: /p/<clave>?v=<variante>."""
import datetime
import json
import mimetypes
import os
import re
import sys
import traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import jinja2

REPO = os.environ.get('REPO', '/tmp/vis')
sys.path.insert(0, os.path.dirname(__file__))
import mocks  # noqa: E402
import pages  # noqa: E402
import importlib  # noqa: E402


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def get(self, k, d=None):
        return self.__dict__.get(k, d)


@jinja2.pass_context
def url_for(ctx, name, **kw):
    if name == 'static':
        p = kw.get('path', '')
        try:
            v = int(os.path.getmtime(os.path.join(REPO, 'static', p)))
        except OSError:
            v = 0
        return f'/static/{p}?v={v}'
    return '/' + name


def make_env():
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.join(REPO, 'templates')), undefined=jinja2.ChainableUndefined, autoescape=jinja2.select_autoescape(['html']))
    env.globals.update(url_for=url_for, company_name='Golden Eventos y Logística S.A.S.', event_logo_url=lambda e: '/static/img/logo-golden.png', event_logo_attrs=lambda e: '', golden_logo_attrs=lambda *a: '',
                       public_base_url=lambda: 'https://app.ejemplo.test', print_settings_json=lambda e: '{}', deploy_env=lambda: '',
                       legal=lambda: {'company': 'Golden Eventos y Logística S.A.S.', 'nit': '900.000.000-0', 'address': 'Calle Falsa 123, Bogotá', 'email': 'datos@ejemplo.test', 'phone': '601 000 0000'})
    env.filters['fromjson'] = json.loads
    env.filters['local_dt'] = lambda dt: dt.strftime('%d/%m/%Y %I:%M %p') if dt else ''
    return env


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype='text/html; charset=utf-8', headers=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def handle_any(self, method):
        importlib.reload(mocks); importlib.reload(pages)
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path.startswith('/static/'):
            fp = os.path.join(REPO, u.path.lstrip('/'))
            if os.path.isfile(fp):
                ct = mimetypes.guess_type(fp)[0] or 'application/octet-stream'
                if fp.endswith('.js'):
                    ct = 'application/javascript'
                return self.send(200, open(fp, 'rb').read(), ct)
            return self.send(404, 'no')
        if u.path.startswith('/p/'):
            key = u.path[3:]
            try:
                env = make_env()
                tpl, ctx = pages.context(key, q.get('v', ''), Obj)
                local = ctx.pop('__local_server', False)
                env.globals['local_server'] = local
                ctx.setdefault('request', Obj(session={'staff_role': ctx.get('staff_role', 'admin')}, query_params={}, base_url='https://app.ejemplo.test/', url=Obj(path='/x')))
                html = env.get_template(tpl).render(**ctx)
                return self.send(200, html)
            except Exception:
                return self.send(500, '<pre>' + traceback.format_exc() + '</pre>')
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else b''
        ck = re.search(r'vv=([^;]*)', self.headers.get('Cookie', '') or '')
        res = mocks.handle(method, u.path, q, body, ck.group(1) if ck else '')
        if res is None:
            print('SIN SIMULAR', method, u.path, flush=True)
            return self.send(404, json.dumps({'detail': 'sin simular'}), 'application/json')
        code, data, hdrs = res
        if isinstance(data, (dict, list)):
            return self.send(code, json.dumps(data, default=str), 'application/json', hdrs)
        return self.send(code, data, (hdrs or {}).pop('Content-Type', 'text/plain'), hdrs)

    def do_GET(self):
        self.handle_any('GET')

    def do_POST(self):
        self.handle_any('POST')

    def do_PUT(self):
        self.handle_any('PUT')

    def do_PATCH(self):
        self.handle_any('PATCH')

    def do_DELETE(self):
        self.handle_any('DELETE')


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
