"""Modo de arranque (`APP_MODE`): qué parte de la aplicación sirve este proceso. Hoy TODO corre junto (`all`, el valor por defecto: nada cambia);
está preparado para separar en tres servicios en Cloud Run (Fase 2) sin tocar el código de las rutas:

  publico   formularios públicos, pagos (Wompi), escarapela/certificado digital, ruleta del proyector, páginas legales y estáticos.
            Nunca importa dlib.
  web       el panel del personal (todo lo demás). Tampoco importa dlib.
  biometria reconocimiento facial y registro/cargas con fotos. Es el ÚNICO que carga `face_recognition`/dlib (y por eso su /readyz comprueba el modelo).

Los puntos de entrada están en `app/entrypoints/` (`publico.py`, `web.py`, `biometria.py`); cada uno fija APP_MODE y expone `app`. Ver docs/14_FASE0_RESULTADOS.md."""
import os

MODES = ("all", "publico", "web", "biometria")
MODE = os.getenv("APP_MODE", "all")
if MODE not in MODES:
    raise RuntimeError(f"APP_MODE={MODE!r} no es válido (usa uno de {MODES})")

# Rutas de biometría (dlib): viven en routers compartidos, así que se separan por ruta.
BIOMETRIC_PATHS = {
    "/api/recognize", "/api/register", "/api/bulk_register", "/api/bulk_jobs/{job_id}",
    "/api/events/{event_id}/areas/{area_id}/movement-face",
}
# Rutas públicas (sin sesión): lo que miles de personas abren desde su teléfono.
PUBLIC_PREFIXES = ("/f/", "/b/", "/c/", "/r/", "/webhooks/", "/privacidad", "/terminos", "/reembolsos", "/api/email-assets/")
ALWAYS = ("/health", "/ready", "/api/ops/")          # «/health» y «/ready» cubren también /healthz y /readyz


def loads_model() -> bool:
    """¿Este proceso debe tener cargado el modelo facial? (para /readyz y el precalentamiento al arrancar)."""
    return MODE in ("all", "biometria")


def route_allowed(path: str, is_mount: bool = False, mode: str = MODE) -> bool:
    if mode == "all" or path.startswith(ALWAYS):
        return True
    if is_mount:                                           # /static
        return True
    if mode == "biometria":
        return path in BIOMETRIC_PATHS
    if mode == "publico":
        return path.startswith(PUBLIC_PREFIXES)
    return path not in BIOMETRIC_PATHS and not path.startswith(PUBLIC_PREFIXES)      # web
