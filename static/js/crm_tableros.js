/* CRM - Tableros (C4): una carga al abrir y otra al pulsar «Ver». Sin temporizadores. Barras hechas con la variable --w (sin estilos en línea ni librerías).
   El dinero se muestra SIEMPRE separado por moneda: COP y USD nunca se suman. */
(function () {
  "use strict";
  const X = window.CRMX, root = document.getElementById("boardsRoot");
  if (!X || !root) return;
  const { $, el, api, qs, stateBlock } = X;
  const canAdmin = root.dataset.canAdmin === "1";
  const QSTAGE = { borrador: "Borrador", enviada: "Enviada", negociada: "Negociada", aprobada: "Aprobada", rechazada: "Rechazada", vencida: "Vencida" };
  let seq = 0;

  const fmt = (t, key) => X.fmtMoney(t[key || "amount"], t.currency);
  function money(totals, key) { return totals.length ? totals.map((t) => fmt(t, key)).join(" · ") : "—"; }
  function card(title, hint) { const s = el("section", "gw-card gw-stack"); s.appendChild(el("h2", "gw-card__title", title)); if (hint) s.appendChild(el("p", "gw-hint", hint)); return s; }
  function stat(label, value, sub) { const d = el("div", "crm-stat"); d.appendChild(el("p", "crm-stat__label", label)); d.appendChild(el("p", "crm-stat__value", value)); if (sub) d.appendChild(el("p", "crm-stat__sub", sub)); return d; }
  function bar(label, count, max, text) {
    const row = el("div", "crm-bar"), l = el("span", "crm-bar__label", label), track = el("span", "crm-bar__track"), fill = el("span", "crm-bar__fill");
    fill.style.setProperty("--w", String(max ? Math.max(2, Math.round(100 * count / max)) : 0)); track.appendChild(fill); row.appendChild(l); row.appendChild(track); row.appendChild(el("span", "crm-bar__value", String(count))); if (text) row.appendChild(el("span", "crm-bar__text", text)); return row;
  }

  function render(d) {
    const main = $("boardsMain"); main.replaceChildren();
    const open = d.stages.reduce((n, s) => n + s.count, 0), wonN = d.closed.won.count, lostN = d.closed.lost.count;
    const kpis = el("div", "crm-stats");
    kpis.appendChild(stat("Oportunidades abiertas", String(open)));
    kpis.appendChild(stat("Ganadas", String(wonN), money(d.closed.won.totals)));
    kpis.appendChild(stat("Perdidas", String(lostN), money(d.closed.lost.totals)));
    kpis.appendChild(stat("Tasa de cierre", d.win_rate == null ? "—" : d.win_rate + " %", "ganadas ÷ (ganadas + perdidas)"));
    kpis.appendChild(stat("Actividades pendientes", String(d.activities.pending), d.activities.overdue ? d.activities.overdue + " vencidas" : "ninguna vencida"));
    main.appendChild(kpis);

    const pipe = card("Embudo abierto", "Cuántas oportunidades hay en cada etapa. El valor ponderado multiplica por la probabilidad.");
    const maxN = Math.max(0, ...d.stages.map((s) => s.count));
    if (!d.stages.length) pipe.appendChild(el("p", "gw-hint", "No hay oportunidades abiertas."));
    d.stages.forEach((s) => pipe.appendChild(bar(s.name, s.count, maxN, money(s.totals) + (s.totals.length ? " (ponderado " + money(s.totals, "weighted") + ")" : ""))));
    main.appendChild(pipe);

    const acts = card("Actividades hechas en el periodo");
    const maxA = Math.max(0, ...d.activities.done_by_kind.map((k) => k.count));
    if (!d.activities.done_by_kind.length) acts.appendChild(el("p", "gw-hint", "No hay actividades hechas en este periodo."));
    d.activities.done_by_kind.forEach((k) => acts.appendChild(bar(k.label, k.count, maxA)));
    main.appendChild(acts);

    const qs2 = card("Cotizaciones creadas en el periodo", "Por etapa y moneda.");
    const maxQ = Math.max(0, ...d.quotes.map((q) => q.count));
    if (!d.quotes.length) qs2.appendChild(el("p", "gw-hint", "No se crearon cotizaciones en este periodo."));
    d.quotes.forEach((q) => qs2.appendChild(bar(QSTAGE[q.stage] || q.stage, q.count, maxQ, money(q.totals))));
    main.appendChild(qs2);

    if (d.scope === "all") {
      const team = card("Por responsable (abiertas)", "Solo lo que sigue abierto hoy.");
      const maxO = Math.max(0, ...d.by_owner.map((o) => o.count));
      if (!d.by_owner.length) team.appendChild(el("p", "gw-hint", "No hay oportunidades abiertas."));
      d.by_owner.forEach((o) => team.appendChild(bar(o.name, o.count, maxO, money(o.totals) + " (ponderado " + money(o.totals, "weighted") + ")")));
      main.appendChild(team);
    }
    $("boardsSub").textContent = (d.scope === "all" ? "Todo el equipo" : "Tus cifras") + " · últimos " + d.days + " días para lo cerrado, hecho y creado.";
  }

  async function load() {
    const mine = ++seq, main = $("boardsMain"), state = $("boardsState"); main.setAttribute("aria-busy", "true");
    const owner = canAdmin ? $("boardsOwner").value : "";
    try {
      const d = await api("GET", "/api/crm/dashboards" + qs({ days: $("boardsDays").value, owner_id: owner })); if (mine !== seq) return;
      state.hidden = true; main.hidden = false; render(d);
    } catch (e) { if (mine === seq) { main.hidden = true; state.hidden = false; state.replaceChildren(stateBlock("error", "No se pudieron cargar los tableros", e.message, load)); } }
    finally { if (mine === seq) main.setAttribute("aria-busy", "false"); }
  }
  $("boardsFilters").addEventListener("submit", (e) => { e.preventDefault(); load(); });
  (async () => {
    if (canAdmin) { try { (await X.owners()).forEach((o) => $("boardsOwner").appendChild(new Option(o.name, String(o.id)))); } catch (e) { /* sin lista de responsables se ve todo el equipo */ } }
    load();
  })();
})();
