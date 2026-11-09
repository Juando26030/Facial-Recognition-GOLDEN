# 22 · Captura de contactos para expositores (Fase 8, pieza 6)

**Qué resuelve:** un expositor pasa el teléfono por el QR (o la etiqueta NFC) de un asistente y obtiene su contacto para pulsar solo «Guardar». Y al revés: el asistente guarda al expositor. **Nada se comparte por defecto**: cada persona decide, y puede retirarlo cuando quiera.

## Cómo funciona, en simple
1. **La persona decide.** Desde su escarapela digital (enlace `/b/…`) toca «Compartir mis datos con expositores». Lee el texto, confirma que es mayor de 18 años y acepta. Queda una constancia que no se puede borrar ni editar (`audit_contact_shares`: fecha, versión del texto y huella del texto). Retirar también queda registrado.
2. **Su tarjeta.** Al aceptar aparece un QR propio (`/tarjeta/<código largo y aleatorio>`). Quien lo escanea ve nombre, empresa, cargo, teléfono y correo y un botón **Guardar contacto** (descarga un archivo `.vcf` que el teléfono ofrece guardar en la agenda).
3. **El expositor.** El equipo (coordinador o superior) entra al evento → **Expositores** → agrega al expositor y le entrega su **enlace privado** (`/expositor/…`). Con ese enlace, en su teléfono: **Escanear asistente** (lector de QR de siempre; también lee el QR de la escarapela impresa) o escribir la cédula si no hay cámara. Ve su lista, guarda cada contacto en la agenda y baja todo a **Excel**.
4. **Privacidad en la práctica.** El expositor ve **solo** a quienes aceptaron y siguen aceptando: si alguien retira su permiso, desaparece de la lista, del Excel y de la tarjeta al instante. A quien no comparte o no está inscrito se le responde exactamente lo mismo (nadie puede «adivinar» cédulas). Hay tope de escaneos por minuto y por día. Los menores de 18 años no pueden compartir. Nada de esto se escribe en los registros del sistema y la exportación de un evento a otro entorno no lleva estos datos.

## Qué funciona en cada teléfono
| Acción | Android (Chrome) | iPhone (Safari) |
|---|---|---|
| Escanear el QR de la tarjeta con la cámara normal | Sí | Sí |
| Guardar el contacto (.vcf) | Sí (abre Contactos) | Sí (abre «Añadir a Contactos») |
| Leer una etiqueta NFC con la dirección | Sí (acercar el teléfono) | Sí (iPhone XS o más nuevo; sin abrir ninguna app) |
| **Escribir** una etiqueta NFC desde nuestra página | **Sí** (solo Chrome en Android, con https) | **No** (Safari no lo permite) |

Por eso el camino que siempre funciona es el **QR**; el NFC es un extra para quien tiene Android.

## Etiquetas NFC (opcional)
- Compra etiquetas **NTAG213** (suficiente) o **NTAG215**, en pegatina o llavero.
- En un Android con Chrome, abre la página del expositor → **Escribir etiqueta NFC** → acerca la etiqueta a la parte de atrás del teléfono. Queda grabada la dirección de su tarjeta. El botón solo aparece si el teléfono lo soporta.
- Desde ese momento, cualquier teléfono que la toque abre la página **Guardar contacto**.
- Para asistentes, la etiqueta se graba con la dirección de su tarjeta (se muestra en su página «Compartir mis datos»). Grábala solo si la persona ya aceptó compartir.
- No hace falta instalar nada. Si la etiqueta se pierde, cambia los enlaces del expositor con «Cambiar enlaces»: los anteriores dejan de servir.

## Para el equipo
- Ruta del personal: `/kiosk/<evento>/expositores` (coordinador, comercial, administrador y super administrador). API: `/api/events/<evento>/exhibitors` (alta, edición, pausar, cambiar enlaces, borrar).
- Entrega el enlace privado **solo** al expositor correspondiente (cualquiera que lo tenga puede escanear en su nombre). Si se filtra: «Cambiar enlaces».
- Pausar un expositor cierra su acceso sin borrar su lista.
- Al archivar el evento, los enlaces dejan de funcionar.
- Migración: `0114_exhibitor_leads` (cuatro tablas nuevas, no toca las existentes). Los prefijos `/contacto/`, `/tarjeta/` y `/expositor/` son públicos (`app/appmode.py`).

## Pendiente antes de producción
- **La auditora debe revisar** el texto de autorización `v1.0_contacto` (`app/contacts.py`, `SHARE_TEXT`). Si lo ajusta, cambia la versión: las constancias anteriores quedan con su texto original.
- Prueba real con dos teléfonos (Android y iPhone), una etiqueta NTAG y un evento de ensayo. Los tests automáticos (`tests/test_contactos_expositores.py`) aún no se han corrido: van en la prueba única del final.
