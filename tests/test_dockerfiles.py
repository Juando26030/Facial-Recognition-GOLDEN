"""Docker no admite comentarios al final de una instrucción: los toma como argumentos (así falló el COPY de la política en el despliegue de staging, 2026-10-06). Los comentarios van en su propia línea."""
import re
from pathlib import Path

import pytest

INSTRUCTION = re.compile(r"^(FROM|RUN|CMD|COPY|ADD|ENV|ARG|EXPOSE|USER|WORKDIR|ENTRYPOINT|HEALTHCHECK|LABEL|VOLUME|SHELL|STOPSIGNAL|ONBUILD)\b", re.I)
FILES = [p for p in [Path("Dockerfile"), *Path("deploy").rglob("Dockerfile*")] if p.name.startswith("Dockerfile") and not p.name.endswith("ignore")]


def _offenders(path: Path):
    out, continuing = [], False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        starts = bool(INSTRUCTION.match(stripped))
        if (starts or continuing) and re.search(r"\s#", stripped) and not stripped.startswith("#"):
            # un «#» dentro de comillas o de una URL (p. ej. https://x/#y) no es comentario: se ignora lo que está entre comillas
            without_quotes = re.sub(r'"[^"]*"|\'[^\']*\'', "", stripped)
            if re.search(r"\s#", without_quotes):
                out.append((n, stripped[:90]))
        continuing = (starts or continuing) and stripped.endswith("\\")
    return out


@pytest.mark.parametrize("path", FILES, ids=str)
def test_no_dockerfile_has_a_comment_at_the_end_of_an_instruction(path):
    assert _offenders(path) == [], f"{path}: comentario al final de una instrucción (muévelo a su propia línea)"


def test_the_ratified_policy_copy_and_the_dockerignore_exception_are_consistent():
    docker = Path("Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^COPY --chown=golden:golden docs/legal/POLITICA_v1\.1\.md \./docs/legal/POLITICA_v1\.1\.md$", docker, re.M)
    ignore = Path(".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "!docs/legal/POLITICA_v1.1.md" in ignore and Path("docs/legal/POLITICA_v1.1.md").exists()
