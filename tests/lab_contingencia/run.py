# ruff: noqa
"""Laboratorio de contingencia: maneja la pantalla REAL de Registro en Chrome sin pantalla, corta la «red» y comprueba que todo se guarde en el dispositivo y se envíe al volver. Ver LEEME.md.
Uso: python3 tests/lab_contingencia/run.py [nombre_de_caso ...]"""
import json, os, subprocess, sys, time, urllib.request
from playwright.sync_api import sync_playwright
HERE = os.path.dirname(os.path.abspath(__file__)); PORT = int(os.environ.get('PORT', '8766')); B = f'http://127.0.0.1:{PORT}'
CHROME = os.environ.get('CHROME', '/usr/bin/google-chrome')
VIEWS = {'celular': (390, 780), 'celular_horizontal': (780, 390), 'tableta': (800, 1280), 'tableta_horizontal': (1280, 800), 'escritorio': (1600, 900)}
def lab(path): return json.loads(urllib.request.urlopen(B + path, timeout=5).read() or b'{}')

class Lab:
    abiertos = []
    def __init__(self, pw, view='escritorio', role='super_admin'):
        lab('/__lab/reset'); lab('/__lab/role?v=' + role)
        self.b = pw.chromium.launch(executable_path=CHROME, args=['--no-sandbox']); Lab.abiertos.append(self)
        w, h = VIEWS[view]; self.ctx = self.b.new_context(viewport={'width': w, 'height': h}, has_touch=view.startswith(('celular', 'tableta')))
        self.ctx.add_init_script("window.GW_TOURS_OFF = true; try { const s = Storage.prototype.getItem; Storage.prototype.getItem = function (k) { return String(k).indexOf('gw_tour_') === 0 ? 'done' : s.call(this, k); }; } catch (e) {}")          # sin el recorrido de bienvenida
        self.pg = self.ctx.new_page(); self.errs = []; self.toasts = []
        self.pg.on('pageerror', lambda e: self.errs.append('JS: ' + str(e)))
        self.pg.on('console', lambda m: self.errs.append('consola: ' + m.text) if m.type == 'error' and 'Failed to load resource' not in m.text and 'net::ERR' not in m.text else None)
    def until(self, js, timeout=30, what=''):
        """Espera a que la expresión (puede ser una promesa) dé verdadero. `evaluate` sí espera las promesas; `wait_for_function` no."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if self.pg.evaluate(js): return True
            except Exception: pass
            time.sleep(.25)
        raise AssertionError(f'no se cumplió a tiempo: {what or js[:80]}')
    def open(self, wait_copy=True):
        self.pg.goto(B + '/kiosk/7/registro'); self.pg.wait_for_selector('#directoryTableBody tr[data-user-id]', timeout=15000)
        if wait_copy: self.until("(async()=>{const g=window.GoldenContingency&&GoldenContingency.instance; if(!g) return false; await g.ready; const m=await g.peopleMeta(); return !!(m&&m.n>=3 && await g.rosterUsable());})()", 15)
        self.pg.wait_for_function("navigator.serviceWorker && navigator.serviceWorker.controller", timeout=15000); time.sleep(.5)
    def offline(self):
        lab('/__lab/down?v=1'); self.until("GoldenContingency.instance.active()", 40, "entrar en contingencia"); time.sleep(.3)
    def online(self):
        lab('/__lab/down?v=0'); self.until("!GoldenContingency.instance.active()", 60, "salir de contingencia")
    def synced(self):
        self.until("(async()=>{const b=window.GoldenOutbox&&GoldenOutbox.instance, g=window.GoldenContingency&&GoldenContingency.instance; if(!b||!g||!b.supported) return false; await g.ready; const s=await b.stats(); return s.pending===0 && (await g.queueList()).length===0;})()", 60)
    def box(self): return self.pg.evaluate("(async()=>(await GoldenOutbox.instance.list()).map(i=>i.label+' = '+i.status+(i.detail?' ('+i.detail+')':'')))()")
    def toast_texts(self): return self.pg.evaluate("window.__T||[]")
    def row(self, name): return self.pg.locator('#directoryTableBody tr', has_text=name).first
    def edit(self, name):
        self.row(name).locator('button[title="Editar persona"]').evaluate('e => { e.scrollIntoView({ block: "center" }); e.click(); }'); self.pg.wait_for_selector('#editModalForm', timeout=5000)
    def save(self):
        self.pg.evaluate("window.__T=window.__T||[]; if(!window.__TP){window.__TP=1; const o=window.showToast; window.showToast=function(m,t){window.__T.push(String(m)); return o.apply(this,arguments);};} void 0")
        self.pg.click('#editModalSave'); time.sleep(1.2)
    def close(self): self.b.close()

def no_net_error(L, what):
    t = L.toast_texts(); assert not any('Error de red' in x for x in t), f'{what}: salió «Error de red» {t} {L.errs}'
    return t

# ------------------------------------------------------------------ casos
def caso_editar_dato_sin_red(pw):
    """El caso de Juan David (25-nov): sin red, Editar, agregar un dato y Guardar -> se guarda en el dispositivo y se envía al volver la red."""
    L = Lab(pw); L.open(); L.offline(); L.edit('Juan davis')
    L.pg.fill('#editModalForm [name="phone"]', '3001234567'); L.save()
    t = no_net_error(L, 'guardar sin red'); assert L.pg.locator('#editModalForm').count() == 0, f'el modal no se cerró {t} {L.errs}'
    row = L.pg.evaluate("(async()=>{const r=await GoldenContingency.instance.peopleLoad(); return r && r.find(u=>u.id==='10002020') || null;})()")
    if os.environ.get('DBG'): print('toasts', t, 'errs', L.errs, 'row', row, L.pg.evaluate("(async()=>{const g=GoldenContingency.instance; return [await g.peopleMeta(), await g.rosterUsable(), (await g.peopleLoad()||[]).map(u=>u.id+':'+u.status), (await GoldenOutbox.instance.list()).map(i=>i.label+':'+i.status), (await g.queueList()).length];})()"))
    assert row['phone'] == '3001234567' and row['status'] == 'Registrado', row
    assert not [x for x in lab('/__lab/state')['log'] if x['m'] == 'PATCH'], 'no debió llegar nada al servidor todavía'
    L.pg.reload(); L.pg.wait_for_selector('#directoryTableBody tr', timeout=15000)          # recargar sin red: los datos siguen ahí
    L.pg.wait_for_function("document.querySelector('#directoryTableBody').innerText.includes('Juan davis')", timeout=15000)
    L.online(); L.synced(); st = lab('/__lab/state'); u = next(x for x in st['users'] if x['id'] == '10002020')
    assert u['phone'] == '3001234567' and u['status'] == 'Registrado', (u, st['log']); assert not L.errs, L.errs; L.close()

def caso_guardar_justo_al_caerse_la_red(pw):
    """La red se cae y se guarda ENSEGUIDA (el letrero aún no ha salido): tampoco hay «Error de red»; queda en el dispositivo y se envía al volver."""
    L = Lab(pw); L.open(); lab('/__lab/down?v=1'); L.edit('Tester2')
    L.pg.fill('#editModalForm [name="entity"]', 'Entidad Nueva'); L.save(); time.sleep(1)
    t = no_net_error(L, 'guardar justo al caerse'); assert L.pg.locator('#editModalForm').count() == 0, f'el modal no se cerró {t} {L.errs}'
    L.until("GoldenContingency.instance.active()", 40, "entrar en contingencia")
    L.pg.wait_for_function("document.querySelector('#directoryTableBody').innerText.includes('Tester2')", timeout=15000)
    L.online(); L.synced(); u = next(x for x in lab('/__lab/state')['users'] if x['id'] == '10003030')
    assert u['entity'] == 'Entidad Nueva' and u['status'] == 'Registrado', u; L.close()

def caso_vaciar_dato_quitar_registro_cambiar_cedula_y_eliminar(pw):
    L = Lab(pw); L.open(); L.offline()
    L.edit('Juan davis'); L.pg.fill('#editModalForm [name="entity"]', ''); L.pg.fill('#editModalForm [name="email"]', 'a@b.co'); L.save(); no_net_error(L, 'vaciar')
    L.edit('Tester1'); L.pg.select_option('#editModalStatus', 'no_registrado'); L.pg.click('#editModalSave'); time.sleep(.4)
    confirm(L)
    time.sleep(1.2); no_net_error(L, 'quitar registro')
    L.edit('Tester2'); L.pg.fill('#editModalCedulaField', '10003031'); L.pg.click('#editModalSave'); time.sleep(.4); confirm(L); time.sleep(1.2); no_net_error(L, 'cambiar cédula')
    rows = L.pg.evaluate("(async()=>(await GoldenContingency.instance.peopleLoad()).map(u=>[u.id,u.status,u.entity,u.email]))()")
    assert ['10002020', 'Registrado', '', 'a@b.co'] in rows and ['10004040', 'No registrado', '', ''] in rows and any(r[0] == '10003031' for r in rows) and not any(r[0] == '10003030' for r in rows), rows
    L.pg.wait_for_function("document.querySelector('#directoryTableBody').innerText.includes('Tester2')", timeout=10000)
    L.edit('Tester1'); L.pg.locator('#editModalForm ~ button, .gw-modal button', has_text='Eliminar de este evento').first.click(); time.sleep(.4); confirm(L); time.sleep(1.2); no_net_error(L, 'eliminar')
    L.online(); L.synced(); st = lab('/__lab/state'); ids = sorted(x['id'] for x in st['users'])
    assert ids == ['10002020', '10003031'], (ids, L.box(), [(x['m'], x['p']) for x in st['log']]); u = next(x for x in st['users'] if x['id'] == '10002020'); assert u['entity'] == '' and u['email'] == 'a@b.co' and u['status'] == 'Registrado', u
    assert L.pg.evaluate("(async()=>(await GoldenOutbox.instance.list()).filter(i=>i.status==='error').length)()") == 0; assert not L.errs, L.errs; L.close()

TAPADOS = """(() => {
  const ov = [...document.querySelectorAll('[data-golden-banner], .gw-outbox__btn')].filter(e => e.offsetParent !== null || getComputedStyle(e).position === 'fixed').filter(e => { const r = e.getBoundingClientRect(); return r.width && r.height && getComputedStyle(e).display !== 'none'; });
  const inOv = (n) => ov.some(o => o === n || o.contains(n)), bad = [];
  const els = [...document.querySelectorAll('button, a[href], input, select, textarea, summary, [role=button]')].filter(e => !inOv(e));
  const pts = [];
  for (const el of els) { const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (!r.width || !r.height || cs.visibility === 'hidden' || cs.display === 'none' || el.disabled) continue;
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    if (x < 0 || x >= innerWidth || y < 0 || y >= innerHeight) continue;
    let top = document.elementFromPoint(x, y); if (!(top && inOv(top))) continue;
    el.scrollIntoView({ block: 'center' }); const r2 = el.getBoundingClientRect(), x2 = r2.left + r2.width / 2, y2 = r2.top + r2.height / 2;          // ¿sigue tapado aunque se lleve al centro?
    top = document.elementFromPoint(x2, y2); if (top && inOv(top)) pts.push([el, x2, y2]); }
  ov.forEach(o => { o.dataset.pe = o.style.pointerEvents; o.style.pointerEvents = 'none'; });
  for (const [el, x, y] of pts) { const top = document.elementFromPoint(x, y); if (top && (top === el || el.contains(top) || top.contains(el) && top.tagName === 'LABEL')) bad.push((el.id || el.name || el.innerText || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 40)); }
  ov.forEach(o => { o.style.pointerEvents = o.dataset.pe || ''; });
  return bad; })()"""
def nada_tapado(L, donde):
    """Ningún botón, campo o enlace que se pueda tocar queda debajo del letrero de contingencia, del aviso de la bandeja ni de su botón. Se revisa arriba, en medio y abajo de cada zona con barra."""
    scrollers = "[document.scrollingElement, ...document.querySelectorAll('.gw-modal__body, .gw-modal, .gw-modal-backdrop, .gw-registro__overlay, .gw-outbox__modal, .gw-outbox__panel, main')].filter(e => e && e.scrollHeight > e.clientHeight + 4)"
    n = L.pg.evaluate(f"({scrollers}).length")
    bad = set(L.pg.evaluate(TAPADOS))
    for i in range(n):
        for frac in (0.5, 1, 0):
            L.pg.evaluate(f"(()=>{{const e=({scrollers})[{i}]; if(e) e.scrollTop=(e.scrollHeight-e.clientHeight)*{frac};}})()"); time.sleep(.08)
            bad |= set(L.pg.evaluate(TAPADOS))
    assert not bad, f'{donde}: queda tapado -> {sorted(bad)}'
def visible_y_tocable(L, sel, donde):
    ok = L.pg.evaluate("(sel)=>{const e=document.querySelector(sel); if(!e) return 'no existe'; e.scrollIntoView({block:'center'}); const r=e.getBoundingClientRect(); if(r.top<0||r.bottom>innerHeight||r.left<0||r.right>innerWidth) return 'fuera de la pantalla '+JSON.stringify([r.top,r.bottom,innerHeight]); const t=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2); return (t===e||e.contains(t))?'':'tapado por '+(t&&(t.className||t.tagName));}", sel)
    assert ok == '', f'{donde}: {sel} {ok}'

def caso_el_letrero_no_tapa_nada(pw):
    """Pedido de Juan David: el letrero rojo tapaba «Guardar» en el celular. En celular, tableta y computador (vertical y horizontal): lista, Editar, Registrar nuevo y Bandeja."""
    for view in VIEWS:
        L = Lab(pw, view); L.open(); L.offline(); nada_tapado(L, f'{view} lista')
        h = L.pg.evaluate("document.querySelector('[data-golden-banner=\"1\"]').getBoundingClientRect().height"); assert h <= (70 if VIEWS[view][0] < 640 else 60), f'{view}: el letrero mide {h}px'
        L.edit('Juan davis'); time.sleep(.3); visible_y_tocable(L, '#editModalSave', f'{view} editar'); nada_tapado(L, f'{view} editar')
        L.pg.fill('#editModalForm [name="phone"]', '300'); visible_y_tocable(L, '#editModalSave', f'{view} editar'); L.save(); no_net_error(L, view); time.sleep(.4)
        nada_tapado(L, f'{view} lista con pendientes')                                   # ya hay aviso de la bandeja abajo
        L.edit('Tester2'); time.sleep(.3); visible_y_tocable(L, '#editModalSave', f'{view} editar con bandeja'); nada_tapado(L, f'{view} editar con bandeja')
        L.pg.evaluate("document.querySelector('.gw-modal-backdrop.gw-registro__edit')?.querySelector('[data-close], .gw-modal__close, #editModalCancel')?.click()"); time.sleep(.2)
        L.pg.keyboard.press('Escape'); time.sleep(.2)
        assert not L.errs, L.errs; L.b.close()

def caso_registrar_nuevo_sin_red(pw):
    """Sin red: «Registrar nuevo» con sus datos; aparece en la lista del dispositivo y llega al servidor al volver la red. En celular, sin que el letrero tape «Guardar»."""
    L = Lab(pw, 'celular'); L.open(); L.offline(); L.pg.locator('#openRegisterModalBtn').evaluate('e => e.click()'); time.sleep(.4)
    visible_y_tocable(L, '#regForm button[type="submit"]', 'registrar nuevo'); nada_tapado(L, 'celular registrar nuevo')
    L.pg.fill('#regForm [name="id"]', '10009090'); L.pg.fill('#regForm [name="first_name"]', 'Nueva')
    L.pg.evaluate("window.__T=[]; if(!window.__TP){window.__TP=1; const o=window.showToast; window.showToast=function(m,t){window.__T.push(String(m)); return o.apply(this,arguments);};} void 0")
    L.pg.locator('#regForm button[type="submit"]').evaluate('e => e.click()'); time.sleep(1.5); t = no_net_error(L, 'registrar nuevo')
    L.until("document.querySelector('#directoryTableBody').innerText.includes('Nueva')", 10, f'la persona nueva en la lista {t} {L.errs}')
    L.online(); L.synced(); u = next((x for x in lab('/__lab/state')['users'] if x['id'] == '10009090'), None); assert u and u['first_name'] == 'Nueva' and u['status'] == 'Registrado', (u, L.box()); assert not L.errs, L.errs

def caso_areas_sin_red(pw):
    """Control de áreas sin red: entra, no deja reingresar donde no se permite, y al volver la red el servidor recibe los movimientos con su hora real."""
    L = Lab(pw, 'tableta'); L.pg.goto(B + '/kiosk/7/areas'); L.until("window.GoldenContingency && GoldenContingency.instance && document.querySelector('#areaSelect') && document.querySelector('#areaSelect').options.length >= 2", 20, 'cargar áreas')
    L.until("(async()=>{const g=GoldenContingency.instance; await g.ready; return !!(await g.peopleMeta()) && !!(await g.cacheGet('/api/events/7/areas/2/presence')) && !!navigator.serviceWorker.controller;})()", 25, 'copias de áreas')
    L.offline(); nada_tapado(L, 'tableta áreas')
    def scan(ced):
        L.pg.fill('#scanInput', ced); L.pg.locator('#registerBtn').evaluate('e => e.click()'); time.sleep(1.0); return L.pg.evaluate("document.querySelector('#banner').innerText")
    L.pg.evaluate("(()=>{const s=document.querySelector('#areaSelect'); s.value='2'; s.dispatchEvent(new Event('change',{bubbles:true}));})()"); time.sleep(.6)
    r1 = scan('10002020'); assert 'Entró' in r1 or 'Juan' in r1, r1
    r2 = scan('10002020'); assert 'Salió' in r2, r2                          # en automático, la segunda lectura es la salida
    r3 = scan('10002020'); assert 'reingres' in r3.lower() or 'ya había' in r3.lower(), r3          # zona sin reingresos: no vuelve a entrar
    L.pg.reload(); L.until("document.querySelector('#areaSelect') && document.querySelector('#areaSelect').options.length >= 2", 20, 'recargar áreas sin red')
    L.online(); L.synced(); st = lab('/__lab/state'); mv = [x for x in st['log'] if x['p'].endswith('/movement')]
    assert [x['body']['direction'] for x in mv] == ['in', 'out'] and all(x['body'].get('client_time') for x in mv), mv; assert [(r['id'], r['direction']) for r in st['presence']['2']] == [('10002020', 'out')]; assert not L.errs, L.errs

def caso_inventario_sin_red(pw):
    """Control de inventario sin red: entrega, no repite lo que no se repite, y al volver la red llega al servidor."""
    L = Lab(pw, 'tableta'); L.pg.goto(B + '/kiosk/7/inventario'); L.until("window.GoldenContingency && GoldenContingency.instance && document.querySelectorAll('#itemsList input, #itemsList button').length > 0", 20, 'cargar inventario')
    L.until("(async()=>{const g=GoldenContingency.instance; await g.ready; return !!(await g.peopleMeta()) && !!(await g.cacheGet('/api/events/7/inventory')) && !!navigator.serviceWorker.controller;})()", 25, 'copias de inventario')
    L.offline(); nada_tapado(L, 'tableta inventario')
    def entregar(ced):
        L.pg.fill('#scanInput', ced); L.pg.keyboard.press('Enter'); time.sleep(.6)
        L.pg.evaluate("(()=>{const i=document.querySelector('#itemsList input[type=number]'); if(i){ i.value='1'; i.dispatchEvent(new Event('input',{bubbles:true})); i.dispatchEvent(new Event('change',{bubbles:true})); } else { const b=document.querySelector('#itemsList button, #itemsList input[type=checkbox]'); if(b) b.click(); } })()"); time.sleep(.3)
        L.pg.locator('#deliverBtn').evaluate('e => e.click()'); time.sleep(1.0); return L.pg.evaluate("document.querySelector('#resultBanner').innerText")
    r1 = entregar('10004040'); assert 'Entregado' in r1, (r1, L.pg.evaluate("[document.querySelector('#itemsList').innerHTML.slice(0,500), document.querySelector('#personBanner').innerText, document.querySelector('#deliverBtn').disabled]"), L.errs)
    r2 = entregar('10004040'); assert 'ya recibió' in r2.lower() or 'no se pudo' in r2.lower(), r2
    L.online(); L.synced(); st = lab('/__lab/state'); assert [d['user_id'] for d in st['deliveries']] == ['10004040'] and st['items'][0]['available'] == 9, (st['deliveries'], L.box()); assert not L.errs, L.errs

def confirm(L):
    """Acepta el cuadro de confirmación de toast.js (el botón principal del último cuadro abierto)."""
    L.pg.evaluate("(()=>{const b=[...document.querySelectorAll('button')].filter(x=>x.offsetParent&&/^(s[ií]|aceptar|continuar|confirmar|cambiar|eliminar)/i.test(x.innerText.trim())&&x.id!=='editModalSave'&&!/de este evento/i.test(x.innerText)); if(b.length) b[b.length-1].click();})()")

CASOS = {k[5:]: v for k, v in list(globals().items()) if k.startswith('caso_')}          # el nombre del caso es el de la función sin «caso_»
if __name__ == '__main__':
    srv = subprocess.Popen([sys.executable, os.path.join(HERE, 'srv.py'), str(PORT)]); time.sleep(1); bad = 0
    try:
        with sync_playwright() as pw:
            for name in (sys.argv[1:] or list(CASOS)):
                try: CASOS[name](pw); print('OK   ', name)
                except Exception as e: bad += 1; print('FALLA', name, '->', ' '.join(x for x in str(e).split('\n') if 'intercepts' in x or 'waiting for' in x or not x.startswith(' '))[:1100])
                finally:
                    for L in list(Lab.abiertos):
                        try: L.b.close()
                        except Exception: pass
                    Lab.abiertos.clear()
    finally: srv.terminate()
    sys.exit(1 if bad else 0)
