"""Generador de PDF mínimo con la biblioteca estándar (sin dependencias nuevas): texto con Helvetica / Helvetica-Bold (WinAnsi, tildes y ñ), líneas, rectángulos, cambio de página.
Pura: devuelve `bytes`; no toca disco ni base. Lo usa app/crm/quote_pdf.py. Medidas en puntos (A4 = 595 × 842)."""
import unicodedata
from typing import List

PAGE_W, PAGE_H, MARGIN = 595, 842, 42
_W = ("278 278 355 556 556 889 667 191 333 333 389 584 278 333 278 278 556 556 556 556 556 556 556 556 556 556 278 278 584 584 584 556 1015 667 667 722 722 667 611 778 722 278 500 667 556 833 722 778 "
      "667 778 722 667 611 722 667 944 667 667 611 278 278 278 469 556 333 556 556 500 556 556 278 556 556 222 222 500 222 833 556 556 556 556 333 500 278 556 500 722 500 500 500 334 260 334 584").split()
WIDTHS = {chr(32 + i): int(w) for i, w in enumerate(_W)}


def _base(ch: str) -> str:
    return unicodedata.normalize("NFD", ch)[0] if ch not in WIDTHS else ch


def text_width(s: str, size: float, bold: bool = False) -> float:
    return sum(WIDTHS.get(_base(c), 556) for c in s) * size / 1000 * (1.04 if bold else 1)


def _esc(s: str) -> bytes:
    return s.encode("cp1252", "replace").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def wrap(s: str, size: float, width: float, bold: bool = False) -> List[str]:
    """Parte `s` en líneas que caben en `width` puntos; respeta los saltos de línea y corta palabras más largas que la línea."""
    lines: List[str] = []
    for para in (s or "").replace("\r", "").split("\n"):
        cur = ""
        for word in para.split(" "):
            while text_width(word, size, bold) > width and len(word) > 1:          # palabra más ancha que la línea
                cut = len(word)
                while cut > 1 and text_width(word[:cut], size, bold) > width:
                    cut -= 1
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(word[:cut])
                word = word[cut:]
            trial = (cur + " " + word).strip() if cur else word
            if text_width(trial, size, bold) <= width:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


class Doc:
    def __init__(self, title: str = ""):
        self.title = title
        self.pages: List[List[bytes]] = []
        self.y = 0.0
        self.new_page()

    def new_page(self) -> None:
        self.pages.append([])
        self.y = PAGE_H - MARGIN

    def _add(self, cmd: str) -> None:
        self.pages[-1].append(cmd.encode("ascii"))

    def text(self, x: float, y: float, s: str, size: float = 10, bold: bool = False, gray: float = 0.0) -> None:
        self.pages[-1].append(b"BT /%s %.1f Tf %.2f g %.1f %.1f Td (" % (b"F2" if bold else b"F1", size, gray, x, y) + _esc(s) + b") Tj ET")

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.6, gray: float = 0.6) -> None:
        self._add("%.2f G %.2f w %.1f %.1f m %.1f %.1f l S" % (gray, width, x1, y1, x2, y2))

    def rect(self, x: float, y: float, w: float, h: float, gray: float = 0.93) -> None:
        self._add("%.2f g %.1f %.1f %.1f %.1f re f" % (gray, x, y, w, h))

    def need(self, height: float) -> None:
        if self.y - height < MARGIN + 20:
            self.new_page()

    def paragraph(self, s: str, size: float = 10, bold: bool = False, x: float = MARGIN, width: float = PAGE_W - 2 * MARGIN, gap: float = 4, gray: float = 0.0) -> None:
        lead = size * 1.3
        for ln in wrap(s, size, width, bold):
            self.need(lead)
            self.y -= lead
            self.text(x, self.y, ln, size, bold, gray)
        self.y -= gap

    def table_row(self, cells: list, widths: list, aligns: list, size: float = 9, bold: bool = False, shade: bool = False) -> None:
        """Una fila: cada celda se parte en líneas; la fila no se corta entre páginas."""
        cols = [wrap(str(c), size, w - 6, bold) for c, w in zip(cells, widths)]
        lead = size * 1.3
        h = max(len(c) for c in cols) * lead + 6
        self.need(h)
        top = self.y
        if shade:
            self.rect(MARGIN, top - h, sum(widths), h)
        x = MARGIN
        for lines, w, al in zip(cols, widths, aligns):
            for i, ln in enumerate(lines):
                tx = x + 3 if al == "l" else x + w - 3 - text_width(ln, size, bold)
                self.text(tx, top - 3 - size - i * lead, ln, size, bold)
            x += w
        self.y = top - h
        self.line(MARGIN, self.y, MARGIN + sum(widths), self.y, 0.4, 0.8)

    def render(self) -> bytes:
        n = len(self.pages)
        objs: List[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                             b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
        kids = []
        for i, cmds in enumerate(self.pages):
            page_id, content_id = 5 + 2 * i, 6 + 2 * i
            kids.append(b"%d 0 R" % page_id)
            footer = b"BT /F1 8 Tf 0.5 g %d 24 Td (" % MARGIN + _esc("Página %d de %d" % (i + 1, n)) + b") Tj ET"
            stream = b"\n".join(cmds + [footer])
            objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>" % (PAGE_W, PAGE_H, content_id))
            objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        objs[1] = b"<< /Type /Pages /Kids [" + b" ".join(kids) + b"] /Count %d >>" % n
        info_id = len(objs) + 1
        objs.append(b"<< /Title (" + _esc(self.title) + b") /Producer (Orum) >>")
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(objs, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, info_id, xref)
        return bytes(out)
