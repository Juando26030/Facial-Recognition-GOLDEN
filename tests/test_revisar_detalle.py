"""«Revisar el detalle» (0143): columna, interruptor de la plantilla, aviso rojo en el calendario. Pruebas puras (sin base de datos)."""
import json
import re
import subprocess
from pathlib import Path

from app import event_template as et

ROOT = Path(__file__).resolve().parent.parent


def test_switch_and_default_layout():
    assert "review_detail" in et.SWITCH_KEYS
    tpl = et.default_template()
    revisa = [s for s in tpl["creation_layout"]["sections"] if s["id"] == "revisa"][0]
    assert "sw_review_detail" in revisa["keys"]
    assert any(f["key"] == "sw_review_detail" and f["type"] == "switch" and not f["required"] for f in tpl["fields"])


def test_saved_templates_get_the_field_once():
    old = et.default_template()
    old["fields"] = [f for f in old["fields"] if f["key"] != "sw_review_detail"]
    for s in old["creation_layout"]["sections"]:
        s["keys"] = [k for k in s["keys"] if k != "sw_review_detail"]
    merged = et.merge_missing_base(old)
    revisa = [s for s in merged["creation_layout"]["sections"] if s["id"] == "revisa"][0]
    assert revisa["keys"].count("sw_review_detail") == 1
    assert et.merge_missing_base(merged) == merged          # idempotente


def test_migration_chain_and_model_column():
    mig = (ROOT / "alembic/versions/0143_event_review_detail.py").read_text()
    assert 'down_revision = "0142_crm_legacy_fields"' in mig and len('0143_event_review_detail') <= 32
    assert "review_detail = Column(Boolean" in (ROOT / "app/models.py").read_text()
    assert len(re.findall(r"review_detail", (ROOT / "app/routers/events.py").read_text())) >= 4


def test_edit_modal_has_checkbox_and_sends_explicit_value():
    t = (ROOT / "templates/_event_edit_modal.html").read_text()
    assert 'name="review_detail"' in t and "form.review_detail.checked = !!ev.review_detail" in t and "payload.review_detail = form.review_detail.checked" in t


def test_calendar_shows_red_triangle_only_when_on():
    js = """
    const c = require('./static/js/calendar-card.js');
    const base = { id: 1, name: 'Feria', event_code: 'F1', status: 'creado', switches: {} };
    const out = {
      miniOn: c.renderCalendarMini(Object.assign({ review_detail: true }, base)),
      miniOff: c.renderCalendarMini(Object.assign({ review_detail: false }, base)),
      cardOn: c.renderCalendarCard(Object.assign({ review_detail: true }, base), null),
      cardOff: c.renderCalendarCard(Object.assign({ review_detail: false }, base), null),
    };
    console.log(JSON.stringify(out));
    """
    res = subprocess.run(["node", "-e", js], cwd=ROOT, capture_output=True, text=True, check=True)
    o = json.loads(res.stdout)
    assert "cal-card__review" in o["miniOn"] and "cal-card__review" in o["cardOn"]
    assert "cal-card__review" not in o["miniOff"] and "cal-card__review" not in o["cardOff"]
