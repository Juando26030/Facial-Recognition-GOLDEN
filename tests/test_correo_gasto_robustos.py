"""C6 y C11 (Fase 3): asunto de correo con CR/LF y gastos con Decimal no finito. Las de correo no usan base; las de gastos sí."""
from pathlib import Path

import pytest

from tests.conftest import login

ROOT = Path(__file__).resolve().parent.parent


def test_send_mail_never_raises_with_cr_lf_in_subject_or_recipient(monkeypatch):
    from app import mailer
    for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "GRAPH_SENDER", "SMTP_HOST"):
        monkeypatch.delenv(k, raising=False)
    saved = {}
    monkeypatch.setattr(mailer, "_outbox_fallback", lambda msg, to, reason: saved.update(msg=msg, to=to) or {"sent": False, "detail": reason})
    for subject in ("hola\rX", "hola\nBcc: x@y.co", "a\r\nb", "tab\tx", None):
        r = mailer.send_mail("a@b.co", subject, "cuerpo")
        assert isinstance(r, dict) and r["sent"] is False
        assert "\r" not in saved["msg"]["Subject"] and "\n" not in saved["msg"]["Subject"]
        assert "Bcc" not in saved["msg"]                                  # no hay inyección de cabeceras
    r = mailer.send_mail("a@b.co\r\nBcc: z@y.co", "x", "cuerpo")
    assert isinstance(r, dict) and "Bcc" not in saved["msg"]


def test_clean_subject_is_single_line_and_capped():
    from app import mailer
    assert mailer.clean_subject("a\rb\nc") == "a b c"
    assert len(mailer.clean_subject("x" * 500)) == 200


def test_expense_amount_rejects_non_finite_values_in_source():
    src = (ROOT / "app/routers/event_docs.py").read_text(encoding="utf-8")
    chunk = src[src.index("def add_expense("):src.index("evidence_path = evidence_name = None")]
    assert "value.is_finite()" in chunk and "MAX_EXPENSE" in chunk


@pytest.mark.parametrize("amount", ["Infinity", "-Infinity", "NaN", "1E+999", "1e13", "-1"])
def test_expense_endpoint_rejects_bad_amounts(client, factory, amount):
    factory.staff("coordinador", "coo")
    ev = factory.event()
    login(client, "coo")
    r = client.post(f"/api/events/{ev.id}/expenses", data={"category": "Logística", "responsible": "Ana", "amount": amount})
    assert r.status_code == 400, r.text
    ok = client.post(f"/api/events/{ev.id}/expenses", data={"category": "Logística", "responsible": "Ana", "amount": "1500,50"})
    assert ok.status_code == 200, ok.text
