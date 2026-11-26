/* Buscador ÚNICO de personas para Control de Áreas y Control de Inventario (19-nov-2026): una sola caja que funciona como la de Registro.
   Se escribe una cédula, un nombre o una empresa y, MIENTRAS se escribe, aparecen las coincidencias (con el motivo); con Enter:
     · cédula completa, código del lector o QR (propio, vCard, MECARD, enlace o dinámico de la credencial digital) → toma a esa persona si es una sola o es exacta;
     · nombre/empresa o varias coincidencias → se muestran para elegir (nunca se elige a ciegas);
     · sin coincidencias en la lista: una cédula completa se manda tal cual al servidor (él responde «no encontrado»); lo demás avisa que no hay coincidencias.
   El lector de mano que escribe una vCard en VARIAS líneas se junta con QrCode.collect. Una vCard AJENA (el contacto de un celular, sin el código de Golden) se busca por su nombre (FN / N).
   Usa SearchCore (search-core.js) y QrCode (qr.js). Sin DOM propio más allá de la caja y la lista que le pasa la página.

   PersonFinder.attach({ input, box, users: () => lista, purpose: 'area'|'inventory', eventId, onPick(persona, via), onRaw(cedula, via), onMessage(texto) }) -> { submit(), clear() }
     via: 'qr' (QR propio / vCard / dinámico) | 'cedula' | 'lista' (la eligió quien opera de la lista). */
(function (root) {
  'use strict';
  const MAX_ROWS = 8;
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function unfold(text) { return String(text == null ? '' : text).replace(/\r\n|\r/g, '\n').replace(/\n[ \t]/g, ''); }
  function unesc(v) { return String(v).replace(/\\([\\,;:nN])/g, (m, c) => (c === 'n' || c === 'N' ? ' ' : c)); }

  /* Texto de una vCard/MECARD AJENA (sin el código de Golden) → el nombre para buscar; '' si no es de ese tipo. */
  function nameFromForeignCard(raw) {
    const t = unfold(raw);
    if (/^\s*BEGIN:VCARD/i.test(t)) {
      if (!/\n/.test(t.trim())) {                                  // pegada en una sola línea (la caja quita los saltos): se busca FN hasta el siguiente campo
        const one = t.match(/FN(?:;[^:]*)?:(.*?)(?=(?:TEL|EMAIL|ORG|TITLE|URL|NOTE|ADR|BDAY|PHOTO|END)[;:]|$)/i);
        if (one && one[1].trim()) return unesc(one[1]).trim();
        const n1 = t.match(/(?:^|[^A-Z])N:([^;]*);([^;]*)/i);
        if (n1) return (unesc(n1[2]) + ' ' + unesc(n1[1])).trim();
      }
      const fn = t.match(/^FN(?:;[^:\n]*)?:(.*)$/im);
      if (fn && fn[1].trim()) return unesc(fn[1]).trim();
      const n = t.match(/^N(?:;[^:\n]*)?:([^;\n]*);([^;\n]*)/im);
      if (n) return (unesc(n[2]) + ' ' + unesc(n[1])).trim();
      return '';
    }
    const mc = /^\s*MECARD:/i.test(t) ? t.match(/N:((?:\\.|[^;])*);/i) : null;
    if (mc) { const parts = mc[1].split(','); return (unesc(parts[1] || '') + ' ' + unesc(parts[0] || '')).trim(); }
    return '';
  }

  /* Lo que se busca a partir de lo leído: el código de la vCard/MECARD/enlace de Golden o, si es ajena, el nombre; cualquier otro texto, tal cual. */
  function queryText(raw) {
    const V = root.GWVcard, text = V ? V.unwrap(raw) : String(raw == null ? '' : raw);
    if (text !== raw) return text;                                 // era de Golden: ya trae el código
    return nameFromForeignCard(raw) || text;
  }

  function attach(cfg) {
    const SC = root.SearchCore, input = cfg.input, box = cfg.box;
    let results = [];

    const users = () => (typeof cfg.users === 'function' ? cfg.users() : []) || [];
    const fullName = (u) => `${u.first_name || ''} ${u.last_name || ''}`.trim();
    function clearList() { results = []; box.innerHTML = ''; box.hidden = true; }
    function clear() { input.value = ''; clearList(); }
    function say(text) { if (cfg.onMessage) cfg.onMessage(text); else if (typeof root.showToast === 'function') root.showToast(text, 'error'); }

    function find(text) {
      const q = SC.classifyQuery(text);
      if (q.kind === 'vacio') return { q, list: [] };
      const opts = { codeFirst: root.EVENT_CODE_FIRST === true, codeOnly: root.EVENT_CODE_ONLY === true };          // 0166/0168 (Parámetros › Campos)
      const list = SC.search(users(), q, opts);
      const typed = String(text || '').trim().toLowerCase();
      if (typed) {                                                 // el código de la persona en el evento (serial del QR) también es una forma de encontrarla
        const byCode = users().filter((u) => u.code && String(u.code).toLowerCase() === typed && !list.some((r) => r.persona === u));
        byCode.forEach((u) => list.unshift({ persona: u, motivo: 'Código exacto', orden: 0 }));
      }
      return { q, list };
    }

    function draw(list, q) {
      results = list.slice(0, MAX_ROWS);
      if (!results.length) {
        box.innerHTML = q && q.kind !== 'vacio' ? '<p class="gw-hint">Sin coincidencias. Revisa la cédula o prueba con el nombre.</p>' : '';
        box.hidden = !box.innerHTML; return;
      }
      box.innerHTML = (list.length > MAX_ROWS ? `<p class="gw-hint">${list.length} coincidencias: se muestran las primeras ${MAX_ROWS}. Escribe más para afinar.</p>` : `<p class="gw-hint">${list.length} ${list.length === 1 ? 'coincidencia' : 'coincidencias'}</p>`)
        + results.map((r, i) => `<button type="button" data-pf="${i}">${esc(fullName(r.persona))} · ${esc(r.persona.id)}${r.persona.code ? ' · Código: ' + esc(r.persona.code) : ''}${r.persona.entity ? ' · ' + esc(r.persona.entity) : ''} <span class="gw-hint">${esc(r.motivo)}</span></button>`).join('');
      box.hidden = false;
    }

    function pick(u, via) { clear(); if (cfg.onPick) return cfg.onPick(u, via); }

    // Mientras se escribe: coincidencias en vivo (sin elegir nada). Una vCard o un enlace que llega de un lector no se busca a medias.
    input.addEventListener('input', () => {
      const raw = input.value;
      if (/^\s*(BEGIN:VCARD|MECARD:|https?:\/\/)/i.test(raw) || /\n/.test(raw)) return;
      const { q, list } = find(queryText(raw));
      if (q.kind === 'vacio') { clearList(); return; }
      draw(list, q);
    });

    box.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-pf]');
      if (!b) return;
      const r = results[parseInt(b.dataset.pf, 10)];
      if (r) { e.stopPropagation(); pick(r.persona, 'lista'); }
    });

    async function submit() {
      let raw = input.value.trim(); input.value = '';
      if (!raw) return;
      if (root.QrCode && QrCode.collect) { raw = QrCode.collect(raw); if (raw === null) return; }          // vCard con lector de mano: llega en varias líneas (la última la completa)
      let via = 'cedula';
      if (root.QrCode && QrCode.isDynamic && QrCode.isDynamic(raw)) {                                  // credencial digital: el servidor valida firma y vigencia y devuelve a la persona
        try { raw = await QrCode.resolveDynamic(raw, cfg.eventId == null ? root.EVENT_ID : cfg.eventId, cfg.purpose || 'entry'); via = 'qr'; }
        catch (err) { say((err && err.message) || 'No se pudo validar el código'); return; }
      }
      const text = queryText(raw);
      if (text !== raw) via = 'qr';                                                                         // venía envuelto (vCard, MECARD o enlace de Golden)
      const parsed = root.QrCode ? QrCode.parse(text) : null;
      if (parsed && parsed.isQr) via = 'qr';
      const { q, list } = find(text);
      if (q.kind === 'vacio') return;
      const docLike = (q.kind === 'cedula' && !q.corta && q.completa) || q.kind === 'lector' || q.kind === 'qr';
      if (list.length && list[0].motivo === 'Código exacto') { pick(list[0].persona, via); return; }                // el código de la persona en el evento identifica a una sola
      if (docLike && list.length && (list.length === 1 || list[0].orden === 0)) { pick(list[0].persona, via); return; }
      if (docLike && !list.length) {                                                                       // no está en la lista cargada: que el servidor responda (puede ser una persona nueva)
        const ced = (parsed && parsed.cedula) || q.cedula || text;
        clear(); if (cfg.onRaw) cfg.onRaw(String(ced).replace(/[.\s]/g, ''), via); return;
      }
      input.value = text.length < 120 ? text : '';                                                         // se deja lo buscado para afinarlo
      draw(list, q);
      if (!list.length) say('Sin coincidencias. Revisa la cédula o prueba con el nombre.');
    }

    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); submit(); } });
    box.hidden = true;
    return { submit, clear };
  }

  const api = { attach, queryText, nameFromForeignCard };
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.PersonFinder = api;
}(typeof self !== 'undefined' ? self : this));
