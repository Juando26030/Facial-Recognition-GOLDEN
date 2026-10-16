# Diagnóstico: el enlace personal pidió la fecha aunque la lista la traía (evento PRUEBA-ACEPT-03, cédula 9990000028)

Solo leen; no cambian nada. En Cloud Shell:

**0. Conexión (una vez por pestaña)**
```bash
export DBURL="$(gcloud secrets versions access latest --secret golden-direct-database-url-staging --project goldenweb-staging)"; P() { psql "$DBURL" -X -P pager=off "$@"; }; EV=$(P -tAc "select id from events where event_code='PRUEBA-ACEPT-03'"); echo "evento=$EV"
```

**1. Qué hay guardado de esa persona en ese evento**
```bash
P -c "select u.id, u.birth_date, u.is_biometric_enabled, a.accept_trusted, (a.accept_token is not null) tiene_enlace from users u join event_attendees a on a.user_id=u.id and a.tenant_id=u.tenant_id where a.event_id=$EV and u.id='9990000028'"
```
*Debes ver:* una fila. **Si `birth_date` está vacío, la fecha nunca se guardó** (el enlace hizo lo correcto al pedirla). Si trae `2005-03-26`, el problema está en el formulario (eso no lo vi en las pruebas locales).

**2. Si el evento tenía el reconocimiento facial activo al cargar**
```bash
P -c "select facial_enabled, aceptar_enabled, roster_uploaded, optional_field_labels from events where id=$EV"
```
*Debes ver:* `facial_enabled` en `t` hoy. (Hoy; lo importante es cómo estaba **al cargar**: ver el punto 3.) En `optional_field_labels`, si aparece un campo llamado como «fecha de nacimiento», la columna se tomó como un campo opcional cualquiera y no como la fecha.

**3. Qué dijo la carga cuando se hizo (la causa casi segura)**
```bash
P -c "select to_char(created_at at time zone 'America/Bogota','MM-DD HH24:MI:SS') hora, status, left(result_json, 1500) resultado from bulk_jobs where event_id=$EV order by created_at desc limit 5"
```
*Cómo leerlo:* busca en `resultado` el texto **`no se usa en este evento (no tiene reconocimiento facial)`** (dentro de `unused`) o **«NO se guardaron porque este evento no tiene el reconocimiento facial activo»** (esta última frase solo existe en la versión nueva). Si aparece, la causa es esa.

## Qué encontré en el código (probado con pruebas)
| Causa que propusiste | Resultado |
|---|---|
| (a) la carga no entiende el texto dd/mm/aaaa | **No es.** «26/03/2005» como texto y como fecha de Excel se leen bien (prueba nueva). |
| (b) la recarga no completa la fecha vacía de quien ya existe | **No es.** Una recarga con fecha completa a quien existía sin ella (prueba nueva). |
| (c) la fecha está guardada pero el enlace no la lee | **No es.** Con la fecha guardada, el enlace personal no la pide (prueba nueva). |
| **(d) la fecha no se guardó porque el evento no tenía el reconocimiento facial activo al cargar** | **Reproducido.** Es una regla antigua: «sin rostro la fecha de nacimiento no se usa». La columna se ignora; antes el único aviso era una línea escondida en el informe de columnas. |

Es decir: lo más probable es que cargaras la lista **antes** de activar el reconocimiento facial del evento. **Qué hacer con esa lista:** activa el reconocimiento facial del evento y vuelve a cargar **el mismo archivo**: se completan las fechas de quien no tenía.

## Qué cambió en esta versión
- **Aviso claro:** si el evento no tiene el reconocimiento facial activo, el resumen de la carga dice «N fila(s) traían fecha de nacimiento y NO se guardaron… Actívalo y vuelve a cargar el mismo archivo».
- **Fechas ilegibles:** el resumen dice cuántas filas y cuáles («fila(s) 5, 9»), además del aviso por fila de siempre.
- **Recarga:** completa la fecha de quien no la tenía. A quien ya tiene una fecha válida **no se la cambia** (se avisa con la fila) salvo que marques **«Reemplazar las fechas de nacimiento que ya están guardadas»**; si la reemplazas, queda anotado en el historial de la persona.
- La plantilla dice ahora que se active el reconocimiento facial **antes** de cargar.
