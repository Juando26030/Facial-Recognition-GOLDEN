"""Configuración compartida de la prueba de carga contra STAGING (Cloud Run Jobs): la clave de la cuenta de carga no viaja por ningún lado, se DERIVA del `OPS_TOKEN`
del entorno (que el Job de siembra y los generadores leen de Secret Manager): así ni el repositorio, ni la salida de un comando, ni el chat la ven."""
import hashlib
import hmac
import os

TENANT = "carga-staging"
EVENT_CODE = "LOAD-STG"
USERNAME = "carga_dig"
FORM_SLUG = "carga"
PAY_FORM_SLUG = "carga-pago"        # segundo formulario con campo «Pago»: SOLO para cotizar (`quote`); nunca se envía (sin llaves de Wompi en staging el envío daría 503)


def check_host(url: str, allowed=(), production: bool = False):
    """None si `url` es un destino permitido para la prueba de carga; si no, el motivo. Doble candado: (1) el host debe ser de staging (contener «staging») y NO ser el
    dominio de producción; (2) si se dan `allowed` (LOAD_ALLOWED_HOSTS: los hosts EXACTOS que calcula deploy/gcp/config.sh), debe coincidir con uno.
    Así una URL mal escrita (o la de producción) nunca recibe carga, aunque contenga la palabra «staging» en otro sitio.

    `production=True` (19-nov-2026, orden expresa de Juan David: prueba de 40.000 escaneos en un evento sintético de producción) cambia SOLO el punto (1): ya no exige «staging»,
    pero entonces la lista exacta `allowed` es OBLIGATORIA (la URL de Cloud Run del servicio web, que calcula run_phase4.sh) y el dominio real (golden-eventos) sigue prohibido siempre:
    la carga nunca pasa por Cloudflare ni por app.golden-eventos.com."""
    from urllib.parse import urlsplit
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return f"la URL debe ser https://… (recibí {url!r})"
    if "golden-eventos" in host:
        return f"{host!r} es el dominio real de Golden: nunca recibe carga"
    allowed_hosts = [urlsplit(a if "//" in a else "https://" + a).hostname.lower() for a in allowed if a]
    if production:
        if not allowed_hosts:
            return "en producción la lista exacta de destinos (LOAD_ALLOWED_HOSTS) es obligatoria"
        if not host.endswith(".run.app"):
            return f"en producción solo se permite una URL de Cloud Run (*.run.app), no {host!r}"
    elif "staging" not in host:
        return f"{host!r} no es de staging"
    if allowed_hosts and host not in allowed_hosts:
        return f"{host!r} no está entre los hosts permitidos ({', '.join(allowed_hosts)})"
    return None


def derived_password() -> str:
    token = os.environ.get("OPS_TOKEN", "")
    if not token:
        raise SystemExit("Falta OPS_TOKEN: la clave de la cuenta de carga se deriva de él (ver scripts/load_cfg.py).")
    return "Ld" + hmac.new(token.encode(), b"golden-load-account", hashlib.sha256).hexdigest()[:30] + "!9"


def timing_token() -> str:
    """Valor de `X-Timing-Token` para que la app (SERVER_TIMING=1) devuelva `Server-Timing`. Misma fórmula que app/timing.py::token(); vacío sin OPS_TOKEN."""
    token = os.environ.get("OPS_TOKEN", "")
    return hmac.new(token.encode(), b"golden-server-timing", hashlib.sha256).hexdigest()[:20] if token else ""


def quotes_per_user() -> int:
    """Cuántas cotizaciones (`POST /f/<evento>/carga-pago/quote`) hace cada usuario virtual de formularios: LOAD_QUOTES del Job (0 por defecto = ninguna). Un usuario real cotiza una vez al
    dibujar el formulario con pago y otra tras cada cambio. Entero entre 0 y 50; otra cosa detiene el generador."""
    raw = os.environ.get("LOAD_QUOTES", "").strip()
    if not raw:
        return 0
    if not raw.isdigit() or int(raw) > 50:
        raise SystemExit(f"LOAD_QUOTES={raw!r} no es válido: un entero entre 0 y 50 (cotizaciones por usuario; 0 = ninguna).")
    return int(raw)


DEFAULT_SUBMIT_RATIO = 0.5


def submit_ratio() -> float:
    """Proporción (0 a 1) de los usuarios que abren el formulario y además lo ENVÍAN: variable LOAD_SUBMIT_RATIO del Job (0,5 por defecto: ~5.000 envíos con 10.000 aperturas;
    1 = 10.000 envíos). Un valor que no sea un número entre 0 y 1 detiene el generador en vez de correr otra prueba distinta de la pedida."""
    raw = os.environ.get("LOAD_SUBMIT_RATIO", "").strip()
    if not raw:
        return DEFAULT_SUBMIT_RATIO
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if not 0.0 <= value <= 1.0:
        raise SystemExit(f"LOAD_SUBMIT_RATIO={raw!r} no es válido: debe ser un número entre 0 y 1 (0,5 = la mitad de los usuarios envía; 1 = todos).")
    return value
