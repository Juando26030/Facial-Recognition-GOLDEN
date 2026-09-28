/* Subida directa al almacenamiento (app/uploads.py): pide una URL firmada, sube el archivo con PUT y devuelve el token que la
   petición normal manda EN VEZ del archivo. Así ningún archivo grande pasa por la app (Cloud Run corta las peticiones a 32 MiB).
   DirectUpload.upload(file, {signUrl, body, onProgress}) → token
   DirectUpload.replaceFiles(formData, {campoArchivo: [campoToken, propósito]}, {signUrl, body, onProgress}) → el mismo FormData */
(function () {
  function put(sig, file, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open(sig.method || 'PUT', sig.url);
      Object.entries(sig.headers || {}).forEach(([k, v]) => xhr.setRequestHeader(k, v));   // van firmados: se mandan tal cual
      xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded, e.total); };
      xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve()
        : reject(new Error(xhr.status === 413 || xhr.status === 400 ? 'El archivo supera el tamaño permitido' : `No se pudo subir el archivo (código ${xhr.status})`)));
      xhr.onerror = () => reject(new Error('Error de red al subir el archivo'));
      xhr.send(file);
    });
  }

  async function upload(file, { signUrl = '/api/uploads', body = {}, onProgress } = {}) {
    const res = await fetch(signUrl, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, filename: file.name, size: file.size, content_type: file.type || 'application/octet-stream' }),
    });
    const sig = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(sig.detail || 'No se pudo preparar la subida del archivo');
    await put(sig, file, onProgress);
    return sig.token;
  }

  async function replaceFiles(fd, map, { signUrl, body = {}, onProgress } = {}) {
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

  window.DirectUpload = { upload, replaceFiles };
})();
