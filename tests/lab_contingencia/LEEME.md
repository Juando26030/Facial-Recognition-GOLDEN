# Laboratorio de contingencia

Maneja las pantallas REALES del quiosco (plantillas y JavaScript del repositorio) en Chrome sin pantalla, les corta la «red» y comprueba que todo se guarde en el dispositivo y llegue al
servidor al volver la conexión. No usa base de datos ni FastAPI: `srv.py` hace de servidor con tres personas inventadas. Nada de datos reales.

```bash
python3 tests/lab_contingencia/run.py                       # todos los casos (unos 8 minutos)
python3 tests/lab_contingencia/run.py editar_dato_sin_red   # uno solo
```

Necesita `playwright` (Python), `jinja2` y Google Chrome (`CHROME=/ruta/al/chrome`). No corre en el CI (no hay Chrome): correrlo a mano antes de tocar contingencia.

| Caso | Qué comprueba |
|---|---|
| `editar_dato_sin_red` | El caso que reportó Juan David (25-nov-2026): sin red, Editar, agregar un dato y Guardar. Se guarda en el dispositivo, sobrevive a recargar sin red y llega al servidor |
| `guardar_justo_al_caerse_la_red` | La red se cae y se guarda enseguida (el letrero aún no ha salido): tampoco hay «Error de red» |
| `vaciar_dato_quitar_registro_cambiar_cedula_y_eliminar` | Vaciar un dato, pasar a «No registrado», cambiar la cédula y eliminar; todo llega en orden |
| `registrar_nuevo_sin_red` | Alta sin red en celular; aparece en la lista local y llega al servidor |
| `areas_sin_red` | Entrada, salida y «sin reingresos» en el dispositivo; el servidor recibe los movimientos con su hora real |
| `inventario_sin_red` | Entrega, «no repetir» y llegada al servidor |
| `el_letrero_no_tapa_nada` | En celular, tableta y computador (vertical y horizontal): ningún botón, campo o enlace queda debajo del letrero de contingencia ni del aviso de la bandeja; «Guardar» siempre se puede tocar |

Lo que el laboratorio NO cubre: la impresora, la cámara y el servidor real (reglas de permisos, base de datos). Eso lo cubren las pruebas de `tests/` y la prueba en staging.
