import gzip

import pytest

from app.crm.importer import gz


def test_plain_passes_through():
    assert gz.maybe_gunzip(b"a,b\n1,2\n") == b"a,b\n1,2\n"


def test_gzip_roundtrip():
    raw = ("Nombre,Ciudad\n" + "Acme,Bogotá\n" * 5000).encode()
    assert gz.maybe_gunzip(gzip.compress(raw)) == raw


def test_corrupt_gzip_is_value_error():
    with pytest.raises(ValueError):
        gz.maybe_gunzip(b"\x1f\x8b" + b"basura que no es gzip")


def test_too_big_is_refused(monkeypatch):
    monkeypatch.setattr(gz, "MAX_UNPACKED", 1000)
    with pytest.raises(ValueError):
        gz.maybe_gunzip(gzip.compress(b"x" * 5000))
