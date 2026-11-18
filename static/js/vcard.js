/* QR en formato vCard (10-nov-2026, Fase 10 bloque C): al escanear la escarapela con el celular se puede GUARDAR EL CONTACTO (nombre y, si vienen con valor: empresa, cargo/rol, teléfono, correo y categorías).
   El código que lee Golden (la cédula del QR impreso o el código firmado «gwq1…» de la credencial digital / Wallet) va en el campo NOTE con la marca «GW:». Ejemplo:

     BEGIN:VCARD
     VERSION:3.0
     N:Perez;Ana;;;
     FN:Ana Perez
     TEL:3001234567
     NOTE:GW:1016100329|Ana|Perez
     END:VCARD

   GWVcard.build({ first_name, last_name, phone, email, org, title, categories, note })  -> texto de la vCard (para dibujar el QR). Solo trae los campos con valor; sin nombre, FN = «Asistente».
   GWVcard.unwrap(texto)                                  -> el código de adentro si es una vCard de Golden; si no, el MISMO texto (el formato anterior sigue valiendo tal cual).
   GWVcard.isVcard(texto)                                 -> true si empieza con BEGIN:VCARD.
   GWVcard.QR_LEVEL                                       -> 'L': la vCard es más larga que el formato anterior; con nivel L el QR queda en una versión más chica (menos cuadritos, más grandes
                                                             al imprimir en la misma etiqueta). El tamaño de la etiqueta y de la imagen NO cambian (parámetros de impresión inamovibles).
   Misma lógica en Python: app/qr_vcard.py (el servidor también acepta ambos formatos). */
(function () {
  const CTRL = /[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029]/g;
  const PREFIX = 'GW:';
  const QR_LEVEL = 'L';

  function esc(v) {
    return String(v == null ? '' : v).replace(CTRL, ' ').replace(/\s+/g, ' ').trim()
      .replace(/\\/g, '\\\\').replace(/,/g, '\\,').replace(/;/g, '\\;');
  }
  function unesc(v) { return String(v).replace(/\\([\\,;nN])/g, (m, c) => (c === 'n' || c === 'N' ? '\n' : c)); }

  function build(o) {
    const d = o || {};
    const first = String(d.first_name == null ? '' : d.first_name).trim();
    const last = String(d.last_name == null ? '' : d.last_name).trim();
    const full = [first, last].filter(Boolean).join(' ') || 'Asistente';
    const phone = String(d.phone == null ? '' : d.phone).replace(/[^\d+()\-.\s]/g, '').trim();
    const lines = ['BEGIN:VCARD', 'VERSION:3.0', `N:${esc(last)};${esc(first)};;;`, `FN:${esc(full)}`];
    if (String(d.org == null ? '' : d.org).trim()) lines.push(`ORG:${esc(d.org)}`);
    if (String(d.title == null ? '' : d.title).trim()) lines.push(`TITLE:${esc(d.title)}`);
    if (phone) lines.push(`TEL:${esc(phone)}`);
    const mail = String(d.email == null ? '' : d.email).trim();
    if (mail && mail.indexOf('@') > 0) lines.push(`EMAIL:${esc(mail)}`);
    const cats = String(d.categories == null ? '' : d.categories).split(',').map((c) => c.trim()).filter(Boolean);
    if (cats.length) lines.push('CATEGORIES:' + cats.map(esc).join(','));
    lines.push(`NOTE:${PREFIX}${esc(d.note)}`, 'END:VCARD');
    return lines.join('\n');
  }

  function isVcard(text) { return /^\s*BEGIN:VCARD/i.test(String(text == null ? '' : text)); }

  function unwrap(text) {
    const raw = String(text == null ? '' : text);
    if (!isVcard(raw)) return raw;
    const t = raw.trim().replace(/\r\n|\r/g, '\n').replace(/\n[ \t]/g, '');            // líneas dobladas (RFC) y saltos de cualquier sistema
    let m = t.match(/^NOTE(?:;[^:\n]*)?:GW:(.*)$/im);
    if (!m) m = t.match(/NOTE:GW:([\s\S]*?)\s*END:VCARD/i);                               // un lector que «se comió» los saltos de línea
    if (!m) return raw;                                                                    // vCard ajena: no es de Golden
    return unesc(m[1].replace(/END:VCARD\s*$/i, '')).trim();
  }

  const api = { build, unwrap, isVcard, QR_LEVEL, PREFIX };
  if (typeof window !== 'undefined') window.GWVcard = api;
  if (typeof module !== 'undefined') module.exports = api;       // para las pruebas en Node
})();
