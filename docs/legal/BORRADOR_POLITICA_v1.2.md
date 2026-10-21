# BORRADOR — Política de Privacidad v1.2 (NO VIGENTE, para revisión de la auditora)

> **Estado:** borrador preparado el 15 de octubre de 2026 para después del piloto. **No está activo:** `POLICY_VERSION` sigue en `1.1`, el archivo ratificado `docs/legal/POLITICA_v1.1.md` (SHA-256 `d0afc7d9…`) no se tocó y la página `/privacidad` sigue mostrando la v1.1. Este documento solo lista los **cambios propuestos** sobre la v1.1; el texto final de la v1.2 se armará como archivo completo nuevo cuando la auditora apruebe estos cambios.

## Cambios propuestos (sobre el texto de la v1.1)

### Sección 5 — Reconocimiento facial
**Agregar** (nueva viñeta, después de «Cuándo se calcula tu vector»), texto de la auditora:
> **Para qué se usa tu fotografía biométrica.** 1. Extraer tu vector facial para el ingreso automatizado. 2. Imprimir tu fotografía en la escarapela física del evento.

*Nota para la auditora:* el segundo propósito exige que el **texto de autorización** que la persona acepta en pantalla (no solo la política) lo mencione; ver «Qué más cambia», punto 2.

### Sección 6 — Datos ordinarios, supresión y copias de seguridad
**Precisar** (después del párrafo de los 90 días), texto de la auditora:
> Tus datos biométricos serán eliminados de nuestros servidores 7 días después de finalizado el evento. Los registros de envío de correos e interacciones con el sistema se conservarán por 60 días exclusivamente para auditoría y respuesta a requerimientos legales.

*Nota:* la v1.1 no generaliza «toda la información» a 7 días (ver la revisión del 9 de octubre en el informe); este párrafo hace explícitos los 60 días que hoy caben en «registros de la plataforma».

### Nueva viñeta en la sección 2 o 5 — Foto aportada en formularios (campo «Adjuntar foto»)
**Agregar**:
> Si en un formulario de inscripción adjuntas una fotografía para tu escarapela, la conservamos **30 días calendario después de finalizado el evento** y la usamos exclusivamente para tu identificación visual y la impresión de tu escarapela. Esa imagen **no** se somete a escaneo biométrico ni a reconocimiento facial.

(El consentimiento en el propio formulario usa el texto literal de la auditora: «Autorizo a Golden Eventos y Logística S.A.S. (y al organizador del evento) a almacenar esta fotografía exclusivamente para mi identificación visual y la impresión de mi escarapela. Entiendo que esta imagen NO será sometida a escaneo biométrico ni reconocimiento facial.»)

## Qué más cambia al activar la v1.2 (lista para el día que se apruebe; nada de esto está hecho)
1. **Archivo y huella nuevos.** Un archivo completo `docs/legal/POLITICA_v1.2.md` ratificado por la auditora con su propio SHA-256 (como `policy_v11.py` hace con la 1.1). La v1.1 queda como histórica en `/privacidad/v1.1`. El `Dockerfile` debe copiar también el archivo nuevo a la imagen.
2. **Texto de autorización y anexo de la constancia.** Si el doble propósito (vector + impresión) debe constar en lo que la persona **acepta**, cambia el texto de `app/legal_texts_data.py` → nueva versión y **nueva huella**. Consecuencias: (a) el correo de constancia muestra en su anexo el texto nuevo solo para quien acepte con él; (b) **quien aceptó con la v1.1 no autorizó la impresión**: el interruptor «Permitir imprimir la foto biométrica en la escarapela» debería, además, exigir que la aceptación de esa persona sea de la versión nueva (cambio de código pendiente).
3. **`/privacidad`.** Mostrar la v1.2 como vigente con su leyenda de ratificación; la 1.1 y la 1.0 como históricas.
4. **`POLICY_VERSION=1.2`** en `deploy/gcp/env/common.yaml` (staging y producción a la vez), con su prueba.
5. **Contingencia.** La condición de la auditora para el modo sin conexión («la huella del texto de la constancia coincide con la política vigente») está atada a la huella de la v1.1: al activar la v1.2 hay que **revisar de nuevo** `docs/legal/CONTINGENCIA_PRODUCCION_LISTA.md` y repetir las pruebas en dispositivos antes de mantener `CONTINGENCY_ENABLED`.
6. **Retenciones en el código.** Ya implementado: registro de envíos a 60 días (`LOG_RETENTION_DAYS`). Pendiente: purga de las fotos de formularios a 30 días tras el evento (llega con el campo «Adjuntar foto», A2) y la pieza L7 (90 días de datos de contacto).
7. **Avisos.** Comunicar el cambio de política a los titulares según la ley (a definir con la auditora).
