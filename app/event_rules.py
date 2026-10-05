"""Reglas por estado de evento (docs/18 §4): qué se habilita mientras un evento está en un estado configurable.

La regla efectiva de un evento sale de su estado (`events.state_id`); si no tiene estado (datos viejos) o al estado le falta una regla, vale el valor por defecto de su estado BASE
(`events.status`), que reproduce el comportamiento de siempre. Las reglas que hoy se hacen cumplir: `client_access`, `temp_digitadores_enter`, `registration` y `client_stats_download`;
las demás (`roulette`, `touch_registration`, `areas`, `inventory_control`, `certificates`) quedan declaradas para que cada módulo las consulte con `allowed()` al cablearlas."""
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Event, EventState

# clave → (etiqueta para el administrador, ayuda)
RULES = {
    "client_access": ("El cliente puede entrar al evento", "Usuarios de tipo cliente autorizados a este evento."),
    "client_stats_download": ("El cliente puede descargar estadísticas e informe", "Exportar estadísticas y descargar el informe."),
    "temp_digitadores_enter": ("Los digitadores temporales pueden entrar", "Digitadores autorizados a este evento."),
    "registration": ("Se puede registrar (cédula, QR, facial, manual)", "Acreditar y registrar personas. Aplica a todos los roles."),
    "roulette": ("Se puede usar la ruleta", ""),
    "touch_registration": ("Se puede usar el registro touch", ""),
    "areas": ("Se puede usar el control de áreas", ""),
    "inventory_control": ("Se puede usar el control de inventario del evento", ""),
    "certificates": ("Se pueden descargar certificados", ""),
}

DEFAULTS_BY_BASE = {
    "creado": {"client_access": False, "client_stats_download": False, "temp_digitadores_enter": False, "registration": False, "roulette": True, "touch_registration": False,
               "areas": True, "inventory_control": True, "certificates": False},
    "en_proceso": {"client_access": True, "client_stats_download": True, "temp_digitadores_enter": True, "registration": True, "roulette": True, "touch_registration": True,
                   "areas": True, "inventory_control": True, "certificates": False},
    "finalizado": {"client_access": False, "client_stats_download": False, "temp_digitadores_enter": False, "registration": False, "roulette": False, "touch_registration": False,
                   "areas": True, "inventory_control": True, "certificates": True},
}
BASE_STATUSES = tuple(DEFAULTS_BY_BASE)


def effective_rules(event: Event, state: Optional[EventState] = None) -> dict:
    """{regla: bool} del evento: los valores por defecto de su estado base, con lo que el estado configurado diga encima."""
    state = state if state is not None else event.state
    rules = dict(DEFAULTS_BY_BASE.get(event.status, DEFAULTS_BY_BASE["creado"]))
    if state is not None:
        rules.update({k: bool(v) for k, v in state.get_rules().items() if k in RULES})
    return rules


def allowed(event: Event, rule: str) -> bool:
    if rule not in RULES:
        raise KeyError(f"regla desconocida: {rule}")
    return effective_rules(event)[rule]


def clean_rules(raw: Optional[dict]) -> dict:
    """Solo reglas conocidas y como booleanos (lo que llega de la pantalla de configuración)."""
    return {k: bool(v) for k, v in (raw or {}).items() if k in RULES}


def default_state(db: Session, base_status: str) -> Optional[EventState]:
    """Primer estado activo con ese estado base (el que se asigna cuando alguien cambia `status` sin elegir uno)."""
    return (db.query(EventState).filter(EventState.base_status == base_status, EventState.is_active == True)  # noqa: E712
            .order_by(EventState.position, EventState.id).first())
