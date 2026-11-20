"""Llaves de producto del servidor local: lógica pura (app/server_keys.py). No usa base de datos."""
from datetime import datetime, timedelta
from types import SimpleNamespace as K

from app import server_keys as sk

NOW = datetime(2026, 11, 20, 12)
I, J = "a" * 16, "b" * 16


def mk(**kw):
    base = dict(disabled_at=None, activated_at=None, claimed_at=None, expires_at=NOW + timedelta(days=7), installation_id=None)
    return K(**{**base, **kw})


def test_generate_and_normalize():
    code = sk.generate()
    assert sk.KEY_RE.match(code) and code.startswith("GLD-")
    assert sk.normalize(code.lower().replace("-", " ")) == code and sk.normalize(" " + code + " ") == code
    assert sk.normalize("abc") is None and sk.normalize("XYZ-AAAA-BBBB-CCCC") is None and sk.normalize(None) is None
    assert len({sk.generate() for _ in range(200)}) == 200


def test_status_flow():
    assert sk.status(mk(), NOW) == "unused"
    assert sk.status(mk(), NOW + timedelta(days=8)) == "expired"                 # sin usar vence a los 7 días
    assert sk.status(mk(claimed_at=NOW, installation_id=I), NOW + timedelta(hours=47)) == "claimed"
    assert sk.status(mk(claimed_at=NOW, installation_id=I), NOW + timedelta(hours=49)) == "expired"
    assert sk.status(mk(activated_at=NOW), NOW + timedelta(days=99)) == "active"     # una activa no vence
    assert sk.status(mk(activated_at=NOW, disabled_at=NOW), NOW) == "disabled"       # deshabilitada manda sobre todo


def test_claim_is_single_use_but_retry_from_same_installation_is_ok():
    assert sk.check_claim(mk(), I, NOW)[0]
    assert sk.check_claim(mk(claimed_at=NOW, installation_id=I), I, NOW)[0]          # reintento de la misma instalación
    assert sk.check_claim(mk(claimed_at=NOW, installation_id=I), J, NOW)[1] == "other_install"
    assert sk.check_claim(mk(activated_at=NOW), I, NOW)[1] == "active"
    assert sk.check_claim(mk(disabled_at=NOW), I, NOW)[1] == "disabled"
    assert sk.check_claim(mk(), I, NOW + timedelta(days=8))[1] == "expired"


def test_activate_needs_the_claim_of_the_same_installation():
    assert sk.check_activate(mk(), I, NOW)[1] == "not_claimed"
    assert sk.check_activate(mk(claimed_at=NOW, installation_id=I), I, NOW)[0]
    assert sk.check_activate(mk(claimed_at=NOW, installation_id=I), J, NOW)[1] == "other_install"
    assert sk.check_activate(mk(activated_at=NOW), I, NOW)[1] == "active"
    assert sk.check_activate(mk(claimed_at=NOW, installation_id=I, disabled_at=NOW), I, NOW)[1] == "disabled"


def test_ticket_is_signed_bound_to_installation_and_expires():
    t = sk.make_ticket("secreto", 7, I, 1000)
    assert sk.read_ticket("secreto", t, I, 1001) == 7
    assert sk.read_ticket("secreto", t, J, 1001) is None                             # otra instalación
    assert sk.read_ticket("otro", t, I, 1001) is None                                # otra firma
    assert sk.read_ticket("secreto", t, I, 1000 + sk.TICKET_SECONDS + 1) is None     # vencido
    assert sk.read_ticket("secreto", "basura", I, 1) is None and sk.read_ticket("secreto", None, I, 1) is None

