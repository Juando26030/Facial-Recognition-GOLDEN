# Modo sin conexión (contingencia) en producción: lista de verificación y cambio exacto

**Estado:** APAGADO en producción hasta que pasen las pruebas de dispositivos del 21 al 23 de octubre de 2026. En staging está encendido.

## Qué es y qué dice la política
Con el modo encendido, cada quiosco guarda en el navegador (IndexedDB) una copia mínima de la lista: nombre para mostrar, categoría, estado y una huella con sal de la cédula (nunca fotos, vectores ni la cédula en claro), más una cola de ingresos y de altas hechas sin red. La cola y las decisiones se guardan cifradas (AES-GCM, clave no extraíble del dispositivo) y se borran solas a los 7 días, con avisos desde el día 3 y el día 6. La copia de la lista se borra a las 24 horas, al finalizar el evento o al cerrar sesión.

**Política v1.1, sección 8** («Funcionamiento local temporal en modo de contingencia»), ratificada por la auditora el 6 de octubre de 2026 sin cambios en esa sección: describe exactamente lo anterior (lista técnica con hash con sal; ninguna foto ni vector en navegadores o terminales; cola local de hasta 7 días calendario con supresión automática). Encender el modo en producción NO exige texto nuevo; lo que el código pedía además era **pruebas en dispositivos reales y la decisión de Juan David**. Si quieres una frase expresa de la auditora autorizando el encendido en producción, es una consulta de una línea.
En un evento sin biometría el modo funciona igual y no lleva ningún dato de autorización (la lista local sale con `consent: null`).

## Lista de verificación (pruebas del 21 al 23)
Dispositivos: iPad (Safari), iPhone, un Android (Chrome) y un portátil (Chrome o Edge). Se prueba en STAGING con el mismo código que irá a producción.

1. **Instalación:** abrir el quiosco con red; debe descargar la lista y mostrar el indicador de «copia local lista».
2. **Corte de red a mitad de la acreditación:** activar modo avión; debe seguir acreditando por cédula y por QR; cada ingreso queda en la cola local; la pantalla avisa «sin conexión».
3. **Alta de una persona nueva sin red:** queda en la cola, sin foto.
4. **Reconexión:** al volver la red todo sincroniza una sola vez, sin duplicados (cada ingreso lleva un identificador propio); la cola local queda vacía.
5. **Recarga de la página y reinicio del navegador sin red:** el quiosco abre desde la copia (service worker) y conserva la cola.
6. **Cola cifrada:** en las herramientas del navegador, la cola no muestra nombres ni cédulas en claro (solo el identificador y la marca de tiempo).
7. **Vencimiento a los 7 días:** con la fecha del dispositivo adelantada 3, 6 y 7 días, aparecen el aviso amarillo, el rojo y la eliminación con aviso visible (nunca en silencio).
8. **Cierre de sesión:** al cerrar sesión se borran la lista y la cola de ese evento (el cierre avisa si había ingresos sin sincronizar).
9. **Evento finalizado:** la copia se borra y el servidor no entrega la lista.
10. **Límites:** más de 12 descargas de la lista en 10 minutos por usuario responde «espera unos minutos»; la lista vence a las 24 h.
11. **Evento sin biometría:** el mismo recorrido, sin ninguna pantalla de autorización.
12. **Evento con rostro:** sin red no hay reconocimiento facial (cédula o QR); la aceptación o el rechazo pendientes se envían al reconectar.
13. **iPad en particular:** Safari borra los datos de un sitio que no se abre durante 7 días; confirmar que eso no deja una cola sin sincronizar sin aviso.
14. **Rendimiento:** cédula y QR con la copia local no se vuelven más lentos que con red (cronometrar 10 ingresos).

**Criterio:** los 14 puntos sin fallos en iPad y en un Android. Un fallo en el punto 4 (duplicados) o en el 6 (datos en claro) bloquea el encendido.

## El cambio exacto para encenderlo en producción (solo si pasan)
Hoy `deploy/gcp/config.sh` fija producción en apagado (línea 27):
```bash
if [ "$GOLDEN_ENV" = production ]; then CONTINGENCY_ENABLED=0; else CONTINGENCY_ENABLED="${CONTINGENCY_ENABLED:-1}"; fi
```
El cambio es una sola línea (producción pasa a encendido):
```bash
if [ "$GOLDEN_ENV" = production ]; then CONTINGENCY_ENABLED=1; else CONTINGENCY_ENABLED="${CONTINGENCY_ENABLED:-1}"; fi
```
Va en la rama `corte/main` / `main` como cualquier cambio de producción (con tu autorización expresa). El siguiente despliegue de producción escribe `CONTINGENCY_ENABLED: "1"` en los servicios (`deploy/gcp/deploy.sh`, línea 95) y el quiosco empieza a registrar el service worker. Para apagarlo: volver la línea a `=0` y redesplegar (el service worker se desinstala solo en la siguiente visita; hay prueba: `tests/test_contingency_flag.py`).
**Solo con la variable por consola** (`gcloud run services update … --update-env-vars CONTINGENCY_ENABLED=1`) el cambio dura hasta el próximo despliegue, que lo vuelve a apagar: sirve para una prueba, no para el piloto.

Cualquier cambio a `main` o a producción necesita tu autorización expresa; no se hace nada de esto antes del 23 de octubre.
