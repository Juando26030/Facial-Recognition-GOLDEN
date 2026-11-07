"""Calendario (Fase 2, entrega 1): quién lo ve y que el clic en un evento abra el cuadrito de acciones (no el editor directo)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "templates" / "calendario.html").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
CAL_API = (ROOT / "app" / "routers" / "calendar.py").read_text(encoding="utf-8")


def test_calendar_minimum_role_is_coordinador():
    """Ven el calendario super_admin, admin, comercial y coordinador; digitador (temporal) y cliente no."""
    assert re.search(r'def calendario_page.*?_require_page_role\(request, "coordinador"\)', MAIN, re.S)
    assert CAL_API.count('Depends(require_role("coordinador"))') >= 3          # eventos, recordatorios y destinatarios
    models = (ROOT / "app" / "models.py").read_text(encoding="utf-8")
    roles = re.search(r"^STAFF_ROLES = \((.*?)\)", models, re.M).group(1).replace('"', "").replace(" ", "").split(",")          # sin importar la app: se lee la jerarquía
    ok = set(roles[roles.index("coordinador"):])
    assert ok == {"coordinador", "comercial", "admin", "super_admin"}


def test_click_opens_actions_box_with_shared_logic():
    assert "EventActions.create(" in PAGE and "openEventActions(evBtn)" in PAGE
    assert "openEventModal(" not in PAGE                                    # el editor ya no se abre directo: sale desde «Editar» del cuadrito
    for script in ("js/event-actions.js", "js/calendar-card.js", "js/revert-event.js"):
        assert f"path='{script}'" in PAGE
    assert 'staff_role == "super_admin"' in PAGE and "js/event-transfer.js" in PAGE        # Exportar, igual que en Eventos
    assert "renderCalendarCard(e, CARD_LAYOUT)" in PAGE


def test_contract_is_documented_in_the_function_header():
    src = (ROOT / "static" / "js" / "calendar-card.js").read_text(encoding="utf-8")
    assert "CONTRATO" in src and "'left' | 'right' | 'bottom'" in src
