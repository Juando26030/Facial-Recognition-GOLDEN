# Pruebas de carga (Fase 0 de escalabilidad)

Escenarios de [Locust](https://locust.io) contra un servidor **local** con una base de datos **sintética** (`golden_load`): nadie real, ningún encoding real.
**Nunca** contra producción: los scripts se niegan a correr contra un host que no sea local/staging.

## Preparación (una vez)

```bash
pip install locust                       # solo para pruebas de carga
python tests/load/setup_load_db.py       # crea golden_load con 8.000 personas sintéticas, un evento en curso y un formulario abierto
```

`setup_load_db.py` toma `DATABASE_URL` del `.env` y solo cambia el nombre de la base a `golden_load`; se niega a correr si el servidor de base
de datos no es local. Deja `tests/load/.load_env.json` (ignorado por git) con los ids y el usuario/clave de prueba.

## Correr

```bash
# Arranca y apaga el servidor por cada escenario (recomendado: un escenario que deje el servidor colgado no contamina al siguiente)
python tests/load/run_scenarios.py --label antes --spawn --workers 1 --scale 1.0 --duration 45
python tests/load/run_scenarios.py --label despues --spawn --workers 3 --scale 1.0 --duration 45
# Contra un servidor que ya levantaste tú
python tests/load/run_scenarios.py --label prueba --host http://127.0.0.1:5002 --only a,b
```

| Escenario | Qué hace |
|---|---|
| a | 300 personas abren el formulario público y lo envían (~150 envíos/s) |
| b | 200 estaciones escanean cédulas del roster (~57/s) |
| c | 20 estaciones escanean con foto (reconocimiento facial) |
| d | mezcla 60 % formulario / 30 % cédula / 10 % facial, 200 usuarios |
| e | 20 pantallas con el directorio en vivo abierto (8.000 personas) |

`--scale 0.1` corre con el 10 % de usuarios (carga ligera). Cada usuario virtual llega con su propia IP (`X-Forwarded-For`), como en la vida real.
Usa `127.0.0.1`, no `localhost`: en Windows `localhost` prueba primero IPv6 y cada intento tarda ~2 s.

## Fotos del escenario (c) y de `scripts/bench_jitters.py`

Se leen de la carpeta que diga la variable `FOTOS_PRUEBA_DIR` (por defecto `C:\JDRJ\Golden\fotos_prueba`), **fuera del repo**. Si no existe se usa una foto
de dominio público de scikit-image (la astronauta): sirve para medir el costo de detectar y codificar, no la precisión.

## Resultados

Los CSV y la tabla se guardan en `LOAD_RESULTS_DIR` (por defecto `C:\JDRJ\Golden\perf_results`), **fuera del repo**: pueden incluir nombres de fotos.
**Nunca copies fotos, encodings ni resultados con datos de personas dentro del repo** (es público). Verifica con `git status` antes de cada commit.
