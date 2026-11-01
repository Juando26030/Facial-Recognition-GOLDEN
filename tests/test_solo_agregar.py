"""«Solo agregar personas nuevas» a un evento en curso (pista Eventos en curso, pedido A): nunca toca a quien ya existe, no crea campos y no estorba al registro en vivo."""
import pytest

from app import event_rules
from app.models import Event


@pytest.mark.parametrize("status, uploaded, normal_blocked, append_blocked", [
    ("finalizado", False, True, True), ("finalizado", True, True, True),
    ("en_proceso", True, True, False), ("en_proceso", False, False, False),
    ("creado", False, False, False), ("creado", True, False, False)])
def test_append_only_is_allowed_in_progress_but_never_finalized(status, uploaded, normal_blocked, append_blocked):
    ev = Event(status=status, roster_uploaded=uploaded)
    assert bool(event_rules.roster_block_reason(ev)) is normal_blocked
    assert bool(event_rules.roster_block_reason(ev, append_only=True)) is append_blocked
