"""Archivos VM → Cloud Storage con MD5 (scripts/migrate_files_to_gcs.py), contra el emulador de Cloud Storage."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("STORAGE_EMULATOR_HOST"), reason="necesita el emulador de Cloud Storage (fsouza/fake-gcs-server)")


def test_files_are_copied_with_md5_resumable_and_readable_by_the_app(tmp_path):
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import storage as gcs

    from app.storage import GcsStorage
    from scripts import migrate_files_to_gcs as mig

    data = tmp_path / "data"
    (data / "acme" / "known_people").mkdir(parents=True)
    (data / "acme" / "known_people" / "1001.jpg").write_bytes(b"GWENC1:foto-cifrada")
    (data / "acme" / "signatures").mkdir()
    (data / "acme" / "signatures" / "1_2_firma.png").write_bytes(os.urandom(5000))
    (data / "uploads" / "x").mkdir(parents=True)
    (data / "uploads" / "x" / "temporal.zip").write_bytes(b"no se migra")
    (data / "acme" / "a.part").write_bytes(b"a medio escribir")

    client = gcs.Client(project="test", credentials=AnonymousCredentials())
    name = f"golden-mig-{os.urandom(4).hex()}"
    client.create_bucket(name)
    args = ["--source", str(data), "--bucket", name, "--prefix", "app"]

    assert mig.main(args, client=client) == 0
    blobs = sorted(b.name for b in client.list_blobs(name))
    assert blobs == ["app/acme/known_people/1001.jpg", "app/acme/signatures/1_2_firma.png"]
    assert GcsStorage(name, "app", client=client).get("acme/known_people/1001.jpg") == b"GWENC1:foto-cifrada"   # la app lo lee con su clave

    assert mig.main(args, client=client) == 0                                   # repetir no vuelve a subir nada
    client.bucket(name).blob("app/acme/known_people/1001.jpg").upload_from_string(b"otro contenido")
    assert mig.main(args + ["--verify-only"], client=client) == 1               # distinto en el bucket → se detecta
    assert mig.main(args, client=client) == 0                                   # y una pasada normal lo corrige
