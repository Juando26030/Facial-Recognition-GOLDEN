"""Fase 9-B: copia semanal cifrada a OneDrive con Microsoft Graph SIMULADO (sin red)."""
import io
import json
import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app import offsite_copy as oc

KEY = Fernet.generate_key().decode()


class FakeBlob:
    def __init__(self, name, data=b"", updated=None, store=None):
        self.name, self.data, self.updated, self.store = name, data, updated or datetime(2026, 11, 8, 3), store

    @property
    def size(self):
        return len(self.data)

    def open(self, mode="rb"):
        return io.BytesIO(self.data)

    def exists(self):
        return self.name in self.store

    def download_as_text(self):
        return self.store[self.name]

    def upload_from_string(self, txt, content_type=None):
        self.store[self.name] = txt


class FakeBucket:
    def __init__(self, backups=()):
        self.backups, self.store = list(backups), {}

    def list_blobs(self, prefix=""):
        return [b for b in self.backups if b.name.startswith(prefix)]

    def blob(self, name):
        return FakeBlob(name, store=self.store)


class FakeGraph:
    """Servidor de Graph en memoria: token, PUT simple, sesión de carga con Content-Range, listado y borrado."""

    def __init__(self, existing=(), fail_puts=0):
        self.files = {n: b"x" for n in existing}      # nombre -> contenido
        self.calls, self.session, self.fail_puts = [], None, fail_puts

    def http(self, method, url, headers, data):
        self.calls.append((method, url.split("?")[0]))
        if url.endswith("/oauth2/v2.0/token"):
            assert b"client_credentials" in data
            return 200, json.dumps({"access_token": "T"}).encode(), {}
        if "uploadsession-fake" in url:
            assert "Authorization" not in headers                         # la URL de sesión va SIN token
            rng = headers["Content-Range"]
            a, rest = rng[len("bytes "):].split("-")
            b, total = rest.split("/")
            a, b, total = int(a), int(b), int(total)
            assert a == self.session["pos"] and len(data) == b - a + 1
            if b + 1 < total:
                assert len(data) % (320 * 1024) == 0                     # trozos intermedios: múltiplos de 320 KiB
            self.session["buf"] += data
            self.session["pos"] = b + 1
            if b + 1 == total:
                self.files[self.session["name"]] = self.session["buf"]
                return 201, b"{}", {}
            return 202, b"{}", {}
        if method == "POST" and url.endswith(":/createUploadSession"):
            self.session = {"name": _name(url), "pos": 0, "buf": b""}
            return 200, json.dumps({"uploadUrl": "https://up.example/uploadsession-fake"}).encode(), {}
        if method == "PUT" and url.endswith(":/content"):
            if self.fail_puts:
                self.fail_puts -= 1
                return 503, b"{}", {"Retry-After": "0"}
            self.files[_name(url)] = data
            return 201, b"{}", {}
        if method == "GET" and "/children" in url:
            return 200, json.dumps({"value": [{"id": f"id-{n}", "name": n} for n in self.files] + [{"id": "carpeta", "name": "golden_db_sub.gwbk", "folder": {}}, {"id": "otro", "name": "foto.jpg"}]}).encode(), {}
        if method == "DELETE":
            iid = url.rsplit("/", 1)[1]
            self.files.pop(iid[3:], None)
            return 204, b"", {}
        raise AssertionError(f"llamada inesperada {method} {url}")


def _name(url):
    from urllib.parse import unquote
    return unquote(url.split("/root:/")[1].split(":")[0]).split("/")[-1]


@pytest.fixture
def cfg(monkeypatch):
    for k, v in {"ONEDRIVE_TENANT_ID": "t", "ONEDRIVE_CLIENT_ID": "c", "ONEDRIVE_CLIENT_SECRET": "s", "ONEDRIVE_DRIVE_USER": "u@empresa.com",
                 "ONEDRIVE_FOLDER": "Respaldos GoldenWeb", "BACKUP_COPY_ENCRYPTION_KEY": KEY, "OFFSITE_KEEP_WEEKS": "3"}.items():
        monkeypatch.setenv(k, v)


def _graph(**kw):
    g = FakeGraph(**kw)
    return g, oc.GraphClient(http=g.http, sleep=lambda s: None)


# ------------------------------------------------------------------ cifrado
@pytest.mark.parametrize("n", [0, 1, 100, 4096])
def test_encrypt_roundtrip_and_exact_size(n):
    data = os.urandom(n)
    enc = b"".join(oc.encrypt_stream(io.BytesIO(data), KEY, chunk=1000))
    assert b"".join(oc.decrypt_stream(io.BytesIO(enc), KEY)) == data
    assert len(enc) == oc.encrypted_size(n, chunk=1000)


def test_encrypt_exact_chunk_multiple_marks_last_correctly():
    data = os.urandom(3000)
    enc = b"".join(oc.encrypt_stream(io.BytesIO(data), KEY, chunk=1000))
    assert len(enc) == oc.encrypted_size(3000, chunk=1000)
    assert b"".join(oc.decrypt_stream(io.BytesIO(enc), KEY)) == data


def test_decrypt_detects_truncation_wrong_key_and_reorder():
    data = os.urandom(3500)
    enc = b"".join(oc.encrypt_stream(io.BytesIO(data), KEY, chunk=1000))
    with pytest.raises(ValueError):
        list(oc.decrypt_stream(io.BytesIO(enc[:-50]), KEY))
    with pytest.raises(ValueError):
        list(oc.decrypt_stream(io.BytesIO(enc), Fernet.generate_key().decode()))
    # quitar el último trozo entero (queda bien formado pero sin marca «último»)
    pos, parts = len(oc.MAGIC), []
    while pos < len(enc):
        ln = int.from_bytes(enc[pos:pos + 4], "big")
        parts.append(enc[pos:pos + 4 + ln])
        pos += 4 + ln
    with pytest.raises(ValueError):
        list(oc.decrypt_stream(io.BytesIO(oc.MAGIC + b"".join(parts[:-1])), KEY))
    with pytest.raises(ValueError):
        list(oc.decrypt_stream(io.BytesIO(oc.MAGIC + parts[1] + parts[0] + b"".join(parts[2:])), KEY))


def test_encrypted_file_does_not_contain_plain_text():
    enc = b"".join(oc.encrypt_stream(io.BytesIO(b"CREATE TABLE secreto"), KEY))
    assert b"secreto" not in enc


# ------------------------------------------------------------------ ejecución
def test_not_configured_does_nothing(monkeypatch):
    for k in oc.REQUIRED:
        monkeypatch.delenv(k, raising=False)
    assert oc.run(bucket=FakeBucket()) == "copia semanal no configurada"


def test_small_backup_uses_simple_put_and_state(cfg):
    b = FakeBucket([FakeBlob("db/daily/2026/11/golden_db_20261108_0300.sql.gz", b"hola" * 10)])
    g, client = _graph()
    now = datetime(2026, 11, 8, 12, 0)                                    # 7 a. m. hora Bogotá
    msg = oc.run(now=now, bucket=b, graph=client)
    assert "golden_db_20261108_0300.gwbk" in msg
    stored = g.files["golden_db_20261108_0300.gwbk"]
    assert b"".join(oc.decrypt_stream(io.BytesIO(stored), KEY)) == b"hola" * 10
    st = json.loads(b.store[oc.STATE_KEY])
    assert st["last_status"] == "ok" and st["last_ok_at"] == "2026-11-08T12:00:00Z" and st["history"][-1]["ok"] is True
    assert "hola" not in json.dumps(st)


def test_large_backup_uses_upload_session(cfg, monkeypatch):
    monkeypatch.setattr(oc, "SMALL_LIMIT", 1000)
    monkeypatch.setattr(oc, "SESSION_CHUNK", 320 * 1024)
    data = os.urandom(900 * 1024)
    b = FakeBucket([FakeBlob("db/hourly/2026/11/golden_db_20261108_0900.sql.gz", data)])
    g, client = _graph()
    oc.run(now=datetime(2026, 11, 8, 15), bucket=b, graph=client)
    assert any(c[1].endswith(":/createUploadSession") for c in g.calls)
    assert b"".join(oc.decrypt_stream(io.BytesIO(g.files["golden_db_20261108_0900.gwbk"]), KEY)) == data


def test_retention_deletes_only_old_golden_copies(cfg):
    old = [f"golden_db_2026100{i}_0300.gwbk" for i in range(1, 6)]
    b = FakeBucket([FakeBlob("db/daily/x/golden_db_20261108_0300.sql.gz", b"d")])
    g, client = _graph(existing=old)
    msg = oc.run(now=datetime(2026, 11, 8, 12), bucket=b, graph=client)
    left = sorted(g.files)
    assert left == ["golden_db_20261004_0300.gwbk", "golden_db_20261005_0300.gwbk", "golden_db_20261108_0300.gwbk"]    # se conservan 3
    assert "se borraron 3" in msg
    assert not any(c[0] == "DELETE" and ("carpeta" in c[1] or "otro" in c[1]) for c in g.calls)


def test_planted_future_copies_cannot_make_the_real_copy_be_deleted(cfg):
    """F5-9 E: con permiso de escritura en la carpeta, dejar copias con fecha futura hacía que cada copia real se borrara al subirse."""
    planted = [f"golden_db_2099010{i}_0000.gwbk" for i in range(1, 6)] + ["golden_db_hack.gwbk"]
    b = FakeBucket([FakeBlob("db/daily/x/golden_db_20261108_0300.sql.gz", b"d")])
    g, client = _graph(existing=planted + ["golden_db_20261001_0300.gwbk"])
    oc.run(now=datetime(2026, 11, 8, 12), bucket=b, graph=client)
    assert "golden_db_20261108_0300.gwbk" in g.files and "golden_db_20261001_0300.gwbk" in g.files
    assert all(p in g.files for p in planted)                         # lo ajeno no se cuenta ni se borra


def test_foreign_next_link_does_not_receive_the_token(cfg):
    calls = []

    def http(method, url, headers, data):
        calls.append((url, headers.get("Authorization")))
        if url.endswith("/oauth2/v2.0/token"):
            return 200, json.dumps({"access_token": "T"}).encode(), {}
        return 200, json.dumps({"value": [], "@odata.nextLink": "https://evil.example/next"}).encode(), {}
    client = oc.GraphClient(http=http, sleep=lambda s: None)
    with pytest.raises(oc.GraphError):
        client.list_copies()
    assert not any(u.startswith("https://evil.example") for u, _ in calls)


def test_retry_on_503_then_ok(cfg):
    b = FakeBucket([FakeBlob("db/daily/x/golden_db_20261108_0300.sql.gz", b"d")])
    g, client = _graph(fail_puts=2)
    oc.run(now=datetime(2026, 11, 8, 12), bucket=b, graph=client)
    assert "golden_db_20261108_0300.gwbk" in g.files


def test_failure_records_state_and_raises_without_secrets(cfg):
    b = FakeBucket([FakeBlob("db/daily/x/golden_db_20261108_0300.sql.gz", b"d")])
    g, client = _graph(fail_puts=99)
    with pytest.raises(oc.GraphError):
        oc.run(now=datetime(2026, 11, 8, 12), bucket=b, graph=client)
    st = json.loads(b.store[oc.STATE_KEY])
    assert st["last_status"] == "fail" and "503" in st["last_error"] and "s" != st["last_error"]
    assert "last_ok_at" not in st


def test_no_backup_in_bucket_fails(cfg):
    with pytest.raises(RuntimeError, match="No hay respaldos"):
        oc.run(now=datetime(2026, 11, 8, 12), bucket=FakeBucket(), graph=_graph()[1])


# ------------------------------------------------------------------ cuándo toca
def test_due_rules(cfg):
    now = datetime(2026, 11, 8, 12)                                       # 7 a. m. Bogotá
    assert oc.due(now, {}) is True
    assert oc.due(now, {"last_ok_at": "2026-11-05T12:00:00Z"}) is False   # hace 3 días
    assert oc.due(now, {"last_ok_at": "2026-11-01T12:00:00Z"}) is True    # hace 7 días
    assert oc.due(now, {"last_ok_at": "2026-11-01T12:00:00Z", "last_attempt_at": "2026-11-08T09:00:00Z"}) is False    # reintento solo tras 6 h
    assert oc.due(datetime(2026, 11, 8, 8), {}) is False                  # 3 a. m. Bogotá: antes de la hora


def test_stale_more_than_10_days_raises_for_alert(cfg):
    b = FakeBucket([FakeBlob("db/daily/x/golden_db_20261108_0300.sql.gz", b"d")])
    b.store[oc.STATE_KEY] = json.dumps({"last_ok_at": "2026-10-20T12:00:00Z", "last_attempt_at": "2026-11-08T11:00:00Z", "last_error": "HTTP 403"})
    with pytest.raises(RuntimeError, match="más de 10 días"):
        oc.run(now=datetime(2026, 11, 8, 12), bucket=b, graph=_graph()[1])


def test_up_to_date_does_not_call_graph(cfg):
    b = FakeBucket()
    b.store[oc.STATE_KEY] = json.dumps({"last_ok_at": "2026-11-06T12:00:00Z", "since": "2026-10-01T00:00:00Z"})
    g, client = _graph()
    assert "al día" in oc.run(now=datetime(2026, 11, 8, 12), bucket=b, graph=client)
    assert g.calls == []


# ------------------------------------------------------------------ /sistema y alerta
def test_status_item_levels(cfg, monkeypatch):
    now = datetime(2026, 11, 8, 12)
    b = FakeBucket()
    assert oc.status_item(b, now)["value"] == "sin copia todavía"
    b.store[oc.STATE_KEY] = json.dumps({"last_ok_at": "2026-11-06T12:00:00Z", "last_size": 5 * 1048576})
    assert oc.status_item(b, now)["level"] == "green"
    b.store[oc.STATE_KEY] = json.dumps({"last_ok_at": "2026-10-30T12:00:00Z"})
    assert oc.status_item(b, now)["level"] == "yellow"
    b.store[oc.STATE_KEY] = json.dumps({"last_ok_at": "2026-10-20T12:00:00Z", "last_error": "HTTP 403"})
    assert oc.status_item(b, now)["level"] == "red"


def test_status_item_not_configured(monkeypatch):
    for k in oc.REQUIRED:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("BACKUP_BUCKET", raising=False)
    it = oc.status_item(None)
    assert it["value"] == "copia semanal no configurada" and it["level"] == "yellow"


def test_hourly_includes_offsite_step_and_failure_does_not_stop_others(monkeypatch):
    from app import ops_runner
    ran = []
    monkeypatch.setattr(ops_runner, "backup_db", lambda kind, now=None: "ok")
    monkeypatch.setattr(ops_runner, "check_backups", lambda: "ok")
    monkeypatch.setattr(ops_runner, "offsite_copy", lambda: (_ for _ in ()).throw(RuntimeError("sin copia")))
    monkeypatch.setattr(ops_runner, "sweep", lambda: ran.append("sweep") or "ok")
    monkeypatch.setattr(ops_runner, "purge_reports", lambda: "ok")
    monkeypatch.setattr(ops_runner, "warmup", lambda: ran.append("warmup") or "ok")
    r = ops_runner.hourly(now=datetime(2026, 11, 8, 9, 5))
    assert r["offsite-copy"]["ok"] is False and ran == ["sweep", "warmup"]
    assert "offsite-copy" in ops_runner.TASKS


def test_open_backup_copy_script(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("obc", os.path.join(os.path.dirname(__file__), "..", "scripts", "open_backup_copy.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src, dst = tmp_path / "a.gwbk", tmp_path / "a.sql.gz"
    src.write_bytes(b"".join(oc.encrypt_stream(io.BytesIO(b"datos"), KEY)))
    monkeypatch.setenv("BACKUP_COPY_ENCRYPTION_KEY", KEY)
    assert mod.main(["x", str(src), str(dst)]) == 0 and dst.read_bytes() == b"datos"
    bad = tmp_path / "b.sql.gz"
    monkeypatch.setenv("BACKUP_COPY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert mod.main(["x", str(src), str(bad)]) == 1 and not bad.exists() and not (tmp_path / "b.sql.gz.parcial").exists()
