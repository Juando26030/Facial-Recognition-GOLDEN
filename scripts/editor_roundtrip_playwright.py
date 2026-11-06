#!/usr/bin/env python3
"""Prueba REAL en navegador del editor de formularios (templates/kiosk_formulario_editor.html).

Levanta un servidor local que (1) renderiza la plantilla con jinja2, (2) sirve /static, y (3) simula la API de formularios usando la
validación REAL del servidor (app/formlib.sanitize_settings / sanitize_design): lo que el editor envía se pasa por ella y se devuelve
fusionado, igual que `PUT /api/events/{id}/forms/{id}`. Luego maneja Chromium con Playwright y comprueba que NADA de lo cargado se pierde
al guardar (pre-llenado, imágenes, textos con formato, cupos, devoluciones, seguridad...).

Uso (desde la raíz del repo; necesita `pip install playwright` + Chromium, por eso NO está en tests/ ni corre en el CI):
    python scripts/editor_roundtrip_playwright.py                 # plantilla actual del árbol de trabajo
    python scripts/editor_roundtrip_playwright.py --ref e6608f2   # otra versión de la plantilla, sacada de git
    python scripts/editor_roundtrip_playwright.py --shots out/    # además guarda capturas a 1280 y 390 px
Sale con código 1 si algún escenario falla.
"""
import argparse, copy, json, os, subprocess, sys, threading, types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from jinja2 import ChainableUndefined, Environment, FileSystemLoader, DictLoader, ChoiceLoader  # noqa: E402
from app import formlib  # noqa: E402

EV, FID = 11, 4
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000" "1f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")


def synthetic_form(prefill_mode="cedula"):
    ids = [f"f_{i:02d}" for i in range(10)]
    fields = {}
    for i in range(4):
        fields[ids[i]] = {"id": ids[i], "type": "text_short", "key": ["id", "first_name", "last_name", None][i], "label": ["Cédula", "Nombres", "Apellidos", "Ciudad"][i], "required": i < 3, "stats": False}
    fields[ids[4]] = {"id": ids[4], "type": "image", "src": "x/campo.jpeg", "label": "Imagen"}
    fields[ids[5]] = {"id": ids[5], "type": "paragraph", "content": "Texto con <b>negrilla</b>"}
    fields[ids[6]] = {"id": ids[6], "type": "paragraph", "content": "Segundo texto"}
    fields[ids[7]] = {"id": ids[7], "type": "heading", "content": "Título uno"}
    fields[ids[8]] = {"id": ids[8], "type": "heading", "content": "Título dos"}
    fields[ids[9]] = {"id": ids[9], "type": "checkbox", "label": "Acepto", "required": False, "stats": False}
    design = {"theme": {"title": "Formulario de prueba", "subtitle": "Sub", "logo": "x/logo.jpeg", "bg_image": "", "logo_full": True, "bg_color": "#F4F5F9", "card_color": "#FFFFFF",
                        "text_color": "#0A0E2E", "accent": "#D4AF37", "button_text": "Enviar", "font": "Montserrat"},
              "rows": [{"align": "left", "items": [i]} for i in ids], "fields": fields}
    design = formlib.sanitize_design(design, set())
    settings = {
        "security": {"enabled": True, "type": "cedula", "code": ""}, "prefill": {"mode": prefill_mode, "source": "event"},
        "closed_template": {"title": "Cerrado", "text": 'Vuelve <span style="font-weight:bold">mañana</span>', "image": "x/c.jpeg"},
        "thanks": {"mode": "template", "title": "Gracias", "text": 'Listo <span style="font-weight:bold">ya</span>', "image": "x/t.jpeg", "url": ""},
        "identify": {"title": "Identifícate", "text": 'Escribe tu <span style="font-weight:bold">cédula</span>', "image": "x/i.jpeg", "button": "Seguir"},
        "refunds": {"days": 15, "note": "Nota de devolución"},
        "quotas": {"rules": [{"id": "q1", "label": "VIP", "message": "Se llenó {cupo}", "match": "all", "limit": 5, "conds": [{"field": ids[3], "op": "equals", "value": "Bogotá"}]},
                             {"id": "q2", "label": "General", "message": "Sin cupo general", "match": "all", "limit": 0, "conds": [{"field": ids[3], "op": "contains", "value": "a"}]}]},
        "feed": "manual", "max_mb": 10, "language": "es", "translate": True, "send_digital_badge": False, "block_repeats": {"enabled": True, "field": ""},
    }
    settings = formlib.sanitize_settings(settings)
    return design, settings


class State:
    def __init__(self, prefill_mode="cedula"):
        self.design, self.settings = synthetic_form(prefill_mode)
        self.manual_status, self.capacity, self.use_schedule, self.schedule = "cerrado", None, False, []
        self.puts, self.uploads, self.unknown, self.n_up = [], [], [], 0

    def detail(self):
        qs = [{"id": r["id"], "used": 0, "left": r["limit"]} for r in self.settings["quotas"]["rules"] if r.get("id") and r.get("limit") is not None]
        return {"id": FID, "name": "Formulario de prueba", "slug": "prueba", "manual_status": self.manual_status, "use_schedule": self.use_schedule, "status": self.manual_status,
                "public_state": self.manual_status, "capacity": self.capacity, "submissions": 0, "test_submissions": 0, "preregistered": 0, "registered_hold": 0, "feed": self.settings["feed"],
                "public_url": f"http://localhost/f/{EV}/prueba", "test_url": f"http://localhost/f/{EV}/prueba?k=abc", "design": self.design, "settings": self.settings, "schedule": self.schedule,
                "test_key": "abc", "fed_at": None, "quota_status": qs, "digital_badge_enabled": True,
                "payments": {"has_field": False, "sandbox_configured": False, "production_configured": False}}

    def put(self, data):
        self.puts.append(copy.deepcopy(data))
        if "name" in data or "slug" in data:
            pass
        if "design" in data:
            self.design = formlib.sanitize_design(data["design"], set())
        if "settings" in data:
            self.settings = formlib.sanitize_settings(data["settings"])
        return self.detail()


def make_env():
    env = Environment(loader=FileSystemLoader(os.path.join(ROOT, "templates")), undefined=ChainableUndefined, autoescape=True)
    env.globals.update(url_for=lambda name, path="", **k: f"/{name}/{path}?v=1", company_name="Golden", public_base_url=lambda: "http://localhost", event_logo_url=lambda e: "",
                       event_logo_attrs=lambda e: "", deploy_env=lambda: "", legal=lambda *a, **k: {}, print_settings_json=lambda *a, **k: "{}")
    return env


def render(env, source_text):
    tpl = env.from_string(source_text)
    event = types.SimpleNamespace(id=EV, name="Evento", event_code="EV", tenant_id="x", tenant=types.SimpleNamespace(name="Cliente"))
    return tpl.render(event=event, form_id=FID, staff_name="Ana", staff_role="coordinador", sidebar_active="eventos", request=None)


def serve(state_box, html_text):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def body_json(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def do_GET(self):
            p = urlparse(self.path).path
            st = state_box[0]
            if p.startswith("/kiosk/"):
                return self.send(200, html_text, "text/html; charset=utf-8")
            if p.startswith("/static/"):
                f = os.path.join(ROOT, "static", p[len("/static/"):])
                if os.path.isfile(f):
                    ct = {"css": "text/css", "js": "application/javascript", "svg": "image/svg+xml", "png": "image/png", "woff2": "font/woff2"}.get(f.rsplit(".", 1)[-1], "application/octet-stream")
                    return self.send(200, open(f, "rb").read(), ct)
                return self.send(404, "")
            if p.startswith("/api/badge-assets/"):
                return self.send(200, PNG, "image/png")
            if p == f"/api/events/{EV}/forms/{FID}":
                return self.send(200, st.detail())
            if p.startswith("/api/"):
                if not (p.endswith("form-event-fields") or p.endswith("form-id-docs") or p == "/api/events" or p.endswith("discount-codes")):
                    st.unknown.append(("GET", p))
                return self.send(200, [])
            return self.send(404, "")

        def do_PUT(self):
            p, st = urlparse(self.path).path, state_box[0]
            data = self.body_json()
            if p == f"/api/events/{EV}/forms/{FID}":
                try:
                    return self.send(200, st.put(data))
                except ValueError as e:
                    return self.send(400, {"detail": str(e)})
            if p == f"/api/events/{EV}/forms/{FID}/status":
                st.manual_status = data.get("manual_status", st.manual_status); st.capacity = data.get("capacity", st.capacity)
                return self.send(200, st.detail())
            st.unknown.append(("PUT", p)); return self.send(200, {})

        def do_POST(self):
            p, st = urlparse(self.path).path, state_box[0]
            n = int(self.headers.get("Content-Length") or 0); self.rfile.read(n)
            if p.endswith("forms-upload-image"):
                st.n_up += 1; st.uploads.append(p)
                return self.send(200, {"storage_path": f"x/nuevo{st.n_up}.jpeg"})
            st.unknown.append(("POST", p)); return self.send(200, {})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ------------------------------------------------------------------ escenarios
FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FALLA ") + msg)
    if not cond:
        FAILS.append(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", help="commit/rama de donde sacar la plantilla (por defecto, el archivo del árbol de trabajo)")
    ap.add_argument("--shots", help="carpeta donde guardar capturas (1280 y 390 px)")
    a = ap.parse_args()
    if a.ref:
        src = subprocess.check_output(["git", "show", f"{a.ref}:templates/kiosk_formulario_editor.html"], cwd=ROOT).decode()
    else:
        src = open(os.path.join(ROOT, "templates/kiosk_formulario_editor.html"), encoding="utf-8").read()
    html_text = render(make_env(), src)
    from playwright.sync_api import sync_playwright
    state_box = [State()]
    srv = serve(state_box, html_text)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    url = f"{base}/kiosk/{EV}/formularios/{FID}"

    with sync_playwright() as pw:
        br = pw.chromium.launch()

        def open_editor(prefill="cedula", w=1280, mut=None):
            state_box[0] = State(prefill)
            if mut:
                mut(state_box[0])
            ctx = br.new_context(viewport={"width": w, "height": 900}, color_scheme="light")
            ctx.route("**/*", lambda r: r.abort() if not r.request.url.startswith(base) else r.continue_())
            ctx.add_init_script("try { localStorage.setItem('gw_tour_editor-formulario', 'done'); } catch (e) {}")      # sin el recorrido guiado de primera vez
            pg = ctx.new_page(); errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("dialog", lambda d: d.accept())
            pg.goto(url); pg.wait_for_function("document.querySelector('#fname') && document.querySelector('#fname').value !== ''", timeout=15000)
            pg.wait_for_timeout(300)
            return pg, errs, state_box[0]

        def tab(pg, name):
            pg.click(f'#tabs [data-tab="{name}"]')
            pg.evaluate("document.querySelectorAll('.pane.active details').forEach((d) => { d.open = true; })")      # la nueva pantalla agrupa en secciones plegables: se abren todas
            pg.wait_for_timeout(150)

        def save(pg):
            # versión vieja (e6608f2): dos botones, «Guardar diseño» y «Guardar configuración» (#cfgSave); la nueva tiene uno solo (#saveBtn)
            if pg.locator("#cfgSave").count() and pg.locator("#pane-config.active, .pane.active#pane-config").count():
                pg.click("#cfgSave")
            else:
                pg.click("#saveBtn")
            pg.wait_for_timeout(700)

        def last_settings(st):
            s = [p for p in st.puts if "settings" in p]
            return s[-1]["settings"] if s else None

        def same(sent, orig, keys):
            return {k: sent.get(k) for k in keys} == {k: orig.get(k) for k in keys}

        # (vi) abrir Configuración, no tocar, guardar: lo enviado == lo cargado
        print("Escenario vi/i: Configuración sin cambios + Guardar")
        pg, errs, st = open_editor(); orig = copy.deepcopy(st.settings); orig_d = copy.deepcopy(st.design)
        check(not errs, f"sin errores de JS al cargar {errs[:2]}")
        tab(pg, "config"); save(pg)
        sent = last_settings(st)
        check(sent is not None, "Guardar envió un PUT con settings")
        if sent:
            for k in ("security", "prefill", "identify", "closed_template", "thanks", "refunds", "feed", "language", "translate", "send_digital_badge", "block_repeats"):
                check(sent.get(k) == {kk: vv for kk, vv in orig[k].items()} if isinstance(orig[k], dict) else sent.get(k) == orig[k], f"enviado.{k} == cargado.{k}" + ("" if sent.get(k) == orig[k] else f"  (envió {sent.get(k)!r}, tenía {orig[k]!r})"))
            check([ (r["label"], r["message"], r["limit"], r["conds"]) for r in sent["quotas"]["rules"]] == [(r["label"], r["message"], r["limit"], r["conds"]) for r in orig["quotas"]["rules"]], "cupos (nombre, mensaje, máximo, condiciones) intactos")
        check(st.settings == orig, "settings guardados en el servidor == los cargados" + ("" if st.settings == orig else f"\n      guardado: {json.dumps(st.settings, ensure_ascii=False)}\n      original: {json.dumps(orig, ensure_ascii=False)}"))
        check(st.design == orig_d, "el diseño no cambió")
        check(pg.input_value("#preMode") == "cedula", "el select de pre-llenado muestra «cedula» tras guardar")
        pg.context.close()

        # (ii) pre-llenado: lo pintado == lo cargado == lo enviado
        print("Escenario ii: pre-llenado none / cedula / invite")
        for mode in ("none", "cedula", "invite"):
            pg, errs, st = open_editor(mode)
            check(pg.input_value("#preMode") == mode, f"[{mode}] el select pinta «{mode}»")
            tab(pg, "config"); save(pg); s = last_settings(st)
            check(s and s["prefill"]["mode"] == mode, f"[{mode}] el PUT envía prefill.mode={mode}")
            if mode != "none":
                check(pg.is_visible("#preSrcBox"), f"[{mode}] se ve «¿De dónde salen los datos?»")
            pg.context.close()

        # (ii-b) origen del pre-llenado «base de otro evento»: aunque /api/events no lo liste, no se debe perder
        print("Escenario ii-b: prefill.source = event:99 con lista de eventos vacía")
        pg, errs, st = open_editor(); st.settings["prefill"]["source"] = "event:99"
        pg.reload(); pg.wait_for_function("document.querySelector('#fname').value !== ''"); pg.wait_for_timeout(500)
        tab(pg, "config"); save(pg); s = last_settings(st)
        check(s and s["prefill"]["source"] == "event:99", f"el PUT conserva prefill.source=event:99 (envió {s and s['prefill']['source']!r})")
        pg.context.close()

        # (iii) negrilla en los tres textos con formato
        print("Escenario iii: Negrilla en bienvenida / gracias / cerrado")
        def plain(st):      # textos de partida SIN negrilla: así el botón «N» la pone (con negrilla previa, el mismo botón la quita)
            for k in ("identify", "thanks", "closed_template"):
                st.settings[k]["text"] = "texto normal"
        pg, errs, st = open_editor(mut=plain); tab(pg, "config")
        for host, key, sub, word in (("#idTextRt", "identify", "text", "BIENVENIDA"), ("#thTextRt", "thanks", "text", "GRACIAS"), ("#clTextRt", "closed_template", "text", "CERRADO")):
            ed = pg.locator(f"{host} .rt-ed"); ed.scroll_into_view_if_needed(); ed.click()
            pg.keyboard.press("Control+A"); pg.keyboard.type(word)
            pg.keyboard.press("Control+A")
            pg.locator(f'{host} button[title="Negrilla"]').click()
        save(pg); s = last_settings(st)
        for key, word in (("identify", "BIENVENIDA"), ("thanks", "GRACIAS"), ("closed_template", "CERRADO")):
            t = (s or {}).get(key, {}).get("text", "")
            bold = lambda x: ("font-weight:bold" in x.replace(" ", "")) or "<b>" in x or "<strong>" in x
            check(word in t and bold(t), f"[{key}] el texto enviado lleva negrilla: {t!r}")
            t2 = st.settings[key]["text"]
            check(bold(t2), f"[{key}] el servidor la conservó: {t2!r}")
        pg.context.close()

        # (iii-b) negrilla en un texto informativo del Diseño (mismo editor con formato)
        print("Escenario iii-b: Negrilla en un texto informativo de Diseño")
        pg, errs, st = open_editor(); tab(pg, "design")
        pg.locator('#canvas .ccard[data-id="f_06"]').click(position={"x": 30, "y": 30}); pg.wait_for_timeout(300)
        ed = pg.locator("#pContentRt .rt-ed"); ed.click(); pg.keyboard.press("Control+A"); pg.keyboard.type("Texto nuevo"); pg.keyboard.press("Control+A")
        pg.locator('#pContentRt button[title="Negrilla"]').click(); save(pg)
        c = st.design["fields"]["f_06"]["content"]
        check("Texto nuevo" in c and ("font-weight:bold" in c.replace(" ", "") or "<b>" in c or "<strong>" in c), f"el texto informativo guardado lleva negrilla: {c!r}")
        pg.context.close()

        # (iv) subir imágenes
        print("Escenario iv: subir imágenes (Diseño y Configuración)")
        pg, errs, st = open_editor(); tab(pg, "config")
        png = {"name": "n.png", "mimeType": "image/png", "buffer": PNG}
        for inp in ("#idImgFile", "#thImgFile", "#clImgFile"):
            pg.set_input_files(inp, png); pg.wait_for_timeout(400)
        save(pg); s = last_settings(st)
        check(s and s["identify"]["image"].startswith("x/nuevo"), f"identify.image nueva: {s and s['identify']['image']}")
        check(s and s["thanks"]["image"].startswith("x/nuevo"), f"thanks.image nueva: {s and s['thanks']['image']}")
        check(s and s["closed_template"]["image"].startswith("x/nuevo"), f"closed_template.image nueva: {s and s['closed_template']['image']}")
        pg.context.close()
        pg, errs, st = open_editor(); tab(pg, "design")
        pg.set_input_files("#tLogo", png); pg.wait_for_timeout(400); pg.set_input_files("#tBg", png); pg.wait_for_timeout(400)
        pg.locator('#canvas .ccard[data-id="f_04"]').click(position={'x': 30, 'y': 40})
        pg.wait_for_timeout(300)
        if pg.locator("#pImg").count():
            pg.set_input_files("#pImg", png); pg.wait_for_timeout(400)
        save(pg); d = st.design
        check(d["theme"]["logo"].startswith("x/nuevo"), f"theme.logo nuevo: {d['theme']['logo']}")
        check(d["theme"]["bg_image"].startswith("x/nuevo"), f"theme.bg_image nuevo: {d['theme']['bg_image']}")
        check(d["fields"]["f_04"]["src"].startswith("x/nuevo"), f"imagen de campo nueva: {d['fields']['f_04']['src']}")
        pg.context.close()

        # (v) editar solo en Diseño y guardar sin abrir Configuración
        print("Escenario v: solo Diseño")
        pg, errs, st = open_editor(); orig = copy.deepcopy(st.settings)
        tab(pg, "design")
        pg.fill("#fname", "Otro nombre"); pg.wait_for_timeout(100)
        save(pg)
        check(any("design" in p for p in st.puts), "se envió el diseño")
        check(st.settings == orig, "settings intactos tras guardar solo el diseño" + ("" if st.settings == orig else f"\n      guardado: {json.dumps(st.settings, ensure_ascii=False)}"))
        check(st.design["theme"]["logo"] == "x/logo.jpeg" and st.design["fields"]["f_04"]["src"] == "x/campo.jpeg", "logo e imagen de campo intactos")
        check(not any("settings" in p for p in st.puts), "no se envió settings sin haber tocado Configuración")
        pg.context.close()

        # (b) lo que ve la persona sobre imágenes cargadas
        print("Escenario b: indicación de imágenes ya cargadas en Configuración")
        pg, errs, st = open_editor(); tab(pg, "config")
        for hint in ("#idImgName", "#thImgName", "#clImgName"):
            check("cargada" in pg.inner_text(hint), f"{hint} dice «imagen cargada»")
        for inp in ("#idImgFile", "#thImgFile", "#clImgFile"):
            loc = pg.locator(f"{inp} >> xpath=../*[@data-gwe-file-name]")
            if not loc.count():
                continue      # versión vieja: control de archivo del navegador, sin rótulo propio
            nm = loc.inner_text()
            check("Ningún archivo" not in nm, f"{inp}: el rótulo del control NO dice «Ningún archivo seleccionado» cuando ya hay imagen guardada (dice: {nm!r})")
        pg.context.close()

        print("Escenario b2: rótulos de Diseño con logo/fondo/imagen ya guardados")
        pg, errs, st = open_editor(); tab(pg, "design")
        loc = pg.locator("#tLogo >> xpath=../*[@data-gwe-file-name]")
        if loc.count():
            check("Ningún archivo" not in loc.inner_text(), f"#tLogo (el formulario ya tiene logo) no dice «Ningún archivo seleccionado»: {loc.inner_text()!r}")
        pg.context.close()

        # capturas
        if a.shots:
            os.makedirs(a.shots, exist_ok=True)
            for w in (1280, 390):
                pg, errs, st = open_editor(w=w)
                for t in ("design", "config"):
                    tab(pg, t); pg.wait_for_timeout(200)
                    pg.screenshot(path=os.path.join(a.shots, f"editor_{t}_{w}.png"), full_page=True)
                    ov = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                    check(ov <= 1, f"sin desborde horizontal en {t} a {w} px (sobra {ov} px)")
                pg.context.close()
        if state_box[0].unknown:
            print("  (llamadas a la API no simuladas:", sorted(set(state_box[0].unknown)), ")")
        br.close()
    srv.shutdown()
    print("\nRESULTADO:", "TODO PASA" if not FAILS else f"{len(FAILS)} FALLA(S)")
    for f in FAILS:
        print("  -", f[:200])
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
