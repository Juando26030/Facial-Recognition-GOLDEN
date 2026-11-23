# Firma del instalador de Golden Local

Windows muestra «Windows protegió su PC» (SmartScreen) a todo `.exe` sin firma digital reconocida. La firma exige un **certificado de firma de código** comprado a una autoridad (no se puede crear uno propio que Windows acepte).

## Qué decidir (Juan David)
| Opción | Costo aprox. | Efecto |
|---|---|---|
| Certificado EV (token USB o firma en la nube) | ~300–500 USD/año | SmartScreen confía desde la primera descarga |
| Certificado OV (.pfx) | ~100–250 USD/año | Sale la editorial «Golden Eventos y Logística S.A.S.», pero el aviso desaparece cuando el archivo gana reputación |
| Azure Trusted Signing | ~10 USD/mes | Requiere verificar la empresa (suele pedir antigüedad); sin archivo .pfx |
| Sin firma | 0 | En cada equipo: «Más información» → «Ejecutar de todas formas» |

El instalador ya declara el editor «Golden Eventos y Logística S.A.S.»; falta el certificado.

## Cómo se firma (con un .pfx)
En Cloud Shell, después de construir el instalador:
```
GW_SIGN_PFX=$HOME/certificado.pfx bash deploy/windows/firmar_instalador.sh build/windows/out/GoldenLocal-Setup-<versión>.exe
```
Pide la contraseña a ciegas, firma con SHA-256 y sello de tiempo, verifica y reemplaza el `.exe`. Luego se sube igual que hoy a `.../system/local-installer/`. El certificado nunca va al repo ni al chat.
Con EV en token/HSM el proveedor da su propia herramienta de firma; se firma en un Windows con el token y no con este script.

## Mientras tanto
Los equipos que ya tienen Golden Local instalado se actualizan solos (el actualizador no pasa por SmartScreen); el aviso solo aparece al instalar por primera vez.
