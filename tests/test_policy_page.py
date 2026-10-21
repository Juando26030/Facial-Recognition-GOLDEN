"""Página pública /privacidad con la política v1.1 RATIFICADA: se muestra el archivo exacto (hash verificado) sin la marca de borrador y con la leyenda de ratificación; el archivo no se toca."""
import hashlib
import re
from pathlib import Path

import pytest

from app import policy_v11

SHA = "d0afc7d95083b62115ce001abeb1ab8e86925e35a14d80011e06bf75e253c844"


def test_the_ratified_hash_in_the_code_is_the_one_the_auditor_ratified_and_the_file_is_untouched():
    assert policy_v11.RATIFIED_SHA256 == SHA
    assert hashlib.sha256(Path("docs/legal/POLITICA_v1.1.md").read_bytes()).hexdigest() == SHA
    assert Path("docs/legal/POLITICA_v1.1.md.sha256").read_text(encoding="utf-8").split()[0] == SHA


def test_default_keeps_v1_0_and_v1_1_needs_the_activation_variable(client, monkeypatch):
    monkeypatch.delenv("POLICY_VERSION", raising=False)
    page = client.get("/privacidad").text
    assert "versión 1.1" not in page.lower() and "Texto con constancia" in page                      # la 1.0 con su constancia, como siempre
    monkeypatch.setenv("POLICY_VERSION", "1.1")
    assert "Ratificada el 6 de octubre de 2026" in client.get("/privacidad").text


def test_v1_1_page_hides_the_draft_marker_and_shows_the_ratification_legend_with_the_hash(client, monkeypatch):
    monkeypatch.setenv("POLICY_VERSION", "1.1")
    page = client.get("/privacidad").text
    assert f"Ratificada el 6 de octubre de 2026 · SHA-256 {SHA}" in page
    for draft in ("PENDIENTE DE RATIFICACIÓN", "BORRADOR", "PENDIENTE DE REVISIÓN LEGAL", "(texto de la auditora)", "no está publicada"):
        assert draft not in page, draft
    assert "Política de Privacidad y Tratamiento de Datos Personales — versión 1.1" in page and "<table>" in page


def test_the_auditors_literal_sentences_are_shown_unchanged(client, monkeypatch):
    monkeypatch.setenv("POLICY_VERSION", "1.1")
    page = client.get("/privacidad").text
    texts = Path("docs/legal/TEXTOS_AUDITORA_2026-10-05.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    import html
    import re
    c3 = re.search(r"```text\n(8\. FUNCIONAMIENTO.*?)\n```", texts, re.S).group(1)
    for line in c3.split("\n"):
        assert html.escape(line, quote=False) in page                                                # la sección 8, línea por línea, tal cual
    for heading in ("### 8.1", "### 8.2", "### 8.3"):
        phrase = re.search(re.escape(heading) + r".*?```text\n(.*?)\n```", texts, re.S).group(1)
        assert html.escape(phrase, quote=False) in page
    assert "soporteit@goldenlogisticas.com" in page and "901.542.833-2" in page


def test_a_changed_file_is_never_shown(client, monkeypatch, tmp_path):
    fake = tmp_path / "p.md"
    fake.write_text("# Otro texto\n", encoding="utf-8")
    monkeypatch.setattr(policy_v11, "POLICY_FILE", fake)
    monkeypatch.setenv("POLICY_VERSION", "1.1")
    page = client.get("/privacidad").text
    assert "Otro texto" not in page and "Ratificada el" not in page and "Texto con constancia" in page    # cae a la 1.0
    monkeypatch.setattr(policy_v11, "POLICY_FILE", tmp_path / "no-existe.md")
    assert client.get("/privacidad").status_code == 200


def test_v1_0_stays_available_as_historic(client, monkeypatch):
    monkeypatch.setenv("POLICY_VERSION", "1.1")
    page = client.get("/privacidad/v1.0").text
    assert "Versión histórica" in page and "Texto con constancia" in page and "Ratificada el" not in page


def test_the_image_carries_the_ratified_file_and_both_environments_activate_it():
    assert "docs/legal/POLITICA_v1.1.md" in Path("Dockerfile").read_text(encoding="utf-8")
    ignore = Path(".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "!docs/legal/POLITICA_v1.1.md" in ignore and ignore.index("!docs/legal/POLITICA_v1.1.md") > ignore.index("*.md")      # la excepción va DESPUÉS de las exclusiones
    common = Path("deploy/gcp/env/common.yaml").read_text(encoding="utf-8")
    assert re.findall(r'^POLICY_VERSION:\s*"([^"]*)"', common, re.M) == ["1.1"]                       # staging Y producción (el archivo común lo copian los dos)
    deploy = Path("deploy/gcp/deploy.sh").read_text(encoding="utf-8")
    assert "POLICY_VERSION" not in re.sub(r"#.*", "", deploy)                                          # sin un segundo origen: nada que lo apague por entorno ni lo duplique


def test_deploy_never_repeats_a_key_that_common_yaml_already_sets():
    """`env_file` copia common.yaml y le agrega líneas `echo "CLAVE: …"`: una clave en los dos sitios daría un YAML con claves repetidas."""
    common = set(re.findall(r"^([A-Z][A-Z0-9_]*):", Path("deploy/gcp/env/common.yaml").read_text(encoding="utf-8"), re.M))
    block = Path("deploy/gcp/deploy.sh").read_text(encoding="utf-8").split("env_file() {", 1)[1].split(chr(10) + "}" + chr(10), 1)[0]
    added = set(re.findall(r'echo "([A-Z][A-Z0-9_]*):', block))
    assert common & added == set(), common & added
    assert {"POLICY_VERSION", "ENVIRONMENT", "DOMAIN"} <= common and "CONTINGENCY_ENABLED" in added                    # contingencia sigue por entorno (config.sh), la política no


def test_production_serves_the_ratified_policy_with_the_common_setting(client, monkeypatch):
    values = dict(re.findall(r'^([A-Z][A-Z0-9_]*):\s*"([^"]*)"', Path("deploy/gcp/env/common.yaml").read_text(encoding="utf-8"), re.M))
    monkeypatch.setenv("POLICY_VERSION", values["POLICY_VERSION"])
    monkeypatch.setenv("ENVIRONMENT", "production")
    for k in ("COMPANY_NAME", "COMPANY_NIT", "PRIVACY_EMAIL", "DOMAIN"):
        monkeypatch.setenv(k, values[k])
    page = client.get("/privacidad")
    assert page.status_code == 200 and "Ratificada el 6 de octubre de 2026" in page.text and "FUNCIONAMIENTO LOCAL TEMPORAL EN MODO DE CONTINGENCIA" in page.text


@pytest.mark.parametrize("raw,expected", [("**ESTADO: PENDIENTE DE RATIFICACIÓN** x\n\n# T\n\nhola *a* **b**", "<h1>T</h1>\n<p>hola <i>a</i> <b>b</b></p>")])
def test_markdown_conversion_drops_only_the_draft_paragraph(raw, expected):
    assert policy_v11.to_html(raw) == expected
