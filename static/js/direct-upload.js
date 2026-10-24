/* Subida directa al almacenamiento (app/uploads.py): pide una URL firmada, sube el archivo con PUT y devuelve el token que la
   petición normal manda EN VEZ del archivo. Así ningún archivo grande pasa por la app (Cloud Run corta las peticiones a 32 MiB).
   DirectUpload.upload(file, {signUrl, body, onProgress}) → token
   DirectUpload.replaceFiles(formData, {campoArchivo: [campoToken, propósito]}, {signUrl, body, onProgress}) → el mismo FormData */
(function () {
  // Cabeceras que un navegador se niega a fijar (fetch spec «forbidden header name»): setRequestHeader falla con «Refused to set unsafe header». Las firmadas que el navegador manda solo (Host) no hacen falta.
  const FORBIDDEN = /^(accept-charset|accept-encoding|access-control-request-headers|access-control-request-method|connection|content-length|cookie2?|date|dnt|expect|host|keep-alive|origin|referer|set-cookie|te|trailer|transfer-encoding|upgrade|via|proxy-.*|sec-.*)$/i;
  function put(sig, file, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open(sig.method || 'PUT', sig.url);
      Object.entries(sig.headers || {}).forEach(([k, v]) => { if (!FORBIDDEN.test(k)) xhr.setRequestHeader(k, v); });   // van firmados: se mandan tal cual, salvo las que el navegador no deja fijar (Host, Content-Length…: las pone él)
      xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded, e.total); };
      xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve()
        : reject(new Error(xhr.status === 413 || xhr.status === 400 ? 'El archivo supera el tamaño permitido' : `No se pudo subir el archivo (código ${xhr.status})`)));
      xhr.onerror = () => reject(new Error('Error de red al subir el archivo'));
      xhr.send(file);
    });
  }

  const timing = { sign_ms: 0, put_ms: 0, bytes: 0 };           // tiempos de la última subida (firma de la URL y envío al almacenamiento); los lee la pantalla de carga para su bitácora

  async function upload(file, { signUrl = '/api/uploads', body = {}, onProgress } = {}) {
    const t0 = performance.now();
    const res = await fetch(signUrl, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, filename: file.name, size: file.size, content_type: file.type || 'application/octet-stream' }),
    });
    const sig = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(sig.detail || 'No se pudo preparar la subida del archivo');
    const t1 = performance.now();
    await put(sig, file, onProgress);
    timing.sign_ms += t1 - t0; timing.put_ms += performance.now() - t1; timing.bytes += file.size;
    return sig.token;
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

  window.DirectUpload = { upload, replaceFiles, timing, _forbidden: FORBIDDEN };
})();
