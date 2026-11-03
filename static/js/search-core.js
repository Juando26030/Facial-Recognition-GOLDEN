/* Núcleo PURO del buscador único (Fase 1A, pieza 1): sin DOM, sin red, sin dependencias. Corre en el navegador (window.SearchCore) y en Node (module.exports).
   Todavía NO lo usa directory.js (se integra en un PR posterior); aquí solo vive la lógica y su prueba (tests/js/search_core_check.js).

   classifyQuery(texto) -> { kind, raw, cedula?, words, ... }
     kind: 'vacio' | 'cedula' | 'lector' | 'qr' | 'texto'
       - 'cedula': solo dígitos (con puntos, espacios o guiones de separador), 5 o más dígitos. `cedula` = clave normalizada (sin separadores ni ceros a la izquierda).
       - 'lector': lo que escupe el lector de códigos de barras de la cédula vieja («1016100329,JHOAN,SEBASTIAN,ANGARITA,ROJAS,19980206») o un número con ceros a la izquierda.
       - 'qr': el QR de la escarapela («cédula|nombre|apellido»).
       - 'texto': todo lo demás; se busca como NOMBRE y como EMPRESA a la vez (prefijo de palabra).
   matchPerson(persona, consulta, opts) -> { coincide, motivo }
     motivo (corto, en español, para mostrar POR QUÉ coincidió): «Cédula exacta» | «Código del lector» | «Nombre» | «Empresa» | «Nombre y empresa»; '' si no coincide.
     persona: { id, first_name, last_name, entity } (directorio en línea) o una fila de la copia local (`__local`, `__h` = huella de la cédula, sin entidad).
     opts.hash: huella (GC.hashFor) de la cédula consultada; solo hace falta con filas locales, que NO guardan la cédula: ahí la comparación es por huella EXACTA.
   Reglas (decisión D2): la cédula SIEMPRE es coincidencia EXACTA (nunca subcadena: «12345» no lista a «1234567»); nombre y empresa, por prefijo de palabra sin tildes ni mayúsculas. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SearchCore = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const MIN_CEDULA_DIGITS = 5;
  const MOTIVOS = { cedula: 'Cédula exacta', lector: 'Código del lector', nombre: 'Nombre', empresa: 'Empresa', ambos: 'Nombre y empresa' };

  function stripAccents(text) {
    return String(text == null ? '' : text).normalize('NFD').replace(/[̀-ͯ]/g, '');
  }
  function normalize(text) {                                    // minúsculas, sin tildes y con espacios simples
    return stripAccents(text).toLowerCase().replace(/\s+/g, ' ').trim();
  }
  function wordsOf(text) {
    return stripAccents(text).toLowerCase().match(/[a-z0-9]+/g) || [];
  }

  /* Clave de comparación de una cédula: sin puntos, espacios ni guiones, y sin ceros a la izquierda si es numérica
     («0001.016.100-329» -> «1016100329»). Un documento con letras (pasaporte) solo pierde separadores y mayúsculas. */
  function cedulaKey(raw) {
    const s = String(raw == null ? '' : raw).replace(/[\s.\-]/g, '').toLowerCase();
    return /^\d+$/.test(s) ? s.replace(/^0+(?=\d)/, '') : s;
  }

  /* Cédula vieja (código de barras): CSV «cedula,nombre1,nombre2,apellido1,apellido2,AAAAMMDD». Devuelve la cédula o null. */
  function parseBarcode(text) {
    if (!text.includes(',')) return null;
    const parts = text.split(',');
    if (parts.length < 5) return null;
    const first = parts[0].trim();
    return /^\d[\d.\s-]*$/.test(first) ? first : null;
  }
  /* QR de la escarapela: «cédula|nombre|apellido» (la cédula es la parte numérica de 4+ dígitos; si no hay, la primera). */
  function parseQr(text) {
    if (!text.includes('|')) return null;
    const parts = text.split('|').map((p) => p.trim()).filter(Boolean);
    if (!parts.length) return null;
    const found = parts.find((p) => /^\d[\d.\s-]{2,}\d$/.test(p) && p.replace(/\D/g, '').length >= 4);
    return found === undefined ? parts[0] : found;
  }

  function classifyQuery(texto) {
    const raw = String(texto == null ? '' : texto);
    const text = raw.replace(/[\r\n\t]+/g, ' ').trim();
    if (!text) return { kind: 'vacio', raw, words: [] };
    const qr = parseQr(text);
    if (qr !== null) return { kind: 'qr', raw, cedula: cedulaKey(qr), words: [] };
    const barcode = parseBarcode(text);
    if (barcode !== null) return { kind: 'lector', raw, cedula: cedulaKey(barcode), words: [] };
    if (/^[\d.\s-]+$/.test(text)) {
      const digits = text.replace(/\D/g, '');
      if (digits.length >= MIN_CEDULA_DIGITS) {
        // Ceros a la izquierda: así rellena el número el lector de códigos.
        return { kind: /^0\d/.test(digits) ? 'lector' : 'cedula', raw, cedula: cedulaKey(digits), words: [] };
      }
    }
    return { kind: 'texto', raw, words: wordsOf(text), normalized: normalize(text), compact: cedulaKey(text) };
  }

  /* Lo que se compara de cada persona se calcula UNA vez (con 10.000 personas, una tecla no puede volver a normalizar a todas). */
  const keysCache = new WeakMap();
  function keysOf(p) {
    let k = keysCache.get(p);
    if (!k) {
      k = { id: cedulaKey(p.id), name: wordsOf((p.first_name || '') + ' ' + (p.last_name || '') + (p.first_name ? '' : ' ' + (p.n || ''))), entity: wordsOf(p.entity) };
      keysCache.set(p, k);
    }
    return k;
  }
  function prepare(personas) { for (let i = 0; i < personas.length; i++) keysOf(personas[i]); return personas; }

  /* Cada palabra escrita debe ser prefijo de una palabra DISTINTA de lo guardado, en cualquier orden. */
  function prefixMatch(haystack, queryWords) {
    if (!queryWords.length) return false;
    const used = new Array(haystack.length).fill(false);
    for (let q = 0; q < queryWords.length; q++) {
      let hit = -1;
      for (let i = 0; i < haystack.length; i++) if (!used[i] && haystack[i].startsWith(queryWords[q])) { hit = i; break; }
      if (hit < 0) return false;
      used[hit] = true;
    }
    return true;
  }

  const NO = { coincide: false, motivo: '' };
  function matchPerson(persona, consulta, opts) {
    if (!persona) return NO;
    const q = (consulta && typeof consulta === 'object') ? consulta : classifyQuery(consulta);
    if (q.kind === 'vacio') return NO;
    if (q.kind === 'cedula' || q.kind === 'lector' || q.kind === 'qr') {
      const motivo = q.kind === 'cedula' ? MOTIVOS.cedula : MOTIVOS.lector;
      if (persona.__local) {                                    // fila de la copia local: no guarda la cédula, solo su huella (comparación exacta)
        const h = opts && opts.hash;
        return h && persona.__h === h ? { coincide: true, motivo } : NO;
      }
      return q.cedula && keysOf(persona).id === q.cedula ? { coincide: true, motivo } : NO;
    }
    const k = keysOf(persona);
    // Documento con letras (pasaporte): se escribe como texto, pero si es IGUAL al documento guardado es cédula exacta.
    if (!persona.__local && q.compact && /\d/.test(q.compact) && /[a-z]/.test(q.compact) && k.id === q.compact) return { coincide: true, motivo: MOTIVOS.cedula };
    const inName = prefixMatch(k.name, q.words), inEntity = prefixMatch(k.entity, q.words);
    if (inName && inEntity) return { coincide: true, motivo: MOTIVOS.ambos };
    if (inName) return { coincide: true, motivo: MOTIVOS.nombre };
    if (inEntity) return { coincide: true, motivo: MOTIVOS.empresa };
    return NO;
  }

  return { classifyQuery, matchPerson, cedulaKey, normalize, wordsOf, prepare, MOTIVOS, MIN_CEDULA_DIGITS };
}));
