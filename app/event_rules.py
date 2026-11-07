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
# Reglas que se apagan en un evento ARCHIVADO (Fase 3): nadie registra, entra como cliente/digitador ni usa ruleta o registro touch. Certificados, áreas e inventario (consulta) y los datos quedan como estaban.
ARCHIVED_OFF = ("client_access", "client_stats_download", "temp_digitadores_enter", "registration", "roulette", "touch_registration")


# Mensajes de «Adjuntar Base de Datos» cuando el evento no admite la carga (los usa el servidor Y la pantalla: una sola regla, para que no vuelvan a divergir).
ROSTER_BLOCKED_FINALIZED = ("Este evento está FINALIZADO: ya no se puede cargar la base de datos. Si de verdad necesitas cargarla, un administrador puede reabrir el evento "
                            "(pasarlo a «Creado» desde la lista de eventos).")
ROSTER_BLOCKED_IN_PROGRESS = ("Este evento ya tiene una base cargada y está EN PROCESO. La carga normal no se permite porque pisaría los datos de quienes ya se registraron en vivo. "
                              "Qué hacer: usa «Solo agregar personas nuevas» (no toca a nadie que ya esté en el evento), pide a un administrador que lo devuelva a «Creado» o crea un evento nuevo.")
APPEND_BLOCKED_FINALIZED = "Este evento está FINALIZADO: ya no se pueden agregar personas."


def roster_block_reason(event: Event, append_only: bool = False) -> Optional[str]:
    """None si el evento admite cargar la base; si no, el motivo en palabras simples (qué pasa y qué hacer). Regla del servidor: finalizado nunca; en proceso solo si todavía no tuvo
    una carga exitosa (`roster_uploaded`: volver a cargar pisaría o duplicaría registros hechos en vivo). `append_only` («solo agregar personas nuevas», nunca toca a quien ya existe)
    se admite en cualquier estado salvo finalizado, también con el evento en proceso y la base ya cargada."""
    if event.status == "finalizado":
        return APPEND_BLOCKED_FINALIZED if append_only else ROSTER_BLOCKED_FINALIZED
    if event.status == "en_proceso" and event.roster_uploaded and not append_only:
        return ROSTER_BLOCKED_IN_PROGRESS
    return None


def effective_rules(event: Event, state: Optional[EventState] = None) -> dict:
    """{regla: bool} del evento: los valores por defecto de su estado base, con lo que el estado configurado diga encima."""
    state = state if state is not None else event.state
    rules = dict(DEFAULTS_BY_BASE.get(event.status, DEFAULTS_BY_BASE["creado"]))
    if state is not None:
        rules.update({k: bool(v) for k, v in state.get_rules().items() if k in RULES})
    if getattr(event, "archived_at", None) is not None:          # Fase 3: un evento archivado queda de solo lectura, diga lo que diga su estado configurable
        rules.update({k: False for k in ARCHIVED_OFF})
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
