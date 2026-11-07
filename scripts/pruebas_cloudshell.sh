#!/usr/bin/env bash
# Pruebas completas (las mismas del CI de GitHub) en Cloud Shell, con una base Postgres temporal en Docker.
# NO toca producción, staging ni Neon: la base vive solo en este Cloud Shell y se borra al terminar.
# Uso: nohup bash ~/pruebas_cloudshell.sh <commit-o-rama> > ~/pruebas.log 2>&1 &
set -uo pipefail
REF="${1:-main}"
W=~/pruebas_gw; rm -rf "$W"; mkdir -p "$W"; cd "$W"
echo "== 1/6 clonando $REF"
git clone --depth 60 --branch "$REF" https://github.com/Juando26030/Facial-Recognition-GOLDEN.git repo 2>&1 | tail -1 || exit 1
cd repo; echo "commit: $(git log --oneline -1)"
echo "== 2/6 base Postgres 16 temporal (Docker)"
docker rm -f gw-pg-test >/dev/null 2>&1
docker run -d --name gw-pg-test -e POSTGRES_PASSWORD=postgres -p 55432:5432 postgres:16 >/dev/null || { echo "NO PUDE ARRANCAR DOCKER"; exit 1; }
for i in $(seq 1 30); do docker exec gw-pg-test pg_isready -U postgres >/dev/null 2>&1 && break; sleep 2; done
echo "== 3/6 Python 3.13 y dependencias (sin dlib ni face-recognition, como el CI)"
pip install -q --user uv 2>&1 | tail -1; export PATH="$HOME/.local/bin:$PATH"
uv venv --python 3.13 .venv -q 2>&1 | tail -2 || exit 1
grep -viE '^(face[-_]recognition|dlib)' requirements.txt > /tmp/req-ci.txt
uv pip install -q --python .venv/bin/python -r /tmp/req-ci.txt pytest httpx pyyaml 2>&1 | tail -3
echo "== 4/6 pruebas de Python (esto tarda)"
export DATABASE_URL=postgresql://postgres:postgres@localhost:55432/golden_db SECRET_KEY=ci-only-secret
.venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -60
RES=${PIPESTATUS[0]}
echo "== 5/6 pruebas de JS"
( command -v node >/dev/null && npm ci --silent 2>&1 | tail -2 && for f in tests/js/*_check.js; do node "$f" || { echo "FALLO JS: $f"; JSFAIL=1; }; done ) 
echo "== 6/6 limpieza"
docker rm -f gw-pg-test >/dev/null 2>&1
echo "RESULTADO_PYTEST_CODIGO=$RES  (0 = todo pasó)"
echo "FIN"
