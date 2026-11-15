/* CRM - comportamientos que reaccionan a lo que la persona hace (escribir, o pintar una pantalla): buscador predictivo y búsqueda al teclear en las listas.
   Los temporizadores de aquí son solo esperas de ~0,3 s DESPUÉS de una acción de la persona (para no consultar en cada tecla): nada se repite ni se refresca solo, no hay sondeos.
   Se carga justo después de crm_common.js y le agrega sus funciones a window.CRMX. Lo escrito por personas se pinta con textContent. */
(function () {
  "use strict";
  const X = window.CRMX; if (!X) return;
  const { el, api, qs } = X;
  /* ---------------------------------------------------------------- buscador predictivo
     Un solo campo: se escribe y salen sugerencias (a los ~0,25 s de dejar de teclear); flechas + Enter o clic para elegir; Escape cierra. Al elegir queda la selección (`value`); si se vuelve a editar el texto, se pierde.
     cfg = { id, placeholder, fetch: async (texto) => [{ id, label, sub? }], onPick(item) }. Lo escrito por personas se pinta con textContent. */
  function picker(cfg) {
    const wrap = el("div", "crm-picker"), inp = el("input", "gw-input"), list = el("ul", "crm-picker__list"), ok = el("span", "crm-picker__ok", "✓ Elegida");
    inp.type = "text"; inp.id = cfg.id || ""; inp.autocomplete = "off"; inp.maxLength = 120; inp.placeholder = cfg.placeholder || "Escribe para buscar…";
    inp.setAttribute("role", "combobox"); inp.setAttribute("aria-autocomplete", "list"); inp.setAttribute("aria-expanded", "false");
    list.setAttribute("role", "listbox"); list.hidden = true; ok.hidden = true;
    wrap.appendChild(inp); wrap.appendChild(ok); wrap.appendChild(list);
    let chosen = null, items = [], active = -1, timer = null, seq = 0;
    const api_ = {
      el: wrap, input: inp, get value() { return chosen ? chosen.id : ""; }, get item() { return chosen; },
      set(item) { chosen = item; inp.value = item ? item.label : ""; ok.hidden = !item; wrap.classList.toggle("is-chosen", !!item); close(); },
      clear() { api_.set(null); }, focus() { inp.focus(); },
    };
    function close() { list.hidden = true; inp.setAttribute("aria-expanded", "false"); active = -1; }
    function paint() {
      list.replaceChildren();
      if (!items.length) { const li = el("li", "crm-picker__empty", "Sin resultados. Prueba con otra parte del nombre."); li.setAttribute("role", "presentation"); list.appendChild(li); }
      items.forEach((it, i) => {
        const li = el("li", "crm-picker__opt" + (i === active ? " is-active" : "")); li.setAttribute("role", "option"); li.dataset.i = String(i);
        li.appendChild(el("span", "crm-picker__name", it.label)); if (it.sub) li.appendChild(el("span", "crm-picker__sub", it.sub)); list.appendChild(li);
      });
      list.hidden = false; inp.setAttribute("aria-expanded", "true");
    }
    async function search() {
      const mine = ++seq;
      try { const r = await cfg.fetch(inp.value.trim()); if (mine !== seq) return; items = r || []; active = items.length ? 0 : -1; paint(); }
      catch (e) { if (mine !== seq) return; items = []; list.replaceChildren(el("li", "crm-picker__empty", "No se pudo buscar. Intenta de nuevo.")); list.hidden = false; }
    }
    function pick(i) { const it = items[i]; if (!it) return; api_.set(it); if (cfg.onPick) cfg.onPick(it); }
    inp.addEventListener("input", () => { if (chosen) { chosen = null; ok.hidden = true; wrap.classList.remove("is-chosen"); if (cfg.onPick) cfg.onPick(null); } clearTimeout(timer); timer = setTimeout(search, 250); });
    inp.addEventListener("focus", () => { if (!chosen) search(); });
    inp.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); if (list.hidden) { search(); return; } if (!items.length) return; active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length; paint(); const a = list.querySelector(".is-active"); if (a && a.scrollIntoView) a.scrollIntoView({ block: "nearest" }); }
      else if (e.key === "Enter" && !list.hidden && active >= 0) { e.preventDefault(); pick(active); }
      else if (e.key === "Escape" && !list.hidden) { e.stopPropagation(); close(); }
    });
    list.addEventListener("mousedown", (e) => { const li = e.target.closest(".crm-picker__opt"); if (li) { e.preventDefault(); pick(Number(li.dataset.i)); } });
    inp.addEventListener("blur", () => setTimeout(close, 120));
    return api_;
  }
  function pickerField(id, label, pk, hint) {
    const w = el("div", "gw-field"), l = el("label", "gw-label", label); l.htmlFor = id; pk.input.id = id; w.appendChild(l); w.appendChild(pk.el); if (hint) w.appendChild(el("p", "gw-hint", hint)); return w;
  }
  /* Cuentas: nombre, código o NIT. Oportunidades de una cuenta: `accountId()` devuelve la cuenta elegida (o vacío = cualquiera). */
  function accountPicker(id, placeholder) {
    return picker({ id, placeholder: placeholder || "Escribe el nombre, el código o el NIT de la cuenta…",
      fetch: async (q) => (await api("GET", "/api/crm/accounts" + qs({ q, size: 8 }))).items.map((a) => ({ id: a.id, label: a.name, sub: "Cód. " + a.code })) });
  }
  function opportunityPicker(id, accountId) {
    return picker({ id, placeholder: "Escribe el nombre de la oportunidad (opcional)…",
      fetch: async (q) => (await api("GET", "/api/crm/opportunities" + qs({ q, size: 8, account_id: accountId() || "" }))).items.map((o) => ({ id: o.id, label: o.name, sub: o.account_name || "" })) });
  }

  /* Buscadores de las listas: se busca mientras se escribe (sin pulsar «Buscar»). Con 1 sola letra espera; vacío = quitar el filtro. */
  (function liveSearch() {
    document.querySelectorAll("form.crm-filters input[type='search']").forEach((inp) => {
      const form = inp.form; if (!form) return; let t = null;
      inp.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { const n = inp.value.trim().length; if (n === 1) return; form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true })); }, 350); });
    });
  })();


  Object.assign(X, { picker, pickerField, accountPicker, opportunityPicker });
})();
