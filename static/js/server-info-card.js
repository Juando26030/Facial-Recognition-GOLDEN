/* Configuración › Servidor local, SOLO en un servidor local: muestra los datos de este servidor (sin instalador ni llaves). */
(function () {
  "use strict";
  var body = document.getElementById("serverInfoBody");
  if (!body) return;

  function get(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
  }
  function row(label, value) {
    var dt = document.createElement("dt"); dt.textContent = label;
    var dd = document.createElement("dd"); dd.textContent = value;
    body.appendChild(dt); body.appendChild(dd);
  }

  Promise.all([get("/api/ops/server-id"), get("/api/ops/local-address"), get("/api/ops/version"), get("/api/ops/update-status")]).then(function (r) {
    var id = r[0], addr = r[1], ver = r[2], upd = r[3];
    body.textContent = "";
    row("Llave de producto", id && id.configured ? (id.disabled ? "Deshabilitada" : "Activa") : "Sin configurar");
    if (id && id.id) row("Identificador del servidor", String(id.id));
    var list = addr && (addr.addresses || []);
    row("Cómo conectarse (cable)", list && list.length ? list.map(function (a) { return "https://" + a + ":8443"; }).join("   ") : "No se encontró una dirección de red");
    if (ver) row("Versión", String(ver.version || ver.commit || "—"));
    if (upd) row("Actualizaciones", upd.message || upd.status || "Al día");
  }).catch(function () {
    body.textContent = "No se pudieron leer los datos del servidor.";
  });
})();
