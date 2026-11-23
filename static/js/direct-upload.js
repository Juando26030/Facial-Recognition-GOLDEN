/* Subida directa al almacenamiento (app/uploads.py): pide una URL firmada, sube el archivo con PUT y devuelve el token que la
   petición normal manda EN VEZ del archivo. Así ningún archivo grande pasa por la app (Cloud Run corta las peticiones a 32 MiB).
   DirectUpload.upload(file, {signUrl, body, onProgress}) → token
   DirectUpload.replaceFiles(formData, {campoArchivo: [campoToken, propósito]}, {signUrl, body, onProgress}) → el mismo FormData
   Hotfix 21-nov-2026 (formulario del evento 14, «Error de red al subir el archivo» en celulares):
   - el archivo se COPIA A MEMORIA al elegirlo: en Android, un PDF tomado de Drive/WhatsApp/Descargas puede dejar de poderse leer mientras la persona llena el resto
     del formulario, y el navegador lo reporta como «error de red»;
   - si la conexión se corta (datos del celular, señal débil), se reintenta solo, pidiendo una URL nueva cada vez (4 intentos con espera creciente);
   - si al final no sube, el mensaje dice qué hacer y lo escrito no se pierde. */
(function () {
  // Cabeceras que un navegador se niega a fijar (fetch spec «forbidden header name»): setRequestHeader falla con «Refused to set unsafe header». Las firmadas que el navegador manda solo (Host) no hacen falta.
  const FORBIDDEN = /^(accept-charset|accept-encoding|access-control-request-headers|access-control-request-method|connection|content-length|cookie2?|date|dnt|expect|host|keep-alive|origin|referer|set-cookie|te|trailer|transfer-encoding|upgrade|via|proxy-.*|sec-.*)$/i;
  const ATTEMPTS = 4;
  const WAIT_MS = [0, 1500, 4000, 8000];
  const MAX_COPY = 60 * 1024 * 1024;                       // archivos más grandes (cargas masivas) no se copian a memoria
  const copies = new WeakMap();                            // File elegido → copia en memoria (se lee siempre igual aunque el original ya no se pueda abrir)
  const pending = new WeakMap();                           // File → promesa de su copia (si la persona envía antes de que termine de copiarse)

  function netError(retry) { const e = new Error('network'); e.retry = retry; return e; }

  function readCopy(file) {
    if (!file || typeof file.arrayBuffer !== 'function' || typeof Blob === 'undefined' || file.size > MAX_COPY) return Promise.resolve(file);
    if (copies.has(file)) return Promise.resolve(copies.get(file));
    if (pending.has(file)) return pending.get(file);
    const p = file.arrayBuffer().then((buf) => {
      const copy = typeof File !== 'undefined' ? new File([buf], file.name, { type: file.type, lastModified: file.lastModified }) : new Blob([buf], { type: file.type });
      copies.set(file, copy); pending.delete(file); return copy;
    }, (err) => { pending.delete(file); throw err; });
    pending.set(file, p);
    return p;
  }

  // Copia al elegir el archivo (antes de que Android le quite el permiso). Si falla aquí no pasa nada: se vuelve a intentar al enviar.
  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('change', (e) => {
      const input = e.target;
      if (input && input.type === 'file' && input.files) Array.from(input.files).forEach((f) => readCopy(f).catch(() => {}));
    }, true);
  }

  function put(sig, file, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open(sig.method || 'PUT', sig.url);
      Object.entries(sig.headers || {}).forEach(([k, v]) => { if (!FORBIDDEN.test(k)) xhr.setRequestHeader(k, v); });   // van firmados: se mandan tal cual, salvo las que el navegador no deja fijar (Host, Content-Length…: las pone él)
      xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded, e.total); };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) return resolve();
        if (xhr.status === 413) return reject(new Error('El archivo supera el tamaño permitido'));
        if (xhr.status >= 500 || xhr.status === 408 || xhr.status === 429 || xhr.status === 400 || xhr.status === 403) return reject(netError(true));   // 400/403: URL vencida o cortada a mitad: con una URL nueva se puede
        reject(new Error(`No se pudo subir el archivo (código ${xhr.status})`));
      };
      xhr.onerror = () => reject(netError(true));
      xhr.ontimeout = () => reject(netError(true));
      xhr.onabort = () => reject(netError(true));
      xhr.send(file);
    });
  }

  const timing = { sign_ms: 0, put_ms: 0, bytes: 0 };           // tiempos de la última subida (firma de la URL y envío al almacenamiento); los lee la pantalla de carga para su bitácora
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function upload(file, { signUrl = '/api/uploads', body = {}, onProgress } = {}) {
    const name = (file && file.name) || 'archivo';
    let data;
    try { data = await readCopy(file); } catch (e) {
      throw new Error(`No se pudo leer el archivo «${name}» en este celular. Vuelve a elegirlo (si está en Drive o WhatsApp, descárgalo primero) e intenta de nuevo.`);
    }
    let lastErr = null;
    for (let attempt = 0; attempt < ATTEMPTS; attempt++) {
      if (WAIT_MS[attempt]) await sleep(WAIT_MS[attempt]);
      const t0 = performance.now();
      let res, sig;
      try {
        res = await fetch(signUrl, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...body, filename: name, size: file.size, content_type: file.type || 'application/octet-stream' }),
        });
        sig = await res.json().catch(() => ({}));
      } catch (e) { lastErr = netError(true); continue; }                 // sin conexión al pedir la URL: se reintenta
      if (!res.ok) {
        if (res.status >= 500 || res.status === 429) { lastErr = netError(true); continue; }
        throw new Error(sig.detail || 'No se pudo preparar la subida del archivo');   // tamaño, formato, formulario cerrado…: reintentar no sirve
      }
      const t1 = performance.now();
      try {
        await put(sig, data, onProgress);
      } catch (e) {
        if (!e.retry) throw e;
        lastErr = e; continue;
      }
      timing.sign_ms += t1 - t0; timing.put_ms += performance.now() - t1; timing.bytes += file.size;
      return sig.token;
    }
    throw new Error(`No se pudo subir «${name}»: se cortó la conexión. Revisa tu internet (o acércate a una red Wi-Fi) y vuelve a pulsar el botón; lo que escribiste no se pierde.`, { cause: lastErr });
  }

  async function replaceFiles(fd, map, { signUrl, body = {}, onProgress } = {}) {
    timing.sign_ms = timing.put_ms = timing.bytes = 0;
    const items = Object.entries(map).map(([name, [tokenName, purpose]]) => ({ name, tokenName, purpose, file: fd.get(name) }));
    const todo = items.filter((it) => it.file instanceof Blob && it.file.size);
    const total = todo.reduce((sum, it) => sum + it.file.size, 0);
    let before = 0;
    for (const it of todo) {
      const token = await upload(it.file, { signUrl, body: { ...body, purpose: it.purpose }, onProgress: (loaded) => onProgress && onProgress(before + loaded, total) });
      before += it.file.size;
      fd.set(it.tokenName, token);
    }
    items.forEach((it) => fd.delete(it.name));            // ni el archivo ni un <input type=file> vacío viajan en la petición
    return fd;
  }

  window.DirectUpload = { upload, replaceFiles, timing, _forbidden: FORBIDDEN, _readCopy: readCopy };
})();
