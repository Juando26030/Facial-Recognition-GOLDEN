/* CRM - Búsqueda global (C3). Solo busca al enviar el formulario (nada de «buscar mientras escribes»): una petición, sin temporizadores. Todo texto con textContent. */
(function () {
  "use strict";
  const X = window.CRMX, root = document.getElementById("searchRoot");
  if (!X || !root) return;
  const { $, el, api, qs, stateBlock } = X;
  const GROUPS = [
    ["accounts", "Cuentas", (r) => ["/crm/cuentas/" + r.id, r.name, "Código " + r.code]],
    ["contacts", "Contactos", (r) => ["/crm/cuentas/" + r.account_id, r.name, r.job_title || ""]],
    ["opportunities", "Oportunidades", (r) => ["/crm/oportunidades/" + r.id, r.name, "N.º " + r.code]],
    ["quotes", "Cotizaciones", (r) => ["/crm/cotizaciones/" + r.id, r.title, "N.º " + r.number + (r.version > 1 ? " · v" + r.version : "")]],
    ["leads", "Leads", (r) => ["/crm/leads?q=" + encodeURIComponent(r.name || ""), r.name, r.company_name || ""]],
  ];
  async function run() {
    const q = $("searchQ").value.trim(), box = $("searchResults");
    try { window.history.replaceState(null, "", window.location.pathname); } catch (e) { /* sin historial: el texto buscado no queda en la dirección */ }
    box.setAttribute("aria-busy", "true"); box.replaceChildren();
    try {
      const d = await api("GET", "/api/crm/search" + qs({ q }));
      let any = false;
      GROUPS.forEach(([key, title, fmt]) => {
        const rows = d[key] || []; if (!rows.length) return; any = true;
        const sec = el("section", "gw-card gw-stack"); sec.setAttribute("aria-label", title);
        sec.appendChild(el("h2", "crm-panel__title", title + " (" + rows.length + ")"));
        const ul = el("ul", "crm-search__list");
        rows.forEach((r) => { const [href, main, sub] = fmt(r), li = el("li"), a = el("a", "crm-search__link", main || "Sin nombre"); a.href = href; li.appendChild(a); if (sub) li.appendChild(el("span", "crm-sub", sub)); ul.appendChild(li); });
        sec.appendChild(ul); box.appendChild(sec);
      });
      if (!any) box.appendChild(stateBlock("empty", "No encontramos nada", "Prueba con otra palabra, el correo completo o el número.", null, "search"));
    } catch (e) { box.appendChild(stateBlock("error", "No se pudo buscar", e.message, run)); }
    finally { box.setAttribute("aria-busy", "false"); }
  }
  $("searchForm").addEventListener("submit", (e) => { e.preventDefault(); run(); });
})();
