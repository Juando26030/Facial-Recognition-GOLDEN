#!/usr/bin/env bash
# Publica el SITIO WEB CORPORATIVO (https://golden-eventos.com) en su propio sitio de Firebase Hosting. No toca la plataforma
# (app.golden-eventos.com): ni Cloud Run, ni la base, ni migraciones, ni el sitio de Hosting de la app. Por eso aquí no existe FORCE ni congelamiento.
# Lo corre Juan David en Cloud Shell, desde la raíz del repositorio de la plataforma. Paso a paso y cómo deshacer: docs/26_SITIO_WEB_MONTAJE.md.
#
#   bash deploy/sitio/deploy_sitio.sh <ID-del-proyecto>              # p. ej. goldenweb-prod
#   SOLO_COMPILAR=1 bash deploy/sitio/deploy_sitio.sh <ID>           # compila y revisa dist/, NO publica (ensayo)
#   CANAL=prueba bash deploy/sitio/deploy_sitio.sh <ID>              # publica en un canal de vista previa de Firebase (dirección temporal, 7 días), no en el dominio
#
# Qué hace: 1) trae golden-sitio-web en el commit EXACTO de deploy/sitio/VERSION; 2) aplica deploy/sitio/parche/*.patch (si hay);
# 3) npm ci && PUBLIC_INDEXAR=1 npm run build; 4) comprueba que dist/ tenga lo esperado (si algo falta, NO publica);
# 5) firebase deploy --only hosting:sitio. Termina con «== LISTO (sitio, commit <sha>)».
# Variables (ninguna es secreta): SITIO_REPO (dirección del repositorio del sitio), FIREBASE_SITE_SITIO (nombre del sitio de Hosting;
# por defecto golden-sitio-<número del proyecto>), SITIO_DOMINIO (por defecto https://golden-eventos.com), SITIO_DIR (copia del sitio ya
# descargada en el commit de VERSION: la usa GitHub Actions; con ella no se clona).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PROJECT_ID="${1:?Uso: $0 <ID-del-proyecto de Google Cloud> (p. ej. goldenweb-prod)}"
SITIO_REPO="${SITIO_REPO:-https://github.com/Juando26030/golden-sitio-web.git}"
SITIO_DOMINIO="${SITIO_DOMINIO:-https://golden-eventos.com}"
VERSION="$(tr -d ' \r\n' < deploy/sitio/VERSION)"
WORK="$ROOT/build/sitio"
say() { echo -e "\n== $*"; }
fail() { echo "ERROR: $*" >&2; exit 1; }

[[ "$VERSION" =~ ^[0-9a-f]{40}$ ]] || fail "deploy/sitio/VERSION debe tener el commit completo (40 caracteres) del sitio; tiene «$VERSION»."
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
[ "$NODE_MAJOR" -ge 22 ] || fail "hace falta Node 22 o superior (hay $(node --version 2>/dev/null || echo ninguno)). En Cloud Shell: nvm install 22 && nvm use 22"

say "1. CÓDIGO DEL SITIO en el commit ${VERSION:0:7}"
if [ -n "${SITIO_DIR:-}" ]; then
  SRC="$(cd "$SITIO_DIR" && pwd)"
else
  rm -rf "$WORK"; mkdir -p "$WORK"; SRC="$WORK/src"
  git clone -q "$SITIO_REPO" "$SRC" || fail "no se pudo clonar $SITIO_REPO (si el repositorio es privado: gh auth login, o SITIO_REPO con otra dirección)"
  git -C "$SRC" checkout -q --detach "$VERSION" || fail "el commit $VERSION no existe en $SITIO_REPO"
fi
[ "$(git -C "$SRC" rev-parse HEAD)" = "$VERSION" ] || fail "la copia del sitio no está en el commit de deploy/sitio/VERSION"
[ -z "$(git -C "$SRC" status --porcelain)" ] || fail "la copia del sitio tiene cambios sin guardar; se publica solo lo que está en el commit + el parche"

say "2. PARCHE (deploy/sitio/parche/*.patch)"
shopt -s nullglob; PARCHES=("$ROOT"/deploy/sitio/parche/*.patch); shopt -u nullglob
if [ "${#PARCHES[@]}" -eq 0 ]; then echo "sin parche: el sitio ya trae todo en su rama"; fi
for p in "${PARCHES[@]}"; do
  git -C "$SRC" apply --check "$p" || fail "el parche $(basename "$p") no aplica sobre ${VERSION:0:7}: hay que regenerarlo (docs/26_SITIO_WEB_MONTAJE.md, «Regenerar el parche»)"
  git -C "$SRC" apply "$p"; echo "aplicado: $(basename "$p")"
done

# Staging (el ID del proyecto lleva «staging») se compila SIN PUBLIC_INDEXAR: el sitio de ensayo pide no ser indexado (noindex + robots Disallow) para que Google no lo confunda con golden-eventos.com. Producción: indexable.
if [[ "$PROJECT_ID" == *staging* ]]; then INDEXAR=0; else INDEXAR=1; fi
say "3. COMPILAR (npm ci && npm run build, con PUBLIC_INDEXAR=$INDEXAR)"
( cd "$SRC" && npm ci --no-audit --no-fund && if [ "$INDEXAR" = 1 ]; then PUBLIC_INDEXAR=1 npm run build; else npm run build; fi ) || fail "no compiló; no se publica nada"
DIST="$SRC/dist"

say "4. COMPROBAR dist/"
MAL=0
need() { if [ -e "$DIST/$1" ]; then echo "  ok  $1"; else echo "  FALTA  $1" >&2; MAL=1; fi; }
has() { if grep -q -- "$2" "$DIST/$1" 2>/dev/null; then echo "  ok  $1 contiene «$3»"; else echo "  MAL  $1 no contiene «$3»" >&2; MAL=1; fi; }
hasnt() { if grep -rq -- "$1" "$DIST" --include='*.html' --include='*.txt' --include='*.xml' 2>/dev/null; then echo "  MAL  aparece «$2» en dist/" >&2; MAL=1; else echo "  ok  no aparece «$2»"; fi; }
# Una página por cada archivo de src/pages (lo que el sitio declara es lo que debe salir, ni más ni menos)
ESPERADAS="$(cd "$SRC/src/pages" && find . -name '*.astro' ! -name '_*' ! -name '*\[*' | sed -e 's|^\./||' -e 's|\.astro$||' | sort)"
for pg in $ESPERADAS; do
  case "$pg" in index) need "index.html" ;; 404) need "404.html" ;; */index) need "${pg%/index}/index.html" ;; *) need "$pg/index.html" ;; esac
done
N_ESPERADAS="$(echo "$ESPERADAS" | wc -l)"; N_HTML="$(find "$DIST" -name '*.html' | wc -l)"
if [ "$N_ESPERADAS" = "$N_HTML" ]; then echo "  ok  $N_HTML páginas HTML (las mismas que src/pages)"; else echo "  MAL  dist/ tiene $N_HTML páginas HTML y src/pages declara $N_ESPERADAS" >&2; MAL=1; fi
for f in robots.txt sitemap.xml site.webmanifest favicon.ico favicon.png apple-touch-icon.png img/og.jpg _astro fonts; do need "$f"; done
has index.html "rel=\"canonical\" href=\"${SITIO_DOMINIO}/\"" "canónica ${SITIO_DOMINIO}/"
has index.html 'application/ld+json' 'datos estructurados'
has index.html 'property="og:image"' 'og:image'
if [ "$INDEXAR" = 1 ]; then has robots.txt '^Allow: /' 'Allow: /'; else has robots.txt '^Disallow: /' 'Disallow: / (staging no se indexa)'; fi
if [ "$INDEXAR" = 1 ]; then
  has robots.txt "^Sitemap: ${SITIO_DOMINIO}/sitemap.xml" 'Sitemap'
  has sitemap.xml "<loc>${SITIO_DOMINIO}/</loc>" 'la portada'
fi
if [ "$INDEXAR" = 1 ]; then
  if grep -q 'name="robots" content="noindex"' "$DIST/index.html"; then echo "  MAL  la portada pide noindex (¿faltó PUBLIC_INDEXAR=1?)" >&2; MAL=1; else echo "  ok  la portada no pide noindex"; fi
else
  if grep -q 'name="robots" content="noindex' "$DIST/index.html"; then echo "  ok  la portada de staging pide noindex"; else echo "  MAL  la portada de staging NO pide noindex" >&2; MAL=1; fi
fi
hasnt 'pages\.dev' 'pages.dev (dirección de la vista previa)'
hasnt 'localhost' 'localhost'
[ "$MAL" = 0 ] || fail "dist/ no es lo esperado; NO se publica. Corrige y vuelve a correr el mismo comando."
echo "dist/: $(find "$DIST" -type f | wc -l) archivos, $(du -sh "$DIST" | cut -f1)"

if [ "${SOLO_COMPILAR:-0}" = 1 ]; then say "ENSAYO TERMINADO (SOLO_COMPILAR=1): no se publicó nada. dist/ quedó en $DIST"; exit 0; fi

say "5. FIREBASE HOSTING"
if [ -z "${FIREBASE_SITE_SITIO:-}" ]; then
  PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')" || fail "no se pudo leer el proyecto $PROJECT_ID"
  FIREBASE_SITE_SITIO="golden-sitio-${PROJECT_NUMBER}"
fi
PUB="$WORK/publicar"; rm -rf "$PUB"; mkdir -p "$PUB"
cp "$ROOT/deploy/sitio/firebase.json" "$PUB/firebase.json"; cp -r "$DIST" "$PUB/dist"
# Formulario de cotización (22-nov-2026): /api/public/** del sitio llega al servicio público de GoldenWeb de ESTE proyecto (producción: golden-publico; staging: golden-publico-staging).
SERVICIO_PUBLICO="${SERVICIO_PUBLICO:-golden-publico$([[ "$PROJECT_ID" == *staging* ]] && echo -staging || true)}"
python3 - "$PUB/firebase.json" "$SERVICIO_PUBLICO" "${REGION:-us-east4}" <<'PY'
import json, sys
path, service, region = sys.argv[1:4]
cfg = json.load(open(path))
cfg["hosting"]["rewrites"] = [{"source": "/api/public/**", "run": {"serviceId": service, "region": region}}]
json.dump(cfg, open(path, "w"), indent=2)
PY
cd "$PUB"
fb() { npx -y firebase-tools@13 "$@" --project "$PROJECT_ID" --non-interactive; }
fb hosting:sites:get "$FIREBASE_SITE_SITIO" >/dev/null 2>&1 || fail "no existe el sitio de Hosting «$FIREBASE_SITE_SITIO» en $PROJECT_ID. Créalo una vez (docs/26, paso 1): npx -y firebase-tools@13 hosting:sites:create $FIREBASE_SITE_SITIO --project $PROJECT_ID --non-interactive"
fb target:apply hosting sitio "$FIREBASE_SITE_SITIO"
if [ -n "${CANAL:-}" ]; then
  fb hosting:channel:deploy "$CANAL" --only sitio --expires 7d
  say "LISTO (sitio, canal de prueba «$CANAL», commit ${VERSION:0:7}). La dirección temporal está arriba; el dominio NO cambió."
else
  fb deploy --only hosting:sitio -m "sitio ${VERSION:0:7} + parche"
  say "LISTO (sitio, commit ${VERSION:0:7}). Sitio de Hosting: $FIREBASE_SITE_SITIO → https://${FIREBASE_SITE_SITIO}.web.app y ${SITIO_DOMINIO}"
  echo "Volver atrás: consola de Firebase → Hosting → sitio $FIREBASE_SITE_SITIO → historial de versiones → «Revertir» en la versión anterior."
fi
