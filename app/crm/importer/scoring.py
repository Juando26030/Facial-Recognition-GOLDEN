"""Emparejamiento de clientes de la plataforma (hexadecimal) con cuentas de SuiteCRM. Usa la MISMA `normalize` que la búsqueda del CRM.
seguro: puntaje ≥ 95, margen ≥ 10 sobre el segundo mejor y la pareja es mutua; dudoso: 70–94 (o seguro sin margen/mutualidad); sin_pareja: < 70."""
import re
from difflib import SequenceMatcher
from typing import Optional

from app.crm import normalize

SAFE_MIN, DOUBT_MIN, MARGIN = 95, 70, 10
_NOISE = {"sas", "s a s", "s.a.s", "ltda", "sa", "s a", "ltd", "inc", "cia", "y cia", "&", "de", "la", "el", "los", "las", "colombia"}


def company_key(name: Optional[str]) -> str:
    """Nombre de empresa sin tildes ni formas societarias, para comparar."""
    s = re.sub(r"[^\w\s]", " ", normalize(name))
    s = re.sub(r"\b(s\s?a\s?s|ltda|s\s?a|ltd|inc|cia|y\s?cia)\b", " ", s)
    return " ".join(w for w in s.split() if w not in _NOISE)


def score(a: Optional[str], b: Optional[str]) -> int:
    ka, kb = company_key(a), company_key(b)
    if not ka or not kb:
        return 0
    if ka == kb:
        return 100
    ratio = SequenceMatcher(None, ka, kb).ratio()
    ta, tb = set(ka.split()), set(kb.split())
    jacc = len(ta & tb) / len(ta | tb)
    return int(round(100 * max(ratio * 0.9 + jacc * 0.1, jacc * 0.9)))


def pair_all(left: list, right: list) -> list:
    """`left`: [(id, nombre)] de la plataforma; `right`: [(id, nombre)] de SuiteCRM. Devuelve [(left_id, right_id|None, puntaje, bucket)] para cada elemento de `left`."""
    best_for_right = {}
    scored = {}
    for lid, lname in left:
        ranked = sorted(((score(lname, rname), rid) for rid, rname in right), reverse=True)
        scored[lid] = ranked
        for s, rid in ranked[:1]:
            if s > best_for_right.get(rid, (-1, None))[0]:
                best_for_right[rid] = (s, lid)
    out = []
    for lid, _ in left:
        ranked = scored[lid]
        if not ranked or ranked[0][0] < DOUBT_MIN:
            out.append((lid, None, ranked[0][0] if ranked else 0, "sin_pareja"))
            continue
        top, rid = ranked[0]
        second = ranked[1][0] if len(ranked) > 1 else 0
        mutual = best_for_right.get(rid, (0, None))[1] == lid
        bucket = "seguro" if top >= SAFE_MIN and top - second >= MARGIN and mutual else "dudoso"
        out.append((lid, rid, top, bucket))
    return out
