// IndexedDB falso (lo mínimo que usa static/js/contingency.js: open/onupgradeneeded, object stores con keyPath, get/getAll/put/delete/clear y transacciones con oncomplete).
// Solo para las pruebas Node; NO es una prueba de un IndexedDB real (ver el reporte: lo que no se probó en un navegador).
function fakeIndexedDB() {
  const dbs = new Map();
  return {
    dbs,
    open(name) {
      const r = {};
      setImmediate(() => {
        let d = dbs.get(name);
        const isNew = !d;
        if (isNew) { d = { stores: new Map() }; dbs.set(name, d); }
        r.result = {
          createObjectStore(n, { keyPath }) { d.stores.set(n, { keyPath, data: new Map() }); return {}; },
          transaction(names) {
            const tx = { pending: 0, oncomplete: null };
            const finish = () => { if (tx.pending === 0) setImmediate(() => tx.oncomplete && tx.oncomplete()); };
            const op = (fn) => {
              const rq = {}; tx.pending++;
              const result = fn();
              setImmediate(() => { rq.result = result; if (rq.onsuccess) rq.onsuccess(); tx.pending--; finish(); });
              return rq;
            };
            tx.objectStore = (n) => {
              if (!names.includes(n)) throw new Error(`store ${n} fuera de la transacción`);
              const st = d.stores.get(n);
              return {
                get: (k) => op(() => { const v = st.data.get(k); return v === undefined ? undefined : structuredClone(v); }),
                getAll: () => op(() => [...st.data.values()].map((v) => structuredClone(v))),
                put: (v) => op(() => { st.data.set(v[st.keyPath], structuredClone(v)); return v[st.keyPath]; }),
                delete: (k) => op(() => { st.data.delete(k); }),
                clear: () => op(() => { st.data.clear(); }),
              };
            };
            return tx;
          },
          close() {},
        };
        if (isNew && r.onupgradeneeded) r.onupgradeneeded();
        if (r.onsuccess) r.onsuccess();
      });
      return r;
    },
  };
}
module.exports = { fakeIndexedDB };
