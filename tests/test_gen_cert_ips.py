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


def test_route_metrics_is_wired_so_the_router_cable_does_not_cut_internet():
    ps = lambda n: (ROOT / "deploy/windows" / n).read_text(encoding="utf-8-sig")
    cfg = ps("config.ps1")
    assert "function Update-RouteMetrics" in cfg and "IPv4Connectivity" in cfg and "-InterfaceMetric $mark" in cfg and "-AutomaticMetric Enabled" in cfg          # baja solo la red SIN internet y la devuelve a automático
    assert "Update-RouteMetrics" in ps("updater-service.ps1") and "Update-RouteMetrics" in ps("prereq.ps1") and "fMinimizeConnections" in ps("prereq.ps1")


def test_tls_real_con_verificacion_estricta_de_python(tmp_path):
    """Python 3.13 verifica en modo estricto y rechazaba el certificado («Missing Authority Key Identifier»): un cliente con la autoridad propia debe conectar."""
    import socket
    import ssl
    import threading
    gen_cert.make(tmp_path, "SERVIDOR", ["192.168.1.45"])
    srv = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    srv.load_cert_chain(tmp_path / "server.pem", tmp_path / "server.key")
    lsock = socket.socket()
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(1)
    port = lsock.getsockname()[1]

    def serve():
        conn, _ = lsock.accept()
        try:
            with srv.wrap_socket(conn, server_side=True) as s:
                s.recv(10)
        except ssl.SSLError:
            pass
    t = threading.Thread(target=serve, daemon=True)
    t.start()
    cli = ssl.create_default_context(cafile=str(tmp_path / "ca.pem"))
    assert cli.verify_flags & ssl.VERIFY_X509_STRICT
    with socket.create_connection(("127.0.0.1", port)) as raw, cli.wrap_socket(raw, server_hostname="localhost") as s:
        s.sendall(b"hola")
    t.join(5)
    lsock.close()
    assert not gen_cert.lacks_key_ids(tmp_path / "server.pem")


def test_certificado_viejo_sin_aki_se_marca_para_volver_a_firmar(tmp_path):
    from cryptography import x509 as _x
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    import datetime
    k = ec.generate_private_key(ec.SECP256R1())
    n = _x.Name([_x.NameAttribute(_x.oid.NameOID.COMMON_NAME, "viejo")])
    now = datetime.datetime.now(datetime.timezone.utc)
    c = _x.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key()).serial_number(1).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=5)).sign(k, hashes.SHA256())
    (tmp_path / "server.pem").write_bytes(c.public_bytes(serialization.Encoding.PEM))
    assert gen_cert.lacks_key_ids(tmp_path / "server.pem")
