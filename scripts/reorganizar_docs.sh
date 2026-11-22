#!/usr/bin/env bash
# Reorganiza docs/ según la estructura propuesta en docs/00_README.md §3 (detalle: docs/REORGANIZACION_DOCS_PROPUESTA.md).
# MODO SECO POR DEFECTO: solo imprime los `git mv` que haría y cuántos enlaces cambiaría; no toca nada.
#
#   bash scripts/reorganizar_docs.sh              # modo seco
#   bash scripts/reorganizar_docs.sh --aplicar    # mueve con `git mv` y corrige enlaces en los .md (incluido CLAUDE.md). NO hace commit.
#
# Mueve, no reescribe. Después de --aplicar: revisar `git status`, corregir a mano los archivos NO .md que el modo seco lista al final
# (pruebas, scripts y flujos que citan rutas de docs/), correr `python -m pytest -q` y `ruff check .`, y hacer UN commit solo de esto.
# Hacerlo cuando ningún otro trabajo esté tocando docs/ (rompe enlaces de ramas abiertas).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

APLICAR=0
case "${1:-}" in
  "") ;;
  --aplicar) APLICAR=1 ;;
  -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
  *) echo "Uso: bash scripts/reorganizar_docs.sh [--aplicar]" >&2; exit 2 ;;
esac

# «origen destino» (rutas dentro de docs/). Un origen puede ser un archivo, una carpeta o un patrón con * (solo en la raíz de docs/).
# Lo que no aparece aquí se queda donde está (00_README.md, INDEX.md, ux/, legal/).
MAPA='
REGLAS_INAMOVIBLES_Y_DECISIONES.md      reglas/
REGLAS_Y_FORMA_DE_TRABAJO.md            reglas/
IMPRESION_PARAMETROS_INAMOVIBLES.md     reglas/
COORDINADOR_TEMPORAL.md                 reglas/
ESTADO_2026-11-11.md                    estado/2026-11-11_punto_de_retorno.md
HANDOFF.md                              estado/
13_ARQUITECTURA_ESCALABILIDAD.md        arquitectura/
14_FASE0_RESULTADOS.md                  arquitectura/
15_MIGRACION.md                         arquitectura/
04_ARQUITECTURA.md                      arquitectura/
05_MODELO_DATOS.md                      arquitectura/
observabilidad.md                       arquitectura/
SEGURIDAD_SESIONES.md                   arquitectura/
19_GUIA_PRODUCCION.md                   operacion/
13_RUNBOOK_PRODUCCION.md                operacion/
runbook_evento.md                       operacion/
recuperacion_desastre.md                operacion/
24_COPIA_SEMANAL_ONEDRIVE.md            operacion/
PRUEBA_CARGA_PRODUCCION.md              operacion/
EVENTOS_EN_CURSO_LANZAMIENTO.md         operacion/
PASO_A_PRODUCCION_2026-11-16.md         operacion/
PASO_CRM_PRODUCCION_2026-11-16.md       operacion/
26_SITIO_WEB_MONTAJE.md                 operacion/
18_EVENTO_CAMPOS_ESTADOS.md             modulos/registro/
COLOR_POR_EVENTO.md                     modulos/registro/
ESCARAPELA_DIGITAL_DATOS.md             modulos/registro/
PRUEBA_LECTOR_CEDULA.md                 modulos/registro/
PRUEBA_FISICA_AUTOIMPRESION.md          modulos/registro/
1B_reimpresion_permisos.md              modulos/registro/
20_FORM_YA_INSCRITO.md                  modulos/formularios/
20_URL_LIMPIA_INSCRIPCIONES.md          modulos/formularios/
21_ESTADISTICAS_FORMULARIO_Y_CLIENTE.md modulos/formularios/
23_COBROS_WOMPI_MULTICUENTA.md          modulos/formularios/
25_INVENTARIO_POR_BASE.md               modulos/inventario/
FASE_5_INVENTARIO.md                    modulos/inventario/
ALMACEN.md                              modulos/almacen/
crm                                     modulos/crm
17_SERVIDOR_LOCAL.md                    modulos/servidor_local/
23_EVENTO_COMPARTIDO_NUBE.md            modulos/servidor_local/
FASE_6_SERVIDOR_LOCAL.md                modulos/servidor_local/
EXPLICACION_SERVIDOR_LOCAL_SIMPLE.md    modulos/servidor_local/
20_FIRMA_INSTALADOR.md                  modulos/servidor_local/
18_EXPORTAR_EVENTOS.md                  modulos/servidor_local/
FASE_9_PLATAFORMA.md                    modulos/plataforma/
20_CUENTAS_POR_SERVICIO.md              modulos/plataforma/
22_SESION_INACTIVIDAD.md                modulos/plataforma/
22_CONTACTOS_EXPOSITORES.md             modulos/plataforma/
21_QR_DINAMICO_WALLET.md                modulos/plataforma/
16_BACKLOG_PRODUCTO.md                  producto/
00_REQUERIMIENTOS_ROADMAP.md            producto/
01_VISION_Y_ALCANCE.md                  producto/
02_CLASIFICACION_FURPS.md               producto/
03_PRODUCT_BACKLOG.md                   producto/
06_BRIEF_SPRINT_1.md                    producto/
FASE_2_ALCANCE.md                       producto/
historial.md                            historico/
CIERRE_*.md                             historico/
FASE_3_*.md                             historico/
FASE_4_*.md                             historico/
FASE_5_*.md                             historico/
FASE_8_*.md                             historico/
FASE_10_*.md                            historico/
0B_*                                    historico/
0C_*                                    historico/
0D_*                                    historico/
4B_*                                    historico/
5_*                                     historico/
etapa                                   historico/etapa
seguridad                               historico/seguridad
29_PLAN_MAESTRO_ETAPA_2026-10-29.md     historico/
REVISION_F5-9_PLAN_VS_CODIGO.md         historico/
PLAN_PRUEBAS_COMPLETAS_F5-9.md          historico/
HANDOFF_IMPRESION_COMPARTIDA_29OCT.md   historico/
investigaciones_reunion_2026-09-21.md   historico/
PROMPT_SESION_NUEVA_2026-11-11.md       historico/
comp_de_check.py.txt                    historico/
revision_2026-11-22                     revisiones/revision_2026-11-22
'

# Lista final «origen<TAB>destino» (rutas desde la raíz del repo). El primer renglón que nombra un archivo gana (FASE_5_INVENTARIO va a
# modulos/inventario/ aunque después coincida con FASE_5_*).
PLAN="$(mktemp)"; trap 'rm -f "$PLAN" "$PLAN.py"' EXIT
declare -A VISTO=()
while read -r origen destino; do
  [ -n "$origen" ] || continue
  shopt -s nullglob; coincidencias=(docs/$origen); shopt -u nullglob
  for src in "${coincidencias[@]}"; do
    [ -e "$src" ] || continue
    [ -z "${VISTO[$src]:-}" ] || continue
    VISTO[$src]=1
    case "$destino" in */) dst="docs/${destino}$(basename "$src")" ;; *) dst="docs/$destino" ;; esac
    [ "$src" = "$dst" ] || printf '%s\t%s\n' "$src" "$dst" >> "$PLAN"
  done
done <<< "$MAPA"

n="$(wc -l < "$PLAN" | tr -d ' ')"
if [ "$APLICAR" = 1 ]; then echo "APLICANDO $n movimientos (sin commit)…"; else echo "MODO SECO: $n movimientos que haría (nada se toca). Con --aplicar se ejecutan."; fi
while IFS=$'\t' read -r src dst; do
  echo "git mv \"$src\" \"$dst\""
  if [ "$APLICAR" = 1 ]; then mkdir -p "$(dirname "$dst")"; git mv "$src" "$dst"; fi
done < "$PLAN"

# Enlaces: en cada .md versionado (CLAUDE.md, README.md, CHANGELOG.md, CONTRIBUTING.md, docs/**), (1) los enlaces Markdown relativos `](ruta)` se
# recalculan desde la ubicación nueva del archivo hacia la ubicación nueva del destino; (2) las menciones en texto con ruta desde la raíz
# (`docs/15_MIGRACION.md`) se cambian por la ruta nueva. En modo seco solo cuenta. Las formas cortas (`docs/15`) NO se tocan: revisarlas a mano.
cat > "$PLAN.py" <<'PY'
import os, re, subprocess, sys
plan_path, aplicar = sys.argv[1], sys.argv[2] == "1"
moves = [ln.rstrip("\n").split("\t") for ln in open(plan_path, encoding="utf8") if ln.strip()]
tracked = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout.decode("utf8").split("\0")
tracked = [t for t in tracked if t]
if aplicar:                                    # tras los git mv, el índice ya tiene las rutas nuevas: se reconstruyen las viejas
    back = {dst: src for src, dst in moves}
    def old_of(p):
        for dst, src in back.items():
            if p == dst or p.startswith(dst + "/"):
                return src + p[len(dst):]
        return p
    pairs = [(old_of(p), p) for p in tracked]
else:
    fwd = dict(moves)
    def new_of(p):
        for src, dst in fwd.items():
            if p == src or p.startswith(src + "/"):
                return dst + p[len(src):]
        return p
    pairs = [(p, new_of(p)) for p in tracked]
old2new = dict(pairs)
for src, dst in moves:                         # carpetas movidas: también como destino de enlace
    old2new.setdefault(src, dst)
old_dirs = {os.path.dirname(o) for o in old2new} | {""}
moved = {o: n for o, n in old2new.items() if o != n}
LINK = re.compile(r"(\]\()([^)\s]+)((?:\s+\"[^\"]*\")?\))")
TEXT = re.compile(r"(?<![\w/.\-])(" + "|".join(re.escape(o) for o in sorted(moved, key=len, reverse=True)) + r")(?![\w\-])") if moved else None
total_files = total_links = 0
for old, new in pairs:
    if not old.endswith(".md"):
        continue
    path = new if aplicar else old
    try:
        text = open(path, encoding="utf8").read()
    except (OSError, UnicodeDecodeError):
        continue
    count = 0
    def fix_link(m):
        global count
        target = m.group(2)
        if re.match(r"^(?:[a-z][a-z0-9+.\-]*:|#|/)", target, re.I):
            return m.group(0)
        raw, sep, anchor = target.partition("#")
        if not raw:
            return m.group(0)
        resolved = os.path.normpath(os.path.join(os.path.dirname(old), raw)).replace("\\", "/")
        if resolved not in old2new and resolved not in old_dirs:
            return m.group(0)                  # no es un archivo del repo (o ya estaba roto): no se toca
        dest = old2new.get(resolved, resolved)
        rel = os.path.relpath(dest, os.path.dirname(new) or ".").replace("\\", "/")
        if raw.endswith("/") and not rel.endswith("/"):
            rel += "/"
        if rel == raw:
            return m.group(0)
        count += 1
        return m.group(1) + rel + sep + anchor + m.group(3)
    out = LINK.sub(fix_link, text)
    if TEXT:
        def fix_text(m):
            global count
            count += 1
            return moved[m.group(1)]
        out = TEXT.sub(fix_text, out)
    if count:
        total_files += 1
        total_links += count
        if aplicar:
            open(path, "w", encoding="utf8", newline="\n").write(out)
print(f"Enlaces y menciones en .md: {total_links} en {total_files} archivos " + ("CORREGIDOS." if aplicar else "que se corregirían."))
# Lo que NO se corrige solo: archivos que no son .md y citan una ruta movida (pruebas que leen docs/, scripts, flujos, plantillas).
others = []
if TEXT:
    for old, new in pairs:
        path = new if aplicar else old
        if old.endswith(".md") or not re.search(r"\.(py|sh|yml|yaml|html|js|ps1|toml|txt|iss)$", old):
            continue
        try:
            hits = len(TEXT.findall(open(path, encoding="utf8").read()))
        except (OSError, UnicodeDecodeError):
            continue
        if hits:
            others.append((path, hits))
if others:
    print(f"A MANO ({len(others)} archivos que no son .md citan rutas movidas; si una prueba LEE el archivo, fallará hasta corregirla):")
    for path, hits in sorted(others):
        print(f"  {path} ({hits})")
PY
python3 "$PLAN.py" "$PLAN" "$APLICAR"
if [ "$APLICAR" = 1 ]; then
  echo "Hecho. Falta (a mano): fundir docs/INDEX.md en docs/00_README.md, revisar la lista «A MANO», pruebas y ruff, y UN commit."
else
  echo "Nada se movió. Detalle y riesgos: docs/REORGANIZACION_DOCS_PROPUESTA.md"
fi
