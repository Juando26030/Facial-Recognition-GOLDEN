# Ratificación de la Política de Privacidad v1.1

| Dato | Valor |
|---|---|
| Documento ratificado | `docs/legal/POLITICA_v1.1.md` (rama `producto/legal-piloto`) |
| Fecha de la ratificación | 6 de octubre de 2026 |
| Quién ratifica | La abogada auditora de la empresa, T.P. 284.912 (nombre completo: completar por Juan David) |
| SHA-256 del archivo ratificado | `d0afc7d95083b62115ce001abeb1ab8e86925e35a14d80011e06bf75e253c844` (guardado también en `docs/legal/POLITICA_v1.1.md.sha256`) |
| Alcance | Política de Privacidad y Tratamiento de Datos Personales, versión 1.1, tal como está en el archivo con ese hash. Autorizada su publicación en app.golden-eventos.com/privacidad. |
| Sección 8 (modo de contingencia sin conexión) | Queda como está, sin cambios. |
| Compuertas levantadas | Las tres que condicionaban la constancia: (1) purga de la cola local a los 7 días, (2) restricción del pre-cálculo de vectores (solo con anexo firmado) y (3) prohibición de captura biométrica a menores de edad. (Confirmar con la auditora que son esas tres.) |

## Reglas

- El archivo `POLITICA_v1.1.md` y su `.sha256` **no se editan**: cualquier cambio rompe la ratificación y exige hash nuevo y nueva ratificación. Una prueba automática (`tests/test_policy_hash.py`) falla si el archivo cambia.
- La página pública solo muestra la política si el archivo coincide con ese hash (`app/policy_v11.py`); si no coincide, cae a la versión 1.0.
- Al mostrarla, la página omite el párrafo de estado de borrador y las etiquetas «(texto de la auditora)», y agrega aparte la leyenda «Ratificada el 6 de octubre de 2026 · SHA-256 …». El archivo no se modifica.

## Versiones y activación

- **v1.1 (vigente):** se activa con `POLICY_VERSION=1.1`. El despliegue de **staging** ya la activa (`deploy/gcp/deploy.sh`). En **producción** NO se activa todavía (aún no existe): el día del corte se agrega `POLICY_VERSION: "1.1"` al entorno de producción.
- **v1.0 (histórica):** sigue disponible en `/privacidad/v1.0`, con su constancia del 5 de octubre de 2026.
