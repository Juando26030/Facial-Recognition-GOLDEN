/* CRM - Importar de SuiteCRM (C1c, solo administradores). Sin temporizadores ni sondeos: el botón «Actualizar» vuelve a leer las corridas. Todo texto se pinta con textContent. */
(function () {
  "use strict";
  const X = window.CRMX, root = document.getElementById("impRoot");
  if (!X || !root) return;
  const { $, el, api, stateBlock } = X;
  const MODES = { sample: "Muestra", dry_run: "Prueba completa", apply: "Carga" };
  const STATUS = { queued: "En cola", running: "En curso", done: "Terminada", failed: "Falló", cancelled: "Cancelada" };
  const KINDS = { accounts: "Cuentas", contacts: "Contactos", products: "Productos", opportunities: "Oportunidades", activities: "Actividades", quotes: "Cotizaciones", quote_lines: "Líneas de cotización", proformas: "Proformas" };
  let lastDry = null, applyEnabled = false;

  function say(text) { $("impMsg").textContent = text || ""; }
  function line(label, c) { return label + ": " + c.read + " leídas · " + c.created + " nuevas · " + c.skipped_existing + " ya existían · " + c.rejected + " rechazadas"; }

  function runCard(r) {
    const card = el("section", "gw-card gw-stack"); card.setAttribute("aria-label", "Corrida " + r.id);
    const bar = el("div", "crm-panel__bar"); bar.appendChild(el("h2", "crm-panel__title", MODES[r.mode] + " #" + r.id));
    bar.appendChild(el("span", "gw-badge " + (r.status === "done" ? "gw-badge--ok" : r.status === "failed" ? "gw-badge--warn" : "gw-badge--info"), STATUS[r.status] || r.status)); card.appendChild(bar);
    card.appendChild(el("p", "gw-hint", X.fmtDateTime(r.created_at)));
    if (r.error) card.appendChild(el("p", "gw-text", r.error));
    Object.keys(KINDS).forEach((k) => {
      const s = r.counts && r.counts[k]; if (!s) return;
      card.appendChild(el("p", "gw-text", line(KINDS[k], s.counts)));
      if (s.note) card.appendChild(el("p", "gw-hint", s.note));
      const c = s.counts || {}, extra = [];
      if (c.without_account) extra.push(c.without_account + " sin cuenta conocida"); if (c.unlinked) extra.push(c.unlinked + " sin oportunidad ni cuenta");
      if (c.without_quote) extra.push(c.without_quote + " sin cotización ligada"); if (c.stage_unmapped) extra.push(c.stage_unmapped + " con etapa no reconocida");
      if (c.currency_defaulted) extra.push(c.currency_defaulted + " con moneda no reconocida (COP)"); if (c.total_only) extra.push(c.total_only + " solo con total (sin líneas)");
      if (c.lines) extra.push(c.lines + " líneas");
      if (extra.length) card.appendChild(el("p", "gw-hint", extra.join(" · ")));
      (s.rejected || []).slice(0, 10).forEach((x) => card.appendChild(el("p", "gw-hint", "Fila " + x.row + ": " + x.reason)));
    });
    if (r.counts && r.counts.pairs) {
      const p = r.counts.pairs; card.appendChild(el("p", "gw-text", "Parejas con clientes de la plataforma: " + p.seguro + " seguras · " + p.dudoso + " dudosas · " + p.sin_pareja + " sin pareja"));
      const b = el("button", "gw-btn gw-btn--secondary gw-btn--sm", "Revisar parejas"); b.type = "button"; b.dataset.act = "pairs"; b.dataset.run = r.id; card.appendChild(b);
    }
    const box = el("div", "gw-stack"); box.dataset.pairs = r.id; card.appendChild(box);
    return card;
  }

  async function load() {
    const box = $("impRuns"); box.setAttribute("aria-busy", "true");
    try {
      const d = await api("GET", "/api/crm/import/runs"); applyEnabled = d.apply_enabled; box.replaceChildren();
      lastDry = (d.items.find((r) => r.mode === "dry_run" && r.status === "done") || {}).id || null;
      $("impApply").disabled = !applyEnabled; $("impApply").title = applyEnabled ? "" : "La carga real está desactivada en este entorno.";
      if (!d.items.length) box.appendChild(stateBlock("empty", "Todavía no hay corridas", "Sube un archivo de prueba y pulsa «Muestra».", null, "upload"));
      d.items.forEach((r) => box.appendChild(runCard(r)));
    } catch (e) { box.replaceChildren(stateBlock("error", "No se pudieron cargar las corridas", e.message, load)); }
    finally { box.setAttribute("aria-busy", "false"); }
  }

  // Cloud Run rechaza peticiones de más de 32 MB: los CSV se comprimen aquí (el servidor los descomprime solo).
  async function gzipFile(file) {
    if (typeof CompressionStream === "undefined") return [file];
    const blob = await new Response(file.stream().pipeThrough(new CompressionStream("gzip"))).blob();
    return [blob, file.name + ".gz"];
  }

  async function start(mode) {
    const fd = new FormData();
    const picked = [...root.querySelectorAll("input[type=file][data-kind]")].filter((i) => i.files[0]);
    if (!picked.length) { say("Elige al menos un archivo."); return; }
    say("Preparando archivos…");
    try { for (const i of picked) fd.append(i.dataset.kind, ...(await gzipFile(i.files[0]))); } catch (e) { say("No se pudo preparar el archivo: " + e.message); return; }
    fd.append("mode", mode);
    if (mode === "apply") {
      if (!lastDry) { say("Primero termina una prueba completa con estos mismos archivos."); return; }
      const word = await showPrompt("Para cargar de verdad escribe CARGAR.", { title: "Confirmar la carga", confirmLabel: "Cargar" });
      if (word == null) return; fd.append("confirm", word); fd.append("dry_run_id", String(lastDry));
    }
    say("Enviando…");
    try {
      const r = await fetch("/api/crm/import/runs", { method: "POST", body: fd }), data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "No se pudo iniciar la corrida.");
      say("Corrida #" + data.id + " en cola. Pulsa «Actualizar» en unos segundos."); await load();
    } catch (e) { say(e.message); }
  }

  async function pairs(runId, box) {
    box.replaceChildren(); const d = await api("GET", "/api/crm/import/runs/" + runId + "/pairs");
    if (!d.items.length) { box.appendChild(el("p", "gw-hint", "No hay parejas para revisar.")); return; }
    d.items.forEach((p) => {
      const row = el("div", "crm-actions");
      row.appendChild(el("span", "gw-text", p.tenant_name + " ↔ " + (p.suitecrm_name || "—") + " (" + p.score + " · " + p.bucket + (p.decision !== "pending" ? " · " + p.decision : "") + ")"));
      if (p.suitecrm_code != null && p.decision !== "applied") ["approved", "rejected"].forEach((dec) => { const b = el("button", "gw-btn gw-btn--secondary gw-btn--sm", dec === "approved" ? "Aprobar" : "Rechazar"); b.type = "button"; b.dataset.act = "decide"; b.dataset.run = runId; b.dataset.pair = p.id; b.dataset.dec = dec; row.appendChild(b); });
      box.appendChild(row);
    });
    const go = el("button", "gw-btn gw-btn--primary gw-btn--sm", "Aplicar parejas aprobadas"); go.type = "button"; go.dataset.act = "applypairs"; go.dataset.run = runId; go.disabled = !applyEnabled; box.appendChild(go);
  }

  root.addEventListener("click", async (e) => {
    const t = e.target.closest("button"); if (!t) return;
    try {
      if (t.dataset.mode) await start(t.dataset.mode);
      else if (t.id === "impRefresh") await load();
      else if (t.dataset.act === "pairs") await pairs(t.dataset.run, root.querySelector('[data-pairs="' + t.dataset.run + '"]'));
      else if (t.dataset.act === "decide") { await api("POST", "/api/crm/import/runs/" + t.dataset.run + "/pairs/decide", { pair_ids: [Number(t.dataset.pair)], decision: t.dataset.dec }); await pairs(t.dataset.run, t.closest("[data-pairs]")); }
      else if (t.dataset.act === "applypairs") {
        const word = await showPrompt("Para aplicar las parejas aprobadas escribe CARGAR.", { title: "Confirmar", confirmLabel: "Aplicar" }); if (word == null) return;
        const fd = new FormData(); fd.append("confirm", word);
        const r = await fetch("/api/crm/import/runs/" + t.dataset.run + "/pairs/apply", { method: "POST", body: fd }), d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || "No se pudo aplicar.");
        showToast("Parejas aplicadas: " + d.applied + " (omitidas: " + d.skipped + ")", "success");
      }
    } catch (err) { showToast(err.message, "error"); }
  });
  load();
})();
