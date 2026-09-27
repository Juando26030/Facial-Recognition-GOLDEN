"""Doble del proceso hijo del motor facial para probar el pool de procesos sin dlib (lo importa el proceso hijo por nombre)."""
import os


def warm() -> None:
    return None


child_init = warm


def ping() -> bool:
    return True


def extract(image_array, kwargs: dict):
    if kwargs.get("crash"):
        os._exit(1)                                  # el proceso muere de golpe (como un fallo de dlib)
    return [float(image_array.shape[0]), float(kwargs.get("jitters", 0)), float(os.getpid())]
