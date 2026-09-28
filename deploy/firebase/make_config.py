"""Arma la configuración de Firebase Hosting de un entorno (dominio propio → Cloud Run) a partir de app/appmode.py, para que el reparto de
rutas entre servicios sea UNO solo (el mismo que usa la app para no servir lo que no le toca).

    python deploy/firebase/make_config.py staging <proyecto> <región> <sitio>   → build/firebase/{firebase.json, .firebaserc, public/static}
    npx firebase-tools deploy --only hosting --project <proyecto> --config build/firebase/firebase.json

Límites de Firebase Hosting que el diseño respeta (docs/15): 60 s por petición (lo pesado va a Cloud Run Jobs), solo la cookie
`__session` llega a Cloud Run (SESSION_COOKIE=__session), las respuestas dinámicas son `private` salvo que la app diga `public`
(el cascarón del formulario público lo hace, s-maxage=60). Los archivos de /static salen de la CDN de Firebase, sin tocar Cloud Run."""
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from app import appmode  # noqa: E402


def rewrites(suffix: str, region: str) -> list:
    run = lambda name: {"run": {"serviceId": f"golden-{name}{suffix}", "region": region}}  # noqa: E731
    out = [{"source": p, **run("web")} for p in ("/healthz", "/readyz", "/api/ops/**")]
    out += [{"source": re.sub(r"\{[^/]+\}", "*", p), **run("biometria")} for p in sorted(appmode.BIOMETRIC_PATHS)]
    for prefix in appmode.PUBLIC_PREFIXES:
        base = prefix.rstrip("/")
        out += [{"source": base, **run("publico")}, {"source": f"{base}/**", **run("publico")}]
    out.append({"source": "**", **run("web")})
    return out


def build(env: str, project: str, region: str, site: str, out_dir: str = os.path.join(ROOT, "build", "firebase")) -> str:
    suffix = "" if env == "production" else f"-{env}"
    public = os.path.join(out_dir, "public")
    shutil.rmtree(out_dir, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "static"), os.path.join(public, "static"))
    config = {"hosting": {
        "site": site, "public": "public", "trailingSlash": False,
        "headers": [{"source": "/static/**", "headers": [{"key": "Cache-Control", "value": "public, max-age=3600"}]}],
        "rewrites": rewrites(suffix, region),
    }}
    with open(os.path.join(out_dir, "firebase.json"), "w", encoding="utf8") as fh:
        json.dump(config, fh, indent=2)
    with open(os.path.join(out_dir, ".firebaserc"), "w", encoding="utf8") as fh:
        json.dump({"projects": {"default": project}}, fh)
    return out_dir


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] not in ("staging", "production"):
        sys.exit("Uso: make_config.py staging|production <proyecto> <región> <sitio>")
    print(build(*sys.argv[1:]))
