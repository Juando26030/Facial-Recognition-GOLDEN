"""Certificado HTTPS del servidor local y cambios de IP (20-nov-2026). Puras: solo `cryptography`, sin base ni Windows."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("cryptography")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deploy" / "windows"))
import gen_cert  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_new_ip_is_detected_added_and_old_ones_are_kept(tmp_path):
    gen_cert.make(tmp_path, "PC-GOLDEN", ["192.168.1.45"])
    pem = tmp_path / "server.pem"
    assert gen_cert.missing_ips(pem, ["192.168.1.45"]) == []
    assert gen_cert.missing_ips(pem, ["192.168.1.45", "192.168.0.77"]) == ["192.168.0.77"]
    ca_before = (tmp_path / "ca.pem").read_bytes()
    gen_cert.make(tmp_path, "PC-GOLDEN", ["192.168.0.77"])
    assert (tmp_path / "ca.pem").read_bytes() == ca_before          # la autoridad es la misma: los celulares no repiten nada
    assert set(gen_cert.cert_ips(pem)) >= {"127.0.0.1", "192.168.1.45", "192.168.0.77"}
    assert gen_cert.missing_ips(pem, ["192.168.1.45", "192.168.0.77"]) == []          # alternar entre las dos ya no regenera


def test_public_and_garbage_ips_never_enter_the_certificate(tmp_path):
    gen_cert.make(tmp_path, "PC", ["192.168.1.5", "8.8.8.8", "100.64.1.2", "no-es-ip"])
    assert set(gen_cert.cert_ips(tmp_path / "server.pem")) == {"127.0.0.1", "192.168.1.5"}
    assert gen_cert.missing_ips(tmp_path / "server.pem", ["8.8.8.8", "100.64.1.2"]) == []          # no se «falta» lo que no se puede cubrir


def test_missing_cert_or_unreadable_is_empty_not_a_crash(tmp_path):
    assert gen_cert.cert_ips(tmp_path / "no-existe.pem") == []


def test_scripts_wire_the_check_in_all_three_places():
    ps = lambda n: (ROOT / "deploy/windows" / n).read_text(encoding="utf-8-sig")
    assert "function Update-ServerCert" in ps("config.ps1") and "--missing" in ps("config.ps1")
    assert "Update-ServerCert" in ps("run-app.ps1") and "Update-ServerCert" in ps("updater-service.ps1") and "--missing" in ps("install.ps1")
