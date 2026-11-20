/* Cierre de sesión por inactividad del personal (3-nov-2026; servidor: app/idle.py, docs/22_SESION_INACTIVIDAD.md).
   Esta página solo AVISA y avisa al servidor cuando la persona hizo algo real (clic, teclas, toque, scroll); el que hace cumplir el tiempo es el servidor (401 «session_expired»).
   - Los sondeos y refrescos de la página NO cuentan: solo `POST /api/session/touch` (como mucho cada 30 s mientras haya uso) renueva la sesión.
   - Un minuto antes de vencer sale el aviso «Tu sesión se cerrará por inactividad» con «Seguir conectado». Al vencer: se cierra la sesión y se lleva a /login?expirada=1.
   - Sin conexión NO se expulsa a nadie: si el servidor no responde, no se avisa ni se cierra; los ingresos hechos sin red (IndexedDB: contingencia / bandeja de salida) quedan guardados y se envían al volver a entrar.
   - Una página que no debe cerrarse sola pone `window.GW_IDLE_OFF = true` antes de cargar este archivo. */
(function (root) {
  "use strict";
  var TOUCH_MS = 30000, TICK_MS = 5000;

  /* Núcleo sin DOM (se prueba con tests/js/idle_session_check.js). d = { now(), call(method, url) -> Promise<{status, json}> (rechaza si no hay red), isOnline(), warn(secondsLeft, onContinue) -> {close()}, expire() }. */
  function create(d) {
    var limitMs = 0, deadline = 0, warnMs = 60000, lastTouch = 0, dirty = false, warned = null, stopped = false, busy = false;

    function apply(j) {
      limitMs = j.idle_seconds * 1000; warnMs = (j.warn_seconds || 60) * 1000;
      deadline = d.now() + j.remaining * 1000;
    }
    function finish() { if (stopped) return; stopped = true; if (warned) { try { warned.close(); } catch (e) { /* ya cerrado */ } warned = null; } d.expire(); }
    function disable() { stopped = true; if (warned) { try { warned.close(); } catch (e) { /* ya cerrado */ } warned = null; } }
    function closeWarn() { if (warned) { try { warned.close(); } catch (e) { /* ya cerrado */ } warned = null; } }

    function handle(res) {            // true si la respuesta es de una sesión viva y ya se aplicó
      if (res.status === 401) { finish(); return false; }
      if (res.status !== 200 || !res.json) return false;
      if (res.json.enabled === false) { disable(); return false; }
      apply(res.json); return true;
    }
    async function info() {
      try { return handle(await d.call("GET", "/api/session/idle")); } catch (e) { return null; }       // null = sin red / sin respuesta: no se toma ninguna decisión
    }
    async function touch() {
      lastTouch = d.now();
      try {
        var ok = handle(await d.call("POST", "/api/session/touch"));
        if (ok) { dirty = false; closeWarn(); }
        return ok;
      } catch (e) { return null; }       // sin red: el uso queda pendiente y se reintenta
    }
    async function check() {
      var ok = await info();
      if (ok === null || ok === false || stopped) return;
      if (dirty) { await touch(); return; }                                 // hubo uso desde el último aviso al servidor: se renueva
      var left = deadline - d.now();
      if (left <= 0) { finish(); return; }
      if (left > warnMs) { closeWarn(); return; }                           // otra pestaña la renovó
      if (!warned) warned = d.warn(Math.ceil(left / 1000), function () { return api.keepAlive(); });
    }
    async function tick() {
      if (stopped || busy) return;
      busy = true;
      try {
        if (!limitMs) { await info(); if (limitMs) lastTouch = d.now(); return; }
        if (!d.isOnline()) return;                                          // sin conexión no se avisa ni se cierra
        if (dirty && !warned && d.now() - lastTouch >= TOUCH_MS) { await touch(); return; }
        if (d.now() >= deadline - warnMs) await check();
      } finally { busy = false; }
    }
    var api = {
      start: function () { return info().then(function (ok) { if (ok) lastTouch = d.now(); }); },
      tick: tick,
      input: function () { if (!stopped && !warned) dirty = true; },        // con el aviso abierto solo cuenta el botón «Seguir conectado»
      keepAlive: async function () { var ok = await touch(); if (ok === null) warned = null; return ok; },      // sin red: se vuelve a avisar en el siguiente ciclo
      state: function () { return { limitMs: limitMs, deadline: deadline, dirty: dirty, warned: !!warned, stopped: stopped }; },
    };
    return api;
  }

  /* Detecta en CUALQUIER petición de la página el 401 «session_expired» (otra pestaña venció, o el servidor la cerró): avisa y lleva al inicio de sesión sin descartar la cola sin conexión. */
  function boot() {
    if (root.GW_IDLE_OFF || root.__gwIdle || typeof root.fetch !== "function" || !root.document) return;
    root.__gwIdle = true;
    var original = root.fetch.bind(root), done = false;
    function goLogin() {
      if (done) return; done = true;
      try { root.dispatchEvent(new Event("gw:session-expired")); } catch (e) { /* sin eventos */ }
      var box = document.createElement("div");
      box.setAttribute("role", "alertdialog");
      box.style.cssText = "position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;background:rgba(10,14,46,.82);padding:24px";
      box.innerHTML = '<div style="background:#fff;border-radius:16px;padding:24px 28px;max-width:440px;text-align:center;font:600 1.05rem system-ui,sans-serif;color:#0a0e2e"><div style="font-size:2rem">🔒</div><p style="margin:8px 0">Tu sesión se cerró por inactividad.</p><p style="margin:8px 0;font-weight:400;font-size:.95rem">Los ingresos hechos sin conexión siguen guardados en este dispositivo. Te llevamos al inicio de sesión…</p></div>';
      (document.body || document.documentElement).appendChild(box);
      original("/logout", { method: "POST", credentials: "same-origin", redirect: "manual", headers: { "X-Gw-Passive": "1" } }).catch(function () { /* el servidor ya la cerró */ });
      var here = (root.location.pathname || "/") + (root.location.search || "") + (root.location.hash || "");          // el servidor revalida la dirección (app/nextpage.py): solo vuelve a páginas del mismo sitio
      var back = here.charAt(0) === "/" && here.indexOf("/login") !== 0 ? "&next=" + encodeURIComponent(here) : "";
      setTimeout(function () { root.location.href = "/login?expirada=1" + back; }, 2500);
    }
    root.fetch = function () {
      return original.apply(null, arguments).then(function (res) {
        if (res && res.status === 401 && !done) res.clone().json().then(function (j) { if (j && j.detail === "session_expired") goLogin(); }, function () {});
        return res;
      });
    };
    var ctl = create({
      now: function () { return Date.now(); },
      isOnline: function () { return root.navigator ? root.navigator.onLine !== false : true; },
      call: function (method, url) {
        return original(url, { method: method, credentials: "same-origin", cache: "no-store", headers: { "X-Gw-Passive": method === "GET" ? "1" : "0" } })
          .then(function (res) { return res.json().then(function (j) { return { status: res.status, json: j }; }, function () { return { status: res.status, json: null }; }); });
      },
      warn: function (secondsLeft, onContinue) {
        if (typeof root.showToast !== "function") return null;
        return root.showToast("Tu sesión se cerrará por inactividad en " + (secondsLeft >= 50 ? "1 minuto" : secondsLeft + " segundos") + ".", "error", { duration: 60000, action: { label: "Seguir conectado", onClick: function () { onContinue(); } } });
      },
      expire: goLogin,
    });
    ["click", "keydown", "pointerdown", "touchstart", "wheel", "scroll"].forEach(function (ev) { document.addEventListener(ev, function () { ctl.input(); }, { capture: true, passive: true }); });
    document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") ctl.tick(); });
    setInterval(function () { ctl.tick(); }, TICK_MS);
    ctl.start();
  }

  if (typeof module !== "undefined" && module.exports) module.exports = { create: create, TOUCH_MS: TOUCH_MS };
  else boot();
})(typeof window !== "undefined" ? window : this);
