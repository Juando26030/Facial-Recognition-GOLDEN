"""Escenarios de carga (Locust) para GoldenWeb. SOLO contra una base/servidor LOCAL o de staging (ver README.md); nunca contra producción.

Clases (cada una es un escenario; se pueden combinar):
  FormUser        (a) abre el formulario público (página + estáticos + estado) y lo envía con una cédula nueva
  CedulaScanner   (b) escaneo por cédula (POST /api/checkin-cedula) con una cédula del roster
  FaceScanner     (c) escaneo facial (POST /api/recognize) con una foto de prueba
  DirectoryViewer (e) directorio en vivo (GET /api/users) del evento de 8.000 personas
  Mixed           (d) las tres primeras juntas, con pesos (por defecto 60 % formulario / 30 % cédula / 10 % facial)

Fotos para (c): carpeta en la variable FOTOS_PRUEBA_DIR (por defecto C:\\JDRJ\\Golden\\fotos_prueba), FUERA del repo. Si no existe, se usa como
sustituto una foto de dominio público de scikit-image (la astronauta), generada en memoria; los resultados lo indican. NUNCA guardes fotos ni
resultados con datos de personas dentro del repo.
"""
import glob
import io
import json
import os
import random
import time

from locust import HttpUser, between, constant, constant_pacing, events, task

HERE = os.path.dirname(os.path.abspath(__file__))


def _cfg() -> dict:
    """Local: `.load_env.json` (lo escribe setup_load_db.py). En Cloud Run Jobs contra staging: variables LOAD_EVENT_ID, LOAD_FORM_SLUG, LOAD_PEOPLE y OPS_TOKEN
    (la clave de la cuenta de carga se deriva de él, scripts/load_cfg.py; nunca viaja en claro)."""
    path = os.path.join(HERE, ".load_env.json")
    if os.path.exists(path):
        return json.load(open(path, encoding="utf8"))
    from scripts.load_cfg import USERNAME, derived_password
    return {"event_id": int(os.environ["LOAD_EVENT_ID"]), "form_slug": os.environ["LOAD_FORM_SLUG"], "password": derived_password(),
            "people": int(os.getenv("LOAD_PEOPLE", "5000")), "digitador": USERNAME}


CFG = _cfg()
EVENT_ID, SLUG, PASSWORD = CFG["event_id"], CFG["form_slug"], CFG["password"]
N_PEOPLE = CFG["people"]
STAFF_USER = CFG.get("digitador", "carga_dig")
_photo_cache: list = []


def _photos() -> list:
    """Lista de (nombre, bytes JPEG). Se cargan una vez por proceso."""
    if _photo_cache:
        return _photo_cache
    folder = os.getenv("FOTOS_PRUEBA_DIR", r"C:\JDRJ\Golden\fotos_prueba")
    for path in sorted(glob.glob(os.path.join(folder, "*.jp*g")) + glob.glob(os.path.join(folder, "*.png")))[:20]:
        with open(path, "rb") as fh:
            _photo_cache.append((os.path.basename(path), fh.read()))
    if not _photo_cache:
        try:
            from PIL import Image
            from skimage import data
            buf = io.BytesIO()
            Image.fromarray(data.astronaut()).save(buf, "JPEG", quality=90)
            _photo_cache.append(("astronaut(skimage, sustituto)", buf.getvalue()))
            print(f"[locust] {folder} no existe: uso una foto de dominio público de scikit-image como sustituto.")
        except Exception as e:  # noqa: BLE001
            print(f"[locust] sin fotos de prueba ({e}); FaceScanner enviará una imagen sin rostro (mide el costo de detección, no el de comparación).")
            from PIL import Image
            buf = io.BytesIO()
            Image.new("RGB", (640, 480), (120, 120, 120)).save(buf, "JPEG")
            _photo_cache.append(("sin_rostro", buf.getvalue()))
    return _photo_cache


def _fake_ip() -> str:
    """Cada usuario virtual llega con su propia IP (cabecera que Nginx/Cloudflare ponen en producción): así los límites por IP se prueban como en la vida real."""
    return ".".join(str(random.randint(1, 254)) for _ in range(4))


def _login(client, username: str) -> None:
    r = client.post("/login", data={"username": username, "password": PASSWORD}, allow_redirects=False, name="/login")
    if r.status_code not in (302, 303):
        raise RuntimeError(f"login falló ({r.status_code}): revisa que el servidor use la base golden_load")


class FormUser(HttpUser):
    """(a) Una persona que abre el formulario y lo envía. Espera 1-6 s entre abrir y enviar (lo que tarda en escribir)."""
    wait_time = between(1, 3)
    counter = 0

    def on_start(self):
        self.client.headers["X-Forwarded-For"] = _fake_ip()

    @task
    def open_and_submit(self):
        with self.client.get(f"/f/{EVENT_ID}/{SLUG}", name="GET /f/{ev}/{slug} (pagina)", catch_response=True) as r:
            r.success() if r.status_code == 200 else r.failure(f"{r.status_code}")
        self.client.get("/static/js/form-render.js", name="GET static form-render.js")
        self.client.get("/static/css/style.css", name="GET static style.css")
        self.client.get(f"/f/{EVENT_ID}/{SLUG}/state", name="GET /f/{ev}/{slug}/state")
        self.client.post(f"/f/{EVENT_ID}/{SLUG}/beacon", json={"sid": f"s{id(self)}", "kind": "view"}, name="POST beacon")
        self.environment.runner  # noqa: B018
        FormUser.counter += 1
        n = random.randint(10**9, 10**10 - 1)
        payload = {"values": {"cedula": str(n), "nombres": "Prueba", "apellidos": "Carga", "correo": f"carga{n}@example.com", "tel": "3001234567"}, "sid": f"sid{n}"}
        with self.client.post(f"/f/{EVENT_ID}/{SLUG}/submit", json=payload, name="POST submit", catch_response=True) as r:
            if r.status_code == 200:
                r.success()
            else:
                r.failure(f"submit {r.status_code}: {r.text[:120]}")


DONE = {"users": 0}          # usuarios de FormBurst que ya terminaron su recorrido (run_task.py espera a que lleguen al total)


RETRY_DEADLINE = float(os.getenv("LOAD_RETRY_DEADLINE", "150"))          # s: lo mismo que el navegador real (templates/form_public.html)
RETRY_BASE = float(os.getenv("LOAD_RETRY_BASE_MS", "1500")) / 1000


def _is_busy(r) -> bool:
    """Misma regla que `isBusy` de templates/form_public.html: 502/503/504 y el 429 que NO es de la app (el «Rate exceeded.» de Cloud Run es texto plano; los de la app traen JSON)."""
    return r.status_code in (502, 503, 504) or (r.status_code == 429 and "json" not in (r.headers.get("content-type") or ""))


def _retry_delay(r, attempt: int) -> float:
    """Misma espera que `retryDelay` del navegador: lo que diga `Retry-After` como mínimo, espera creciente (x1, x2, x4, x8) y un poco al azar."""
    try:
        after = float(r.headers.get("Retry-After", ""))
    except ValueError:
        after = 0.0
    return max(after, RETRY_BASE * 2 ** min(attempt, 3)) + random.uniform(0, RETRY_BASE)


def _attempt(client, method: str, url: str, name: str, ok_codes=(200,), **kw):
    """Un intento HTTP. Un intento «ocupado» (contrapresión) NO es un fallo: se cuenta aparte, con otro nombre («… (contrapresión 503)»)."""
    with client.request(method, url, name=name, catch_response=True, **kw) as r:
        if _is_busy(r):
            try:
                infra = r.status_code == 503 and '"busy"' not in r.text          # 503 sin nuestro cuerpo JSON «busy» (p. ej. el HTML de Google): se distingue en el informe
                r.request_meta["name"] = f"{name} (contrapresión {r.status_code}{' infra' if infra else ''})"
            except Exception:  # noqa: BLE001
                pass
            r.success()
        elif r.status_code in ok_codes:
            r.success()
        else:
            r.failure(f"{name} {r.status_code}: {r.text[:120]}")
        return r


def _user_result(label: str, started: float, failed: bool = False) -> None:
    """El resultado FINAL de un usuario que envía («[usuario] inscrito / cupo lleno / se rindió / error»), con el tiempo total desde su primer intento: es lo que vive una persona."""
    events.request.fire(request_type="USER", name=f"[usuario] {label}", response_time=(time.time() - started) * 1000, response_length=0,
                        exception=Exception(label) if failed else None, context={})


class FormBurst(HttpUser):
    """Fase 4 (docs/15): cada usuario virtual abre el formulario UNA vez y, con probabilidad LOAD_SUBMIT_RATIO (0,5 → 10.000 aperturas y ~5.000 envíos), lo envía tras
    unos segundos (lo que tarda en escribir). Reintenta como el navegador real (mismas reglas y esperas: 502/503/504 y 429 de infraestructura, con la misma `sid`, hasta
    LOAD_RETRY_DEADLINE s); esos intentos «ocupado» son CONTRAPRESIÓN, no fallos. Un 10 % de los envíos ya inscritos se repite con la MISMA `sid` (debe salir «replayed»).
    Con el formulario lleno el 409 «cupo completo» es la respuesta CORRECTA. Al final se registra el resultado del usuario: inscrito / cupo lleno / se rindió tras N reintentos."""
    wait_time = constant(0)

    def on_start(self):
        self.client.headers["X-Forwarded-For"] = _fake_ip()
        self.client.headers.update(_timing_headers())

    @task
    def once(self):
        import gevent
        with self.client.get(f"/f/{EVENT_ID}/{SLUG}", name="GET pagina del formulario", catch_response=True) as r:
            r.success() if r.status_code == 200 else r.failure(f"{r.status_code}")
        started, attempt = time.time(), 0
        while True:                                   # el navegador también reintenta la apertura si el servicio está saturado (hasta ~40 s)
            r = _attempt(self.client, "GET", f"/f/{EVENT_ID}/{SLUG}/state", "GET state")
            if not _is_busy(r) or time.time() - started + _retry_delay(r, attempt) > 40:
                break
            gevent.sleep(_retry_delay(r, attempt))
            attempt += 1
        if random.random() < float(os.getenv("LOAD_SUBMIT_RATIO", "0.5")):
            gevent.sleep(random.uniform(1, float(os.getenv("LOAD_THINK_MAX", "30"))))
            n = random.randint(10**9, 10**10 - 1)
            payload = {"values": {"cedula": str(n), "nombres": "Prueba", "apellidos": "Carga", "correo": f"carga{n}@example.com", "tel": "3001234567"}, "sid": f"sid{n}"}
            url, started, attempt, label = f"/f/{EVENT_ID}/{SLUG}/submit", time.time(), 0, None
            while label is None:
                r = _attempt(self.client, "POST", url, "POST envio" if attempt == 0 else "POST envio (reintento por contrapresión)", ok_codes=(200, 409), json=payload)
                if r.status_code == 200:
                    label = "inscrito"
                elif r.status_code == 409:
                    label = "cupo lleno" if "closed" in r.text else "duplicado"          # cupo completo (o duplicado): respuesta correcta, no error
                elif _is_busy(r):
                    wait = _retry_delay(r, attempt)
                    if time.time() - started + wait > RETRY_DEADLINE:
                        label = f"se rindió tras {attempt} reintentos"
                    else:
                        gevent.sleep(wait)
                        attempt += 1
                else:
                    label = "error"
            _user_result(label, started, failed=label.startswith("se rindió") or label == "error")
            if label == "inscrito" and random.random() < 0.10:
                _attempt(self.client, "POST", url, "POST envio (reintento, misma sid)", ok_codes=(200, 409), json=payload)
        # NO `self.stop()`: Locust REPONE a los usuarios detenidos para mantener constante el total pedido, y cada reposición abría el formulario otra vez
        # (3.ª corrida: ~17.700 aperturas para 10.000 usuarios). El usuario terminado se queda dormido hasta que el generador termine.
        DONE["users"] += 1
        gevent.sleep(10 ** 6)


class _Staff(HttpUser):
    abstract = True

    def on_start(self):
        self.client.headers["X-Forwarded-For"] = _fake_ip()
        _login(self.client, STAFF_USER)


class CedulaScanner(_Staff):
    """(b) Una estación que escanea cédulas: una cada ~3,5 s en promedio (ver constant_pacing en el comando para forzar ritmo)."""
    wait_time = between(2.5, 4.5)

    @task
    def scan(self):
        cedula = f"9{random.randint(0, N_PEOPLE - 1):09d}"
        with self.client.post("/api/checkin-cedula", data={"event_id": EVENT_ID, "cedula": cedula, "confirm": "true", "force": "true"}, name="POST checkin-cedula", catch_response=True) as r:
            r.success() if r.status_code == 200 and r.json().get("result") in ("SÍ", "DUPLICADO") else r.failure(f"{r.status_code} {r.text[:100]}")


class FaceScanner(_Staff):
    """(c) Escaneo facial con imagen de prueba. La persona de la foto no está en el roster sintético: es el peor caso (recorre a todos)."""
    wait_time = between(2.5, 4.5)

    @task
    def scan(self):
        name, data = random.choice(_photos())
        with self.client.post("/api/recognize", data={"event_id": EVENT_ID, "confirm": "true", "force": "true"}, files={"file": ("scan.jpg", data, "image/jpeg")},
                              name="POST recognize", catch_response=True) as r:
            r.success() if r.status_code == 200 else r.failure(f"{r.status_code} {r.text[:100]}")


class DirectoryViewer(_Staff):
    """(e) Alguien con el directorio en vivo abierto: pide la lista cada ~5 s."""
    wait_time = constant_pacing(5)

    @task
    def directory(self):
        self.client.get(f"/api/users?event_id={EVENT_ID}", name="GET /api/users (directorio 8000)")


class Mixed(_Staff):
    """(d) Todo junto: cada usuario virtual hace, según pesos, formulario / cédula / facial."""
    wait_time = between(1, 3)

    @task(60)
    def form(self):
        n = random.randint(10**9, 10**10 - 1)
        self.client.get(f"/f/{EVENT_ID}/{SLUG}", name="GET /f/{ev}/{slug} (pagina)")
        self.client.get(f"/f/{EVENT_ID}/{SLUG}/state", name="GET /f/{ev}/{slug}/state")
        self.client.post(f"/f/{EVENT_ID}/{SLUG}/submit", json={"values": {"cedula": str(n), "nombres": "P", "apellidos": "C", "correo": f"m{n}@example.com"}, "sid": f"m{n}"}, name="POST submit")

    @task(30)
    def cedula(self):
        self.client.post("/api/checkin-cedula", data={"event_id": EVENT_ID, "cedula": f"9{random.randint(0, N_PEOPLE - 1):09d}", "confirm": "true", "force": "true"}, name="POST checkin-cedula")

    @task(10)
    def face(self):
        name, data = random.choice(_photos())
        self.client.post("/api/recognize", data={"event_id": EVENT_ID, "confirm": "true", "force": "true"}, files={"file": ("scan.jpg", data, "image/jpeg")}, name="POST recognize")


def _timing_headers() -> dict:
    """Con SERVER_TIMING=1 en el servicio, `X-Timing-Token` (derivado de OPS_TOKEN) hace que responda `Server-Timing`; sin OPS_TOKEN no se pide nada."""
    try:
        from scripts.load_cfg import timing_token
        token = timing_token()
    except Exception:  # noqa: BLE001
        token = ""
    return {"X-Timing-Token": token} if token else {}


def _server_app_ms(header: str):
    """`app;dur=12.3, thread;dur=…` → 12.3 (ms que la app dice haber tardado); None si no viene."""
    for part in (header or "").split(","):
        name, _, rest = part.strip().partition(";")
        if name == "app" and rest.startswith("dur="):
            try:
                return float(rest[4:])
            except ValueError:
                return None
    return None


@events.request.add_listener
def _outside_the_app(request_type, name, response_time, response=None, **_):
    """Latencia que queda FUERA de la app (Cloud Run: cola de concurrencia, red, Firebase, el propio generador) = total medido por el cliente − `app;dur` del servidor.
    Se registra como una petición aparte «[fuera de la app] …» (mismo reporte y percentiles); solo cuando el servicio devolvió `Server-Timing`. Sin datos de personas."""
    if name.startswith("[fuera de la app]") or response is None:
        return
    app_ms = _server_app_ms(response.headers.get("Server-Timing", ""))
    if app_ms is not None:
        events.request.fire(request_type="APP", name=f"[fuera de la app] {name}", response_time=max(0.0, response_time - app_ms), response_length=0, exception=None, context={})


@events.quitting.add_listener
def _fail_on_errors(environment, **_):
    stats = environment.stats.total
    if stats.num_requests and stats.fail_ratio > 0.01:
        environment.process_exit_code = 1
