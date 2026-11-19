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

  /* 18-nov-2026: otros dos formatos de QR (cada QR de la escarapela elige el suyo, ver badge-render.js qrText):
       MECARD  «MECARD:N:Apellido,Nombre;TEL:…;EMAIL:…;NOTE:GW:código;;»  más corto que la vCard (no admite empresa ni rol); iPhone y Android lo leen distinto, probar en los celulares del evento.
       ENLACE  «https://…/tarjeta/<token>#GW:código»  el QR solo lleva el enlace de la tarjeta de la persona (que muestra datos SOLO si ella aceptó compartirlos); el código va en el fragmento (#), que el
               celular no envía a ningún servidor, y los lectores de Golden lo sacan sin red. */
  function mesc(v) { return String(v == null ? '' : v).replace(CTRL, ' ').replace(/\s+/g, ' ').trim().replace(/([\\;,:])/g, '\\$1'); }
  function buildMecard(o) {
    const d = o || {};
    const first = String(d.first_name == null ? '' : d.first_name).trim(), last = String(d.last_name == null ? '' : d.last_name).trim();
    const phone = String(d.phone == null ? '' : d.phone).replace(/[^\d+()\-.\s]/g, '').trim();
    const mail = String(d.email == null ? '' : d.email).trim();
    let t = 'MECARD:N:' + mesc(last) + ',' + mesc(first || (last ? '' : 'Asistente')) + ';';
    if (phone) t += 'TEL:' + mesc(phone) + ';';
    if (mail && mail.indexOf('@') > 0) t += 'EMAIL:' + mesc(mail) + ';';
    return t + 'NOTE:' + PREFIX + mesc(d.note) + ';;';
  }
  function buildLink(url, code) {
    const u = String(url == null ? '' : url).trim().split('#')[0];
    return u + '#' + PREFIX + encodeURIComponent(String(code == null ? '' : code));
  }
  function isMecard(text) { return /^\s*MECARD:/i.test(String(text == null ? '' : text)); }
  function isLink(text) { return /^https?:\/\/\S+#GW:\S*$/i.test(String(text == null ? '' : text).trim()); }

  function isVcard(text) { return /^\s*BEGIN:VCARD/i.test(String(text == null ? '' : text)); }

  function unwrap(text) {
    const raw = String(text == null ? '' : text);
    if (isLink(raw)) { const frag = raw.trim().slice(raw.trim().indexOf('#GW:') + 4); try { return decodeURIComponent(frag).trim(); } catch (e) { return frag.trim(); } }
    if (isMecard(raw)) { const mm = raw.match(/NOTE:GW:((?:\\.|[^;\\])*);/i); return mm ? mm[1].replace(/\\(.)/g, '$1').trim() : raw; }
    if (!isVcard(raw)) return raw;
    const t = raw.trim().replace(/\r\n|\r/g, '\n').replace(/\n[ \t]/g, '');            // líneas dobladas (RFC) y saltos de cualquier sistema
    let m = t.match(/^NOTE(?:;[^:\n]*)?:GW:(.*)$/im);
    if (!m) m = t.match(/NOTE:GW:([\s\S]*?)\s*END:VCARD/i);                               // un lector que «se comió» los saltos de línea
    if (!m) return raw;                                                                    // vCard ajena: no es de Golden
    return unesc(m[1].replace(/END:VCARD\s*$/i, '')).trim();
  }

  /* Lector 2D que escribe la vCard SIN saltos de línea («BEGIN:VCARDVERSION:3.0N:PEREZ;ANA;;;FN:ANA PEREZTEL:300…NOTE:GW:123END:VCARD»): los campos se separan por su ORDEN fijo
     (el de build), buscando cada nombre desde donde terminó el anterior. Sirve igual con saltos de línea. Devuelve { campo: valor } con las claves en MAYÚSCULAS. */
  const ORDER = ['BEGIN:VCARD', 'VERSION:', 'N:', 'FN:', 'ORG:', 'TITLE:', 'TEL:', 'EMAIL:', 'CATEGORIES:', 'NOTE:', 'END:VCARD'];
  function fields(text) {
    const t = String(text == null ? '' : text).replace(/\r\n|\r/g, '\n').replace(/\n[ \t]/g, '');
    const found = [];
    let pos = 0;
    for (const key of ORDER) {
      const name = key.replace(/:$/, '');
      const re = key === 'END:VCARD' ? /END:VCARD/i : new RegExp(name + '(?:;[^:\\n]*)?:', 'i');       // con parámetros opcionales: «TEL;TYPE=CELL:»
      const m = re.exec(t.slice(pos));
      if (!m) continue;
      found.push({ key: name, at: pos + m.index, len: m[0].length });
      pos += m.index + m[0].length;
    }
    const out = {};
    found.forEach((f, i) => { const end = i + 1 < found.length ? found[i + 1].at : t.length; out[f.key] = t.slice(f.at + f.len, end).replace(/\n+$/g, '').trim(); });
    return out;
  }
  /* Qué trae lo leído: { golden, code, name, phone }. `golden` = lleva el código de Golden (NOTE:GW:…); `name` sale de FN (o de N: Apellido;Nombre); null si no es una vCard. */
  function parseCard(text) {
    if (!isVcard(text)) return null;
    const f = fields(text);
    const note = f.NOTE || '';
    const golden = /^GW:/i.test(note);
    let name = f.FN ? unesc(f.FN).trim() : '';
    if (!name && f.N) { const p = f.N.split(';'); name = (unesc(p[1] || '') + ' ' + unesc(p[0] || '')).trim(); }
    return { golden, code: golden ? unesc(note.replace(/^GW:/i, '')).trim() : '', name, phone: f.TEL || '' };
  }
  /* Una vCard que todavía se está escribiendo (el lector teclea carácter por carácter): sin END:VCARD no se busca nada. */
  function isPartial(text) { return isVcard(text) && !/END:VCARD/i.test(String(text)); }

  const api = { build, buildMecard, buildLink, unwrap, isVcard, isMecard, isLink, fields, parseCard, isPartial, QR_LEVEL, PREFIX };
  if (typeof window !== 'undefined') window.GWVcard = api;
  if (typeof module !== 'undefined') module.exports = api;       // para las pruebas en Node
})();
