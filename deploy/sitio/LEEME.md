# deploy/sitio — sitio web corporativo (golden-eventos.com)

Todo lo necesario para publicar el sitio web (repositorio `Juando26030/golden-sitio-web`, Astro, estático) en un sitio de Firebase Hosting
**aparte** del de la plataforma. Guía completa para Juan David y para el bot del sitio: [`docs/26_SITIO_WEB_MONTAJE.md`](../../docs/26_SITIO_WEB_MONTAJE.md).

| Archivo | Qué es |
|---|---|
| `VERSION` | Commit completo del sitio que está aprobado para producción. Cambiarlo = decidir qué se publica. |
| `parche/*.patch` | Cambios que el sitio necesita y aún no están en su rama (SEO, canónica, sitemap, datos estructurados, páginas legales en borrador…). Meta: que quede vacío. |
| `firebase.json` | Configuración de Hosting del sitio: caché, cabeceras, direcciones limpias, 404. |
| `deploy_sitio.sh` | Lo corre Juan David en Cloud Shell: trae el sitio en `VERSION`, aplica el parche, compila, comprueba `dist/` y publica. |
| `rehacer_parche.sh` | Comprueba o regenera el parche cuando el sitio cambió. |
| `comparar.py` | Compara dos compilaciones del sitio (capturas en 9 anchos) para demostrar que se ven igual. |

Ningún agente ejecuta esto contra la nube: lo corre Juan David. El flujo de GitHub `.github/workflows/sitio-deploy.yml` hace lo mismo, a mano y con `PUBLICAR`.
