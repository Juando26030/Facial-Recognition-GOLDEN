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
  function activitySection(title, hint, items, emptyText) {
    const sec = section(title, hint, items.length), ul = el("ul", "crm-day-list");
    if (!items.length) sec.appendChild(empty(emptyText)); else { items.forEach((a) => ul.appendChild(activityRow(a))); sec.appendChild(ul); } return sec;
  }
  function oppSection(title, hint, items, emptyText, more) {
    const sec = section(title, hint, items.length), ul = el("ul", "crm-day-list");
    if (!items.length) { sec.appendChild(empty(emptyText)); return sec; }
    items.forEach((o) => {
      const li = document.createElement("li"), left = el("div", "crm-name-wrap");
      left.appendChild(link(o.name, "/crm/oportunidades/" + o.id)); left.appendChild(el("span", "crm-sub", o.account_name + (o.expected_close ? " · Cierre " + X.fmtDay(o.expected_close) : "")));
      li.appendChild(left); li.appendChild(el("span", "crm-day-amount", X.fmtMoney(o.amount, o.currency))); ul.appendChild(li);
    });
    sec.appendChild(ul); if (more) sec.appendChild(el("p", "gw-hint", "Hay más; se muestran las primeras " + items.length + ". Usa el filtro «Sin próxima actividad» en Oportunidades.")); return sec;
  }
  function quoteSection(title, hint, items, emptyText) {
    const sec = section(title, hint, items.length), ul = el("ul", "crm-day-list");
    if (!items.length) { sec.appendChild(empty(emptyText)); return sec; }
    items.forEach((q) => {
      const li = document.createElement("li"), left = el("div", "crm-name-wrap");
      left.appendChild(link("N.º " + q.number + (q.version > 1 ? " · v" + q.version : "") + " · " + q.title, "/crm/cotizaciones/" + q.id)); left.appendChild(el("span", "crm-sub", q.account_name + " · Válida hasta " + X.fmtDay(q.valid_until)));
      li.appendChild(left); li.appendChild(el("span", "crm-day-amount", X.fmtMoney(q.total, q.currency))); ul.appendChild(li);
    });
    sec.appendChild(ul); return sec;
  }

  async function load() {
    const mine = ++seq, main = $("dayMain"), state = $("dayState"); main.setAttribute("aria-busy", "true");
    try {
      const d = await api("GET", "/api/crm/today"); if (mine !== seq) return;
      state.hidden = true; main.hidden = false; main.replaceChildren();
      const total = d.overdue.length + d.due_today.length + d.reminders.length;
      $("daySub").textContent = total ? "Tienes " + total + (total === 1 ? " pendiente" : " pendientes") + " para atender." : "No tienes pendientes vencidos ni de hoy.";
      main.appendChild(activitySection("Vencidas", "Actividades cuya fecha ya pasó.", d.overdue, "Nada vencido. Bien."));
      main.appendChild(activitySection("Para hoy", "Lo que está programado para hoy.", d.due_today, "No tienes actividades para hoy."));
      main.appendChild(activitySection("Recordatorios", "Actividades futuras cuyo aviso ya llegó.", d.reminders, "Sin recordatorios por ahora."));
      main.appendChild(oppSection("Oportunidades sin próxima actividad", "Abiertas y sin nada programado: se enfrían.", d.no_next_activity, "Todas tus oportunidades abiertas tienen algo programado.", d.no_next_activity_more));
      main.appendChild(oppSection("Por cerrar pronto", "Abiertas con fecha de cierre en los próximos " + d.close_soon_days + " días (o ya pasada).", d.closing_soon, "Ninguna oportunidad cierra pronto."));
      main.appendChild(quoteSection("Cotizaciones por vencer", "Abiertas y válidas hasta dentro de " + d.quote_soon_days + " días o menos.", d.quotes_expiring, "Ninguna cotización está por vencer."));
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
