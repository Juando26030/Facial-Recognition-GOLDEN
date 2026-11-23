# Plan 07 · Registro de decisiones del modelo facial y pruebas de sesgo

Fecha: 23-nov-2026 · Rama `saas/revision-integral` · Es un PLAN (no hay código nuevo). Lo ejecuta otro desarrollador y alguien de Golden con apoyo de la auditora; lo que decide Juan David está al final.
Origen: hallazgo 17 y propuestas D1, D2, D3, D4, D6 de `docs/revision_2026-11-22/08_google_seo_ux_regulacion_ia.md`; Fase 6, punto 3, de `docs/revision_2026-11-22b/00_PLAN_SEGUNDA_PASADA.md`.

## 0. En palabras sencillas (para Juan David)

- El reconocimiento facial de la plataforma se calibró con **39 personas** (conjunto cerrado y un ensayo con una persona «quitada» de la lista). Funcionó bien, pero **nadie midió si funciona igual para hombres y mujeres, para pieles claras y oscuras, para distintas edades, con gafas o con tapabocas**. Es una pregunta legítima de cualquier auditor o cliente corporativo y hoy no se puede responder con datos.
- Este plan hace dos cosas: (1) deja **por escrito, en un solo lugar, qué se decidió, por qué y con qué evidencia** (el «registro de decisiones»), y (2) define **cómo medir el sesgo por grupos** sin guardar datos personales reales en el repositorio: solo cifras agregadas.
- Lo que **NO** se puede decir hoy (y no debe decirse en ningún texto, ficha ni propuesta comercial): «el sistema funciona igual para todos» o «no tiene sesgo». Ver §3.

## 1. Qué se decidió ya (con la evidencia que hay)

Todo lo de esta tabla se verificó en el código y en `docs/14_FASE0_RESULTADOS.md`.

| Decisión | Valor | Dónde vive en el código | Evidencia y fecha | Observación |
|---|---|---|---|---|
| Modelo | `dlib` ResNet de 128 dimensiones vía `face_recognition` (paquete `dlib==20.0.1`; modelos `face_recognition_models`, fijados por huella en `requirements.txt` líneas 12-18) | `app/biometrics.py`, `app/faces.py` | Decisión de origen del proyecto; no hay documento de comparación con otros modelos | Es un modelo abierto de hace años. La literatura documenta rendimiento distinto por grupo en modelos de esta familia; **no medido aquí**. |
| Umbral de coincidencia | **0,55** (distancia euclídea; menor = más parecido) | `app/faces.py` línea 35 (`FACE_TOLERANCE`); `app/biometrics.py` líneas 103-104 (`tolerance=0.55`, «redujimos de 0.68 a 0.55») | `docs/14` §6.2 (2026-09-28): 39 personas, 195 escaneos por valor. Con 0,55: 97-98 % de aciertos, 0 falsos positivos. Con 0,50: se pierden entre 8 y 25 aciertos de 195 sin ganar nada medible | El motivo de bajar de 0,68 a 0,55 no está documentado en `docs/14` (solo el comentario del código). |
| Jitters en el escaneo en vivo | **2** en producción y staging | `deploy/gcp/env/common.yaml` línea 22. **El valor por omisión del código es 10** (`app/faces.py` línea 37) y `.env.example` lo deja comentado en 10 | `docs/14` §6.2: 1, 2 y 5 jitters dan la misma precisión con 0,55; con 2 jitters un escaneo cuesta 202 ms frente a ~4 veces más con 10 | **Riesgo de configuración:** una instalación que no lea `common.yaml` (servidor local, VM heredada, desarrollo) usa 10. Verificar en `docs/17_SERVIDOR_LOCAL.md` y `deploy/windows/` qué valor lleva el servidor local (no lo encontré definido allí). |
| Jitters en el registro | **25** (referencia) | Docstring de `app/faces.py` línea 13 («El registro (25 jitters) no pasa por aquí») | Los registros de las pruebas se enrolaron con 25, como en producción | — |
| Margen para «DUDOSO» | **0,10** en la nube; **0,06** por omisión en el código | `deploy/gcp/env/common.yaml` líneas 23-24; `app/faces.py` líneas 43 y 240-242 | `docs/14` §6.3 (2026-09-29): con 39 personas, los márgenes 0,04-0,08 nunca se activan; 0,10 es el menor valor probado que atrapa el único falso positivo del conjunto abierto; cuesta 2,1 % de escaneos por verificar | **La evidencia es UN falso positivo.** Decisión razonable pero frágil. |
| Ingreso automático en la puerta | distancia ≤ **0,50** y margen ≥ `MATCH_MARGIN` | `app/routers/door.py` línea 35 (`DOOR_AUTO_MAX_DIST`, 0,50) y línea 91 | `docs/legal/GUIA_ENTRADA_ROSTRO.md` líneas 11 y 34: «el 0,50 se calibra con la prueba de la sección 4» | **No encontré el resultado de esa calibración escrito** en `docs/14` ni en `docs/legal/`. Está pendiente de evidencia. |
| Palabras de confianza para el operador | «Muy parecido» < 0,40; «Parecido» 0,40-0,50; «Revisar con cuidado» 0,50-0,55 | `app/faces.py` líneas 229-237 (`confidence`) | `docs/14` §6.2 las propone con «p. ej.» (ejemplo), sin calibración propia | Son bandas orientativas, no medidas por grupo. |
| Supervisión humana | El operador ve foto de registro, captura, confianza en palabras y los 5 candidatos más cercanos; un resultado DUDOSO **nunca** se registra solo | `app/routers/api.py` líneas 709-810 (`/recognize`, `/recognize/candidates`, `/recognize/photo`); `docs/14` §6.3 | Implementado el 2026-09-29 | Falta ponerlo como regla escrita en la capacitación (D5 del reporte 08). |
| Prueba de vida (movimiento) en la puerta | **Retirada** el 2026-10-16 | `app/liveness.py` líneas 3-4 | Decisión del dueño del producto | No hay defensa contra foto impresa o pantalla más allá de la supervisión humana. **No medido.** |
| Voluntariedad y alternativa | Reconocimiento facial voluntario; siempre existe cédula o QR | `CLAUDE.md` (Biometría L1-L4), `docs/legal/POLITICA_v1.1.md` | Textos de la auditora | Es la mitigación principal de un falso negativo: nadie queda fuera por un error del modelo. |

## 2. Qué evidencia falta

1. **Tamaño y composición de la muestra.** 39 personas, una foto de registro y una de kiosco cada una; conjunto cerrado salvo el ensayo «abierto» (`docs/14` §6.2-§6.3). Los propios documentos advierten: «sirve para comparar valores, no para estimar la tasa de falsos positivos de un evento de miles».
2. **Cero desglose por grupo.** Ni sexo, ni edad, ni tono de piel, ni gafas, ni tapabocas, ni barba, ni iluminación. Está documentado como hallazgo 17 (reporte 08).
3. **Falsos positivos de verdad.** En §6.2 el margen entre «misma persona» e «impostor más cercano» fue **−0,013 con 2 jitters** (una foto de la misma persona a 0,555 y un impostor a 0,542) y el margen global mínimo de §6.3 fue **0,0018**. Es decir, las distribuciones se tocan. Con miles de personas habrá más parecidos.
4. **Personas NO registradas que se parecen a alguien que sí lo está** (conjunto abierto): una sola prueba (190 escaneos, 1 caso).
5. **Resultados reales en eventos.** No existe registro de qué dijo el sistema y qué hizo el operador en cada reconocimiento (D1 del reporte 08): no se mide el falso positivo ni el falso negativo reales, ni el porcentaje de DUDOSO en producción. `access_logs` (`app/models.py` líneas 134-148) guarda el ingreso y el método (`registration_method`), no la distancia, el segundo candidato ni la acción del operador.
6. **Calidad de imagen de la puerta real** (cámara, luz, ángulo, tapabocas): las pruebas usaron fotos de personas voluntarias, no el entorno de un evento.
7. **El 0,50 de la puerta** (ingreso automático) sin resultado de calibración publicado.
8. **Reproducibilidad.** `scripts/bench_jitters.py` y `scripts/calibrate_match_margin.py` existen y no imprimen nombres ni vectores, pero la carpeta de fotos (`C:\JDRJ\Golden\fotos_prueba`) fue declarada borrable (`docs/14` §6.3): **no hay forma de repetir esas mediciones exactas**.

## 3. Qué NO se puede concluir sin datos reales

Esta sección debe copiarse tal cual a la ficha del sistema (D4) y a cualquier respuesta a un cliente.

- **No se puede afirmar** que el sistema tenga la misma precisión para todos los grupos. Tampoco que tenga sesgo. **No se sabe.**
- **No se puede estimar** la tasa de falsos positivos de un evento real a partir de 39 personas. Con 0 errores en n pruebas, el límite superior al 95 % es de aproximadamente 3/n (regla de tres): con 195 escaneos, hasta 1,5 %, **y los 195 escaneos son 39 personas × 5 repeticiones, no 195 personas** (las repeticiones no son independientes). El límite honesto es mayor.
- **No se puede concluir** que «0,55 es el umbral correcto» para toda la población; solo que fue razonable en esa muestra y que la persona equivocada más cercana quedó a 0,54-0,58.
- **No se puede concluir** nada sobre menores (no pasan por biometría), personas mayores, personas con barba, maquillaje, tapabocas o gafas oscuras: no hay datos.
- **No se puede concluir** nada sobre ataques de suplantación (foto, pantalla, video): la prueba de vida está retirada.
- **Los promedios no demuestran equidad:** un promedio de 97 % puede esconder 100 % en un grupo y 85 % en otro.
- **Con grupos de 20 personas** la resolución de una tasa es de 5 puntos porcentuales (1 persona = 5 %): se detectan diferencias grandes, no pequeñas. Un resultado «sin diferencia» con n=20 significa «no se vio una diferencia grande», no «no la hay».

## 4. Protocolo de prueba de sesgo por grupos

Se ejecuta fuera de la nube, en un computador de Golden, con voluntarios. **Nada de fotos, nombres, cédulas ni vectores entra al repositorio, a un commit, a un log ni a un chat.** Solo se publican tablas de cifras agregadas.

### 4.1 Voluntarios y consentimiento
- Mínimo **20 personas por grupo** que se quiera reportar (el reporte 08, D2, ya lo fija); recomendado 30. Solo mayores de 18 años (la plataforma excluye menores de biometría, `app/minors.py`).
- **Consentimiento específico para la prueba**, por escrito, con su finalidad («medir la calidad del reconocimiento facial por grupos»), plazo de borrado y derecho a retirarse. **No se puede reutilizar el texto de autorización del evento** (los textos de la auditora son literales e inamovibles, `CLAUDE.md`): esta prueba necesita su texto propio, redactado o aprobado por la auditora.
- Las fotos son un dato biométrico sensible. El grupo declarado (tono de piel, sexo) puede revelar origen racial o étnico, que también es sensible. Por eso: el grupo lo **autodeclara** la persona, en categorías gruesas, y se guarda en un archivo APARTE de las fotos, con un código anónimo (P001…), sin nombre ni cédula.
- Derecho de retiro: quien se retire borra su carpeta y su fila sin explicación.

### 4.2 Qué se fotografía y cómo
- Por persona: **una foto de registro** (como en un evento: de frente, luz normal) y **tres fotos de «puerta»**: de frente, 15 grados de giro, luz distinta (más oscura o a contraluz). Para los grupos con accesorio (gafas, tapabocas): fotos con y sin el accesorio de la MISMA persona.
- Cámara: la misma que se usa en un evento real (la del quiosco o tableta), no la del celular del investigador, para medir lo que de verdad pasa en la puerta.
- Las fotos se guardan en una carpeta local cifrada del computador (BitLocker; ver `deploy/windows/proteger-disco.ps1`, sin probar), una subcarpeta por código de persona. Se borran al terminar (plazo en el consentimiento, recomendado ≤ 30 días).

### 4.3 Grupos a medir
Se reportan por separado (no cruzados, porque con n=20 los cruces quedan vacíos):

| Dimensión | Categorías sugeridas | Nota |
|---|---|---|
| Sexo declarado | mujer / hombre / otro o prefiere no decir (solo se reporta si n ≥ 20) | Autodeclarado |
| Rango de edad | 18-29 / 30-44 / 45-59 / 60 o más | |
| Tono de piel | escala Monk (10 tonos) agrupada en claro (1-3) / medio (4-7) / oscuro (8-10); alternativa: escala Fitzpatrick | Autodeclarado con la tarjeta de la escala; no lo decide el investigador |
| Gafas | sin / con gafas transparentes / con gafas oscuras | Misma persona con y sin |
| Tapabocas | sin / con | Misma persona con y sin |
| Vello facial | sin / con barba o bigote | |
| Luz de la puerta | normal / baja o contraluz | Por condición, no por persona |

### 4.4 Cómo se calcula (extensión de `scripts/bench_jitters.py`, D2 del reporte 08)
- Aceptar una **etiqueta de grupo por subcarpeta** mediante un archivo de etiquetas aparte (`grupos.csv`: código, dimensión, categoría) fuera del repositorio.
- Configuración de la prueba idéntica a producción: registro con 25 jitters, escaneo con `RECOGNITION_JITTERS=2` (el valor real de `common.yaml`), lado mayor 640 px, rostro más grande, umbral 0,55 **y** 0,50, `MATCH_MARGIN=0,10`.
- Se reportan, por grupo y para el total:

| Métrica | Qué es | Cómo se calcula |
|---|---|---|
| **FNMR** (falso rechazo) | % de escaneos de personas registradas que el sistema NO reconoce (sin coincidencia o DUDOSO) | no reconocidos ÷ escaneos con rostro detectado |
| **Tasa de sin rostro** | % de fotos donde no se detecta cara | sin rostro ÷ total de fotos |
| **FMR** (falsa aceptación) | % de comparaciones de impostores que quedan bajo el umbral | impostores bajo 0,55 ÷ comparaciones de impostores **del mismo grupo** (los impostores del mismo grupo son los más parecidos y es donde aparece el sesgo) |
| **Matriz de FMR entre grupos** | lo mismo, cruzando grupo de la persona A con grupo de B | tabla grupo × grupo |
| **Top-1 en conjunto cerrado** | % de escaneos donde la persona correcta es la más cercana | como en `docs/14` §6.3 |
| **Tasa de DUDOSO** | % de escaneos con margen menor a `MATCH_MARGIN` | como en `docs/14` §6.3 |
| **Distribución de distancias** | media, p95 y máximo de «misma persona»; mínimo y p1 de «otra persona» | como en `docs/14` §6.2 |
| **Falso positivo en conjunto abierto** | % de escaneos que reconocen a alguien cuando la persona verdadera se QUITA de la galería | como en `docs/14` §6.3 |

- **Intervalos de confianza:** para cada tasa, intervalo de Wilson al 95 %. Como un escaneo repetido de la misma persona no es independiente, el remuestreo se hace **por persona** (bootstrap por persona), no por escaneo.
- **Tamaño mínimo para publicar:** una celda con menos de 20 personas se marca «n insuficiente» y no se interpreta.
- **Privacidad de la salida:** el script nunca imprime nombres, nombres de archivo, códigos ni vectores; cada cifra va con su n; una celda con 1-4 personas no se publica (riesgo de reidentificación). Los resultados se escriben fuera del repositorio.

### 4.5 Reglas de decisión (escribirlas ANTES de medir)
Propuesta (la aprueban Juan David y la auditora antes de mirar los números):
1. Si el límite superior del FNMR de un grupo supera el **doble** del FNMR del total, o la FMR de un grupo supera el **doble** de la del total, se documenta como **limitación conocida de ese grupo** y se activa lo de §4.6.
2. Si la FMR de cualquier grupo con 0,55 supera **1 de cada 1.000** comparaciones, se baja el umbral para TODOS (no por grupo) y se repite la prueba.
3. **No se pone un umbral distinto por grupo.** Exigiría clasificar a las personas por su apariencia, es más difícil de justificar legalmente y más fácil de equivocar.

### 4.6 Qué hacer si aparece una diferencia
Por orden de preferencia: (a) explicar la limitación en la ficha del sistema y en la capacitación del personal; (b) reforzar la verificación humana para ese caso (siempre cédula o QR ante «Revisar con cuidado» o DUDOSO); (c) cambiar condiciones de captura (luz, cámara, distancia); (d) evaluar otro modelo (esto sería un cambio de modelo: repetir toda la prueba y registrar la decisión); (e) en un evento con una población donde la limitación sea grave, desactivar el reconocimiento facial y usar solo cédula o QR (el sistema ya lo permite por evento).

### 4.7 Cuándo repetir
Cada vez que cambie: el modelo o su versión (`dlib`, `face_recognition_models`), el umbral, los jitters, `MATCH_MARGIN`, la cámara del quiosco, o cuando se acumulen **12 meses** desde la última medición.

## 5. Medición con eventos reales sin guardar datos personales (opcional, etapa 2)

Es la propuesta D1 del reporte 08, acotada para no crear un riesgo nuevo.

- **No se pueden medir grupos en producción:** la plataforma no recoge sexo, tono de piel ni edad exacta de las personas por rostro, y **no debe empezar a hacerlo** para esto (sería ampliar datos sensibles sin finalidad). La medición por grupos se hace SOLO con la prueba voluntaria de §4.
- **Sí se puede medir calidad real en producción con contadores agregados:** una tabla nueva (por ejemplo `recognition_stats`, migración propia aditiva, id ≤ 32 caracteres) con una fila por evento y día y solo conteos: escaneos, sin rostro, sin coincidencia, coincidencia, DUDOSO, y por nivel de confianza (`high/medium/low`), más la acción del operador (confirmó el principal / eligió otro candidato / rechazó / pasó a cédula) y los valores vigentes de `FACE_TOLERANCE`, `MATCH_MARGIN`, `RECOGNITION_JITTERS`. **Sin cédula, sin nombre, sin distancia por persona.** Se alimenta donde se consume el token (`app/routers/api.py` líneas 731 y 792, `faces.read_match_payload`), dentro de la misma transacción.
- Con eso se mide: % de DUDOSO real (la regla de `docs/14` §6.3 dice «si pasa de 5 %, subir `MATCH_MARGIN` hacia 0,12»), % de veces que el operador **eligió otro candidato** (indicio de falso positivo del modelo) y % de «pasó a cédula».
- Si se quisiera guardar distancia y candidato por persona (D1 completo), sería un dato personal nuevo: necesita decisión de Juan David, su plazo en `docs/legal/TABLA_RETENCION_REGISTROS.md` y la opinión de la auditora. No se recomienda en esta etapa.
- Retención de los contadores: sin datos personales; conservar 3 años como `audit_consent_logs` para poder responder reclamos.

## 6. Plantilla del registro de decisiones

Un archivo `docs/legal/REGISTRO_DECISIONES_MODELO_FACIAL.md` (nuevo, solo texto) con **una entrada por decisión**. Se agrega una entrada cada vez que cambie algo de la tabla de §1 o aparezca un incidente (D6 del reporte 08). No se borran entradas: una decisión reemplazada se marca «Reemplazada por DEC-00X».

```
## DEC-000 · Título corto (ej.: «Umbral de coincidencia 0,55»)
- Fecha: AAAA-MM-DD
- Estado: Vigente | Reemplazada por DEC-00X | En revisión
- Quién la propone / quién la autoriza (nombres de cargo; sin datos personales de terceros):
- Qué se decidió (valor exacto y dónde vive: archivo, variable de entorno, valor por omisión):
- Por qué (el problema que resuelve, en lenguaje sencillo):
- Alternativas que se descartaron y por qué:
- Evidencia usada: documento y sección (ej.: docs/14 §6.2), tamaño de la muestra (n personas, n escaneos), fecha, quién midió.
- Lo que la evidencia NO demuestra (límites, sin adornos):
- Resultados por grupo (si existen): enlace a la tabla agregada; si no existen, escribir «NO MEDIDO».
- Riesgo si estamos equivocados: falso positivo (entra otra persona) / falso negativo (fila y molestia) / sesgo por grupo / otro.
- Mitigaciones activas (operador humano, DUDOSO, cédula/QR, voluntariedad, retención de 7 días):
- Cómo se detecta que fue un error (indicador y umbral de alarma, ej.: DUDOSO > 5 %):
- Fecha de revisión obligatoria (máximo 12 meses):
- Datos personales involucrados: ninguno | cuáles y su plazo (ver TABLA_RETENCION_REGISTROS.md)
- Revisó la auditora: Sí (fecha, constancia) | No | No aplica
- Commit o despliegue donde se aplicó:
```

Entradas iniciales que hay que escribir (con los datos de §1): DEC-001 modelo `dlib`/`face_recognition`; DEC-002 umbral 0,55 (incluida la bajada desde 0,68, motivo **no documentado**: dejarlo así y no inventarlo); DEC-003 jitters 25 al registrar y 2 al escanear (con el riesgo del valor por omisión 10); DEC-004 `MATCH_MARGIN` 0,10 (evidencia: un falso positivo); DEC-005 ingreso automático de la puerta con 0,50 (evidencia: **pendiente**); DEC-006 retiro de la prueba de vida (2026-10-16); DEC-007 verificación humana obligatoria y DUDOSO sin autoregistro; DEC-008 bandas de confianza en palabras.

## 7. Ley 1581 de 2012, la auditora y la responsabilidad demostrada

Lo que sigue es el mapa que ya usa el proyecto; **no es asesoría jurídica** y cada punto lo confirma la auditora.

| Tema | Qué dice el marco (como lo cita el proyecto) | Cómo lo cubre este plan |
|---|---|---|
| Dato sensible | La imagen facial y el vector son datos biométricos sensibles; tratarlos requiere autorización expresa y es facultativo (Ley 1581 de 2012, art. 6; `docs/legal/POLITICA_v1.1.md`) | La prueba de sesgo usa voluntarios con autorización PROPIA y específica; el grupo autodeclarado también es sensible (puede revelar origen racial o étnico) |
| Finalidad | Los datos solo se usan para lo autorizado (principio de finalidad, art. 4) | No se reutilizan fotos de eventos ni autorizaciones de eventos para medir sesgo. La prueba tiene su finalidad escrita |
| Calidad y veracidad | Los datos deben ser veraces y completos (art. 4) | Medir el sesgo es evidencia de que el tratamiento no perjudica injustamente a un grupo; falta esa evidencia hoy |
| Seguridad y circulación restringida | Cifrado, acceso limitado (art. 4) | Fotos de la prueba en disco cifrado, sin subir a la nube, borradas al terminar; el repositorio, los logs y los chats solo ven agregados |
| Responsabilidad demostrada | Poder DEMOSTRAR las medidas (Decreto 1377/2013, arts. 26-27, hoy en el Decreto 1074/2015; Circular Externa 002 de 2015 de la SIC; citados en `docs/revision_2026-11-22/08`, D3) | El registro de decisiones (§6) y los contadores (§5) son esa demostración; falta además la evaluación de impacto (D3, `docs/legal/EVALUACION_IMPACTO_BIOMETRIA.md`, **no existe todavía**) |
| Regulación reciente | La política cita la Resolución 52185 de 2025 de la SIC (`POLITICA_v1.1.md` línea 5) | **No la leí ni la verifiqué:** pedirle a la auditora que indique si impone algo específico sobre pruebas de sesgo o evaluación de impacto |
| Registro de bases de datos (RNBD) | El contador certificó en octubre de 2026 activos por debajo de 100.000 UVT: no está obligada; se revisa cada año (`docs/legal/DECISIONES_Y_PENDIENTES.md` línea 104) | Sin cambio; si algún año se superan, inscribir la base de asistentes con biométricos |
| Referencias internacionales (no obligatorias en Colombia) | Art. 10 y 27 del reglamento europeo de IA, marco NIST de gestión de riesgos de IA, NIST FRVT, OCDE, UNESCO (citados en el reporte 08, hallazgo 17) | Sirven de guía de buenas prácticas para el diseño de la prueba |

**Con la auditora** (lo que hay que pedirle por escrito, y no se publica nada hasta su visto bueno, regla del plan de la segunda pasada, decisión 10):
1. Texto de consentimiento propio para voluntarios de la prueba de sesgo.
2. Confirmar si autodeclarar el tono de piel o el sexo para una prueba cuenta como dato sensible adicional y qué cuidado exige.
3. Confirmar el plazo de conservación de los resultados agregados y de los contadores de §5.
4. Confirmar si debe agregarse a la política una mención de las pruebas de calidad por grupos y de los contadores agregados.
5. Revisar la ficha del sistema (D4) y la frase pública sobre IA (`docs/legal/PENDIENTE_AUDITORA_2026-11-22.md`, texto E).
6. Redactar o validar la evaluación de impacto (D3).

## 8. Orden de pasos y horas

| # | Paso | Quién | Horas |
|---|---|---|---|
| 1 | Crear `docs/legal/REGISTRO_DECISIONES_MODELO_FACIAL.md` con la plantilla y las 8 entradas iniciales de §6 (solo texto, desde `docs/14` y el código) | Desarrollador | 3-4 |
| 2 | Comprobar y corregir el riesgo del valor por omisión de jitters y margen (código 10 y 0,06 frente a producción 2 y 0,10): decidir si el servidor local debe definirlos; documentar. Si se cambia el valor por omisión del código, necesita decisión de Juan David | Desarrollador | 1-2 |
| 3 | Pedir a la auditora lo de §7 y esperar | Juan David | — |
| 4 | Extender `scripts/bench_jitters.py` con grupos, FNMR/FMR, Wilson, bootstrap por persona y salida agregada (y su prueba pura con datos sintéticos, sin fotos) | Desarrollador | 8-12 |
| 5 | Reclutar 20-30 voluntarios por grupo, recoger consentimientos, tomar fotos, ejecutar | Golden | 16-24 (esfuerzo humano, no de código) |
| 6 | Escribir la tabla de resultados agregada y la entrada DEC de la prueba; decidir según §4.5 | Desarrollador + Juan David | 4-6 |
| 7 | Ficha del sistema (D4) y evaluación de impacto (D3) | Desarrollador + auditora | 8-12 + revisión legal |
| 8 | (Etapa 2) Contadores agregados `recognition_stats` | Desarrollador | 8-12 |

## 9. Qué decide Juan David

1. **¿Se hace la prueba de sesgo?** a) Sí, antes de vender a otras empresas; b) Sí, pero solo si un cliente o la auditora lo pide; c) No. **Recomendación: (a).** Un cliente corporativo o la auditora lo preguntarán, y hoy la respuesta honesta es «no lo sabemos». Mientras no se haga, el reconocimiento facial no debe ofrecerse como «sin sesgo» ni «igual para todos».
2. **¿Quién recluta a los voluntarios?** a) El personal de Golden y sus familiares; b) Una universidad o gremio; c) Un proveedor externo. **Recomendación: (a) para empezar,** sabiendo que la muestra puede quedar sesgada hacia un solo perfil; si faltan grupos, (b).
3. **Reglas de decisión de §4.5** (doble del total, 1 en 1.000, sin umbral por grupo): ¿se aprueban o se cambian? **Recomendación: aprobarlas tal cual** antes de ver cualquier número.
4. **¿Qué se hace si aparece una diferencia grande?** a) Documentarla y reforzar la verificación humana; b) Desactivar el reconocimiento facial para ese tipo de evento; c) Buscar otro modelo. **Recomendación: (a) primero,** (c) solo si la diferencia es grande y repetida, y siempre con la prueba repetida.
5. **¿Se publica el resultado?** a) Solo interno; b) Un resumen agregado en la ficha pública del sistema (`/inteligencia-artificial` del sitio). **Recomendación: (b)** una vez la auditora dé su visto bueno, porque convierte la prueba en ventaja comercial.
6. **Contadores agregados en eventos (§5).** a) Sí, sin datos personales; b) Con distancia y candidato por persona (más datos personales); c) No. **Recomendación: (a).**
7. **El 0,50 de la puerta.** Hay que decidir si se hace la calibración que la guía pide (`docs/legal/GUIA_ENTRADA_ROSTRO.md` §4) o se deja el ingreso automático apagado hasta tenerla. **Recomendación: no encender el ingreso automático en un evento con público hasta tener esa calibración y la prueba de sesgo.**
8. **El valor por omisión del código** (jitters 10, margen 0,06) frente a producción (2 y 0,10). **Recomendación: igualar el servidor local a producción y dejar escrito el motivo;** cambiar el valor por omisión del código solo con su autorización.

## 10. Qué no pude comprobar

- No ejecuté `scripts/bench_jitters.py`, `scripts/calibrate_match_margin.py` ni ninguna prueba; no vi fotos. Todas las cifras (39 personas, 195 escaneos, 97-98 %, 0,555 / 0,542, 0,0018, 2,1 %, 1 de 190) salen de lo escrito en `docs/14_FASE0_RESULTADOS.md` §6.2-§6.3; no las reproduje.
- No verifiqué qué valores de jitters y margen usa el servidor local ni la VM heredada: solo vi `deploy/gcp/env/common.yaml` y los valores por omisión del código.
- No encontré el motivo escrito de bajar el umbral de 0,68 a 0,55 ni la calibración del 0,50 de la puerta; pueden existir en otro lugar (documentos del proyecto de Claude, `claude/NN_…`) que no pude abrir desde aquí.
- No leí la Resolución 52185 de 2025 de la SIC ni los decretos citados; la sección 7 repite lo que ya citan los documentos del proyecto. Nada de la sección 7 es una conclusión jurídica.
- No sé cuántos voluntarios de cada grupo se pueden conseguir ni si la cámara del quiosco que se usa en eventos es siempre la misma.
- Las reglas de decisión de §4.5 (doble, 1 en 1.000) son propuestas mías, no un estándar; no están calibradas contra ninguna norma.
- La afirmación de la literatura sobre rendimiento distinto por grupo en modelos de esta familia viene del reporte 08 (hallazgo 17); no revisé las fuentes.
