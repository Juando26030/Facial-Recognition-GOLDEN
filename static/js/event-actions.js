/* Cuadrito de acciones de un evento (Calendario, Fase 2 entrega 1).
   Al tocar un evento se abre un cuadrito anclado a él con LAS MISMAS acciones de la fila de Eventos / Clientes, con los mismos permisos:
     Ingresar (todos) · Editar (todos) · Cambiar estado (todos; «En proceso» -> «Creado» solo admin y super_admin, con su ventana de motivo)
     · Devolver a Creado (admin, super_admin; solo si está «En proceso») · Exportar (solo super_admin) · Eliminar (admin, super_admin).
   Lo que el rol no puede NO aparece (el servidor sigue siendo quien manda: cada ruta vuelve a validar el rol).
   Reutiliza: openEventEditModal (_event_edit_modal.html), revertEventToCreated (revert-event.js), data-export-event (event-transfer.js, por delegación),
   confirmStatusChange / showConfirm / showToast (toast.js) y GW.busy (gw-busy.js).
   En pantallas angostas (<= 40rem) el cuadrito pasa a hoja inferior con fondo atenuado. Escape o clic fuera lo cierran y el foco vuelve al evento. */
(function (root, factory) {
  var api = factory(root);
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.EventActions = api;
})(typeof window !== 'undefined' ? window : this, function (globalRoot) {
  'use strict';

  var STATUS_LABELS = { creado: 'Creado', en_proceso: 'En Proceso', finalizado: 'Finalizado' };
  var STATUS_BADGE = { creado: 'gw-badge--info', en_proceso: 'gw-badge--ok', finalizado: '' };
  var NARROW = '(max-width: 40rem)';

  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]; }); }

  /* Parte pura (probada en tests/js/event_actions_check.js): qué acciones le tocan a un rol sobre un evento. */
  function actionsFor(ev, role) {
    var isAdmin = role === 'admin' || role === 'super_admin';
    var acts = [
      { id: 'enter', label: 'Ingresar', icon: 'home', href: '/kiosk/' + ev.id },
      { id: 'edit', label: 'Editar', icon: 'edit' },
      { id: 'status', label: 'Estado', icon: 'clock', status: ev.status }
    ];
    if (isAdmin && ev.status === 'en_proceso') acts.push({ id: 'revert', label: 'Devolver a Creado', icon: 'undo' });
    if (role === 'super_admin') acts.push({ id: 'export', label: 'Exportar', icon: 'download' });
    if (isAdmin) acts.push({ id: 'delete', label: 'Eliminar', icon: 'trash', danger: true });
    return acts;
  }

  function create(cfg) {
    var root = cfg.env || globalRoot;          // `env` solo lo usan las pruebas (DOM falso)
    var doc = root.document;
    var role = cfg.role;
    var icon = cfg.icon || function () { return ''; };
    var scrim = doc.createElement('div');
    scrim.className = 'cal-pop-scrim';
    scrim.hidden = true;
    var panel = doc.createElement('div');
    panel.className = 'gw-popover cal-pop';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.hidden = true;
    doc.body.appendChild(scrim);
    doc.body.appendChild(panel);

    var current = null;      // { ev, opener }

    function isOpen() { return !panel.hidden; }
    function focusables() {
      return Array.prototype.filter.call(panel.querySelectorAll('a[href], button:not([disabled]), select:not([disabled])'), function (x) { return x.offsetWidth || x.offsetHeight; });
    }

    function html(ev) {
      var acts = actionsFor(ev, role);
      var items = acts.map(function (a) {
        if (a.id === 'status') {
          return '<div class="cal-pop__row"><label class="gw-label" for="calPopStatus">Cambiar estado</label>' +
            '<select class="gw-select" id="calPopStatus" data-pop-status data-event-id="' + esc(ev.id) + '" data-initial="' + esc(ev.status) + '">' +
            Object.keys(STATUS_LABELS).map(function (v) { return '<option value="' + v + '"' + (v === ev.status ? ' selected' : '') + '>' + STATUS_LABELS[v] + '</option>'; }).join('') +
            '</select></div>';
        }
        var inner = icon(a.icon, 'gw-icon--sm') + ' ' + esc(a.label);
        if (a.href) return '<a class="gw-menu__item" href="' + esc(a.href) + '">' + inner + '</a>';
        var attr = { edit: 'data-pop-edit', revert: 'data-revert-event="' + esc(ev.id) + '"', export: 'data-export-event="' + esc(ev.id) + '" data-event-name="' + esc(ev.name) + '"', 'delete': 'data-pop-delete' }[a.id];
        return '<button type="button" class="gw-menu__item' + (a.danger ? ' gw-menu__item--danger' : '') + '" ' + attr + '>' + inner + '</button>';
      });
      var meta = [ev.tenant_name, ev.event_code ? 'Código ' + ev.event_code : ''].filter(Boolean).join(' · ');
      return '<div class="cal-pop__head"><div class="cal-pop__titles"><p class="gw-popover__title" id="calPopTitle">' + esc(ev.name) + '</p>' +
        (meta ? '<p class="gw-muted cal-pop__meta">' + esc(meta) + '</p>' : '') + '</div>' +
        '<span class="gw-badge ' + (STATUS_BADGE[ev.status] || '') + '">' + esc(STATUS_LABELS[ev.status] || ev.status) + '</span></div>' +
        '<div class="cal-pop__list" role="group" aria-label="Acciones del evento">' + items.join('') + '</div>' +
        '<button type="button" class="gw-btn gw-btn--secondary gw-btn--sm cal-pop__close" data-pop-close>Cerrar</button>';
    }

    function position(anchor) {
      if (root.matchMedia && root.matchMedia(NARROW).matches) { panel.style.left = ''; panel.style.top = ''; return; }          // hoja inferior: la coloca el CSS
      var r = anchor.getBoundingClientRect();
      var w = panel.offsetWidth, h = panel.offsetHeight, vw = root.innerWidth, vh = root.innerHeight, gap = 4;
      var left = Math.max(gap, Math.min(r.left, vw - w - gap));
      var top = r.bottom + gap;
      if (top + h > vh - gap && r.top - h - gap >= gap) top = r.top - h - gap;          // no cabe abajo: encima del evento
      panel.style.left = left + 'px';
      panel.style.top = Math.max(gap, top) + 'px';
    }

    function open(opener, ev) {
      if (isOpen()) close(false);
      current = { ev: ev, opener: opener };
      panel.innerHTML = html(ev);
      panel.setAttribute('aria-labelledby', 'calPopTitle');
      scrim.hidden = false;
      panel.hidden = false;
      position(opener);
      opener.setAttribute('aria-expanded', 'true');
      var first = focusables()[0];
      if (first) first.focus();
    }

    function close(restoreFocus) {
      if (!isOpen()) return;
      var opener = current && current.opener;
      panel.hidden = true;
      scrim.hidden = true;
      panel.innerHTML = '';
      if (opener) {
        opener.setAttribute('aria-expanded', 'false');
        if (restoreFocus !== false && doc.contains(opener)) { try { opener.focus(); } catch (e) { /* sin foco */ } }
      }
      current = null;
    }

    function changed() { close(false); if (cfg.onChanged) cfg.onChanged(); }

    scrim.addEventListener('click', function () { close(true); });
    doc.addEventListener('mousedown', function (e) {          // clic fuera (escritorio); el abridor tiene su propio manejo
      if (isOpen() && !panel.contains(e.target) && !(current && current.opener.contains(e.target))) close(false);
    });
    doc.addEventListener('keydown', function (e) {
      if (!isOpen() || doc.querySelector('.gw-modal-backdrop--top')) return;          // un confirmar/preguntar encima maneja su propio teclado
      if (e.key === 'Escape') { e.preventDefault(); close(true); return; }
      if (e.key !== 'Tab') return;
      var f = focusables();
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (!panel.contains(doc.activeElement)) { e.preventDefault(); first.focus(); }
      else if (e.shiftKey && doc.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && doc.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    root.addEventListener('resize', function () { close(false); });
    root.addEventListener('scroll', function (e) { if (isOpen() && !panel.contains(e.target) && !(root.matchMedia && root.matchMedia(NARROW).matches)) close(false); }, true);

    // Export lo atiende event-transfer.js (captura en document); aquí solo cerramos el cuadrito cuando termine de propagarse.
    doc.addEventListener('click', function (e) {
      if (isOpen() && e.target.closest && e.target.closest('.cal-pop [data-export-event]')) root.setTimeout(function () { close(false); }, 0);
    }, true);

    panel.addEventListener('click', function (e) {
      if (e.target.closest('[data-pop-close]')) { close(true); return; }
      if (!current) return;
      var ev = current.ev;
      if (e.target.closest('[data-pop-edit]')) {
        close(false);
        if (root.openEventEditModal) root.openEventEditModal(ev, cfg.onChanged);
        return;
      }
      var rev = e.target.closest('[data-revert-event]');
      if (rev) {
        root.GW.busy(rev, async function () { if (await root.revertEventToCreated(rev.dataset.revertEvent)) changed(); });
        return;
      }
      var del = e.target.closest('[data-pop-delete]');
      if (del) {
        root.GW.busy(del, async function () {
          var ok = await root.showConfirm(
            '¿Está seguro que quiere eliminar el evento "' + esc(ev.name) + '"?<br><br>Recuerde que este evento está en estado <strong>' + esc(STATUS_LABELS[ev.status] || ev.status) +
            '</strong>. Esta acción es permanente y no se puede deshacer.', { confirmLabel: 'Eliminar evento' });
          if (!ok) return;
          var res = await fetch('/api/events/' + encodeURIComponent(ev.id), { method: 'DELETE' });
          root.showToast(res.ok ? 'Evento eliminado' : 'No se pudo eliminar el evento', res.ok ? 'success' : 'error');
          if (res.ok) changed();
        });
      }
    });

    panel.addEventListener('change', async function (e) {
      var select = e.target.closest('[data-pop-status]');
      if (!select || !current) return;
      var newStatus = select.value, previous = select.dataset.initial;
      if ((role === 'admin' || role === 'super_admin') && previous === 'en_proceso' && newStatus === 'creado') {          // el retroceso tiene su propia ventana y su propio rastro
        select.value = previous;
        if (await root.revertEventToCreated(select.dataset.eventId)) changed();
        return;
      }
      if (!(await root.confirmStatusChange(newStatus, STATUS_LABELS[newStatus]))) { select.value = previous; return; }
      select.disabled = true;
      select.setAttribute('aria-busy', 'true');
      var ok = false;
      try {
        var res = await fetch('/api/events/' + encodeURIComponent(select.dataset.eventId), { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: newStatus }) });
        ok = res.ok;
      } catch (err) { ok = false; }
      select.disabled = false;
      select.removeAttribute('aria-busy');
      root.showToast(ok ? 'Evento pasó a "' + STATUS_LABELS[newStatus] + '"' : 'No se pudo actualizar el evento', ok ? 'success' : 'error');
      if (ok) changed(); else select.value = previous;
    });

    return { open: open, close: close, isOpen: isOpen };
  }

  return { actionsFor: actionsFor, create: create, STATUS_LABELS: STATUS_LABELS };
});
