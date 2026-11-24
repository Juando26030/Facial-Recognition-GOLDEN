"""Hotfix 24-nov-2026 (sin base de datos): varias personas inscritas desde el mismo celular con «Permitir que la misma persona vuelva a enviar».
La prueba completa (con base) está en tests/test_form_ya_inscrito.py."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def read(p):
    return (ROOT / p).read_text(encoding="utf-8")


def test_reserve_slot_checks_the_retry_by_cedula_when_repeats_are_allowed():
    src = read("app/formsvc.py")
    assert "own_retry = (not dedupe) and bool(person_id) and bool(sid)" in src
    assert '"sid": None if own_retry else sid' in src                       # la función SQL ya no confunde a otra persona con un reintento
    assert 'if res.get("ok") and own_retry and confirmed_retry(db, form, sid, person_id, is_test):' in src
    assert "FormSubmission.person_id == person_id" in src.split("def confirmed_retry")[1].split("def ")[0]


def test_public_form_renews_the_submission_key_after_a_confirmed_submission():
    html = read("templates/form_public.html")
    assert "let SID = " in html
    done = html.split("function done(thanks) {")[1].split("\n}\n")[0]
    assert 'sessionStorage.removeItem("sid_" + BASE)' in done and "SID = Math.random()" in done
