/* Contraseñas: ojito para ver/ocultar lo que se escribe + lista de requisitos EN VIVO con ✓/✗ e indicador de fuerza.
   La política (largos, lista de comunes, textos) la manda el servidor: GET /api/password-policy (app/security.py es la fuente de verdad);
   acá solo se evalúa. El servidor vuelve a validar siempre al guardar.
   Uso en HTML:  <input type="password" data-gw-eye ...>   (ojito automático)
                 <form data-gw-pwcheck data-gw-strict="1|0" data-gw-username="..."> con inputs [data-gw-new], [data-gw-confirm], [data-gw-current] opcionales,
                 un contenedor [data-gw-rules] y un botón [data-gw-submit]. La política puede venir en <script type="application/json" id="gwPolicy">. */
(function (root) {
  "use strict";

  function lower(s) { return String(s || "").trim().toLowerCase(); }
  function isLetter(c) { return c.toLowerCase() !== c.toUpperCase(); }
  function isDigit(c) { return c >= "0" && c <= "9"; }

  // Mismos criterios que app/security.py::password_rules (los fija tests/test_password_policy.py con los mismos casos que tests/js/password_policy_check.js).
  function evaluate(policy, password, username, extra) {
    password = password || "";
    const chars = Array.from(password);
    const low = lower(password);
    const letters = Array.from(low).filter(isLetter).join("");
    const common = new Set(policy.common || []);
    const checks = {
      length: chars.length >= policy.min_length,
      letter_digit: chars.some(isLetter) && chars.some(isDigit),
      not_username: !(username && low === lower(username)),
      not_common: !(common.has(low) || (common.has(letters) && letters.length >= 4) || (low.replace(/^[0-9]+|[0-9]+$/g, "") === "" && new Set(Array.from(low)).size <= 2)),
    };
    const rules = (policy.rules || []).map(function (r) { return { id: r.id, label: r.label, problem: r.problem, ok: !!checks[r.id] }; });
    extra = extra || {};
    if (extra.confirm !== undefined) rules.push({ id: "match", label: "Las dos contraseñas nuevas son iguales", problem: "Las contraseñas no coinciden", ok: password.length > 0 && password === extra.confirm });
    if (extra.current !== undefined) rules.push({ id: "different", label: "Es distinta a la contraseña actual", problem: "La contraseña nueva debe ser distinta a la actual", ok: password.length > 0 && password !== extra.current });
    const allOk = rules.length > 0 && rules.every(function (r) { return r.ok; });
    return { rules: rules, allOk: allOk, strength: strength(password, allOk) };
  }

  // 0..4. Sin cumplir los requisitos nunca pasa de «Débil»; por encima sube con el largo y la variedad (minúsculas, mayúsculas, números, símbolos).
  function strength(password, allOk) {
    const chars = Array.from(password || "");
    if (!chars.length) return { level: 0, label: "" };
    const kinds = [/[a-záéíóúñü]/, /[A-ZÁÉÍÓÚÑÜ]/, /[0-9]/, /[^A-Za-z0-9áéíóúñüÁÉÍÓÚÑÜ]/].filter(function (re) { return re.test(password); }).length;
    let pts = (chars.length >= 8 ? 1 : 0) + (chars.length >= 12 ? 1 : 0) + (chars.length >= 16 ? 1 : 0) + (kinds >= 3 ? 1 : 0) + (kinds >= 4 ? 1 : 0);
    let level = pts <= 1 ? 1 : pts === 2 ? 2 : pts === 3 ? 3 : 4;
    if (!allOk) level = Math.min(level, 1);
    return { level: level, label: ["", "Débil", "Aceptable", "Buena", "Muy buena"][level] };
  }

  const api = { evaluate: evaluate, strength: strength };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.GwPassword = api;
  if (typeof document === "undefined" || !document.addEventListener) return;

  /* ---------------------------------------------------------------- ojito */
  const script = document.currentScript;
  const ICONS = (script && script.getAttribute("data-icons")) || "/static/img/icons.svg";
  const SVGNS = "http://www.w3.org/2000/svg";

  function iconNode(name) {
    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("class", "gw-icon"); svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(SVGNS, "use");
    use.setAttribute("href", ICONS + "#" + name);
    svg.appendChild(use);
    return svg;
  }

  function addEye(input) {
    if (input.dataset.gwEyeDone) return;
    input.dataset.gwEyeDone = "1";
    const wrap = document.createElement("span");
    wrap.className = "gw-pw-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    input.classList.add("gw-pw-input");
    input.setAttribute("autocapitalize", "none"); input.setAttribute("autocorrect", "off"); input.setAttribute("spellcheck", "false");
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "gw-pw-eye"; btn.setAttribute("data-gw-eye-btn", "");
    btn.setAttribute("aria-label", "Mostrar contraseña"); btn.setAttribute("aria-pressed", "false");
    btn.appendChild(iconNode("i-eye"));
    wrap.appendChild(btn);
  }

  function setShown(btn, input, show) {
    input.type = show ? "text" : "password";
    btn.setAttribute("aria-label", show ? "Ocultar contraseña" : "Mostrar contraseña");
    btn.setAttribute("aria-pressed", show ? "true" : "false");
    btn.replaceChildren(iconNode(show ? "i-eye-off" : "i-eye"));
  }

  // pointerdown/mousedown no le quitan el foco al campo (en celular tampoco se cierra el teclado); al activar se devuelve el foco con el cursor donde estaba.
  document.addEventListener("mousedown", function (e) { if (e.target.closest && e.target.closest("[data-gw-eye-btn]")) e.preventDefault(); });
  document.addEventListener("click", function (e) {
    const btn = e.target.closest && e.target.closest("[data-gw-eye-btn]");
    if (!btn) return;
    const input = btn.parentNode.querySelector("input.gw-pw-input");
    if (!input) return;
    const a = input.selectionStart, b = input.selectionEnd;
    setShown(btn, input, input.type === "password");
    input.focus();
    try { if (a !== null) input.setSelectionRange(a, b); } catch (err) { /* sin cursor: no pasa nada */ }
  });
  // Nunca dejar la contraseña a la vista al enviar o al salir/volver a la página.
  function hideAll() {
    document.querySelectorAll("[data-gw-eye-btn]").forEach(function (btn) {
      const input = btn.parentNode.querySelector("input.gw-pw-input");
      if (input && input.type !== "password") setShown(btn, input, false);
    });
  }
  document.addEventListener("submit", hideAll, true);
  window.addEventListener("pagehide", hideAll);

  /* ------------------------------------------------- requisitos en vivo */
  function readPolicy(form) {
    const el = document.getElementById(form.getAttribute("data-gw-policy-id") || "gwPolicy");
    if (el) { try { return Promise.resolve(JSON.parse(el.textContent)); } catch (e) { /* cae al endpoint */ } }
    return fetch("/api/password-policy?strict=" + (form.getAttribute("data-gw-strict") === "1" ? 1 : 0), { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
  }

  function mountCheck(form) {
    if (form.dataset.gwPwMounted) return;
    form.dataset.gwPwMounted = "1";
    const nw = form.querySelector("[data-gw-new]"), cf = form.querySelector("[data-gw-confirm]"), cur = form.querySelector("[data-gw-current]");
    const box = form.querySelector("[data-gw-rules]"), submit = form.querySelector("[data-gw-submit]");
    const userEl = form.querySelector("[data-gw-username-input]");
    if (!nw || !box) return;
    const fixedUser = form.getAttribute("data-gw-username") || "";
    let policy = null;
    if (submit) submit.disabled = true;
    box.innerHTML = "";
    const title = document.createElement("p"); title.className = "gw-pw-title"; title.textContent = "Tu contraseña nueva debe cumplir:";
    const list = document.createElement("ul"); list.className = "gw-pw-rules";
    const meter = document.createElement("div"); meter.className = "gw-pw-meter";
    const bar = document.createElement("span"); bar.className = "gw-pw-meter__bar";
    const mlabel = document.createElement("span"); mlabel.className = "gw-pw-meter__label";
    meter.appendChild(bar); meter.appendChild(mlabel);
    const live = document.createElement("p"); live.className = "gw-sr-only"; live.setAttribute("aria-live", "polite");
    box.appendChild(title); box.appendChild(list); box.appendChild(meter); box.appendChild(live);

    function render() {
      if (!policy) return;
      const res = evaluate(policy, nw.value, userEl ? userEl.value : fixedUser, {
        confirm: cf ? cf.value : undefined, current: cur ? cur.value : undefined,
      });
      // «Repite» y «distinta a la actual» solo se marcan como faltantes cuando ya se escribió algo; antes se muestran neutros.
      const items = res.rules.map(function (r) {
        const li = document.createElement("li");
        const touched = nw.value.length > 0;
        li.className = "gw-pw-rule " + (r.ok ? "is-ok" : touched ? "is-bad" : "is-idle");
        const mark = document.createElement("span"); mark.className = "gw-pw-mark"; mark.setAttribute("aria-hidden", "true"); mark.textContent = r.ok ? "✓" : touched ? "✗" : "•";
        const txt = document.createElement("span"); txt.textContent = r.label;
        const sr = document.createElement("span"); sr.className = "gw-sr-only"; sr.textContent = r.ok ? " (se cumple)" : " (falta)";
        li.appendChild(mark); li.appendChild(txt); li.appendChild(sr);
        return li;
      });
      list.replaceChildren.apply(list, items);
      bar.className = "gw-pw-meter__bar lvl-" + res.strength.level;
      mlabel.textContent = res.strength.label ? "Fuerza: " + res.strength.label : "";
      const missing = res.rules.filter(function (r) { return !r.ok; }).length;
      live.textContent = nw.value ? (missing ? "Faltan " + missing + " requisitos" : "Cumple todos los requisitos") : "";
      if (submit) submit.disabled = !res.allOk || (cur ? !cur.value : false);
      form.dataset.gwPwOk = res.allOk ? "1" : "0";
    }
    form.addEventListener("reset", function () { setTimeout(render, 0); });
    form.addEventListener("input", render);          // delegación: cualquier campo de la forma
    readPolicy(form).then(function (p) { if (!p) { if (submit) submit.disabled = false; return; } policy = p; render(); });   // sin política (fallo de red): se deja enviar y manda el servidor
    form.addEventListener("submit", function (e) { if (form.dataset.gwPwOk === "0" && policy) e.preventDefault(); });
  }

  function init() {
    document.querySelectorAll("input[type=password][data-gw-eye]").forEach(addEye);
    document.querySelectorAll("form[data-gw-pwcheck]").forEach(mountCheck);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
  api.init = init;
})(typeof window !== "undefined" ? window : globalThis);
