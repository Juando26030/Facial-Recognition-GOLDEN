"""Hallazgo 5 (revisión de seguridad 22-nov-2026), pruebas PURAS y de texto (`python3 -m pytest --noconftest -q tests/test_foto_pendiente_puro.py`).
Con base: tests/test_foto_pendiente_bd.py."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_every_biometric_deletion_goes_through_the_single_helper():
    """Nadie borra/consulta la foto de registro con photo_key directo (se olvidaría la pendiente): todo pasa por enroll.delete_photos / has_any_photo / move_photos."""
    bad = []
    for path in (ROOT / "app").rglob("*.py"):
        if path.name in ("enroll.py", "storage.py", "aceptar.py"):                # aceptar.py pregunta por la vigente a propósito (sin foto previa no hay nada que suplantar)
            continue
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"(delete|delete_all_versions|move)\(\s*photo_key\(|exists\(photo_key\(", src):
            line = src[: m.start()].count("\n") + 1
            if path.name in ("digital_public.py", "badges.py") and "badge_bio_photo_allowed" in src.splitlines()[line - 1]:
                continue                                               # esas dos solo preguntan si hay foto vigente para mostrarla en la escarapela
            bad.append(f"{path.relative_to(ROOT)}:{line}")
    assert not bad, bad


def test_the_helper_covers_current_and_pending_and_every_site_uses_it():
    enroll = _read("app/enroll.py")
    assert 'PENDING_SUFFIX = ".pending.jpg"' in enroll and "def pending_photo_key" in enroll and "def delete_photos" in enroll and "def has_any_photo" in enroll
    assert "photo_key(tenant_id, str(user_id))[: -len(\".jpg\")] + PENDING_SUFFIX" in enroll          # mismo prefijo biométrico (BIOMETRIC_KEY_PREFIX) que la vigente
    for rel, needle in (("app/privacy.py", "enroll.delete_photos("), ("app/roster_delete.py", "enroll.delete_photos("), ("app/ops_runner.py", "enroll.has_any_photo("),
                        ("app/routers/api.py", "enroll_mod.delete_photos("), ("app/routers/api.py", "enroll_mod.move_photos(")):
        assert needle in _read(rel), (rel, needle)
    privacy = _read("app/privacy.py")
    assert privacy.count("enroll.delete_photos(") == 3 and "all_versions=True" in privacy          # _erase, purga por retención y supresión/revocación
    assert "delete_photos(tenant, uid)" in enroll                                                  # run_enroll sin aceptación: tampoco queda la pendiente


def test_the_pending_photo_is_never_exported_between_environments():
    transfer = _read("app/event_transfer.py")
    assert "pending_photo_key" not in transfer and "photo_keys(" not in transfer           # solo `photo_key` (la vigente) viaja


def test_the_operator_screens_only_use_the_current_photo():
    for rel in ("app/routers/door.py", "app/routers/badges.py", "app/routers/digital_public.py"):
        src = _read(rel)
        assert "pending_photo_key" not in src and "photo_keys(" not in src, rel
    assert "def status(" in _read("app/enroll.py") and "no es la foto de registro" in _read("app/enroll.py")


def test_aceptar_ya_no_retiene_la_selfie_y_el_interruptor_no_esta_en_pantalla():
    """23-nov-2026 (decisión de Juan David): se eliminó «por verificar»: la selfie de quien acepta reemplaza la foto directamente y no hay interruptor en Parámetros."""
    src = _read("app/routers/aceptar.py")
    assert "hold = False" in src and "accept_verify_photo is not False" not in src
    html = _read("templates/kiosk_parametros.html")
    assert 'id="ccVerifyPhoto"' not in html and "ay_verfoto" not in html
    assert "NOT IN (SELECT user_id FROM web_acceptances" not in _read("app/consent.py")


def test_migration_compiles_chains_and_is_additive():
    p = ROOT / "alembic/versions/0164_accept_verify_photo.py"
    src = p.read_text(encoding="utf-8")
    ast.parse(src)
    rev = re.search(r'^revision = "([^"]+)"', src, re.M).group(1)
    down = re.search(r'^down_revision = "([^"]+)"', src, re.M).group(1)
    assert rev == "0164_accept_verify_photo" and len(rev) <= 32 and down == "0163_local_nodes_tenant"
    assert "ADD COLUMN IF NOT EXISTS accept_verify_photo BOOLEAN NOT NULL DEFAULT TRUE" in src
    heads = [f.name for f in (ROOT / "alembic/versions").glob("*.py") if f'down_revision = "{rev}"' in f.read_text(encoding="utf-8")]
    assert heads == ["0165_each_accepts.py"]                                                  # 0165 (cada quien acepta) cuelga de 0164 y es la cabeza


def test_touched_files_compile():
    for rel in ("app/enroll.py", "app/privacy.py", "app/roster_delete.py", "app/ops_runner.py", "app/routers/api.py", "app/routers/aceptar.py", "app/routers/consents.py", "app/models.py"):
        ast.parse(_read(rel))
