/* CRM - Mi día (C4): una carga al abrir y otra al pulsar «Actualizar» o al marcar algo como hecho. Sin temporizadores ni sondeos (no despierta la base por su cuenta).
   Lo escrito por personas (asuntos, nombres) se pinta con textContent. */
(function () {
  "use strict";
  const X = window.CRMX, root = document.getElementById("dayRoot");
  if (!X || !root) return;
  const { $, el, api, stateBlock, busy } = X;
  let seq = 0;

  function link(text, href, cls) { const a = el("a", cls || "crm-name", text); a.href = href; return a; }
  function section(title, hint, count) {
    const sec = el("section", "gw-card gw-stack"), head = el("div", "crm-card-head"), h = el("h2", "gw-card__title", title);
    head.appendChild(h); if (count != null) head.appendChild(el("span", "gw-badge" + (count ? " gw-badge--info" : ""), String(count)));
    sec.appendChild(head); if (hint) sec.appendChild(el("p", "gw-hint", hint)); return sec;
  }
  function empty(text) { return el("p", "gw-hint", text); }

  function activityRow(a) {
    const li = document.createElement("li"), left = el("div", "crm-name-wrap");
    left.appendChild(el("span", "crm-name", a.kind_label + " · " + a.subject));
    const when = a.due_at ? X.fmtDateTime(a.due_at) : "";
    const where = a.opportunity_id ? link(a.opportunity_name || "Oportunidad", "/crm/oportunidades/" + a.opportunity_id, "crm-sub-link") : a.account_id ? link(a.account_name || "Cuenta", "/crm/cuentas/" + a.account_id, "crm-sub-link") : a.lead_id ? link("Lead", "/crm/leads", "crm-sub-link") : null;
    const sub = el("span", "crm-sub", when + (where ? " · " : "")); if (where) sub.appendChild(where); left.appendChild(sub); li.appendChild(left);
    const done = el("button", "gw-btn gw-btn--secondary gw-btn--sm", "Marcar hecha"); done.type = "button"; done.dataset.done = String(a.id); done.setAttribute("aria-label", "Marcar como hecha: " + a.subject); li.appendChild(done); return li;
  }
  const MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
  function groupKey(a, byMonth) { const d = a.due_at ? X.fmtDay(a.due_at) : "Sin fecha"; if (!a.due_at) return d; const t = new Date(a.due_at); return byMonth ? MONTHS[t.getMonth()] + " de " + t.getFullYear() : d; }
  /* Las actividades se agrupan: por mes las vencidas (hay muchas) y por día el resto. Cada grupo se pliega con su flecha (<details>); el primero queda abierto. */
  function activitySection(title, hint, items, emptyText, opts) {
    const o = opts || {}, sec = section(title, hint, o.total != null ? o.total : items.length);
    sec.dataset.cat = o.cat || "";
    if (!items.length) { sec.appendChild(empty(emptyText)); return sec; }
    const groups = new Map(); items.forEach((a) => { const k = groupKey(a, o.byMonth); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(a); });
    let first = true;
    groups.forEach((list, k) => {
      const det = el("details", "crm-day-group"); det.open = first; first = false;
      const sum = el("summary", "crm-day-group__sum"); sum.appendChild(el("span", "crm-day-group__name", k)); sum.appendChild(el("span", "gw-badge", String(list.length))); det.appendChild(sum);
      const ul = el("ul", "crm-day-list"); list.forEach((a) => ul.appendChild(activityRow(a))); det.appendChild(ul); sec.appendChild(det);
    });
    if (o.total != null && o.total > items.length) sec.appendChild(el("p", "gw-hint", "Se muestran las " + items.length + " más recientes de " + o.total + ". Al marcar o cancelar actividades aparecen las anteriores."));
    return sec;
  }
  function oppSection(title, hint, items, emptyText, more, cat) {
    const sec = section(title, hint, items.length), ul = el("ul", "crm-day-list"); sec.dataset.cat = cat || "";
    if (!items.length) { sec.appendChild(empty(emptyText)); return sec; }
    items.forEach((o) => {
      const li = document.createElement("li"), left = el("div", "crm-name-wrap");
      left.appendChild(link(o.name, "/crm/oportunidades/" + o.id)); left.appendChild(el("span", "crm-sub", o.account_name + (o.expected_close ? " · Cierre " + X.fmtDay(o.expected_close) : "")));
      li.appendChild(left); li.appendChild(el("span", "crm-day-amount", X.fmtMoney(o.amount, o.currency))); ul.appendChild(li);
    });
    sec.appendChild(ul); if (more) sec.appendChild(el("p", "gw-hint", "Hay más; se muestran las primeras " + items.length + ". Usa el filtro «Sin próxima actividad» en Oportunidades.")); return sec;
  }
  function quoteSection(title, hint, items, emptyText, cat) {
    const sec = section(title, hint, items.length), ul = el("ul", "crm-day-list"); sec.dataset.cat = cat || "";
    if (!items.length) { sec.appendChild(empty(emptyText)); return sec; }
    items.forEach((q) => {
      const li = document.createElement("li"), left = el("div", "crm-name-wrap");
      left.appendChild(link("N.º " + q.number + (q.version > 1 ? " · v" + q.version : "") + " · " + q.title, "/crm/cotizaciones/" + q.id)); left.appendChild(el("span", "crm-sub", q.account_name + " · Válida hasta " + X.fmtDay(q.valid_until)));
      li.appendChild(left); li.appendChild(el("span", "crm-day-amount", X.fmtMoney(q.total, q.currency))); ul.appendChild(li);
    });
    sec.appendChild(ul); return sec;
  }

  /* Categorías: una fila de botones con su conteo; «Todo» muestra todas las secciones y cada categoría deja solo la suya. Se recuerda la elegida en este navegador. */
  let cat = "all"; try { cat = localStorage.getItem("gw.crm.midia.cat") || "all"; } catch (e) { /* sin almacenamiento */ }
  function categoryBar(secs) {
    const bar = el("div", "crm-cats"); bar.setAttribute("role", "group"); bar.setAttribute("aria-label", "Qué quieres ver en tu día");
    const mk = (key, label, n) => { const b = el("button", "gw-chip", label + (n != null ? " (" + n + ")" : "")); b.type = "button"; b.dataset.cat = key; b.setAttribute("aria-pressed", key === cat ? "true" : "false"); bar.appendChild(b); };
    mk("all", "Todo", null); secs.forEach((s) => mk(s[0], s[1], s[3]));
    bar.addEventListener("click", (e) => { const b = e.target.closest("[data-cat]"); if (!b) return; cat = b.dataset.cat; try { localStorage.setItem("gw.crm.midia.cat", cat); } catch (er) { /* sin almacenamiento */ } applyCat(); });
    return bar;
  }
  function applyCat() {
    const main = $("dayMain"); if (!main.querySelector(".crm-cats")) return; if (cat !== "all" && !main.querySelector('section[data-cat="' + cat + '"]')) cat = "all";
    main.querySelectorAll(".crm-cats [data-cat]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.cat === cat ? "true" : "false"));
    main.querySelectorAll("section[data-cat]").forEach((s) => { s.hidden = cat !== "all" && s.dataset.cat !== cat; });
  }

  async function load() {
    const mine = ++seq, main = $("dayMain"), state = $("dayState"); main.setAttribute("aria-busy", "true");
    try {
      const d = await api("GET", "/api/crm/today"); if (mine !== seq) return;
      state.hidden = true; main.hidden = false; main.replaceChildren();
      const total = d.overdue.length + d.due_today.length + d.reminders.length;
      $("daySub").textContent = total ? "Tienes " + total + (total === 1 ? " pendiente" : " pendientes") + " para atender." : "No tienes pendientes vencidos ni de hoy.";
      const secs = [
        ["today", "Para hoy", activitySection("Para hoy", "Lo que está programado para hoy.", d.due_today, "No tienes actividades para hoy.", { cat: "today" }), d.due_today.length],
        ["overdue", "Vencidas", activitySection("Vencidas", "Actividades cuya fecha ya pasó, las más recientes primero y por mes.", d.overdue, "Nada vencido. Bien.", { cat: "overdue", byMonth: true, total: d.overdue_total }), d.overdue_total],
        ["reminders", "Recordatorios", activitySection("Recordatorios", "Actividades futuras cuyo aviso ya llegó.", d.reminders, "Sin recordatorios por ahora.", { cat: "reminders" }), d.reminders.length],
        ["cold", "Sin próxima actividad", oppSection("Oportunidades sin próxima actividad", "Abiertas y sin nada programado: se enfrían.", d.no_next_activity, "Todas tus oportunidades abiertas tienen algo programado.", d.no_next_activity_more, "cold"), d.no_next_activity.length],
        ["closing", "Por cerrar pronto", oppSection("Por cerrar pronto", "Abiertas con fecha de cierre en los próximos " + d.close_soon_days + " días (o ya pasada).", d.closing_soon, "Ninguna oportunidad cierra pronto.", false, "closing"), d.closing_soon.length],
        ["quotes", "Cotizaciones por vencer", quoteSection("Cotizaciones por vencer", "Abiertas y válidas hasta dentro de " + d.quote_soon_days + " días o menos.", d.quotes_expiring, "Ninguna cotización está por vencer.", "quotes"), d.quotes_expiring.length],
      ];
      main.appendChild(categoryBar(secs)); secs.forEach((s) => main.appendChild(s[2])); applyCat();
    } catch (e) { if (mine === seq) { $("dayMain").hidden = true; state.hidden = false; state.replaceChildren(stateBlock("error", "No se pudo cargar tu día", e.message, load)); } }
    finally { if (mine === seq) main.setAttribute("aria-busy", "false"); }
  }

  $("dayMain").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-done]"); if (!b) return;
    await busy(b, async () => { try { await api("POST", "/api/crm/activities/" + b.dataset.done + "/complete", {}); showToast("Actividad marcada como hecha.", "success"); await load(); } catch (err) { showToast(err.message, "error"); } });
  });
  $("dayReload").addEventListener("click", load);
  $("dayNew").addEventListener("click", () => X.activityForm({ pick: true }, null, load));
  load();
})();
