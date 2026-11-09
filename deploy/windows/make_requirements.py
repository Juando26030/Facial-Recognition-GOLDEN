"""Genera requirements-local.txt a partir de requirements.txt, SIN lo que no corre ni se necesita en un servidor local de Windows (Fase 6: sin reconocimiento facial → nada de dlib ni
face_recognition; gunicorn no existe en Windows, se usa uvicorn). Uso:  python make_requirements.py requirements.txt requirements-local.txt"""
import re
import sys

EXCLUDED = ("dlib", "face_recognition", "face-recognition", "face_recognition_models", "face-recognition-models", "gunicorn")


def filter_lines(lines):
    out = []
    for line in lines:
        name = re.split(r"[\s=<>!~;@\[]", line.strip(), maxsplit=1)[0].lower() if line.strip() and not line.strip().startswith("#") else ""
        if name and name in EXCLUDED:
            continue
        out.append(line.rstrip("\n"))
    return out


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as fh:
        res = filter_lines(fh.readlines())
    with open(dst, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(res) + "\n")
