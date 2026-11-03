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
     orden (para ordenar resultados): 0 = cédula exacta o código del lector, 1 = cédula por prefijo, 2 = nombre/empresa. `search(personas, consulta, opts)` ya devuelve [{persona, motivo, orden}] así ordenado.
     persona: { id, first_name, last_name, entity } (directorio en línea) o una fila de la copia local (`__local`, `__h` = huella de la cédula).
     opts.cedulaPlain: cédula en claro de ESA fila (la descifra el llamador, en memoria, solo mientras busca); con ella una fila local también se busca por prefijo.
       Alternativa para recorrer una lista: opts.cedulaOf(persona) -> cédula en claro o ''. Este módulo NUNCA guarda ni cachea una cédula recibida por opts.
     opts.hash: huella (GC.hashFor) de la cédula consultada; respaldo de una fila local sin cédula en claro (copia vieja): ahí solo cabe la coincidencia EXACTA.
   Reglas: la búsqueda es PREDICTIVA con y sin red: desde 3 dígitos coincide toda cédula que EMPIECE por lo escrito (nunca subcadena: «345» no lista a «1234567»); la exacta sale primero.
   Nombre y empresa, por prefijo de palabra sin tildes ni mayúsculas. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SearchCore = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const MIN_PREFIX_DIGITS = 3;      // desde aquí la cédula se busca por prefijo (filas con cédula en claro)
  const MIN_CEDULA_DIGITS = 5;      // desde aquí la cédula se considera completa (huella exacta sin red)
  const MOTIVOS = { cedula: 'Cédula exacta', lector: 'Código del lector',
    prefijo: (digits) => 'Cédula (empieza por ' + digits + '…)', nombre: 'Nombre', empresa: 'Empresa', ambos: 'Nombre y empresa' };

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
    if (!text) return { kind: 'vacio', raw, words: [], completa: false };
    const qr = parseQr(text);
    if (qr !== null) return { kind: 'qr', raw, cedula: cedulaKey(qr), words: [], completa: true };
    const barcode = parseBarcode(text);
    if (barcode !== null) return { kind: 'lector', raw, cedula: cedulaKey(barcode), words: [], completa: true };
    if (/^[\d.\s-]+$/.test(text)) {
      const digits = text.replace(/\D/g, '');
      if (digits.length >= MIN_CEDULA_DIGITS && /^0\d/.test(digits)) {       // ceros a la izquierda: así rellena el número el lector de códigos
        return { kind: 'lector', raw, cedula: cedulaKey(digits), words: [], completa: true };
      }
      if (digits.length >= MIN_PREFIX_DIGITS) {
        const completa = digits.length >= MIN_CEDULA_DIGITS;
        return { kind: 'cedula', raw, cedula: cedulaKey(digits), words: [], completa };
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

  const NO = { coincide: false, motivo: '', orden: 9 };
  const hit = (motivo, orden) => ({ coincide: true, motivo, orden });
  function matchPerson(persona, consulta, opts) {
    if (!persona) return NO;
    const q = (consulta && typeof consulta === 'object') ? consulta : classifyQuery(consulta);
    if (q.kind === 'vacio') return NO;
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
      return NO;
    }
    const k = keysOf(persona);
    // Documento con letras (pasaporte): se escribe como texto, pero si es IGUAL al documento guardado es cédula exacta.
    if (!persona.__local && q.compact && /\d/.test(q.compact) && /[a-z]/.test(q.compact) && k.id === q.compact) return hit(MOTIVOS.cedula, 0);
    const inName = prefixMatch(k.name, q.words), inEntity = prefixMatch(k.entity, q.words);
    if (inName && inEntity) return hit(MOTIVOS.ambos, 2);
    if (inName) return hit(MOTIVOS.nombre, 2);
    if (inEntity) return hit(MOTIVOS.empresa, 2);
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

  return { classifyQuery, matchPerson, search, cedulaKey, normalize, wordsOf, prepare, MOTIVOS, MIN_CEDULA_DIGITS, MIN_PREFIX_DIGITS };
}));
