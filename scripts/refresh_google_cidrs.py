"""Genera la lista de rangos de INFRAESTRUCTURA de Google que la app quita del final de `X-Forwarded-For` (opción D de docs/15, «IP real del cliente»).

    python scripts/refresh_google_cidrs.py            # descarga goog.json y cloud.json, escribe app/google_infra_cidrs.txt
    python scripts/refresh_google_cidrs.py --print    # solo imprime el valor para la variable XFF_STRIP_CIDRS (coma-separado), sin escribir el archivo
    python scripts/refresh_google_cidrs.py --age      # dice de cuándo es el archivo actual (para el runbook)

Lista = goog.json (todo lo de Google) MENOS cloud.json (rangos que Google Cloud entrega a clientes). Así, los proxies de Google (Firebase Hosting, el frontend de Cloud Run: 66.102.x,
74.125.x, 64.233.x…) se quitan de la cadena, pero una VM o Cloud Shell de un cliente (34.x, 35.x…) sigue contando como un visitante más. Fuentes oficiales:
https://www.gstatic.com/ipranges/goog.json y https://www.gstatic.com/ipranges/cloud.json.
Refrescar cada mes y antes de un evento grande (docs/15); luego commit + despliegue (o `XFF_STRIP_CIDRS` con `--print` para probar sin desplegar código)."""
import ipaddress
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

URLS = ("https://www.gstatic.com/ipranges/goog.json", "https://www.gstatic.com/ipranges/cloud.json")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "google_infra_cidrs.txt")


def fetch(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


def nets(doc: dict) -> list:
    return [ipaddress.ip_network(p.get("ipv4Prefix") or p.get("ipv6Prefix")) for p in doc["prefixes"]]


def subtract(base: list, holes: list) -> list:
    """Cada red de `base` menos las de `holes` (aritmética de rangos con ipaddress), colapsado."""
    out = []
    for net in base:
        parts = [net]
        for hole in holes:
            if hole.version != net.version or not hole.overlaps(net):
                continue
            nxt = []
            for p in parts:
                if not hole.overlaps(p):
                    nxt.append(p)
                elif hole.supernet_of(p):
                    continue                                    # el trozo entero es de clientes
                else:
                    nxt.extend(p.address_exclude(hole))
            parts = nxt
        out.extend(parts)
    return sorted(ipaddress.collapse_addresses([n for n in out if n.version == 4]), key=lambda n: (int(n.network_address), n.prefixlen)) + \
        sorted(ipaddress.collapse_addresses([n for n in out if n.version == 6]), key=lambda n: (int(n.network_address), n.prefixlen))


def build(goog: dict, cloud: dict) -> tuple:
    result = subtract(nets(goog), nets(cloud))
    header = [f"# Rangos de infraestructura de Google (goog.json - cloud.json). Generado {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} por scripts/refresh_google_cidrs.py",
              f"# goog.json creationTime={goog.get('creationTime')} · cloud.json creationTime={cloud.get('creationTime')} · {len(result)} rangos",
              f"# generated: {goog.get('creationTime', '')[:10]}"]
    return header, result


def main(argv: list) -> int:
    if "--age" in argv:
        for line in open(OUT, encoding="utf8"):
            if line.startswith("# generated:"):
                print(line.strip())
        return 0
    header, result = build(fetch(URLS[0]), fetch(URLS[1]))
    if "--print" in argv:
        print(",".join(str(n) for n in result))
        return 0
    with open(OUT, "w", encoding="utf8", newline="\n") as fh:
        fh.write("\n".join(header + [str(n) for n in result]) + "\n")
    print(f"{len(result)} rangos escritos en {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
