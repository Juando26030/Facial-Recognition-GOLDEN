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

from locust import HttpUser, between, constant_pacing, events, task

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, ".load_env.json"), encoding="utf8"))
EVENT_ID, SLUG, PASSWORD = CFG["event_id"], CFG["form_slug"], CFG["password"]
N_PEOPLE = CFG["people"]
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


class _Staff(HttpUser):
    abstract = True

    def on_start(self):
        self.client.headers["X-Forwarded-For"] = _fake_ip()
        _login(self.client, "carga_dig")


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


@events.quitting.add_listener
def _fail_on_errors(environment, **_):
    stats = environment.stats.total
    if stats.num_requests and stats.fail_ratio > 0.01:
        environment.process_exit_code = 1
