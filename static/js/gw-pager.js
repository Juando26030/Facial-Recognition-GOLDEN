/* Paginación compartida (6-nov-2026, pedido de Juan David): TODAS las listas largas muestran 20 por página y, al final, cada persona elige cuántas quiere ver en SU computador
   (10, 20, 50, 100 o 200). La elección se recuerda por lista en este navegador (localStorage); si no se puede guardar, vale solo hasta recargar. Ya no es un parámetro del evento. */
(function () {
  'use strict';
  var GW = window.GW = window.GW || {};
  var SIZES = [10, 20, 50, 100, 200], DEFAULT = 20, memory = {};
  function storeKey(key) { return 'gw.pagesize.' + key; }
  GW.pageSizes = SIZES;
  GW.pageSize = function (key) {
    var v = memory[key];
    if (v == null) { try { v = Number(window.localStorage.getItem(storeKey(key))); } catch (e) { v = 0; } }
    return SIZES.indexOf(Number(v)) >= 0 ? Number(v) : DEFAULT;
  };
  GW.setPageSize = function (key, n) {
    n = Number(n);
    if (SIZES.indexOf(n) < 0) return;
    memory[key] = n;
    try { window.localStorage.setItem(storeKey(key), String(n)); } catch (e) { /* sin almacenamiento: vale hasta recargar */ }
  };
  /* <label>Por página <select>…</select></label>; `onChange(n)` ya con el valor guardado. */
  GW.pageSizeSelect = function (key, onChange) {
    var label = document.createElement('label'), select = document.createElement('select'), cur = GW.pageSize(key);
    label.className = 'gw-pager__size';
    label.appendChild(document.createTextNode('Por página '));
    select.className = 'gw-select gw-select--auto';
    select.setAttribute('aria-label', 'Filas por página');
    SIZES.forEach(function (n) { var o = document.createElement('option'); o.value = String(n); o.textContent = String(n); if (n === cur) o.selected = true; select.appendChild(o); });
    select.addEventListener('change', function () { GW.setPageSize(key, select.value); if (onChange) onChange(GW.pageSize(key)); });
    label.appendChild(select);
    return label;
  };
  /* Barra completa para listas dibujadas por el navegador: «Mostrando a-b de N · ‹ Anterior · Página x de y · Siguiente › · Por página [20]».
     o = { key, total, page (desde 0), onPage(i), onSize(n) }. Con pocas filas igual deja el selector (hasta el mínimo de filas posible). */
  GW.pagerBar = function (o) {
    var size = GW.pageSize(o.key), total = o.total, pages = Math.max(1, Math.ceil(total / size)), page = Math.max(0, Math.min(o.page || 0, pages - 1));
    var bar = document.createElement('div');
    bar.className = 'gw-pager';
    var info = document.createElement('span');
    info.className = 'gw-pager__info';
    info.textContent = total ? 'Mostrando ' + (page * size + 1) + '-' + Math.min(total, (page + 1) * size) + ' de ' + total + ' · Página ' + (page + 1) + ' de ' + pages : 'Sin filas';
    bar.appendChild(info);
    function btn(label, to, disabled) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'gw-btn gw-btn--secondary gw-btn--sm'; b.textContent = label; b.disabled = !!disabled;
      b.addEventListener('click', function () { o.onPage(to); });
      bar.appendChild(b);
    }
    btn('‹ Anterior', page - 1, page === 0);
    btn('Siguiente ›', page + 1, page >= pages - 1);
    bar.appendChild(GW.pageSizeSelect(o.key, function (n) { if (o.onSize) o.onSize(n); }));
    return bar;
  };
  /* La parte de la lista que toca mostrar. */
  GW.pageSlice = function (key, items, page) {
    var size = GW.pageSize(key), pages = Math.max(1, Math.ceil(items.length / size)), p = Math.max(0, Math.min(page || 0, pages - 1));
    return { items: items.slice(p * size, (p + 1) * size), page: p, pages: pages, size: size };
  };
})();
