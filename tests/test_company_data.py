"""Datos definitivos de la empresa: el NIT lleva siempre su dígito de verificación y el correo de privacidad es uno solo (decisión 2026-10-06)."""
import re
from pathlib import Path

from app import company, legal

_BAD_NIT = re.compile(r"901[.]?542[.]?833(?!-2)")


def test_nit_is_shown_with_its_check_digit(monkeypatch):
    monkeypatch.setenv("COMPANY_NIT", "901542833-2")
    assert company.get("COMPANY_NIT") == "901.542.833-2" and company.nit_display("901.542.833-2") == "901.542.833-2" and company.nit_display("901542833-2") == "901.542.833-2"
    monkeypatch.delenv("COMPANY_NIT")
    monkeypatch.delenv("LEGAL_NIT", raising=False)
    assert legal.info()["nit"] == "901.542.833-2"


def test_no_published_text_carries_the_nit_without_its_check_digit():
    offenders = []
    for folder, pattern in (("app", "*.py"), ("templates", "*.html"), ("static", "*.js"), ("deploy", "*.yaml"), ("docs/legal", "POLITICA*.md"), ("docs/legal", "DECISIONES*.md")):
        for path in Path(folder).rglob(pattern):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if _BAD_NIT.search(text):
                offenders.append(str(path))
    assert not offenders, f"NIT sin el «-2»: {offenders}"


def test_privacy_email_is_a_single_one_and_the_old_variable_is_only_an_obsolete_alias(monkeypatch):
    monkeypatch.setenv("LEGAL_PRIVACY_EMAIL", "soporteit@goldenlogisticas.com")
    monkeypatch.setenv("PRIVACY_EMAIL", "soporteit@goldenlogisticas.com")
    assert legal.info()["privacy_email"] == "soporteit@goldenlogisticas.com"                    # manda PRIVACY_EMAIL
    monkeypatch.delenv("PRIVACY_EMAIL")
    assert legal.info()["privacy_email"] == "soporteit@goldenlogisticas.com"                         # alias obsoleto: solo si falta la nueva


def test_policy_url_uses_the_apps_host(monkeypatch):
    monkeypatch.setenv("DOMAIN", "golden-eventos.com")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.golden-eventos.com")
    assert company.policy_url() == "https://app.golden-eventos.com/privacidad"
    monkeypatch.delenv("PUBLIC_BASE_URL")
    assert company.policy_url() == "https://app.golden-eventos.com/privacidad"                 # sin PUBLIC_BASE_URL: https://app.<DOMAIN>
