"""Paso guiado de biometría del evento: reglas de validación (las que PROTEGEN, en el servidor) y el resumen en lenguaje simple de lo que pasará en la puerta con esa configuración.

Reglas:
  * Activar el reconocimiento facial en un evento de un TERCERO exige razón social, NIT y correo de privacidad del organizador.
  * El pre-cálculo de vectores (fotos previas) solo existe en eventos de terceros, con fotos previas del cliente, referencia y fecha del anexo firmado y la casilla de garantía del cliente, y solo
    lo activa un super_admin (app/routers/consents.py). En un evento propio con fotos previas NO se pre-calcula: el vector se calcula cuando la persona acepta.
  * `/aceptar` y «antes de cada uso» (`every_scan`) vienen apagados por defecto y solo tienen sentido con el rostro activo.
"""
from typing import List, Optional

from app import company, legal_texts
from app.models import Event


def tercero_missing(controller: str, name: Optional[str], nit: Optional[str], email: Optional[str]) -> List[str]:
    if controller != "tercero":
        return []
    return [label for label, v in (("la razón social del organizador", name), ("el NIT del organizador", nit), ("el correo de privacidad del organizador", email)) if not (v or "").strip()]


def validate(controller: str, facial: bool, name, nit, email, photos_before: bool, aceptar: bool, prompt: str, locked: bool = False, accept_link: bool = False) -> List[str]:
    """Errores (en español, para mostrar tal cual) de una configuración propuesta; lista vacía = válida."""
    errors = []
    if locked and (facial or aceptar or photos_before):
        errors.append("Este evento está marcado como SIN biometría: no se puede activar el rostro, la aceptación desde el celular ni las fotos previas. Quita primero el bloqueo.")
    if controller not in ("golden", "tercero"):
        errors.append("El responsable debe ser Golden (evento propio) o un tercero")
    if prompt not in ("once", "every_scan"):
        errors.append("El modo de la autorización debe ser «una vez» o «antes de cada uso»")
    if facial:
        missing = tercero_missing(controller, name, nit, email)
        if missing:
            errors.append("Para activar el reconocimiento facial en un evento de un tercero falta: " + ", ".join(missing))
    if accept_link and not aceptar:
        errors.append("El enlace personal por correo necesita la aceptación desde el celular (página /aceptar) activa")
    if not facial and (aceptar or photos_before or accept_link):
        errors.append("La aceptación desde el celular y las fotos previas solo aplican con el reconocimiento facial activo")
    return errors


def precalc_blockers(event: Event, anexo_ref: Optional[str], anexo_fecha, garantia: bool) -> List[str]:
    """Qué falta para autorizar el pre-cálculo (lista vacía = se puede)."""
    out = []
    if event.controller_mode != "tercero":
        out.append("solo en eventos de un tercero")
    if not event.client_photos_before:
        out.append("el cliente debe entregar fotos antes del evento")
    if not (anexo_ref or "").strip():
        out.append("la referencia del anexo firmado")
    if not anexo_fecha:
        out.append("la fecha del anexo firmado")
    if not garantia:
        out.append("la casilla de garantía del cliente")
    return out


def facial_blockers(event: Event) -> List[str]:
    """Por qué NO se puede activar el rostro en este evento ahora mismo (para la carga masiva y el interruptor)."""
    return tercero_missing(event.controller_mode, event.organizer_name, event.organizer_nit, event.organizer_privacy_email)


def summary(event: Event) -> dict:
    """{ready, missing[], door[]}: qué falta y, en lenguaje simple, qué pasará en la puerta con la configuración actual."""
    missing, door = [], []
    tercero = event.controller_mode == "tercero"
    if tercero:
        door.append(f"El organizador ({event.organizer_name or 'sin completar'}) es el Responsable de los datos y Golden el Encargado.")
    else:
        door.append("Golden es el Responsable único de los datos de este evento.")
    if not event.facial_enabled:      # sin rostro NO es un problema: es una configuración completa
        off = ["Todo el mundo entra por cédula o QR.", "No se pide ninguna autorización biométrica, no se calcula ni se guarda ninguna foto ni vector, y la fecha de nacimiento no se usa."]
        off.append("Este evento está BLOQUEADO sin biometría: nadie puede activar el rostro ni subir fotos." if getattr(event, "biometrics_locked", False)
                   else "Para que sea imposible activar el rostro por error, elige «No usa rostro (bloqueado)» y guarda.")
        return {"ready": True, "headline": "✅ Listo: este evento no usa biometría", "missing": [], "door": door + off}
    missing += [f"Falta {m}" for m in facial_blockers(event)]
    text = legal_texts.render(event)
    for marker in text["blocked"]:
        missing.append(f"Falta configurar {marker.strip('[]')} (el texto de autorización no se muestra sin ese dato)")
    door.append("En la puerta: se escribe o escanea la cédula o el QR; la persona ve la pantalla de autorización, acepta con un clic, se capta su rostro y ese día entra por cédula; desde la siguiente entrada, por rostro.")
    door.append("La autorización se pide " + ("una sola vez por persona y evento." if event.consent_prompt_mode == "once" else "antes de cada uso, con dos botones cortos."))
    if event.aceptar_enabled:
        door.append("Antes del evento, las personas ya inscritas pueden aceptar desde su celular con el QR del cartel o el enlace; en la puerta el personal confirma su identidad con el documento o el QR y desde ahí entran por rostro.")
        if event.accept_link_email:
            door.append("Quien se inscriba por formulario recibirá por correo su enlace personal para autorizar; como el correo lo escribió él mismo, su aceptación igual queda «por verificar»: el personal confirma su identidad en la puerta.")
        if not event.client_photos_before:
            door.append("Fuente de la foto: cada persona se toma una selfie desde su celular (enlace, formulario o QR); se guarda cifrada y el rostro se calcula cuando acepta. Antes de abrir la cámara se valida la fecha de nacimiento: un menor no pasa.")
        door.append("Cuando alguien acepta, recibe por correo su constancia (sin la foto) con la escarapela virtual si el evento la tiene.")
    else:
        door.append("No hay aceptación previa por celular (está apagada).")
    if event.client_photos_before:
        if tercero and event.precalculo_autorizado:
            door.append(f"Las fotos del cliente se procesan al cargarlas (anexo {event.precalculo_anexo_ref or 's/n'}); la persona se reconoce con un clic en la pantalla.")
        elif tercero:
            missing.append("Las fotos previas no se procesan antes del evento hasta que un super administrador registre el anexo firmado y la garantía del cliente")
            door.append("Las fotos del cliente se guardan cifradas, pero el rostro NO se calcula hasta que cada persona acepte.")
        else:
            door.append("Las fotos que cargues se guardan cifradas; el rostro NO se calcula hasta que la persona acepte.")
    door.append("Quien no quiera rostro, sea menor de 18 años o no sea reconocido entra por cédula o QR: la puerta nunca se bloquea.")
    return {"ready": not missing, "missing": missing, "door": door}
