/* CRM - Embudos y etapas (C2, solo administradores). Cada cambio se guarda al pulsar su botón y la lista se vuelve a leer del servidor; el orden se cambia con flechas (sirve con teclado).
   Sin temporizadores ni sondeos. Lo escrito por personas se pinta con textContent / .value. */
(function () {
  "use strict";
  const X = window.CRMX, root = document.getElementById("pipeRoot");
  if (!X || !root) return;
  const { $, el, api, stateBlock, busy } = X;
  const KINDS = { open: "Abierta", won: "Ganada", lost: "Perdida" };
  let pipelines = [];

  function stageRow(p, s, openIds) {
    const tr = el("tr"); tr.dataset.stageId = s.id; tr.dataset.pipelineId = p.id;
    const td = (label, node) => { const c = el("td"); c.dataset.label = label; c.appendChild(node); tr.appendChild(c); return c; };
    const name = X.input("text", 80); name.value = s.name; name.setAttribute("aria-label", "Nombre de la etapa " + s.name); name.dataset.f = "name"; td("Etapa", name);
    const prob = X.input("text", 3); prob.value = String(s.probability); prob.inputMode = "numeric"; prob.setAttribute("aria-label", "Probabilidad de " + s.name); prob.dataset.f = "probability"; td("Probabilidad (%)", prob);
    td("Tipo", el("span", "gw-badge " + (s.kind === "won" ? "gw-badge--ok" : s.kind === "lost" ? "gw-badge--warn" : "gw-badge--info"), KINDS[s.kind]));
    const acts = el("div", "crm-card__actions");
    const mk = (label, act, aria) => { const b = el("button", "gw-btn gw-btn--secondary gw-btn--sm", label); b.type = "button"; b.dataset.act = act; if (aria) b.setAttribute("aria-label", aria); return b; };
    const i = openIds.indexOf(s.id);
    if (i >= 0 && !s.archived) { const up = mk("↑", "up", "Subir " + s.name), dn = mk("↓", "down", "Bajar " + s.name); up.disabled = i === 0; dn.disabled = i === openIds.length - 1; acts.appendChild(up); acts.appendChild(dn); }
    if (!s.archived) acts.appendChild(mk("Guardar", "save")); acts.appendChild(mk(s.archived ? "Restaurar" : "Archivar", s.archived ? "restore" : "archive"));
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
      if (act === "rename") { const n = await askName("Cambiar nombre", "Nombre del embudo", p.name); if (!n) return; await api("PUT", "/api/crm/pipelines/" + pid, { name: n }); }
      else if (act === "default") await api("POST", "/api/crm/pipelines/" + pid + "/default");
      else if (act === "parchive") { if (!await showConfirm("", { variant: "warning", title: "Archivar embudo", text: "El embudo deja de aparecer en el tablero. No se puede archivar si tiene oportunidades abiertas.", confirmLabel: "Archivar" })) return; await api("POST", "/api/crm/pipelines/" + pid + "/archive"); }
      else if (act === "prestore") await api("POST", "/api/crm/pipelines/" + pid + "/restore");
      else if (act === "addstage") { const n = await askName("Nueva etapa", "Nombre de la etapa", ""); if (!n) return; await api("POST", "/api/crm/pipelines/" + pid + "/stages", { name: n, kind: "open", probability: 10 }); }
      else {
        const tr = b.closest("tr"), sid = tr.dataset.stageId;
        if (act === "save") await busy(b, () => api("PUT", "/api/crm/stages/" + sid, { name: tr.querySelector('[data-f="name"]').value.trim(), probability: tr.querySelector('[data-f="probability"]').value.trim() }));
        else if (act === "archive") { if (!await showConfirm("", { variant: "warning", title: "Archivar etapa", text: "La etapa deja de aparecer en el tablero. No se puede archivar si tiene oportunidades abiertas.", confirmLabel: "Archivar" })) return; await api("POST", "/api/crm/stages/" + sid + "/archive"); }
        else if (act === "restore") await api("POST", "/api/crm/stages/" + sid + "/restore");
        else if (act === "up" || act === "down") {
          const ids = p.stages.filter((s) => s.kind === "open" && !s.archived).map((s) => s.id), i = ids.indexOf(Number(sid)), j = act === "up" ? i - 1 : i + 1;
          [ids[i], ids[j]] = [ids[j], ids[i]]; await api("POST", "/api/crm/pipelines/" + pid + "/stages/reorder", { stage_ids: ids });
        }
      }
      showToast("Listo.", "success"); load();
    } catch (err) { showToast(err.message, "error"); load(); }
  });
  load();
})();
