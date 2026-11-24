/* Confirmaciones FUERTES de gestión (revisión 22-nov-2026, docs/revision_2026-11-22/13): una acción que no se puede deshacer cuesta siempre lo mismo, ESCRIBIR una palabra
   (el mismo patrón de «escribe BORRAR» de dependents-upload.js y de «escribe el nombre del evento» de biometric-purge.js). Se apoya en showPrompt/showConfirm de toast.js; nada de alert/confirm.
     GWConfirm.typed(html, palabra, { title, confirmLabel })  → Promise<boolean>   (true solo si escribió la palabra; mayúsculas, tildes y espacios de más no cuentan)
     GWConfirm.matches(escrito, palabra)                      → boolean (lógica pura; probada en tests/js/gw_confirm_typed_check.js)
     GWConfirm.reopenEvent(nombreDelEstado)                   → Promise<boolean>   Finalizado → En proceso, con texto propio
     GWConfirm.activatePaidForm({ account, isGolden })        → Promise<boolean>   publicar («Activo») un formulario que cobra
     GWConfirm.accountLine(payments, { admin })               → HTML de «Cobra con: …» para el editor de formularios (solo lectura)
   Los TEXTOS están aquí para que haya un solo lugar donde leerlos y probarlos. */
(function (root) {
  var norm = function (v) { return String(v == null ? '' : v).normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\s+/g, ' ').trim().toUpperCase(); };
  var esc = function (v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  function matches(typed, word) { var w = norm(word); return !!w && norm(typed) === w; }

  var TEXT = {
    suppressAll: 'Se van a <b>suprimir TODOS los datos</b> de la persona con cédula <b>{id}</b>: sus datos personales, su rostro y su historial de ingresos (queda anónimo). <b>No se puede deshacer</b> y no hay copia para devolverlo.<br><br>Revisa la cédula dígito por dígito: un número mal escrito suprime a otra persona.<br><br>Para confirmar escribe la palabra <b>SUPRIMIR</b>.',
    revoke: 'Se va a <b>revocar la autorización</b> de la persona con cédula <b>{id}</b>: se borran su foto y los datos de su rostro (no se puede deshacer) y queda la constancia. Sigue entrando por cédula o QR.<br><br>Revisa la cédula dígito por dígito.<br><br>Para confirmar escribe la palabra <b>REVOCAR</b>.',
    purgeTemp: 'Se van a <b>ELIMINAR las {n} cuentas de digitador</b> de este evento. <b>No se pueden recuperar.</b> Si alguna también está en otro evento, a esa solo se le quita este evento; el compromiso firmado de cada una queda guardado como evidencia del evento, sin la cuenta.<br><br>Hazlo solo cuando el evento ya terminó.<br><br>Para confirmar escribe la palabra <b>ELIMINAR</b>.',
    refund: 'Se le pedirá a Wompi <b>devolver {amount}</b> del pago <b>{reference}</b>. Es dinero que sale de la cuenta y <b>no se puede deshacer</b>.<br><br>Para confirmar escribe la palabra <b>REEMBOLSAR</b>.',
    reopen: 'Este evento está <b>Finalizado</b> y lo vas a <b>reabrir</b> («{label}»). Al reabrirlo:<br>• Se puede volver a registrar, imprimir y entrar con el rostro.<br>• Los formularios web y el acceso de los usuarios temporales vuelven a funcionar.<br>• <b>Rostros:</b> el plazo de 7 días para borrarlos se detiene y empieza de cero cuando el evento se finalice otra vez. Los rostros que ya se borraron no vuelven.<br><br>Para confirmar escribe la palabra <b>REABRIR</b>.',
    disableKey: 'Vas a <b>deshabilitar la llave {code}</b>. Apenas el servidor que la usa tenga internet, <b>se dará de baja solo</b>: borra su base de datos, los archivos de los eventos, las copias y los secretos, y se desinstala. <b>Lo que no se haya subido a la nube («Pasar a internet» con 0 pendientes) se pierde para siempre</b>, y la llave no se puede reutilizar.<br><br>Para confirmar escribe la palabra <b>DESHABILITAR</b>.',
    activatePaid: 'Vas a dejar este formulario en <b>«Activo»</b> y tiene <b>campo de pago</b>: desde que guardes, el enlace público <b>cobra dinero real</b> a quien se inscriba.<br><br><b>Cobra con:</b> {account}.<br><br>Antes de publicar revisa el precio y haz una inscripción con el enlace de pruebas.',
  };
  var fill = function (tpl, vars) { return tpl.replace(/\{(\w+)\}/g, function (m, k) { return vars && vars[k] != null ? esc(vars[k]) : m; }); };

  function typed(html, word, opts) {
    opts = opts || {};
    if (typeof root.showPrompt !== 'function') return Promise.resolve(false);
    var pending = root.showPrompt(html, { title: opts.title || 'Confirma escribiendo', placeholder: word, confirmLabel: opts.confirmLabel || 'Confirmar',
      validate: function (v) { return matches(v, word) ? '' : 'No se hizo nada: hay que escribir ' + word + ' tal cual. Corrígelo o cancela.'; } });
    // showPrompt arma el cuadro en el acto: el botón de confirmar de una acción que no se deshace va en ROJO (regla de oro 3), no en dorado.
    var okBtn = typeof document !== 'undefined' && document.getElementById ? document.getElementById('toastPromptOk') : null;
    if (okBtn && okBtn.classList) { okBtn.classList.remove('gw-btn--primary'); okBtn.classList.add('gw-btn--danger'); }
    return pending.then(function (v) {
      if (v === null) return false;
      if (matches(v, word)) return true;
      if (root.showToast) root.showToast('No se hizo nada: hay que escribir ' + word + '.', 'error');
      return false;
    });
  }

  function reopenEvent(label) { return typed(fill(TEXT.reopen, { label: label || 'En Proceso' }), 'REABRIR', { title: 'Reabrir un evento finalizado', confirmLabel: 'Reabrir el evento' }); }

  // Nombre legible de la cuenta que cobra. payments = form.payments del API (`account_id` nulo = no se le asignó cuenta de cobro: cobra la de Golden).
  function accountName(payments, accounts) {
    var id = payments && payments.account_id;
    if (!id) return null;
    var a = (accounts || []).filter(function (x) { return x.id === id; })[0];
    return a && a.name ? a.name : 'cuenta de cobro n.º ' + id;
  }
  function accountLine(payments, o) {
    o = o || {};
    var name = accountName(payments, o.accounts);
    var where = o.admin ? '<a href="/cuentas-de-cobro">Cuentas de cobro</a>' : '«Cuentas de cobro» (lo hace un administrador)';
    if (name) return '<b>Cobra con:</b> ' + esc(name) + ' · se cambia en ' + where + '.';
    return '<b>Cobra con:</b> (sin asignar) → asignar en ' + where + '. Mientras no se asigne, cobra la cuenta de Golden.';
  }
  function activatePaidForm(o) {
    o = o || {};
    var account = o.account ? esc(o.account) : '(sin asignar): cobra la cuenta de Golden. Para que cobre otra, asígnala en «Cuentas de cobro» antes de publicar';
    if (typeof root.showConfirm !== 'function') return Promise.resolve(false);
    return root.showConfirm(TEXT.activatePaid.replace('{account}', account), { variant: 'warning', title: 'Publicar un formulario que cobra', confirmLabel: 'Sí, publicar y cobrar' });
  }

  var api = { typed: typed, matches: matches, norm: norm, fill: fill, TEXT: TEXT, reopenEvent: reopenEvent, activatePaidForm: activatePaidForm, accountLine: accountLine, accountName: accountName };
  root.GWConfirm = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
