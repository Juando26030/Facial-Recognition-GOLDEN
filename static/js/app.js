document.addEventListener("DOMContentLoaded", () => {

    const EVENT_ID = window.EVENT_ID;
    function withEvent(url) {
        return url + (url.includes('?') ? '&' : '?') + 'event_id=' + EVENT_ID;
    }

    const tabs = document.querySelectorAll('.tab');
    const sections = document.querySelectorAll('.section');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            sections.forEach(s => s.classList.remove('active'));

            tab.classList.add('active');
            document.getElementById(tab.dataset.tab).classList.add('active');
            try { history.replaceState(null, '', '#' + tab.dataset.tab); } catch (err) { /* sin historial */ }          // al refrescar vuelve a esta pestaña

            if (tab.dataset.tab === 'directorio') {
                loadLiveDirectory();
            }
        });
    });

    function loadLiveDirectory() {
        // La vista de Registro unificada (2026-09-21) monta la búsqueda con GoldenDirectory.mountSearch
        // y guarda la referencia en window.directorySearch — reusamos ese reload() en vez de
        // volver a cargar la tabla "a secas" (perdería los filtros ya escritos por el operador).
        if (window.directorySearch) return window.directorySearch.reload();
        return GoldenDirectory.load('directoryTableBody');
    }

    const wantHash = (location.hash || '').slice(1), wantTab = wantHash && document.querySelector('.tab[data-tab="' + wantHash.replace(/[^a-z]/g, '') + '"]');
    if (wantTab && !wantTab.classList.contains('active')) wantTab.click();          // refrescar deja la pestaña en la que estabas

    // Si "directorio" ya viene activo al cargar la página (ej. rol cliente, que no tiene
    // pestaña de escáner), no hay clic que dispare la carga — hay que hacerlo aquí.
    const directorioSection = document.getElementById('directorio');
    if (directorioSection && directorioSection.classList.contains('active')) {
        loadLiveDirectory();
    }

    const video = document.getElementById('video');
    const canvas = document.getElementById('canvas');
    // Cámara: solo se enciende DESPUÉS de que la persona autoriza el escaneo de su rostro (dato biométrico sensible, Ley 1581).
    // El reconocimiento queda «recordado» únicamente en esta sesión del navegador; quien no autoriza se registra por cédula.
    function startCamera() {
        navigator.mediaDevices.getUserMedia({ video: true })
            .then(stream => { video.srcObject = stream; })
            .catch(err => console.error("Sin acceso a cámara", err));
    }
    function stopCamera() {
        const stream = video && video.srcObject;
        if (stream && stream.getTracks) stream.getTracks().forEach((t) => t.stop());
        if (video) video.srcObject = null;
    }
    // Autorización biométrica (L1): la cámara solo se enciende con una aceptación de la PERSONA registrada (static/js/consent-gate.js). Camino 1: cédula/QR primero; camino 2 (eventos con
    // pre-cálculo autorizado): la pantalla se muestra a quien se acerca y un clic da un token válido para UNA comparación. Tras cada intento la cámara vuelve a apagarse.
    let clickToken = '';
    let enrollCedula = '';                                   // camino A: la persona acaba de aceptar y aún no tiene vector: se capta su rostro y el vector se calcula aparte
    let afterEnroll = () => {};
    let resetGate = () => {};
    if (video) {
        const gate = window.GoldenConsent ? window.GoldenConsent.create({ eventId: EVENT_ID }) : null;
        const ident = document.getElementById('bioIdent'), identInput = document.getElementById('bioCedula'), identBtn = document.getElementById('bioIdentBtn'), identMsg = document.getElementById('bioIdentMsg');
        const cameraBox = document.getElementById('cameraBox'), scanBtn = document.getElementById('escanearBtn'), eventOpen = !(scanBtn && scanBtn.disabled);
        const goCedula = (e, cedula) => {
            if (e) e.preventDefault();
            const tab = document.querySelector('.tab[data-tab="directorio"]'); if (tab) tab.click();
            if (cedula && window.directorySearch && window.directorySearch.submitScannedCedula) window.directorySearch.submitScannedCedula(cedula);
        };
        const altLink = document.getElementById('bioAltLink');
        if (altLink) altLink.addEventListener('click', goCedula);
        const cameraOn = () => { setOff(cameraBox, false); if (scanBtn) scanBtn.disabled = !eventOpen; setOff(ident, true); startCamera(); };
        const cameraOff = () => { stopCamera(); setOff(cameraBox, true); if (scanBtn) scanBtn.disabled = true; setOff(ident, false); identInput.value = ''; clickToken = ''; };
        afterEnroll = (cedula) => { cameraOff(); enrollCedula = ''; goCedula(null, cedula); };
        resetGate = () => { cameraOff(); setTimeout(startClickScreen, 0); };
        async function startClickScreen() {                      // camino 2: solo si el evento lo tiene autorizado (el servidor lo confirma al pedir el token)
            if (!gate || !eventOpen) return;
            const block = await gate.loadBlock();
            if (!block || !block.click_mode) return;
            identMsg.textContent = '';
            const token = await gate.clickFlow();
            if (token) { clickToken = token; cameraOn(); } else { identMsg.textContent = 'Sin reconocimiento facial: ingresa por cédula o QR.'; }
        }
        async function identify() {                              // camino 1
            const cedula = (identInput.value || '').trim();
            if (!cedula) { identMsg.textContent = 'Escribe o escanea la cédula.'; return; }
            if (!gate) { goCedula(null, cedula); return; }
            identBtn.disabled = true; identMsg.textContent = 'Consultando…';
            try {
                let next = await gate.ensure(cedula);
                if (next === 'verify') {                           // camino B: aceptó desde el celular; confirmar identidad en puerta
                    const okId = await showConfirm('Esta persona aceptó el reconocimiento facial desde su celular. Confirma su identidad con el documento físico o el QR: ¿coincide con quien está en la puerta?');
                    next = okId && await gate.verify(cedula) ? await gate.ensure(cedula) : 'cedula';
                }
                if (next === 'camera') { identMsg.textContent = ''; cameraOn(); }
                else if (next === 'enroll') { enrollCedula = cedula; identMsg.textContent = ''; cameraOn(); setResult('Capta el rostro de la persona: hoy ingresa por cédula; desde la próxima entrada, por rostro.', 'gold'); }
                else if (next === 'pending') { identMsg.textContent = 'Tu reconocimiento facial se está preparando: hoy ingresa por cédula o QR.'; goCedula(null, cedula); }
                else { identMsg.textContent = ''; identInput.value = ''; goCedula(null, cedula); }
            } finally { identBtn.disabled = false; }
        }
        if (identBtn) identBtn.addEventListener('click', identify);
        if (identInput) identInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); identify(); } });
        cameraOff();
        startClickScreen();
    }

    const escanearBtn = document.getElementById('escanearBtn');
    const resTexto = document.getElementById('resultadoTexto');
    const printScanBtn = document.getElementById('printScanBtn');
    /* Mostrar / ocultar sin estilos en línea: la clase gw-registro__off (registro.css) esconde; quitarla devuelve el aspecto normal del elemento. */
    const setOff = (el, off) => { if (el) el.classList.toggle('gw-registro__off', !!off); };
    /* Resultado del escáner: el color lo da la clase (ok / warn / err / gold), siempre acompañado de las palabras. */
    const setResult = (text, tone) => { if (!resTexto) return; resTexto.innerText = text; resTexto.className = 'gw-registro__result' + (tone ? ' gw-registro__result--' + tone : ''); };
    /* Acción con rueda (GW.busy): sin el ayudante (pruebas) solo corre la acción. Arranca de inmediato, dentro del gesto del usuario. */
    const busyRun = (btn, work) => (window.GW && window.GW.busy && btn && btn.setAttribute ? window.GW.busy(btn, work) : new Promise((resolve) => resolve(work())));

    // Botón "Imprimir Escarapela" (Historia 2.2) — NUNCA se dispara solo por defecto, el
    // digitador decide si lo pulsa; si el evento tiene la auto-impresión activada
    // (window.EVENT_AUTO_PRINT, switch en el editor de escarapelas), además se abre sola.
    // 'comercial' excluido (Sprint 2.4 Fase 6, pedido explícito: "la comercial no debe poder
    // imprimir") — el backend ya lo bloquea, esto evita ofrecerle un botón que le va a fallar.
    function offerPrint(btn, userId) {
        if (!btn || window.STAFF_ROLE === 'comercial') return;
        setOff(btn, false);
        btn.onclick = () => BadgePrint.openPrintWindow(userId);
        if (window.BadgePrint) BadgePrint.maybeAutoPrint(userId);
    }

    // Verificación del operador (docs/14 §6.3). Cada persona se reconoce UNA vez: la respuesta trae un `match_token` firmado y de corta vida con la persona
    // principal y sus 5 candidatos más cercanos del MISMO cálculo. Con él se piden la foto de registro, la lista «Ver 5 más cercanos» y el registro de quien el
    // operador elija (modal Editar existente: ahí se corrigen datos o se confirma el ingreso de ESA persona, no la del mejor match). Nada de esto se guarda en el
    // navegador: las fotos son blobs temporales que se sueltan al cerrar el resultado.
    const scanResult = document.getElementById('scanResult');
    const scanEls = scanResult ? {
        title: document.getElementById('scanTitle'), main: document.getElementById('scanMain'), live: document.getElementById('scanLive'),
        reg: document.getElementById('scanReg'), regCap: document.getElementById('scanRegCap'), info: document.getElementById('scanInfo'),
        open: document.getElementById('scanOpenBtn'), more: document.getElementById('scanMoreBtn'), cands: document.getElementById('scanCands'),
    } : null;
    let scanToken = null, captureUrl = null, photoUrls = [];

    function hideScanResult() {
        setOff(scanResult, true);
        photoUrls.forEach((u) => URL.revokeObjectURL(u));
        if (captureUrl) URL.revokeObjectURL(captureUrl);
        photoUrls = []; captureUrl = null; scanToken = null;
        if (scanEls) { scanEls.cands.replaceChildren(); scanEls.reg.removeAttribute('src'); scanEls.live.removeAttribute('src'); }
    }

    function scanForm(extra) {
        const fd = new FormData();
        fd.set('event_id', EVENT_ID);
        fd.set('match_token', scanToken);
        Object.keys(extra || {}).forEach((k) => fd.set(k, extra[k]));
        return fd;
    }

    async function loadPhoto(index, img, caption) {
        try {
            const res = await fetch('/api/recognize/photo', { method: 'POST', body: scanForm({ index }) });
            if (!res.ok) { if (caption) caption.textContent = 'Sin foto de registro'; return; }
            const url = URL.createObjectURL(await res.blob());
            photoUrls.push(url);
            img.src = url;
        } catch (e) { if (caption) caption.textContent = 'No se pudo cargar la foto'; }
    }

    function confBadge(view) {
        const b = document.createElement('span');
        b.className = 'scan-conf scan-conf-' + view.confidence.level;
        b.textContent = `${view.confidence.label} (${view.distance.toFixed(2)})`;
        return b;
    }

    function infoRow(dl, label, value) {
        const dt = document.createElement('dt'), dd = document.createElement('dd');
        dt.textContent = label;
        value instanceof Node ? dd.appendChild(value) : (dd.textContent = value);
        dl.append(dt, dd);
    }

    function renderCandidates(list) {
        scanEls.cands.replaceChildren();
        if (!list.length) { const p = document.createElement('p'); p.textContent = 'No hay más candidatos en este evento.'; scanEls.cands.appendChild(p); return; }
        list.forEach((c) => {
            const row = document.createElement('div');
            row.className = 'scan-cand' + (c.within_tolerance ? '' : ' out');
            const img = document.createElement('img'); img.alt = 'Foto de registro del candidato';
            const who = document.createElement('div'); who.className = 'who';
            const name = document.createElement('strong'); name.textContent = c.name || '(sin nombre)';
            const detail = document.createElement('div');
            detail.textContent = `${c.id}${c.categories.length ? ' · ' + c.categories.join(', ') : ''} · ${c.registered ? 'Ya registrado' : 'No registrado'}`;
            const conf = document.createElement('div'); conf.appendChild(confBadge(c));
            if (!c.within_tolerance) { const t = document.createElement('small'); t.textContent = ' Fuera de la tolerancia'; conf.appendChild(t); }
            who.append(name, detail, conf);
            const btn = document.createElement('button');
            btn.type = 'button'; btn.className = 'gw-btn gw-btn--secondary gw-btn--sm scan-pick'; btn.dataset.index = c.index;
            btn.textContent = 'Abrir registro';
            row.append(img, who, btn);
            scanEls.cands.appendChild(row);
            loadPhoto(c.index, img, null);            // las fotos de los candidatos se piden solo ahora, al mostrar la lista
        });
    }

    async function showCandidates(btn) {
        if (btn) btn.disabled = true;
        try {
            const res = await fetch('/api/recognize/candidates', { method: 'POST', body: scanForm() });
            const data = await res.json();
            if (!res.ok) { showToast(data.detail || 'No se pudieron cargar los candidatos', 'error'); return; }
            renderCandidates(data.candidates);
        } catch (e) { showToast('Error de red', 'error'); }
        if (btn) btn.disabled = false;
    }

    // Abre el modal Editar de la persona elegida (posición `index` del token); guardar ahí registra el ingreso de ESA persona.
    async function openPerson(index) {
        try {
            const res = await fetch('/api/recognize/person', { method: 'POST', body: scanForm({ index }) });
            const row = await res.json();
            if (!res.ok) { showToast(row.detail || 'No se pudo abrir el registro', 'error'); return; }
            GoldenDirectory.openEdit(row, { method: 'biometrico', onSaved: (id) => {
                hideScanResult();
                setResult("ACCESO AUTORIZADO Y GUARDADO", 'ok');
                showPrint(id);
            } });
        } catch (e) { showToast('Error de red', 'error'); }
    }

    // «Imprimir» ahí mismo tras guardar. El modal ya dispara la auto-impresión si el evento la tiene (badge-render.js), así que aquí solo se ofrece el botón.
    function showPrint(userId) {
        if (!printScanBtn || window.STAFF_ROLE === 'comercial') return;
        setOff(printScanBtn, false);
        printScanBtn.onclick = () => BadgePrint.openPrintWindow(userId);
    }

    function showScanResult(data) {
        if (!scanResult) return;
        const doubtful = data.result === 'DUDOSO';
        scanEls.title.textContent = doubtful ? 'Coincidencia dudosa — elige a la persona'
            : data.result === 'SÍ' ? 'Ingreso registrado automáticamente' : 'Verifica y confirma el ingreso';
        setOff(scanEls.main, doubtful);
        scanEls.cands.replaceChildren();
        setOff(scanEls.more, !data.has_candidates);
        setOff(scanEls.open, data.result === 'SÍ');
        if (doubtful) {
            renderCandidates(data.candidates);
            const p = document.createElement('p');
            p.textContent = 'Hay varias personas casi igual de parecidas: no se registra nada solo. Compara las fotos y abre el registro de la correcta.';
            scanEls.cands.prepend(p);
        } else {
            const m = data.match || {};
            if (captureUrl) scanEls.live.src = captureUrl;
            scanEls.reg.removeAttribute('src'); scanEls.regCap.textContent = 'Foto de registro';
            loadPhoto(0, scanEls.reg, scanEls.regCap);
            scanEls.info.replaceChildren();
            infoRow(scanEls.info, 'Nombre', `${data.data.first_name || ''} ${data.data.last_name || ''}`.trim());
            infoRow(scanEls.info, 'Cédula', data.data.id);
            infoRow(scanEls.info, 'Categoría', (m.categories || []).join(', ') || '—');
            infoRow(scanEls.info, 'Estado', m.registered || data.result === 'SÍ' ? 'Registrado' : 'No registrado');
            if (m.confidence) infoRow(scanEls.info, 'Confianza', confBadge(m));
        }
        setOff(scanResult, false);
    }

    if (scanResult) {
        scanEls.open.addEventListener('click', () => openPerson(0));
        scanEls.more.addEventListener('click', (e) => showCandidates(e.currentTarget));
        scanEls.cands.addEventListener('click', (e) => {
            const btn = e.target.closest('.scan-pick');
            if (btn) openPerson(Number(btn.dataset.index));
        });
    }

    // Fase 0 de escalabilidad: cada persona se reconoce UNA vez; para forzar un duplicado se reenvía el `match_token` EN VEZ de la foto.
    async function submitRecognize(formData) {
        try {
            const res = await fetch('/api/recognize', { method: 'POST', body: formData });
            const data = await res.json();

            if (!res.ok) {
                setResult(data.detail || "No se pudo procesar", 'err');
                return;
            }
            if (data.match_token) scanToken = data.match_token;

            if (data.result === 'DUPLICADO') {
                setResult("Ya registrado(a) en este evento", 'warn');
                const confirmado = await confirmDuplicateRegistration(data.data, data.times_registered);
                if (confirmado) {
                    formData.set('force', 'true');
                    if (data.match_token) { formData.set('match_token', data.match_token); formData.delete('file'); }
                    await submitRecognize(formData);
                }
                return;
            }

            if (data.result === 'DUDOSO') {
                setResult("Coincidencia dudosa — verifica quién es", 'warn');
                showScanResult(data);
                return;
            }

            if (data.result === 'MISSING_REQUIRED') {           // A3: reconocida, pero le falta un obligatorio: no se acredita; se completa en «Editar persona» y ahí se acredita
                showToast(data.details || 'Falta un campo obligatorio', 'warning');
                if (window.GoldenDirectory && window.GoldenDirectory.openEdit) window.GoldenDirectory.openEdit(Object.assign({ status: 'No registrado' }, data.data), { missing: data.missing || [], method: 'biometrico' });
                return;
            }
            if (data.result === 'MATCH_PENDING') {
                setResult("Coincidencia encontrada — compara las fotos y confirma", 'warn');
                showScanResult(data);
                return;
            }

            if (data.result === 'SÍ') {
                setResult("IDENTIDAD VALIDADA Y ACCESO AUTORIZADO", 'ok');
                showScanResult(data);
                offerPrint(printScanBtn, data.data.id);
                if (window.directorySearch) window.directorySearch.reload();
            } else {
                setOff(printScanBtn, true);
                setResult(data.details, 'err');
            }
        } catch (e) {
            setResult("Error de conexión con el servidor", 'err');
        }
    }

    if(escanearBtn) {
        escanearBtn.addEventListener('click', () => {
            setResult("Analizando geometría facial...", 'gold');
            hideScanResult();
            setOff(printScanBtn, true);

            // Se reduce la foto en el navegador (lado mayor ~640 px, JPEG): pesa ~40 KB en vez de varios MB y el servidor no tiene que reducirla él.
            const MAX_SIDE = 640;
            const scale = Math.min(1, MAX_SIDE / Math.max(video.videoWidth, video.videoHeight));
            canvas.width = Math.round(video.videoWidth * scale);
            canvas.height = Math.round(video.videoHeight * scale);
            canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);

            canvas.toBlob((blob) => {
                captureUrl = URL.createObjectURL(blob);          // la captura solo vive en memoria, para mostrarla junto a la foto de registro
                const formData = new FormData();
                formData.append('file', blob, 'webcam.jpg');
                if (enrollCedula) {                              // camino A: guardar la captura y encolar el vector; la persona entra YA por cédula (nunca se bloquea la puerta)
                    const fd = new FormData(); fd.append('user_id', enrollCedula); fd.append('file', blob, 'webcam.jpg');
                    const who = enrollCedula;
                    fetch(`/api/events/${EVENT_ID}/enroll-face`, { method: 'POST', body: fd }).then((r) => { setResult(r.ok ? 'Listo. Hoy ingresa por cédula o QR; tu rostro quedará listo en unos momentos.' : 'No se pudo guardar el rostro: ingresa por cédula o QR.', r.ok ? 'ok' : 'warn'); }).catch(() => { setResult('Sin conexión: ingresa por cédula o QR.', 'warn'); }).finally(() => afterEnroll(who));
                    return;
                }
                formData.append('event_id', EVENT_ID);
                if (clickToken) formData.append('click_token', clickToken);
                submitRecognize(formData).finally(() => { if (video) resetGate(); });
            }, 'image/jpeg', 0.85);
        });
    }

    const regForm = document.getElementById('regForm');
    if(regForm) {
        // Consentimiento/firma (ítems 16 y 10): se dibujan desde FieldRender, igual que en Editar.
        (window.FIELD_CONFIGS || []).forEach((cfg) => {
            const slot = regForm.querySelector(`[data-render-control="${cfg.key}"]`);
            if (slot) slot.innerHTML = window.FieldRender.renderControl(cfg, '');
        });
        window.FieldRender.initSignatures(regForm);
        window.FieldRender.watchEmailDeliverable(regForm);
        window.FieldRender.watchEmail(regForm, () => regForm.querySelector('[name="id"]').value.trim());
        // Superevento (ítem 19): al terminar de escribir la cédula, avisa si la persona ya asistió a un
        // evento hermano y ofrece SOLO vincularla (sus datos ya están guardados) en vez de capturarlos de nuevo.
        const idInput = regForm.querySelector('[name="id"]');
        const siblingBanner = document.createElement('div');
        siblingBanner.className = 'gw-alert gw-alert--warn gw-registro__sibling'; siblingBanner.hidden = true; siblingBanner.setAttribute('role', 'status');
        idInput.insertAdjacentElement('afterend', siblingBanner);
        idInput.addEventListener('blur', async () => {
            const id = idInput.value.trim();
            siblingBanner.hidden = true;
            if (!id) return;
            let res;
            try { res = await fetch(`/api/users/${encodeURIComponent(id)}/sibling-check?event_id=${EVENT_ID}`); } catch (e) { return; }       // sin red: no hay aviso de hermanos
            if (!res.ok) return;
            const data = await res.json();
            if (!data.siblings.length || !data.user) return;
            const who = `${data.user.first_name || ''} ${data.user.last_name || ''}`.trim();
            siblingBanner.innerHTML = `<div class="gw-registro__grow"><strong></strong> ya asistió a <span class="sib-events"></span> (mismo superevento «<span class="sib-super"></span>»). Sus datos ya están guardados. <button type="button" class="sib-link gw-btn gw-btn--secondary gw-btn--sm">Solo vincular a este evento</button> <span class="gw-hint">(o sigue llenando el formulario para actualizar sus datos)</span></div>`;
            siblingBanner.querySelector('strong').textContent = who || id;
            siblingBanner.querySelector('.sib-events').textContent = data.siblings.map(s => s.event_name).join(', ');
            siblingBanner.querySelector('.sib-super').textContent = data.super_event_name || '';
            siblingBanner.querySelector('.sib-link').addEventListener('click', async () => {
                const fd = new FormData();
                fd.append('event_id', EVENT_ID); fd.append('id', id);
                fd.append('first_name', data.user.first_name || ''); fd.append('last_name', data.user.last_name || '');
                const link = siblingBanner.querySelector('.sib-link');
                await busyRun(link, () => submitManualRegister(fd, link));
            });
            siblingBanner.hidden = false;
        });
        /* «Registrar nuevo» SIEMPRE abre en blanco (5-nov-2026): la cédula de la última persona guardada no puede quedar escrita. Se limpia explícitamente al abrir (además del reset al guardar), también
           lo que el navegador haya recordado. Lo llama el botón «Registrar nuevo» al abrir la ventana. */
        window.resetRegForm = () => {
            regForm.reset();
            regForm.querySelectorAll('input, textarea').forEach((el) => {
                if (el.type === 'checkbox' || el.type === 'radio' || el.type === 'file' || el.type === 'hidden' || el.type === 'submit' || el.type === 'button') return;
                if (el.readOnly || el.disabled) return;
                el.value = el.defaultValue || '';
            });
            idInput.value = '';
            siblingBanner.hidden = true;
            if (window.clearPendingOptionalLabels) window.clearPendingOptionalLabels();
        };
        regForm.addEventListener('reset', () => setTimeout(() => {
            siblingBanner.hidden = true;
            regForm.querySelectorAll('.sig-canvas').forEach(c => c.getContext('2d').clearRect(0, 0, c.width, c.height));
            regForm.querySelectorAll('.sig-wrap').forEach(w => { w._dirty = false; });
        }, 0));

        async function submitManualRegister(formData, btn) {
            // La ventana de impresión se abre AQUÍ, dentro del gesto (el envío del formulario o el clic de una confirmación), antes de la llamada de red; maybeAutoPrint la usa o se cierra al terminar.
            if (window.BadgePrint && BadgePrint.primeWindow) { try { BadgePrint.primeWindow(); } catch (e) { /* sin ventana preparada */ } }
            try {
                if (window.RegTimer) RegTimer.appendTo(formData);          // 1A: tiempo desde la primera tecla / apertura del formulario
                const res = await fetch('/api/register', { method: 'POST', body: formData });
                const data = await res.json();
                if (!res.ok) {
                    showToast(data.detail || "No se pudo registrar", "error");
                    return;
                }
                if (window.BadgePrint && BadgePrint.setFlags) BadgePrint.setFlags(data);         // el servidor dice si se imprime solo (auto_print) y si autorregistra (auto_register)
                if ((data.result === 'NEEDS_LABELS' || data.result === 'DUPLICADO') && window.BadgePrint && BadgePrint.cancelPrimed) BadgePrint.cancelPrimed();       // mientras se pregunta no queda una ventana en blanco
                if (data.result === 'NEEDS_LABELS') {
                    // Camino defensivo: normalmente ya mandamos field_labels de una vez (el botón
                    // "+ Agregar campo opcional" pregunta el nombre en el momento), esto solo se
                    // ejerce si algo quedó sin rotular por alguna otra vía.
                    const labels = await window.promptOptionalLabels(data.fields);
                    if (!labels) return;
                    formData.set('field_labels', JSON.stringify(labels));
                    await submitManualRegister(formData, btn);
                    return;
                }
                if (data.result === 'DUPLICADO') {
                    const confirmado = await confirmDuplicateRegistration(data.data, data.times_registered);
                    if (confirmado) {
                        formData.set('force', 'true');
                        await submitManualRegister(formData, btn);
                    }
                    return;
                }
                showToast(data.message || data.error, data.error ? "error" : "success");
                if (data.digital) showToast(`Escarapela digital: ${data.digital.detail}`, 'success');
                if (!data.error) {
                    if (window.RegTimer) RegTimer.done();
                    const registeredId = formData.get('id');
                    try { await window.FieldRender.saveSignatures(regForm, registeredId); }
                    catch (e) { showToast(e.message, 'error'); }
                    regForm.reset();
                    if (window.resetRegForm) window.resetRegForm();                   // vacía TODO (incluida la cédula) antes de la siguiente alta
                    if (window.clearPendingOptionalLabels) window.clearPendingOptionalLabels();
                    if (window.directorySearch) window.directorySearch.reload();
                    if (window.closeRegisterModal) window.closeRegisterModal();
                    if (window.GoldenDirectory && window.GoldenDirectory.noteRecent) window.GoldenDirectory.noteRecent(registeredId);      // A5: queda primera en la lista de ESTE equipo
                    if (window.BadgePrint) BadgePrint.maybeAutoPrint(registeredId, { auto: data.auto_print });
                    const photoSent = formData.get('file');
                    if (photoSent && photoSent.size) showPrint(registeredId);      // registro facial nuevo: «Imprimir» ahí mismo (la auto-impresión ya se disparó arriba si el evento la tiene)
                }
            } catch(err) { showToast("Error de red", "error"); }
            finally { if (window.BadgePrint && BadgePrint.cancelPrimed) BadgePrint.cancelPrimed(); }
        }

        regForm.onsubmit = async (e) => {
            e.preventDefault();
            // OJO: 'button' a secas agarra el PRIMER <button> del form en orden del DOM — desde
            // que existe "+ Agregar campo opcional" (type="button", va ANTES del submit real en
            // el HTML), ese selector genérico apuntaba al botón equivocado: el submit real nunca
            // se tocaba, y "+ Agregar campo opcional" terminaba heredando el texto "Guardando..."
            // / "Guardar Perfil Biométrico" después de cada alta exitosa (bug real, encontrado en
            // testing de producción 2026-09-15). Hay que pedir el submit explícitamente.
            const btn = e.target.querySelector('button[type="submit"]');
            const photo = e.target.querySelector('#regPhotoInput'), consent = e.target.querySelector('#regBioConsent');
            if (photo && photo.files && photo.files.length && consent && !consent.checked) {   // Ley 1581: sin autorización expresa no se guarda el rostro
                showToast('Para guardar la foto, marca que la persona autoriza el uso de su rostro. Si no la autoriza, quita la foto y registra solo por cédula.', 'error');
                return;
            }
            await busyRun(btn, async () => {          // rueda en «Guardar» y sin doble envío (GW.busy)
            if (window.regPersonForm) window.regPersonForm.applyAll();          // formulario de persona: «Texto al escribir» también en lo que se llenó por lector o por foto de la cédula
            const formData = new FormData(e.target);
            formData.append('event_id', EVENT_ID);

            // Los campos opcionales dinámicos (opcional_1..opcional_N, ver "+ Agregar campo
            // opcional") viven como inputs sueltos en el <form> — el backend espera un solo JSON
            // en 'extra_fields', igual que bulk_register por fila.
            const extras = {};
            for (const key of Array.from(formData.keys())) {
                if (/^opcional_\d+$/.test(key)) {
                    const val = (formData.get(key) || '').trim();
                    if (val) extras[key] = val;
                    formData.delete(key);
                }
            }
            if (Object.keys(extras).length) formData.append('extra_fields', JSON.stringify(extras));

            // Categorías (ítem 14): varias casillas "categories" -> un solo JSON, como extra_fields.
            const cats = formData.getAll('categories');
            formData.delete('categories');
            if (cats.length) formData.append('categories', JSON.stringify(cats));

            // Casilla «Enviar ahora la escarapela digital»: una casilla sin marcar no viaja en el FormData, así que se manda explícita.
            if (e.target.querySelector('input[name="send_digital_now"]') && !formData.has('send_digital_now')) formData.set('send_digital_now', 'false');

            const pending = window.getPendingOptionalLabels ? window.getPendingOptionalLabels() : {};
            if (Object.keys(pending).length) formData.append('field_labels', JSON.stringify(pending));

            // SIN RED (modo contingencia + bandeja de salida, B8 R1): la persona se guarda cifrada en este dispositivo, SIN foto, y se envía sola al volver la red.
            const GCo = window.GoldenContingency && window.GoldenContingency.instance, box = window.GoldenOutbox && window.GoldenOutbox.instance;
            if (GCo && GCo.active && GCo.active() && box && box.supported) {
                await queueOffline(formData, box);
                return;
            }
            await submitManualRegister(formData, btn);
            });
        };

        async function queueOffline(formData, box) {
            const needsSignature = (window.FIELD_CONFIGS || []).filter((c) => c.required && (c.field_type === 'signature' || c.field_type === 'consent'));
            if (needsSignature.length) { showToast(`Este evento exige ${needsSignature.map((c) => c.label || c.key).join(', ')}: no se puede registrar sin conexión. Espera a que vuelva la red.`, 'error'); return; }
            const f = {};
            for (const key of ['id', 'first_name', 'last_name', 'role', 'entity', 'phone', 'email', 'opt_1', 'certificate', 'digital_contact']) { const v = formData.get(key); if (v != null && String(v).trim() !== '') f[key] = String(v).trim(); }
            for (const key of ['extra_fields', 'categories', 'field_labels']) { const v = formData.get(key); if (v) { try { f[key] = JSON.parse(v); } catch (e) { /* se ignora un JSON roto */ } } }
            if (!f.id || !f.first_name) { showToast('Escribe la cédula y los nombres.', 'error'); return; }
            const lastCfg = (window.FIELD_CONFIGS || []).find((c) => c.key === 'last_name');
            if (lastCfg && lastCfg.required && !f.last_name) { showToast(`Escribe ${lastCfg.label ? 'el campo «' + lastCfg.label + '»' : 'el apellido'}: es obligatorio en este evento.`, 'error'); return; }
            const pf = window.PERSON_FORM && window.PersonForm ? window.PERSON_FORM : null;          // formulario de persona: la alta lleva la versión del formulario con que se hizo
            if (pf) PersonForm.applyCase(f, pf);
            const photo = formData.get('file');
            const tm = window.RegTimer ? RegTimer.payload() : null;          // 1A: el tiempo viaja en la bandeja y se envía al sincronizar
            if (tm) { f.took_ms = tm.took_ms; f.ui_flow = tm.ui_flow; }
            try { await box.enqueue(f, `${f.first_name} ${f.last_name || ''}`.trim(), pf ? { form_version: pf.form_version, form_sig: pf.form_sig } : undefined); } catch (e) { showToast(e.message || 'No se pudo guardar en este dispositivo', 'error'); return; }
            if (window.RegTimer) RegTimer.done();
            showToast(`Guardado en este dispositivo${photo && photo.size ? ' (la foto no se guarda sin conexión: agrégala después)' : ''}. Se enviará solo al volver la red.`, 'success');
            regForm.reset();
            if (window.clearPendingOptionalLabels) window.clearPendingOptionalLabels();
            if (window.closeRegisterModal) window.closeRegisterModal();
        }
    }
});
