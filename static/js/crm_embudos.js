/* CRM - Embudos y etapas (C2, solo administradores). Nombre, probabilidad y orden de las etapas (flechas, sirven con teclado) quedan pendientes hasta «Guardar cambios» (barra única, GWParams, bloque «embudos»);
   crear, renombrar un embudo, hacerlo predeterminado, agregar una etapa y archivar/restaurar son actos inmediatos (antes guardan lo pendiente) y la lista se vuelve a leer del servidor.
   Sin temporizadores ni sondeos. Lo escrito por personas se pinta con textContent / .value. */
(function () {
  "use strict";
  const X = window.CRMX, root = document.getElementById("pipeRoot");
  if (!X || !root) return;
  const { $, el, api, stateBlock } = X;
  const KINDS = { open: "Abierta", won: "Ganada", lost: "Perdida" };
  let pipelines = [];

  function stageRow(p, s, openIds) {
    const tr = el("tr"); tr.dataset.stageId = s.id; tr.dataset.pipelineId = p.id;
    if (openIds.indexOf(s.id) >= 0 && !s.archived) tr.dataset.orderable = "1";
    const td = (label, node) => { const c = el("td"); c.dataset.label = label; c.appendChild(node); tr.appendChild(c); return c; };
    const name = X.input("text", 80); name.value = s.name; name.setAttribute("aria-label", "Nombre de la etapa " + s.name); name.dataset.f = "name"; td("Etapa", name);
    const prob = X.input("text", 3); prob.value = String(s.probability); prob.inputMode = "numeric"; prob.setAttribute("aria-label", "Probabilidad de " + s.name); prob.dataset.f = "probability"; td("Probabilidad (%)", prob);
    td("Tipo", el("span", "gw-badge " + (s.kind === "won" ? "gw-badge--ok" : s.kind === "lost" ? "gw-badge--warn" : "gw-badge--info"), KINDS[s.kind]));
    const acts = el("div", "crm-card__actions");
    const mk = (label, act, aria) => { const b = el("button", "gw-btn gw-btn--secondary gw-btn--sm", label); b.type = "button"; b.dataset.act = act; if (aria) b.setAttribute("aria-label", aria); return b; };
    const i = openIds.indexOf(s.id);
    if (i >= 0 && !s.archived) { const up = mk("↑", "up", "Subir " + s.name), dn = mk("↓", "down", "Bajar " + s.name); up.disabled = i === 0; dn.disabled = i === openIds.length - 1; acts.appendChild(up); acts.appendChild(dn); }
    acts.appendChild(mk(s.archived ? "Restaurar" : "Archivar", s.archived ? "restore" : "archive"));
    td("Acciones", acts);
    if (s.archived) tr.className = "crm-row--archived";
    return tr;
  }
  function pipelineCard(p) {
    const card = el("section", "gw-card gw-stack"); card.dataset.pipelineId = p.id; card.setAttribute("aria-label", "Embudo " + p.name);
    const bar = el("div", "crm-panel__bar"), title = el("h2", "crm-panel__title", p.name); bar.appendChild(title);
    const badges = el("div", "crm-badges"); if (p.is_default) badges.appendChild(el("span", "gw-badge gw-badge--ok", "Predeterminado")); if (p.archived) badges.appendChild(el("span", "gw-badge", "Archivado")); bar.appendChild(badges); card.appendChild(bar);
    const acts = el("div", "crm-actions"), mk = (label, act) => { const b = el("button", "gw-btn gw-btn--secondary gw-btn--sm", label); b.type = "button"; b.dataset.act = act; return b; };
    acts.appendChild(mk("Cambiar nombre", "rename")); if (!p.is_default && !p.archived) acts.appendChild(mk("Hacer predeterminado", "default")); if (!p.is_default) acts.appendChild(mk(p.archived ? "Restaurar embudo" : "Archivar embudo", p.archived ? "prestore" : "parchive")); if (!p.archived) acts.appendChild(mk("Agregar etapa", "addstage"));
    card.appendChild(acts);
    const openIds = p.stages.filter((s) => s.kind === "open" && !s.archived).map((s) => s.id);
    const wrap = el("div", "gw-table-wrap"), t = el("table", "gw-table gw-table-cards crm-table"), head = el("thead"), hr = el("tr");
    ["Etapa", "Probabilidad (%)", "Tipo", "Acciones"].forEach((h) => { const th = el("th", null, h); th.scope = "col"; hr.appendChild(th); }); head.appendChild(hr); t.appendChild(head);
    const body = el("tbody"); p.stages.forEach((s) => body.appendChild(stageRow(p, s, openIds))); t.appendChild(body); wrap.appendChild(t); card.appendChild(wrap);
    return card;
  }
  async function load() {
    const box = $("pipeList"); box.setAttribute("aria-busy", "true");
    try {
      pipelines = (await api("GET", "/api/crm/pipelines")).pipelines; box.replaceChildren();
      if (!pipelines.length) box.appendChild(stateBlock("empty", "Todavía no hay embudos", "Crea el primero con «Nuevo embudo».", null, "chart"));
      pipelines.forEach((p) => box.appendChild(pipelineCard(p)));
    } catch (e) { box.replaceChildren(stateBlock("error", "No se pudieron cargar los embudos", e.message, load)); }
    finally { box.setAttribute("aria-busy", "false"); }
  }
  const find = (id) => pipelines.find((p) => p.id === Number(id));
  const origOrder = (p) => p.stages.filter((s) => s.kind === "open" && !s.archived).map((s) => s.id);
  const domOrder = (tbody) => Array.from(tbody.querySelectorAll('tr[data-orderable="1"]')).map((tr) => Number(tr.dataset.stageId));
  function refreshArrows(tbody) {
    const rows = Array.from(tbody.querySelectorAll('tr[data-orderable="1"]'));
    rows.forEach((tr, i) => { const up = tr.querySelector('[data-act="up"]'), dn = tr.querySelector('[data-act="down"]'); if (up) up.disabled = i === 0; if (dn) dn.disabled = i === rows.length - 1; });
  }
  const markDirty = () => { if (window.GWParams) GWParams.markDirty("embudos"); };
  /* Los actos inmediatos vuelven a leer la lista: si hay cambios pendientes, primero se guardan (si no se pueden guardar, el acto no sigue y no se pierde nada). */
  async function savePendingFirst() {
    if (!window.GWParams || !GWParams.hasDirty()) return;
    const r = await GWParams.flush("embudos");
    if (r.failed.length) throw new Error("Primero guarda los cambios de las etapas: " + r.failed[0].error);
  }
  /* Lo guarda la barra única: PUT de cada etapa que cambió y, si cambió el orden, un solo reorder por embudo. Sigue con lo demás aunque una falle y avisa cuáles. */
  async function saveStages() {
    const problems = [];
    for (const p of pipelines) {
      const card = $("pipeList").querySelector('section[data-pipeline-id="' + p.id + '"]'); if (!card) continue;
      for (const tr of card.querySelectorAll("tbody tr")) {
        const s = p.stages.find((x) => x.id === Number(tr.dataset.stageId)); if (!s || s.archived) continue;
        const name = tr.querySelector('[data-f="name"]').value.trim(), prob = tr.querySelector('[data-f="probability"]').value.trim();
        if (name === s.name && prob === String(s.probability)) continue;
        try { const r = await api("PUT", "/api/crm/stages/" + s.id, { name, probability: prob }); s.name = r && r.name != null ? r.name : name; s.probability = r && r.probability != null ? r.probability : Number(prob); }
        catch (e) { problems.push((name || s.name) + ": " + e.message); }
      }
      const tbody = card.querySelector("tbody"), want = domOrder(tbody), have = origOrder(p);
      if (want.length && want.join() !== have.join()) {
        try { await api("POST", "/api/crm/pipelines/" + p.id + "/stages/reorder", { stage_ids: want }); const pos = new Map(want.map((id, i) => [id, i])); const open = p.stages.filter((s) => pos.has(s.id)).sort((a, b) => pos.get(a.id) - pos.get(b.id)); let k = 0; p.stages = p.stages.map((s) => (pos.has(s.id) ? open[k++] : s)); }
        catch (e) { problems.push("Orden de «" + p.name + "»: " + e.message); }
      }
    }
    if (problems.length) throw new Error(problems.join(" · "));
    await load();
  }
  if (window.GWParams) GWParams.register({ key: "embudos", label: "Etapas de los embudos", order: 10, save: saveStages });

  async function askName(title, label, value) {
    const v = await showPrompt(window.escapeHtml(label), { title, confirmLabel: "Guardar" }); return v === null ? null : v.trim();
  }
  $("pipeNew").addEventListener("click", async () => {
    const name = await askName("Nuevo embudo", "Nombre del embudo", ""); if (!name) return;
    try { await api("POST", "/api/crm/pipelines", { name }); showToast("Embudo creado con las etapas Nuevo, Ganada y Perdida.", "success"); load(); } catch (e) { showToast(e.message, "error"); }
  });
  $("pipeList").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-act]"); if (!b) return; const act = b.dataset.act, card = b.closest("[data-pipeline-id]"), pid = card.dataset.pipelineId, p = find(pid);
    try {
      if (act === "up" || act === "down") {          // el orden es una edición: queda pendiente hasta «Guardar cambios»
        const tr = b.closest("tr"), tbody = tr.parentNode, rows = Array.from(tbody.querySelectorAll('tr[data-orderable="1"]')), i = rows.indexOf(tr), other = rows[act === "up" ? i - 1 : i + 1];
        if (!other) return;
        if (act === "up") tbody.insertBefore(tr, other); else tbody.insertBefore(other, tr);
        refreshArrows(tbody); markDirty(); b.focus(); return;
      }
      if (act === "rename") { const n = await askName("Cambiar nombre", "Nombre del embudo", p.name); if (!n) return; await savePendingFirst(); await api("PUT", "/api/crm/pipelines/" + pid, { name: n }); }
      else if (act === "default") { await savePendingFirst(); await api("POST", "/api/crm/pipelines/" + pid + "/default"); }
      else if (act === "parchive") { if (!await showConfirm("", { variant: "warning", title: "Archivar embudo", text: "El embudo deja de aparecer en el tablero. No se puede archivar si tiene oportunidades abiertas.", confirmLabel: "Archivar" })) return; await savePendingFirst(); await api("POST", "/api/crm/pipelines/" + pid + "/archive"); }
      else if (act === "prestore") { await savePendingFirst(); await api("POST", "/api/crm/pipelines/" + pid + "/restore"); }
      else if (act === "addstage") { const n = await askName("Nueva etapa", "Nombre de la etapa", ""); if (!n) return; await savePendingFirst(); await api("POST", "/api/crm/pipelines/" + pid + "/stages", { name: n, kind: "open", probability: 10 }); }
      else {
        const tr = b.closest("tr"), sid = tr.dataset.stageId;
        if (act === "archive") { if (!await showConfirm("", { variant: "warning", title: "Archivar etapa", text: "La etapa deja de aparecer en el tablero. No se puede archivar si tiene oportunidades abiertas.", confirmLabel: "Archivar" })) return; await savePendingFirst(); await api("POST", "/api/crm/stages/" + sid + "/archive"); }
        else if (act === "restore") { await savePendingFirst(); await api("POST", "/api/crm/stages/" + sid + "/restore"); }
      }
      showToast("Listo.", "success"); load();
    } catch (err) { showToast(err.message, "error"); if (!(window.GWParams && GWParams.hasDirty())) load(); }
  });
  load();
})();
