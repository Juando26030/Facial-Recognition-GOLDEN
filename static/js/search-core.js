/* Núcleo PURO del buscador único (Fase 1A, pieza 1): sin DOM, sin red, sin dependencias. Corre en el navegador (window.SearchCore) y en Node (module.exports).
   Todavía NO lo usa directory.js (se integra en un PR posterior); aquí solo vive la lógica y su prueba (tests/js/search_core_check.js).

   classifyQuery(texto) -> { kind, raw, cedula?, words, ... }
     kind: 'vacio' | 'cedula' | 'lector' | 'qr' | 'texto'
       - 'cedula': solo dígitos (con puntos, espacios o guiones de separador), 3 o más. `cedula` = clave normalizada (sin separadores ni ceros a la izquierda).
         `completa` = 5 o más dígitos: solo importa para el respaldo por huella de una fila local SIN cédula en claro (una huella no admite prefijos). Lector y QR siempre son completos.
       - 'lector': lo que escupe el lector de códigos de barras de la cédula vieja («1016100329,JHOAN,SEBASTIAN,ANGARITA,ROJAS,19980206») o un número con ceros a la izquierda.
       - 'qr': el QR de la escarapela («cédula|nombre|apellido»).
       - 'texto': todo lo demás; se busca como NOMBRE y como EMPRESA a la vez (prefijo de palabra).
   matchPerson(persona, consulta, opts) -> { coincide, motivo }
     motivo (corto, en español, para mostrar POR QUÉ coincidió): «Cédula exacta» | «Cédula (empieza por 123…)» | «Código del lector» | «Nombre» | «Empresa» | «Nombre y empresa»; '' si no coincide.
     orden (para ordenar resultados): 0 = cédula exacta o código del lector, 1 = cédula por prefijo, 1.5 = cédula que contiene lo escrito, 2 = nombre/empresa, 2.5 = nombre/empresa corrigiendo un error de tipeo. `search(personas, consulta, opts)` ya devuelve [{persona, motivo, orden}] así ordenado.
     persona: { id, first_name, last_name, entity } (directorio en línea) o una fila de la copia local (`__local`, `__h` = huella de la cédula).
     opts.cedulaPlain: cédula en claro de ESA fila (la descifra el llamador, en memoria, solo mientras busca); con ella una fila local también se busca por prefijo.
       Alternativa para recorrer una lista: opts.cedulaOf(persona) -> cédula en claro o ''. Este módulo NUNCA guarda ni cachea una cédula recibida por opts.
     opts.hash: huella (GC.hashFor) de la cédula consultada; respaldo de una fila local sin cédula en claro (copia vieja): ahí solo cabe la coincidencia EXACTA.
   Reglas: la búsqueda es PREDICTIVA con y sin red: desde 3 dígitos coincide toda cédula que EMPIECE por lo escrito y, después de esas, la que CONTENGA esos dígitos («345» lista a «1234567»: se busca por los últimos dígitos); la exacta sale primero.
   Nombre y empresa, por prefijo de palabra sin tildes ni mayúsculas, y tolerando errores de tipeo («jaun david» encuentra «Juan David»). */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SearchCore = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const MIN_PREFIX_DIGITS = 3;      // desde aquí la cédula se busca por prefijo (filas con cédula en claro)
  const MIN_CEDULA_DIGITS = 5;      // desde aquí la cédula se considera completa (huella exacta sin red)
  const MOTIVOS = { cedula: 'Cédula exacta', lector: 'Código del lector',
    prefijo: (digits) => 'Cédula (empieza por ' + digits + '…)', nombreContiene: 'Nombre (contiene lo escrito)', contiene: (digits) => 'Cédula (contiene ' + digits + ')', nombre: 'Nombre', empresa: 'Empresa', ambos: 'Nombre y empresa',
    codigo: 'Código exacto', codigoPrefijo: (t) => 'Código (empieza por ' + t + '…)', codigoContiene: (t) => 'Código (contiene ' + t + ')' };

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
     («0001.016.100-329» -> «1016100329»). Un documento con letras (pasaporte) solo pierde separadores y mayúsculas.
     Excepción (Plan 5, «No eliminar repetidos»): un SERIAL de cédula repetida, «123456-2» (documento de 5 o más caracteres + guion + 1 o 2 dígitos),
     conserva el guion: «123456-2» y «1234562» son personas distintas. Un guion con 3 o más dígitos detrás («1.016.100-329») sigue siendo solo separador. */
  const SERIAL_RE = /^([0-9a-z]{5,})-(\d{1,2})$/;
  function baseKey(s) { return /^\d+$/.test(s) ? s.replace(/^0+(?=\d)/, '') : s; }
  function cedulaKey(raw) {
    const s = String(raw == null ? '' : raw).replace(/[\s.]/g, '').toLowerCase();
    const m = SERIAL_RE.exec(s);
    if (m) return baseKey(m[1]) + '-' + m[2];
    return baseKey(s.replace(/-/g, ''));
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

  /* Fase 10 (C): el QR de la escarapela ahora es una vCard con el código en NOTE (static/js/vcard.js); si el lector la entrega entera se saca el código de adentro. Sin vcard.js cargado, no cambia nada. */
  function vcardLib() {
    return (typeof module !== 'undefined' && typeof require === 'function') ? (function () { try { return require('./vcard.js'); } catch (e) { return null; } })() : (typeof window !== 'undefined' ? window.GWVcard : null);
  }
  function unwrapVcard(text) {
    const v = vcardLib();
    return v ? v.unwrap(text) : text;
  }

  function classifyQuery(texto) {
    const original = String(texto == null ? '' : texto);
    const V = vcardLib();
    let raw = unwrapVcard(original);
    let card = null;
    if (V && V.isVcard && V.isVcard(original)) {
      // Lector 2D que teclea la vCard (con o sin saltos de línea): mientras llega no se busca nada; completa, se busca por el código de Golden (exacto, aunque sea corto) o, si es una vCard ajena, por el nombre.
      if (V.isPartial(original)) return { kind: 'vacio', raw: '', words: [], completa: false };
      card = V.parseCard(original);
      if (card && !card.golden) raw = card.name || '';
    }
    const text = raw.replace(/[\r\n\t]+/g, ' ').trim();
    if (!text) return { kind: 'vacio', raw, words: [], completa: false };
    if (card && card.golden && /^\d[\d.\s-]*$/.test(text)) return { kind: 'qr', raw, cedula: cedulaKey(text), words: [], completa: true };
    const qr = parseQr(text);
    if (qr !== null) return { kind: 'qr', raw, cedula: cedulaKey(qr), words: [], completa: true };
    const barcode = parseBarcode(text);
    if (barcode !== null) return { kind: 'lector', raw, cedula: cedulaKey(barcode), words: [], completa: true };
    if (/^[\d.\s-]+$/.test(text)) {
      const digits = text.replace(/\D/g, '');
      if (digits.length >= MIN_CEDULA_DIGITS && /^0\d/.test(digits)) {       // ceros a la izquierda: así rellena el número el lector de códigos
        return { kind: 'lector', raw, cedula: cedulaKey(digits), words: [], completa: true };
      }
      if (digits.length >= 1 && digits.length < MIN_PREFIX_DIGITS && /^\d+$/.test(text)) {       // 1-2 dígitos: ya se busca por el inicio de la cédula (no se acredita con Enter)
        return { kind: 'cedula', raw, cedula: cedulaKey(digits), words: [], completa: false, corta: true };
      }
      if (digits.length >= MIN_PREFIX_DIGITS) {
        const completa = digits.length >= MIN_CEDULA_DIGITS;
        const typed = cedulaKey(text);
        return { kind: 'cedula', raw, cedula: typed.includes('-') ? typed : cedulaKey(digits), words: [], completa };
      }
    }
    return { kind: 'texto', raw, words: wordsOf(text), normalized: normalize(text), compact: cedulaKey(text), completa: false };
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

  /* Distancia de edición con transposición (Damerau/OSA): «jaun» vs «juan» = 1. */
  const ROWS = [new Int32Array(66), new Int32Array(66), new Int32Array(66)];        // tres filas reutilizadas: sin crear arreglos por cada comparación (son miles por tecla)
  function editDistance(a, b, max) {
    if (a.length > 64) a = a.slice(0, 64);
    if (b.length > 64) b = b.slice(0, 64);
    let prev2 = ROWS[0], prev = ROWS[1], cur = ROWS[2];
    for (let j = 0; j <= b.length; j++) prev[j] = j;
    let prevMin = 0;
    for (let i = 1; i <= a.length; i++) {
      cur[0] = i;
      let curMin = i;
      for (let j = 1; j <= b.length; j++) {
        const cost = a.charCodeAt(i - 1) === b.charCodeAt(j - 1) ? 0 : 1;
        let v = prev[j] + 1;
        const ins = cur[j - 1] + 1, sub = prev[j - 1] + cost;
        if (ins < v) v = ins;
        if (sub < v) v = sub;
        if (i > 1 && j > 1 && a.charCodeAt(i - 1) === b.charCodeAt(j - 2) && a.charCodeAt(i - 2) === b.charCodeAt(j - 1) && prev2[j - 2] + 1 < v) v = prev2[j - 2] + 1;
        cur[j] = v;
        if (v < curMin) curMin = v;
      }
      if (max !== undefined && curMin > max && prevMin > max) return max + 1;          // ya no puede bajar de ahí
      const t = prev2; prev2 = prev; prev = cur; cur = t; prevMin = curMin;
    }
    return prev[b.length];
  }
  function shareStart(a, b) {                                                       // alguna de las 2 primeras letras de una está entre las 3 primeras de la otra
    for (let i = 0; i < 2 && i < a.length; i++) for (let j = 0; j < 3 && j < b.length; j++) if (a[i] === b[j]) return true;
    for (let i = 0; i < 2 && i < b.length; i++) for (let j = 0; j < 3 && j < a.length; j++) if (b[i] === a[j]) return true;
    return false;
  }
  function wordMatch(qw, hw) {
    if (hw.startsWith(qw)) return 2;
    if (hw.length >= 4 && qw.startsWith(hw)) return 1;
    const shortLen = Math.min(qw.length, hw.length);
    if (shortLen < 4 || /\d/.test(qw) || /\d/.test(hw)) return 0;
    const limit = shortLen <= 6 ? 1 : 2;
    if (hw.length + limit < qw.length) return 0;
    if (!shareStart(qw, hw)) return 0;                                              // filtro barato: un error de tipeo no cambia a la vez las 3 primeras letras
    if (Math.abs(qw.length - hw.length) <= limit && editDistance(qw, hw, limit) <= limit) return 1;
    return hw.length > qw.length && editDistance(qw, hw.slice(0, qw.length), limit) <= limit ? 1 : 0;       // mientras se escribe: contra el inicio de la palabra
  }

  /* Cada palabra escrita debe corresponder a una palabra DISTINTA de lo guardado, en cualquier orden.
     Devuelve 2 si todas fueron por prefijo exacto, 1 si alguna necesitó tolerancia, 0 si no coincide. Primero se prueba el prefijo exacto en todas
     las palabras (rápido) y solo si no alcanza se aplica la tolerancia. */
  function prefixMatch(haystack, queryWords) {
    if (!queryWords.length) return 0;
    const used = new Array(haystack.length).fill(false);
    let fuzzy = false;
    for (let q = 0; q < queryWords.length; q++) {
      let hit = -1, best = 0;
      for (let i = 0; i < haystack.length; i++) {
        if (used[i]) continue;
        if (haystack[i].startsWith(queryWords[q])) { hit = i; best = 2; break; }
      }
      if (hit < 0) {
        for (let i = 0; i < haystack.length; i++) {
          if (used[i]) continue;
          const m = wordMatch(queryWords[q], haystack[i]);
          if (m) { hit = i; best = m; break; }
        }
      }
      if (hit < 0) return 0;
      if (best < 2) fuzzy = true;
      used[hit] = true;
    }
    return fuzzy ? 1 : 2;
  }

  /* Cada palabra escrita (3 letras o más) está DENTRO de alguna palabra guardada. Solo se usa cuando no hubo coincidencia por inicio de palabra. */
  function containsMatch(haystack, queryWords) {
    if (!queryWords.length) return false;
    const used = new Array(haystack.length).fill(false);        // cada palabra escrita corresponde a una palabra DISTINTA
    for (let q = 0; q < queryWords.length; q++) {
      const w = queryWords[q];
      if (w.length < 3 || /^\d+$/.test(w)) return false;
      let found = -1;
      for (let i = 0; i < haystack.length && found < 0; i++) if (!used[i] && haystack[i].includes(w)) found = i;
      if (found < 0) return false;
      used[found] = true;
    }
    return true;
  }

  const NO = { coincide: false, motivo: '', orden: 9 };
  const hit = (motivo, orden) => ({ coincide: true, motivo, orden });

  /* 0166 (25-nov-2026): CÓDIGO de la persona (serial del QR, `persona.code`; solo viene si el evento usa código). Se compara sin mayúsculas ni espacios.
     opts.codeFirst = «Dar prioridad al código al buscar persona» (Parámetros › Campos): las coincidencias por código salen ANTES que las de cédula (orden negativo);
     sin la opción salen después de toda coincidencia por cédula y antes del nombre. Un lector 2D que teclea el código cae aquí igual que lo digitado. */
  function codeKey(raw) { return String(raw == null ? '' : raw).replace(/\s+/g, '').toLowerCase(); }
  const CODE_RANK = { first: [-3, -2, -1], last: [1.6, 1.7, 1.8] };
  function matchCode(persona, q, opts) {
    if (!persona || !persona.code || !q || q.kind === 'vacio') return NO;
    const typed = codeKey(q.raw);
    if (!typed) return NO;
    const code = codeKey(persona.code);
    const r = (opts && (opts.codeFirst || opts.codeOnly)) ? CODE_RANK.first : CODE_RANK.last;
    if (code === typed) return hit(MOTIVOS.codigo, r[0]);
    if (q.kind === 'lector' || q.kind === 'qr') return NO;                 // lo leído por lector es completo: solo cuenta el código exacto
    if (code.startsWith(typed)) return hit(MOTIVOS.codigoPrefijo(typed), r[1]);
    if (typed.length >= MIN_PREFIX_DIGITS && code.includes(typed)) return hit(MOTIVOS.codigoContiene(typed), r[2]);
    return NO;
  }
  function matchPerson(persona, consulta, opts) {
    if (!persona) return NO;
    const q = (consulta && typeof consulta === 'object') ? consulta : classifyQuery(consulta);
    if (q.kind === 'vacio') return NO;
    const byCode = matchCode(persona, q, opts);
    /* 0168: «Solo buscar por código»: lo escrito o leído en NÚMEROS solo se compara con el código (nunca con la cédula); los nombres se siguen buscando. */
    if (opts && opts.codeOnly && (q.kind === 'cedula' || q.kind === 'lector' || q.kind === 'qr')) return byCode;
    const other = matchPersonBase(persona, q, opts);
    if (!byCode.coincide) return other;
    return (!other.coincide || byCode.orden < other.orden) ? byCode : other;
  }
  function matchPersonBase(persona, q, opts) {
    if (q.kind === 'cedula' || q.kind === 'lector' || q.kind === 'qr') {
      const motivo = q.kind === 'cedula' ? MOTIVOS.cedula : MOTIVOS.lector;
      let id;
      if (persona.__local) {
        const plain = opts && (opts.cedulaPlain || (typeof opts.cedulaOf === 'function' ? opts.cedulaOf(persona) : ''));
        if (plain) id = cedulaKey(plain);                       // cédula en claro recibida por parámetro: no se guarda en ninguna parte
        else {                                                  // copia vieja sin cédula en claro: solo la huella, comparación EXACTA
          const h = opts && opts.hash;
          return q.completa && h && persona.__h === h ? hit(motivo, 0) : NO;
        }
      } else id = keysOf(persona).id;
      if (!q.cedula) return NO;
      if (id === q.cedula) return hit(motivo, 0);
      if (q.kind === 'cedula' && id.startsWith(q.cedula)) return hit(MOTIVOS.prefijo(q.cedula), 1);    // predictivo: solo con la cédula en claro
      if (q.kind === 'cedula' && q.cedula.length >= MIN_PREFIX_DIGITS && /^[0-9-]+$/.test(id) && id.includes(q.cedula)) return hit(MOTIVOS.contiene(q.cedula), 1.5);      // los últimos dígitos o un tramo del medio: después de los que empiezan igual
      return NO;
    }
    const k = keysOf(persona);
    // Documento con letras (pasaporte): se escribe como texto, pero si es IGUAL al documento guardado es cédula exacta.
    if (!persona.__local && q.compact && /\d/.test(q.compact) && /[a-z]/.test(q.compact) && k.id === q.compact) return hit(MOTIVOS.cedula, 0);
    const inName = prefixMatch(k.name, q.words), inEntity = prefixMatch(k.entity, q.words);
    const exact = (inName === 2 || inEntity === 2) ? 2 : 2.5;                       // lo escrito bien primero; lo que solo coincide corrigiendo un error de tipeo, después
    if (inName && inEntity) return hit(MOTIVOS.ambos, exact);
    if (inName) return hit(MOTIVOS.nombre, inName === 2 ? 2 : 2.5);
    if (inEntity) return hit(MOTIVOS.empresa, inEntity === 2 ? 2 : 2.5);
    if (containsMatch(k.name.concat(k.entity), q.words)) return hit(MOTIVOS.nombreContiene, 3);        // un tramo del medio de una palabra («lex» en «Alexander»): al final, para que nunca parezca que la búsqueda falla
    return NO;
  }

  /* Filtra y ordena: exacta > prefijo de cédula > nombre/empresa (estable: dentro de cada grupo se respeta el orden original). */
  function search(personas, consulta, opts) {
    const q = (consulta && typeof consulta === 'object') ? consulta : classifyQuery(consulta);
    const out = [];
    for (let i = 0; i < personas.length; i++) {
      const r = matchPerson(personas[i], q, opts);
      if (r.coincide) out.push({ persona: personas[i], motivo: r.motivo, orden: r.orden, i });
    }
    out.sort((a, b) => a.orden - b.orden || a.i - b.i);
    return out.map(({ persona, motivo, orden }) => ({ persona, motivo, orden }));
  }

  return { classifyQuery, matchPerson, search, cedulaKey, codeKey, normalize, wordsOf, prepare, MOTIVOS, MIN_CEDULA_DIGITS, MIN_PREFIX_DIGITS };
}));
