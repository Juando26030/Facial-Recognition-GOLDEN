"""Un evento descargado a un servidor local queda de SOLO LECTURA en la nube: solo ese servidor (token del nodo) escribe (un solo escritor)."""
from types import SimpleNamespace as NS
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import event_lease


def _evento(nodo=None):
    return NS(local_node_name=nodo, local_last_upload_at=None)


def test_nube_no_escribe_en_evento_arrendado():
    with pytest.raises(HTTPException) as e:
        event_lease.assert_writable_by(_evento("Portatil 1"), NS(via_node_name=None))
    assert e.value.status_code == 423


def test_el_propio_nodo_si_escribe_y_un_evento_libre_tambien():
    event_lease.assert_writable_by(_evento("Portatil 1"), NS(via_node_name="Portatil 1"))
    event_lease.assert_writable_by(_evento(None), NS())
    with pytest.raises(HTTPException):
        event_lease.assert_writable_by(_evento("Portatil 1"), NS(via_node_name="Otro"))


def test_las_rutas_de_escritura_de_personas_llevan_el_candado():
    src = (Path(__file__).resolve().parent.parent / "app" / "routers" / "api.py").read_text(encoding="utf-8")
    assert src.count("event_lease.assert_writable_by(") >= 12          # edición, cédula, borrado, carga masiva, estado y las dos rutas de acreditar con persona de prueba
