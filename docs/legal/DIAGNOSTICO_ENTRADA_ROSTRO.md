# Diagnóstico: por qué una cara ya reconocida no entra (evento PRUEBA-ROSTRO-01, staging)

No tengo acceso a la nube, así que estos comandos los corres tú en **Cloud Shell**. **No cambian nada** (solo leen). El umbral `DOOR_AUTO_MAX_DIST` **no se toca** hasta ver los números.

Antes, la conexión (una vez por pestaña):
```bash
export DBURL="$(gcloud secrets versions access latest --secret golden-direct-database-url-staging --project goldenweb-staging)"
P() { psql "$DBURL" -X -P pager=off "$@"; }
EV=$(P -tAc "select id from events where event_code='PRUEBA-ROSTRO-01'"); echo "evento=$EV"
```
*Debes ver:* `evento=` seguido de un número.

## 1. Los últimos intentos (distancia, margen y motivo)
```bash
P -c "select to_char(at at time zone 'America/Bogota','HH24:MI:SS') hora, detail from system_events where kind='door_face' and ref='$EV' order by id desc limit 30"
```
*Cómo leerlo.* El contador **no guarda quién es la persona** (por privacidad), así que reconoces tus intentos por la **hora**. `detail` dice:
- `match d310 m390` → entró; `d310` = distancia **0,310**, `m390` = margen **0,390** sobre el segundo.
- `match_repeat …` → **ya había ingresado** (no se registró otra entrada).
- `no_match d520 m280 far` → hubo candidato, pero su distancia (0,520) estaba **por encima de 0,50** → **distancia alta**.
- `no_match d400 m40 doubtful` → distancia buena pero el margen (0,040) es **menor que 0,06** → **margen bajo**.
- `no_match none` → ningún candidato dentro de 0,55 **o tu cara no está en la lista de la puerta** (sin aceptación vigente / sin vector / marcada como menor).
- `no_face` → no se vio una cara. `reverted` → alguien pulsó «Revisar».

(Los intentos hechos **antes** de este cambio solo dicen `no_match` con o sin números; los nuevos traen el motivo.)

También lo puedes ver sin comandos, cuando esta versión esté desplegada: `GET /api/events/<id>/door-face/stats` → `recent_attempts` (hora, resultado, distancia, margen, motivo) y `reasons`.

## 2. Tu entrada y su reversión
```bash
P -c "select id, to_char(timestamp at time zone 'America/Bogota','HH24:MI:SS') hora, registration_method, record_type from access_logs where event_id=$EV and user_id='9990000020' order by id"
P -c "select to_char(at at time zone 'America/Bogota','HH24:MI:SS') hora, kind, old_value, new_value, detail from person_changes where event_id=$EV and user_id='9990000020' order by id"
```
*Debes ver:* tus entradas (si no hay ninguna fila, la reversión la borró) y el cambio «Registrado → No registrado» con el detalle «entrada con rostro revertida por el personal» y su hora. **Compara esa hora con las de los intentos del punto 1:** si antes de revertir salía `match`/`match_repeat` y después `no_match …`, la reversión cambió algo; si el motivo es el mismo antes y después, no tuvo que ver.

## 3. Tu aceptación, tu foto y tu vector
```bash
P -c "select to_char(consent_timestamp_utc at time zone 'America/Bogota','MM-DD HH24:MI:SS') hora, reason, accepted_biometric, confirmed_adult, ip_or_device_id canal from audit_consent_logs where event_id=$EV and user_id='9990000020' order by consent_timestamp_utc"
P -c "select (face_encoding is not null) tiene_vector, is_biometric_enabled, to_char(face_captured_at at time zone 'America/Bogota','MM-DD HH24:MI:SS') foto_vector_guardado, to_char(biometric_consent_at at time zone 'America/Bogota','MM-DD HH24:MI:SS') consentimiento, biometric_consent_source origen from users where id='9990000020'"
P -c "select to_char(created_at at time zone 'America/Bogota','MM-DD HH24:MI:SS') creada, to_char(verified_at at time zone 'America/Bogota','MM-DD HH24:MI:SS') verificada, verified_via from web_acceptances where event_id=$EV and user_id='9990000020'"
```
*Debes ver:*
- **Aceptación:** la **última** fila de `audit_consent_logs` debe ser `consent` con `accepted_biometric = t`. Si la última es `revocation` o `rejection`, no estás en la lista de la puerta. En `canal` ves cómo se aceptó (`web-link`, `web-portal`, `web-qr`, `staff:<id>` o el quiosco).
- **Vector y foto:** `tiene_vector = t` e `is_biometric_enabled = t`. `foto_vector_guardado` es **cuándo se guardó el vector y la foto vigentes**; `origen` es de dónde vino (`kiosko`, `carga_masiva` o `copiado`; vacío si llegó por /aceptar).
- **Verificación:** si `verificada` está vacía, tu aceptación está «por verificar» y **no entra a la lista de la puerta** hasta que el personal la confirme.

La **fecha de la foto en el bucket** (la imagen misma):
```bash
TEN=$(P -tAc "select tenant_id from events where id=$EV")
gcloud storage ls -l -a "gs://goldenweb-staging-golden-staging-us-east4/biometric/$TEN/known_people/9990000020.jpg"
```
*Debes ver:* una o varias versiones con su fecha y hora de creación; la **última** es la foto vigente.

## 4. Qué haremos con los números
- `far` con distancias **entre 0,50 y 0,55** y tu foto de siempre → es el umbral: lo hablamos con los números de la prueba de calibración.
- `none` → tu cara no está en la matriz de la puerta (aceptación, vector o verificación del punto 3) o la distancia supera 0,55 (mala luz, otra cámara, o la foto guardada es muy distinta a cómo te ves hoy).
- `doubtful` → hay otra persona de prueba muy parecida (por ejemplo un familiar) y el margen es bajo.
- `match_repeat` → ya tenías una entrada (por cédula u otro método): es lo esperado.

Envíame la salida de los comandos 1, 2 y 3 (no contiene fotos ni vectores).
