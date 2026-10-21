"""La política v1.1 se ratifica por el hash del archivo exacto: si el texto cambia sin generar otro hash, esta prueba falla (docs/legal/POLITICA_v1.1.md.sha256)."""
import hashlib
from pathlib import Path


def test_policy_v11_matches_its_ratification_hash():
    raw = Path("docs/legal/POLITICA_v1.1.md").read_bytes()
    expected = Path("docs/legal/POLITICA_v1.1.md.sha256").read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(raw).hexdigest() == expected, "POLITICA_v1.1.md cambió: genera un hash nuevo y pide otra ratificación (no se edita después del hash)"


def test_policy_v11_embeds_the_auditors_literal_phrases():
    policy = Path("docs/legal/POLITICA_v1.1.md").read_text(encoding="utf-8")
    texts = Path("docs/legal/TEXTOS_AUDITORA_2026-10-05.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    import re
    c3 = re.search(r"```text\n(8\. FUNCIONAMIENTO.*?)\n```", texts, re.S).group(1)
    assert c3 in policy
    for heading in ("### 8.1", "### 8.2", "### 8.3"):
        phrase = re.search(re.escape(heading) + r".*?```text\n(.*?)\n```", texts, re.S).group(1)
        assert phrase in policy
    assert "PENDIENTE DE RATIFICACIÓN" in policy
