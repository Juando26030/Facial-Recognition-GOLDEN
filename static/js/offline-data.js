/* Datos para trabajar SIN RED en Control de áreas y Control de inventario (25-nov-2026, docs/28_CONTINGENCIA_COMPLETA.md).
   - `GWOff.json(url)`: pide al servidor como siempre y guarda la respuesta CIFRADA en el dispositivo (contingency.js › cache); si la red falla, devuelve la última copia (o lanza si no hay).
   - `GWOff.users()`: la base de personas del evento; con red se guarda como copia completa (la misma del Registro) y sin red sale de ahí.
   - `GWOff.send(url, opts, label, fake, expect)`: un cambio (POST…). Con red es el fetch de siempre; sin red se guarda en la bandeja de salida y se repite al volver la conexión.
   - Reglas puras de Áreas sin red (`areaDecide`) y de inventario asignado (`assignedView`, `assignedDeliver`), probadas en Node (tests/js/offline_data_check.js).
   No hay rutas nuevas para esto salvo el paquete de asignaciones y dependientes (GET /api/events/{id}/offline-pack), que se pide una vez al abrir la pantalla. */
(function (root) {
  'use strict';
  const gc = () => root.GoldenContingency && root.GoldenContingency.instance;
  const ready = async () => { const g = gc(); if (!g) return null; try { await g.ready; } catch (e) { return null; } return g.supported ? g : null; };
  const off = () => { const g = gc(); return !!(g && g.active && g.active()); };
  const netError = (e) => !e || e.name === 'TypeError' || e.name === 'AbortError' || /fetch|network|red/i.test(String(e.message || ''));

  async function json(url, opts) {
    const key = (opts && opts.key) || url;
    if (!off()) {
      try {
        const res = await root.fetch(url);
        if (!res.ok) { const err = new Error('http ' + res.status); err.status = res.status; throw err; }
        const data = await res.json();
        const g = await ready(); if (g) g.cachePut(key, data);
        return data;
      } catch (e) { if (e && e.status) throw e; }
    }
    const g = await ready();
    const hit = g ? await g.cacheGet(key) : null;
    if (hit == null) throw new Error('Sin conexión y sin una copia de estos datos en el dispositivo');
    return hit;
  }
  async function put(key, data) { const g = await ready(); return g ? g.cachePut(key, data) : false; }
  async function get(key) { const g = await ready(); return g ? g.cacheGet(key) : null; }

  async function users() {
    const url = `/api/users?event_id=${root.EVENT_ID}`;
    if (!off()) {
      try {
        const res = await root.fetch(url);
        if (!res.ok) { const err = new Error('http ' + res.status); err.status = res.status; throw err; }
        const rows = await res.json();
        const g = await ready(); if (g && g.peopleSave && root.STAFF_ROLE !== 'cliente') g.peopleSave(rows);
        return rows;
      } catch (e) { if (e && e.status) throw e; }
    }
    const g = await ready();
    const rows = g && g.peopleLoad ? await g.peopleLoad() : null;
    if (!rows) throw new Error('Sin conexión y sin la base de personas en el dispositivo');
    return rows;
  }

  /* Un cambio: con red, fetch; sin red (o si la red falla a mitad), a la bandeja de salida. `expect` = valores de `result` que cuentan como hecho al repetirlo (p. ej. ['OK']). */
  async function send(url, opts, label, fake, expect) {
    const box = root.GoldenOutbox && root.GoldenOutbox.instance;
    const queue = async () => { await box.enqueueHttp(url, Object.assign({}, opts, expect ? { expect } : null), label); return { ok: true, status: 202, queued: true, json: async () => fake || {} }; };
    if (off() && box && box.supported) return queue();
    try { return await root.fetch(url, opts); }
    catch (e) { if (box && box.supported && netError(e)) return queue(); throw e; }
  }

  /* ---------------- Control de áreas sin red (misma respuesta que POST …/movement; reglas de app/routers/areas_inventory.py › _apply_movement que se pueden comprobar en el dispositivo:
     alternar entrada/salida, «no está adentro» y «sin reingresos» (propio o del grupo). El máximo de entradas por persona lo revisa el servidor al recibirlo. `presence` = {id_zona: {cédula: 'in'|'out'}}. */
  function areaDecide(o) {
    const area = o.area, parent = o.parent || null, pres = o.presence || {}, uid = String(o.user.id);
    const mine = pres[area.id] || {}, last = mine[uid];
    let direction = o.direction;
    if (direction === 'auto' || !direction) direction = last === 'in' ? 'out' : 'in';
    const data = { id: o.user.id, first_name: o.user.first_name || '', last_name: o.user.last_name || '' };
    const who = `${data.first_name} ${data.last_name}`.trim();
    const label = parent ? `${parent.name} › ${area.name}` : area.name;
    if (direction === 'in') {
      const groupNo = !!(parent && !parent.allow_reentry);
      if (groupNo || !area.allow_reentry) {
        const scope = groupNo ? (o.siblings || [area]).map((a) => a.id) : [area.id];
        if (scope.some((id) => (pres[id] || {})[uid])) return { result: 'ALREADY_ENTERED', direction: 'in', area: label, data, details: `${who} YA había entrado a «${groupNo ? parent.name : area.name}» y esta zona no permite reingresos` };
      }
    }
    if (direction === 'out' && last !== 'in') return { result: 'NOT_INSIDE', direction: 'out', area: label, data, details: `${who} no figura adentro de «${label}»` };
    if (!o.autoRegister && !o.autoScan && !o.confirm) return { result: 'FOUND_PENDING', direction, area: label, data };
    return { result: 'OK', direction, area: label, data, time: new Date(o.now || Date.now()).toISOString().replace(/Z$/, '') };
  }

  /* ---------------- Inventario «lo define la base» sin red. `pack.assigned[cédula]` = las líneas que devuelve GET …/inventory/assigned; lo entregado en este dispositivo se suma encima. */
  function assignedView(pack, user, localDone) {
    const base = ((pack && pack.assigned) || {})[String(user.id)] || [];
    const done = localDone || {};
    const lines = base.map((l) => { const extra = done[l.key] || 0, delivered = (l.delivered || 0) + extra, pending = Math.max((l.qty || 0) - delivered, 0); return Object.assign({}, l, { delivered, pending, available: (l.available || 0) - extra, done: pending === 0 && (l.qty || 0) > 0 }); });
    return { person: { id: user.id, first_name: user.first_name, last_name: user.last_name, entity: user.entity }, registered: user.status !== 'No registrado', lines, pending: lines.filter((l) => l.pending > 0 && !l.problem).length };
  }
  /* Qué asignaciones se entregan con este toque: las pedidas (o todas las pendientes), sin las que tienen problema, ya están entregadas o no tienen existencias. */
  function assignedDeliver(view, body) {
    const want = body && body.all ? null : new Set((body && body.keys) || []);
    const lines = view.lines.filter((l) => l.pending > 0 && !l.problem && l.available >= l.pending && (!want || want.has(l.key)));
    return { keys: lines.map((l) => l.key), delivered: lines.map((l) => ({ qty: l.pending, name: l.item_name || l.product, who: l.dependent ? (l.who || 'dependiente') : '' })) };
  }

  const api = { json, put, get, users, send, off, areaDecide, assignedView, assignedDeliver };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.GWOff = api;
})(typeof window !== 'undefined' ? window : globalThis);
