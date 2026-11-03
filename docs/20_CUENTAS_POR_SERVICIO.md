# 20 · Una cuenta de servicio por servicio de Cloud Run (0C, hallazgo E8)

**Estado:** preparado en el código, **apagado por defecto**. No se creó nada en la nube. Lo ejecuta Juan David, primero en staging.

## El problema
Los tres servicios (`web`, `publico`, `biometria`) corren con la misma cuenta (`golden-app[-staging]`) y reciben **todos** los secretos (`APP_SECRETS` en `deploy/gcp/config.sh`). `publico` es el que está abierto a internet (formularios, pagos, aceptación, escarapela digital): si alguien lograra ejecutar código en él, tendría también las credenciales de correo de Microsoft y la llave privada de Wompi (reembolsos), que ese servicio no usa.

## Qué cambia (solo con `SPLIT_SERVICE_ACCOUNTS=1`)
| Servicio | Cuenta | Secretos que recibe |
|---|---|---|
| `golden-web` | `golden-svc-web[-staging]` | todos (panel, cobros y reembolsos, correos) |
| `golden-publico` | `golden-svc-publico[-staging]` | base, `SECRET_KEY`, llave de rostros, `OPS_TOKEN` y las claves públicas/de firma de eventos de Wompi (producción y sandbox). **Sin** Microsoft/correo ni llave privada de Wompi |
| `golden-biometria` | `golden-svc-biometria[-staging]` | base, `SECRET_KEY`, llave de rostros, `OPS_TOKEN`. **Sin** Microsoft ni nada de Wompi |
| Job de carga masiva | `golden-app[-staging]` (sin cambios) | todos |
| Jobs de operaciones y migraciones | `golden-ops[-staging]` (sin cambios) | los de siempre |

Permisos de cada cuenta nueva (los crea `bootstrap.sh`): firmar sus propias URLs de subida, actuar como `golden-invoker`, ser usada por la cuenta de despliegue, `objectAdmin` en el bucket de la app, encolar en `golden-jobs` (los tres) y en `golden-faces` (`web` y `biometria`), lanzar los Jobs de carga masiva y de operaciones (`web` y `biometria`), y listar respaldos (solo `web`). La definición (qué secretos por servicio) está en `config.sh`: `SECRETS_WEB`, `SECRETS_PUBLICO`, `SECRETS_BIOMETRIA`.

Con `SPLIT_SERVICE_ACCOUNTS` vacío o `0` **no cambia nada**: `service_sa` devuelve la cuenta de siempre y `service_secrets` la lista completa. Los scripts y el despliegue actual quedan idénticos.

## Pasos manuales (los corre Juan David, en este orden, primero staging)
Todo es idempotente. No se hace nada en producción sin tu autorización explícita para ESA acción.

1. **Crear cuentas y permisos** (no mueve ningún servicio):
   ```bash
   SPLIT_SERVICE_ACCOUNTS=1 bash deploy/gcp/bootstrap.sh staging
   ```
   *Debe verse:* `golden-svc-web-staging`, `golden-svc-publico-staging` y `golden-svc-biometria-staging` en `gcloud iam service-accounts list`. Los servicios siguen con `golden-app-staging`.
2. **Habilitar el interruptor en el despliegue.** En GitHub, variable del entorno `staging` → `SPLIT_SERVICE_ACCOUNTS=1`, y una línea nueva en `.github/workflows/cloudrun-deploy.yml`, bloque `env:` (no se agregó desde aquí porque modificar flujos de trabajo requiere tu permiso):
   ```yaml
         SPLIT_SERVICE_ACCOUNTS: ${{ vars.SPLIT_SERVICE_ACCOUNTS }}
   ```
   (vacía = apagado). A mano, sin CI: `SPLIT_SERVICE_ACCOUNTS=1 bash deploy/gcp/deploy.sh staging <imagen>`.
3. **Desplegar staging y probar:** `/health` y `/ready` de los tres servicios, un envío de formulario con pago de prueba (Wompi sandbox), una aceptación (`/aceptar`), un reconocimiento, una carga masiva y un cambio de estado de evento (precalentamiento). Si un servicio falla al arrancar por un secreto que sí usa, agrégalo a su lista en `config.sh` y vuelve a desplegar (el log de Cloud Run dice qué variable falta).
4. **Retirar lo que sobra** (solo cuando staging funcione con las cuentas nuevas): los permisos que `golden-app[-staging]` tenía para los servicios se quedan porque el Job de carga masiva los necesita; lo que cambia es que ya ningún servicio corre con esa identidad. Si quieres además que `golden-app` deje de leer `azure-*`, `graph-sender` y `wompi-private-key`, hay que separar también el Job de carga masiva (no se hizo: ese Job no manda correos ni cobra, pero hoy comparte la lista; queda como mejora).
5. **Producción:** el mismo orden (`SPLIT_SERVICE_ACCOUNTS=1 bash deploy/gcp/bootstrap.sh production`, luego variable del entorno `production` y despliegue en su ventana, con la receta habitual de punto de retorno).

## Vuelta atrás
Quitar la variable `SPLIT_SERVICE_ACCOUNTS` (o ponerla en `0`) y volver a desplegar: los servicios regresan a `golden-app` con todos sus secretos. Las cuentas nuevas pueden quedarse sin uso o borrarse (`gcloud iam service-accounts delete`).

## Qué no cubre
- Los tres servicios siguen siendo UNA imagen con el mismo código; la separación es de identidad y de secretos, no de contenido.
- `OPS_TOKEN`, `SECRET_KEY`, la llave de rostros y la base siguen estando en los tres (los exige el arranque de la app).
- Separar la base en roles distintos por servicio (`golden_app` es uno solo) es otro trabajo (Fase 3, matriz de permisos).
