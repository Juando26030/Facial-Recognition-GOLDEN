"""Arma la portada y los gráficos del libro del reporte del evento (Fase 10, bloque E). Sin base de datos ni almacenamiento propio: lo que necesita llega como parámetros (`read_optional` lee un
archivo del almacenamiento y devuelve None si no existe), así se prueba con datos simulados.

UN solo logo en la portada (decisión del 10-nov): el del evento si existe, si no el de Golden (más una marca pequeña de Golden en el pie cuando sale el del evento).
Orden final de las hojas: «Portada» → «Reporte» (lo de siempre) → «Gráficos» → «Historial de cambios» (solo si hubo cambios; la agrega app/reports.py después)."""
import logging
import os
from collections import Counter

from app import report_charts, report_cover
from app.timeutil import to_local, utcnow

log = logging.getLogger("golden.report_book")
STATIC_LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "img", "logo-golden.png")


def cover_logos(event, read_optional) -> tuple:
    """(logo principal, marca del pie). UN solo logo: el del evento si tiene uno propio («custom») y se puede leer; si no, el de Golden. Si el principal es el del evento, el pie lleva una marca
    pequeña de Golden; si el principal ya es Golden, no se repite (None)."""
    try:
        with open(STATIC_LOGO, "rb") as fh:
            golden = fh.read()
    except OSError:
        golden = None
    own = read_optional(getattr(event, "logo_path", None)) if getattr(event, "logo_mode", "") == "custom" else None
    if own and report_cover.prepare_logo(own):
        return own, golden
    return golden, None


def _n(v: int) -> str:
    return f"{v:,}".replace(",", ".")


def cover_info(event, tenant_name: str, df, changes: list) -> dict:
    """Datos de la portada (texto ya armado) a partir del evento y de la tabla del reporte (la persona de prueba ya no está en `df`)."""
    total = len(df)
    registered = int((df["Estado"] == "Registrado").sum()) if total and "Estado" in df.columns else 0
    pct = f"{round(100 * registered / total)} %" if total else "—"
    stamps, hours = [], Counter()
    if total and "Fecha de Registro" in df.columns and "Hora de Registro" in df.columns:
        for d, h in zip(df["Fecha de Registro"], df["Hora de Registro"]):
            if d and h:
                stamps.append(f"{d} {str(h)[:5]}")
                hours[str(h)[:2]] += 1

    def fmt(stamp):
        return f"{stamp[8:10]}/{stamp[5:7]}/{stamp[:4]} {stamp[11:16]}" if stamp else "—"
    peak = f"{max(hours, key=lambda k: (hours[k], k))}:00" if hours else "—"
    place = ", ".join(x for x in (getattr(event, "location", None), getattr(event, "city", None)) if x and str(x).strip())
    coord, comm, etype = getattr(event, "coordinator", None), getattr(event, "commercial", None), getattr(event, "event_type", None)
    return {
        "tenant": tenant_name, "event_name": getattr(event, "name", "") or "", "event_code": getattr(event, "event_code", "") or "",
        "dates": report_cover.dates_text(getattr(event, "start_date", None), getattr(event, "end_date", None)), "place": place,
        "event_type": etype.name if etype else "",
        "coordinator": (coord.full_name or coord.username) if coord else "", "commercial": (comm.full_name or comm.username) if comm else "",
        "generated": to_local(utcnow()).strftime("%d/%m/%Y %H:%M") + " (hora de Colombia)",
        "kpis": [("Personas en la base", _n(total)), ("Registradas", _n(registered)), ("Por registrar", _n(total - registered)), ("Asistencia", pct)],
        "kpis2": [("Primer registro", fmt(min(stamps) if stamps else "")), ("Último registro", fmt(max(stamps) if stamps else "")), ("Hora con más registros", peak), ("Datos modificados", str(len(changes)))],
    }


def decorate(book, event, tenant_name: str, tenant_id: str, df, field_hints: dict, changes: list, read_optional, key_of=None) -> None:
    """Agrega «Gráficos» y «Portada» (la primera) al libro openpyxl `book`, que ya trae la hoja «Reporte». Cada pieza falla por separado sin tumbar a la otra."""
    try:
        report_charts.build_sheet(book, report_charts.build_specs(df, field_hints, changes))
    except Exception:          # los gráficos fallaron: se quita la hoja a medias y la portada sale igual
        log.exception("no se pudieron armar los gráficos del reporte")
        if report_charts.SHEET in book.sheetnames:
            del book[report_charts.SHEET]
    cover = book.create_sheet("Portada", 0)
    logo, footer = cover_logos(event, read_optional)
    report_cover.build_cover(cover, cover_info(event, tenant_name, df, changes), logo, footer)
    for ws in book.worksheets:                         # una sola hoja seleccionada (si no, Excel las agrupa y lo que se escribe cae en todas)
        ws.sheet_view.tabSelected = ws is cover
    book.active = 0
