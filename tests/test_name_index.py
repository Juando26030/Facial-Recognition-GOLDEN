"""Índice de nombres del respaldo «cédula no encontrada → por nombre» (app/name_index.py, 19-nov-2026): mismo resultado que la regla de siempre
(`api._identity_name_matches`: prefijo en ambos sentidos + errores de tipeo), pero sin recorrer a todas las personas en cada escaneo."""
import random

from app import name_index
from app.routers.api import _identity_name_matches

FIRST = "maria jose juan carlos luis ana andres camilo daniela sebastian valentina santiago laura yuliana juliana jhoan sebas".split()
LAST = "gomez rodriguez martinez garcia lopez angarita rojas ramirez ramires munoz muñoz velez vélez".split()


def _typo(w: str, rnd: random.Random) -> str:
    if len(w) < 3:
        return w
    i = rnd.randrange(len(w))
    op = rnd.choice("sdit")
    if op == "s":
        return w[:i] + rnd.choice("abcdefghijklmnopqrstuvwxyz") + w[i + 1:]
    if op == "d":
        return w[:i] + w[i + 1:]
    if op == "i":
        return w[:i] + rnd.choice("aeiou") + w[i:]
    return w[:i] + w[i + 1:i + 2] + w[i:i + 1] + w[i + 2:]


def test_same_result_as_the_original_rule_on_random_names_with_typos():
    rnd = random.Random(11)
    rare = lambda: "".join(rnd.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rnd.randint(2, 10)))  # noqa: E731
    people = []
    for i in range(1500):
        first = " ".join(rnd.choice(FIRST) if rnd.random() > .3 else rare() for _ in range(rnd.choice((1, 2))))
        last = " ".join(rnd.choice(LAST) if rnd.random() > .3 else rare() for _ in range(rnd.choice((1, 2))))
        people.append((str(1000 + i), first.title(), last.upper()))
    people += [("1", "Sebas", "Angarita"), ("2", "Yuliana", "Ramírez"), ("3", None, None), ("4", "", "  ")]
    idx = name_index.NameIndex(people)
    queries = ["JHOAN SEBASTIAN ANGARITA ROJAS", "Juliana Ramirez", "x", "", "a b", "MARÍA JOSÉ GÓMEZ"]
    queries += [" ".join(_typo(w, rnd) for w in f"{p[1]} {p[2]}".split()) for p in rnd.sample(people[:1500], 250)]
    queries += [f"{rnd.choice(FIRST)[:rnd.randint(1, 5)]} {rnd.choice(LAST)}" for _ in range(60)]
    for q in queries:
        want = sorted(p[0] for p in people if _identity_name_matches(f"{p[1] or ''} {p[2] or ''}", q))
        got, total = idx.match(q, limit=10 ** 6)
        assert sorted(r["id"] for r in got) == want and total == len(want), q


def test_results_are_capped_but_the_total_is_reported():
    idx = name_index.NameIndex([(str(i), "Ana", "Gomez") for i in range(120)])
    got, total = idx.match("ANA GOMEZ")
    assert len(got) == name_index.MAX_RESULTS and total == 120
    assert idx.match("   ") == ([], 0)
