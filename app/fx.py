"""Tasas de cambio SOLO DE REFERENCIA para mostrar el precio de un formulario en USD o EUR (Sprint 5, campo «Pago»).
Wompi cobra únicamente en pesos colombianos (COP) y el dinero entra a Golden en COP: estas tasas nunca se usan para
cobrar, solo para que quien mira el precio se ubique en su moneda. Fuente pública sin llave (exchangerate-api.com,
`open.er-api.com`, se actualiza una vez al día; sus términos piden atribución, que la página pública muestra). Se guarda en
memoria 6 h; si la fuente falla se sigue usando la última tasa buena hasta 48 h y, pasado eso, se oculta el selector."""
import json
import time
import urllib.error
import urllib.request
from typing import Optional

URL = "https://open.er-api.com/v6/latest/COP"
CURRENCIES = ("USD", "EUR")
FRESH_FOR, STALE_FOR = 6 * 3600, 48 * 3600
_cache = {"at": 0.0, "data": None}


def _fetch() -> Optional[dict]:
    try:
        with urllib.request.urlopen(urllib.request.Request(URL, headers={"Accept": "application/json"}), timeout=6) as res:
            raw = json.loads(res.read().decode())
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return None
    rates = raw.get("rates") or {}
    if raw.get("result") != "success" or not all(isinstance(rates.get(c), (int, float)) and rates[c] > 0 for c in CURRENCIES):
        return None
    return {"base": "COP", "rates": {c: rates[c] for c in CURRENCIES}, "as_of": str(raw.get("time_last_update_utc") or "")[:16], "source": "exchangerate-api.com"}


def get_rates() -> dict:
    """{"base": "COP", "rates": {"USD": pesos→dólares, "EUR": ...}, "as_of", "source"} o {"rates": {}} si no hay tasa confiable."""
    age = time.time() - _cache["at"]
    if _cache["data"] is None or age > FRESH_FOR:
        fresh = _fetch()
        if fresh:
            _cache.update(at=time.time(), data=fresh)
        elif _cache["data"] is None or age > STALE_FOR:
            _cache.update(at=0.0, data=None)
    return _cache["data"] or {"base": "COP", "rates": {}, "as_of": "", "source": ""}
