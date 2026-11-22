# Cómo contribuir a GoldenWeb 2.0

Guía corta para cualquier persona (o agente) que toque este repositorio. Las reglas técnicas del código viven en
[`CLAUDE.md`](CLAUDE.md); las decisiones del dueño, en [`docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md`](docs/REGLAS_INAMOVIBLES_Y_DECISIONES.md).
Si algo de aquí choca con esos dos, mandan ellos.

## 1. Lo que nunca se hace
- Nada a `main`, ningún merge, ningún despliegue y ninguna migración en producción sin autorización explícita de Juan David
  para ESA acción y ESE commit.
- Nada de secretos (solo nombres de variables) ni de datos personales reales (cédulas, nombres, fotos, vectores) en archivos,
  commits, logs, capturas o reportes. El repositorio es público.
- No se tocan `docs/IMPRESION_PARAMETROS_INAMOVIBLES.md` ni `app/legal_texts_data.py` sin orden escrita.
- No se borran ramas ni recursos: se listan y se pide confirmación.

## 2. Ramas
| Prefijo | Para qué | CI |
|---|---|---|
| `feat/<tema>` | Funcionalidad nueva o cambio de producto. Una pieza = una rama. | Suite completa (`ci.yml`) en cada push |
| `fix/<tema>` | Corrección que no es urgente. | Suite completa |
| `hotfix/<tema>-<fecha>` | Corrección urgente sobre lo que corre en producción. | Suite completa |
| `diag/<tema>` | Trabajo en curso que todavía no debe gastar minutos de GitHub (solo `diag.yml`, corto). Antes de pedir la corrida final se pasa a `feat/`. | Solo diagnóstico |
| `docs/<tema>` | Solo documentación. | Suite completa (barata: casi todo es texto) |
| `saas/<tema>` | Trabajo de la línea SaaS (revisión integral, multiempresa). | Suite completa |

- Las ramas se cortan de la **última rama integrada** (hoy: la que corre en producción; ver «Versión desplegada» en `/sistema`),
  no de `main` mientras `main` esté atrasado.
- Los nombres van en español, en minúsculas, con guiones: `feat/inventario-base`, `hotfix/subida-formulario-2026-11-21`.
- **Marcadores de despliegue:** lo que se desplegó a staging o producción se marca con una **etiqueta** (`git tag prod/2026-11-20-llaves-escaner <sha>`),
  no con una rama `prod/…` o `staging/…`. Las ramas `prod/*` y `staging/*` que existen hoy son históricas y se van reemplazando por etiquetas.
- Una rama termina cuando su contenido está integrado y desplegado: se borra (con confirmación), y queda la etiqueta y el CHANGELOG.

## 3. Commits
- Un commit + push por pieza terminada, con sus pruebas pasando. No se acumulan diez cambios distintos en un commit.
- Primera línea en español, **máximo 72 caracteres**, con el área al principio y dos puntos: `Registro: cédula, nombres y apellidos siempre visibles`.
  Áreas usadas: `Registro`, `Formularios`, `Impresión`, `Inventario`, `Almacén`, `CRM`, `Legalizaciones`, `Gastos`, `Servidor local`, `Carga`, `Docs`, `Pruebas`, `Seguridad`, `Infra`.
- El **porqué** y el detalle van en el cuerpo del commit (líneas de 100 caracteres o menos), no en la primera línea. Si cierra una decisión del dueño, se cita
  la fecha («decisión del 21-nov-2026»).
- Los commits terminan con las líneas de atribución que entregue la sesión (`Co-Authored-By`, `Claude-Session`), si las hay.
- Nunca `git push --force` sobre una rama que alguien más pudo haber bajado.

## 4. Antes de empujar (checklist mínimo)
```bash
ruff check .                                                    # debe decir «All checks passed!»
python3 -m pytest --noconftest -q tests/<archivo_nuevo>.py      # pruebas puras y de texto, sin base
python -m pytest -q                                             # suite completa: necesita Postgres local (crea golden_test sola)
npm ci && for f in tests/js/*_check.js; do node "$f" || break; done   # pruebas de JS (17 usan jsdom)
```
- Si el cambio toca el modelo de datos: migración de Alembic escrita a mano, id ≤ 32 caracteres, **una sola cabeza** (`alembic heads`).
- Si el cambio toca una pantalla: barrido ancho por ancho (320 a 3440 px) sin desplazamiento horizontal; solo tokens `--gw-*`.
- Si el cambio toca impresión, textos legales, biometría o consentimiento: se para y se pregunta.

## 5. Pruebas: qué tipo escribir
1. **Prueba de comportamiento** primero: llama al endpoint con `client` (o a la función pura) y comprueba el resultado. Es la que atrapa errores reales.
2. **Prueba pura** para la lógica sin base (`app/formlib.py`, `app/inv_assign_core.py`, …): rápida y corre en cualquier entorno.
3. **Prueba de texto** (lee el código fuente y busca una frase) **solo** para fijar una decisión que no se puede probar de otra forma
   (parámetros de impresión, trinquete de CSP, huella de archivos congelados). No se usa para comprobar que «un botón existe»: eso se
   rompe con cualquier cambio de redacción y no detecta que el botón no funcione.
4. Nombres que digan qué se garantiza: `test_reload_never_duplicates_delivered_rows`, no `test_1`.

## 6. Definición de «hecho» (una pieza está terminada cuando)
1. Código en su rama, `ruff` limpio y pruebas en verde (las puras localmente; la suite completa en GitHub al final, cuando el dueño aprobó staging).
2. Migración incluida y encadenada si cambió el modelo.
3. Probada en **staging** por Juan David (él prueba; Claude lee `/sistema` y las pantallas).
4. Documentada: entrada en [`CHANGELOG.md`](CHANGELOG.md) (qué cambió, para quién, migración), `CLAUDE.md` si cambió la arquitectura o una regla,
   y el documento técnico de la pieza en `docs/`.
5. Dicho por escrito **qué NO se pudo comprobar** (nunca se afirma lo que no se vio).
6. Desplegada a producción solo con el «sí» del dueño para ese commit, con respaldo (rama de Neon) antes y verificación en `/sistema` después.

## 7. Pull requests
Usa la plantilla de [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md). Un PR = una pieza. El título sigue la regla de la primera
línea del commit. Las corridas completas de GitHub se piden **una sola vez**, al final, cuando el dueño aprobó la versión de staging.

## 8. Documentación
- `docs/` es para el equipo técnico; el índice de entrada es [`docs/00_README.md`](docs/00_README.md).
- Un documento nuevo lleva fecha en la primera línea y dice qué estado tiene (diseño / en staging / en producción).
- Cuando una decisión cambia, se actualiza el documento vivo (no se crea un «ESTADO_ANTERIOR» encima): el historial queda en git y en el CHANGELOG.
