"""Proceso hijo del reconocimiento facial (ver app/faces.py). dlib mantiene el GIL de Python durante todo el cálculo de un encoding (~0,25 s por jitter): ejecutarlo en un
HILO del proceso web congela a los demás hilos (cédulas, formularios...) mientras dure. Por eso el cálculo corre en procesos aparte, y el proceso web solo espera el
resultado (sin retener el GIL). Este módulo es lo único que el hijo importa: nunca carga la aplicación completa."""
import os
import sys
import threading
import time
from typing import Optional


def _parent_alive(parent_pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, parent_pid)          # SYNCHRONIZE
        if not handle:
            return False
        alive = ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x102              # WAIT_TIMEOUT = sigue vivo
        ctypes.windll.kernel32.CloseHandle(handle)
        return alive
    return os.getppid() == parent_pid


def _exit_with_parent() -> None:
    """Si el proceso web muere de golpe (SIGKILL, apagado forzado), el hijo no debe quedar huérfano con ~150 MB de modelos en memoria."""
    parent = os.getppid()

    def watch() -> None:
        while _parent_alive(parent):
            time.sleep(3)
        os._exit(0)

    threading.Thread(target=watch, daemon=True, name="face-parent-watch").start()


def warm() -> None:
    """Carga dlib y sus modelos para que el primer escaneo no pague esa carga."""
    from app.biometrics import _fr
    _fr()


def child_init() -> None:
    """Se ejecuta una vez al crear cada proceso hijo del pool."""
    _exit_with_parent()
    warm()


def extract(image_array, kwargs: dict) -> Optional[list]:
    from app.biometrics import BiometricEngine
    return BiometricEngine.extract_encoding(image_array, **kwargs)


def ping() -> bool:
    return True
