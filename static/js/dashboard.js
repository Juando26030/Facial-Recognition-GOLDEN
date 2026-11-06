/* Inicio del personal sin panel (digitador/cliente): tarjetas por evento con estado, botón «Entrar» y buscador.
   Los datos vienen de /api/my-events; todo el texto dinámico pasa por esc(). */
(function () {
  "use strict";
  const script = document.currentScript;
  const ICONS = (script && script.getAttribute("data-icons")) || "/static/img/icons.svg";
  const list = document.getElementById("myEventsList");
  const searchBox = document.getElementById("eventSearchBox");
  const search = document.getElementById("eventSearch");
  const info = document.getElementById("eventSearchInfo");
  let events = [];

  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const norm = (v) => String(v == null ? "" : v).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  function fmtDate(d) { return d ? new Date(d).toLocaleDateString("es-CO") : ""; }
  function icon(name) { return '<svg class="gw-icon" aria-hidden="true"><use href="' + esc(ICONS) + "#i-" + name + '"/></svg>'; }

  function empty(title, text) {
    list.innerHTML = '<div class="gw-empty">' + icon("calendar") + "<strong>" + esc(title) + "</strong><p>" + esc(text) + "</p></div>";
  }

  function card(e) {
    const place = [e.location, e.city].filter(Boolean).join(" · ");
    const when = fmtDate(e.start_date);
    return '<article class="gw-card-row">' +
      '<div class="gw-card-row__head"><h2 class="gw-card-row__title">' + esc(e.name) + "</h2>" +
      '<span class="gw-badge gw-badge--ok">En proceso</span></div>' +
      '<p class="gw-card-row__meta">' + esc([place, when].filter(Boolean).join(" · ")) + "</p>" +
      '<div class="gw-card-row__actions"><a class="gw-btn gw-btn--primary" href="/kiosk/' + encodeURIComponent(e.id) + '" aria-label="Entrar al evento ' + esc(e.name) + '">Entrar</a></div>' +
      "</article>";
  }

  function render() {
    const q = norm(search.value).trim();
    const shown = q ? events.filter((e) => norm([e.name, e.location, e.city, e.event_code].join(" ")).includes(q)) : events;
    if (!shown.length) { empty("Ningún evento coincide", "Prueba con otra palabra o borra la búsqueda."); }
    else { list.innerHTML = '<div class="gw-cards">' + shown.map(card).join("") + "</div>"; }
    info.textContent = q ? shown.length + " de " + events.length + " eventos" : "";
  }

  async function load() {
    try {
      const res = await fetch("/api/my-events", { credentials: "same-origin" });
      if (!res.ok) throw new Error("http " + res.status);
      const data = await res.json();
      events = data.events || [];
      if (!events.length) {
        // has_any_authorization distingue «no te han asignado a nada» de «te asignaron, pero el evento aún no está En proceso» (QA, 2026-09-16).
        empty(data.has_any_authorization ? "Aún no hay eventos en proceso" : "No tienes eventos autorizados todavía",
          data.has_any_authorization
            ? "Ya tienes evento(s) asignado(s), pero ninguno está «En proceso» todavía. Pide a un coordinador que lo active cuando corresponda."
            : "Pide a un coordinador que te asigne desde el evento.");
        return;
      }
      searchBox.hidden = events.length < 4;
      render();
    } catch (err) {
      empty("No pudimos cargar tus eventos", "Revisa tu conexión y recarga la página.");
      if (window.showToast) window.showToast("No se pudieron cargar los eventos.", "error");
    } finally {
      list.removeAttribute("aria-busy");
    }
  }

  search.addEventListener("input", render);
  load();
})();
