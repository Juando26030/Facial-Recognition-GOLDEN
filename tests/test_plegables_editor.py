"""Fase 1.7 · M7: los cupos por variable del editor de formularios se ven como una línea plegable (details/summary)."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TPL = (ROOT / "templates" / "kiosk_formulario_editor.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "p-plegables.css").read_text(encoding="utf-8")


class PlegablesEditorTests(unittest.TestCase):
    def test_cada_cupo_es_details_con_resumen(self):
        self.assertIn('<details class="gwp-fold" data-qrule=', TPL)
        self.assertIn('<summary class="gwp-fold__sum">${quotaSumHtml(', TPL)
        self.assertIn("function quotaSumHtml", TPL)
        self.assertIn("closeAlertHtml(r.closes_at)", TPL)

    def test_se_conservan_ids_y_data(self):
        for k in ("data-ql=", "data-qn=", "data-qst=", "data-qcl=", "data-qus=", "data-qmsgrt=", "data-qdel=", "id=\"qRules\"", "id=\"qAdd\"", "id=\"qQuick\""):
            self.assertIn(k, TPL)

    def test_abre_el_cupo_con_error_y_conserva_estado(self):
        self.assertIn("openQuotaAt(qi)", TPL)
        self.assertIn("quotaOpen", TPL)

    def test_css_solo_tokens(self):
        self.assertNotIn("#", CSS.replace("/*", "").split("*/")[-1])
        self.assertIn("var(--gw-", CSS)
        self.assertIn("p-plegables.css", TPL)


if __name__ == "__main__":
    unittest.main()
