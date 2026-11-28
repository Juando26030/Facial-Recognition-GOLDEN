"""Créditos de autoría de Orum (28-nov-2026, pedido de Juan David): un pie pequeño en TODAS las páginas HTML, en español e inglés, con el nombre del autor del diseño y el desarrollo.
Se agrega al final de cada respuesta HTML completa (middleware de app/main.py) para no tocar las ~100 plantillas ni depender de que una pantalla incluya un archivo común.
Solo lee/ajusta el HTML que ya se iba a enviar: no toca la base, no escribe nada. Las pantallas de impresión o de proyección (TV, ruleta, escarapela, certificado) lo evitan con el
atributo `data-gw-no-credit` en <body>; además el pie no se imprime (@media print)."""
from __future__ import annotations

AUTHOR = "Juan David Ramírez Juzga"
YEAR = "2026"
MARKER = b"data-gw-credit"
SKIP = b"data-gw-no-credit"

_NAME = AUTHOR.replace("Ramírez Juzga", "Ramírez&nbsp;Juzga")          # el apellido no se parte en dos renglones en celular
_META = f'<meta name="author" content="{AUTHOR}">'.encode()
_FOOTER = (
    '<footer data-gw-credit role="contentinfo" aria-label="Créditos">'
    "<style>[data-gw-credit]{box-sizing:border-box;clear:both;width:100%;margin:0;padding:10px 12px 14px;text-align:center;font:400 11px/1.5 var(--gw-font,system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif);"
    "color:inherit;opacity:.62;overflow-wrap:anywhere}[data-gw-credit] span{display:inline-block;margin:0 .35em}@media (max-width:480px){[data-gw-credit]{font-size:10px;padding:8px 10px 12px}"
    "[data-gw-credit] span{display:block;margin:0}}@media print{[data-gw-credit]{display:none}}</style>"
    f"<span>Orum © {YEAR} · Software diseñado y creado por {_NAME}</span>"
    f"<span>Software designed &amp; built by {_NAME}</span></footer>"
).encode()


def inject(body: bytes) -> bytes:
    """Devuelve el HTML con el meta de autor y el pie de créditos; si no es una página completa (sin </body>), ya lo trae o pide no llevarlo, lo deja igual."""
    if not body or MARKER in body or SKIP in body:
        return body
    low = body.lower()
    end = low.rfind(b"</body>")
    if end < 0:
        return body
    head = low.find(b"</head>")
    out = body[:end] + _FOOTER + body[end:]
    if 0 <= head < end:
        out = out[:head] + _META + out[head:]
    return out
