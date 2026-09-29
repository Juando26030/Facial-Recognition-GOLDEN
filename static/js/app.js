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
    if (video) {
        const gate = document.getElementById('bioGate');
        const ackKey = 'bio_ack_' + EVENT_ID;
        const goCedula = (e) => { if (e) e.preventDefault(); const tab = document.querySelector('.tab[data-tab="directorio"]'); if (tab) tab.click(); };
        const altLink = document.getElementById('bioAltLink');
        if (altLink) altLink.addEventListener('click', goCedula);
        let acked = false;
        try { acked = sessionStorage.getItem(ackKey) === '1'; } catch (err) { /* sin almacenamiento: se vuelve a pedir */ }
        if (acked || !gate) startCamera();
        else {
            gate.style.display = 'block';
            const scanBtn = document.getElementById('escanearBtn'), wasDisabled = !!(scanBtn && scanBtn.disabled);
            if (scanBtn) scanBtn.disabled = true;
            document.getElementById('bioGateAccept').addEventListener('click', () => {
                try { sessionStorage.setItem(ackKey, '1'); } catch (err) { /* opcional */ }
                gate.style.display = 'none';
                if (scanBtn) scanBtn.disabled = wasDisabled;      // vuelve a como estaba (deshabilitado si el evento no está en proceso)
                startCamera();
            });
            document.getElementById('bioGateDecline').addEventListener('click', goCedula);
        }
    }

    const escanearBtn = document.getElementById('escanearBtn');
    const resTexto = document.getElementById('resultadoTexto');
    const printScanBtn = document.getElementById('printScanBtn');

    // Botón "Imprimir Escarapela" (Historia 2.2) — NUNCA se dispara solo por defecto, el
    // digitador decide si lo pulsa; si el evento tiene la auto-impresión activada
    // (window.EVENT_AUTO_PRINT, switch en el editor de escarapelas), además se abre sola.
    // 'comercial' excluido (Sprint 2.4 Fase 6, pedido explícito: "la comercial no debe poder
    // imprimir") — el backend ya lo bloquea, esto evita ofrecerle un botón que le va a fallar.
    function offerPrint(btn, userId) {
        if (!btn || window.STAFF_ROLE === 'comercial') return;
        btn.style.display = 'block';
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
        if (scanResult) scanResult.style.display = 'none';
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
            btn.type = 'button'; btn.className = 'golden-btn scan-pick'; btn.dataset.index = c.index; btn.style.cssText = 'width:auto; padding:6px 12px;';
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
                resTexto.innerText = "✅ ACCESO AUTORIZADO Y GUARDADO";
                resTexto.style.color = "#28a745";
                showPrint(id);
            } });
        } catch (e) { showToast('Error de red', 'error'); }
    }

    // «Imprimir» ahí mismo tras guardar. El modal ya dispara la auto-impresión si el evento la tiene (badge-render.js), así que aquí solo se ofrece el botón.
    function showPrint(userId) {
        if (!printScanBtn || window.STAFF_ROLE === 'comercial') return;
        printScanBtn.style.display = 'block';
        printScanBtn.onclick = () => BadgePrint.openPrintWindow(userId);
    }

    function showScanResult(data) {
        if (!scanResult) return;
        const doubtful = data.result === 'DUDOSO';
        scanEls.title.textContent = doubtful ? '⚠️ Coincidencia dudosa — elige a la persona'
            : data.result === 'SÍ' ? '✅ Ingreso registrado automáticamente' : '🟡 Verifica y confirma el ingreso';
        scanEls.main.style.display = doubtful ? 'none' : 'block';
        scanEls.cands.replaceChildren();
        scanEls.more.style.display = data.has_candidates ? 'inline-block' : 'none';
        scanEls.open.style.display = data.result === 'SÍ' ? 'none' : 'inline-block';
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
        scanResult.style.display = 'flex';
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
                resTexto.innerText = "❌ " + (data.detail || "No se pudo procesar");
                resTexto.style.color = "#dc3545";
                return;
            }
            if (data.match_token) scanToken = data.match_token;

            if (data.result === 'DUPLICADO') {
                resTexto.innerText = "⚠️ Ya registrado(a) en este evento";
                resTexto.style.color = "#f0ad4e";
                const confirmado = await confirmDuplicateRegistration(data.data, data.times_registered);
                if (confirmado) {
                    formData.set('force', 'true');
                    if (data.match_token) { formData.set('match_token', data.match_token); formData.delete('file'); }
                    await submitRecognize(formData);
                }
                return;
            }

            if (data.result === 'DUDOSO') {
                resTexto.innerText = "⚠️ Coincidencia dudosa — verifica quién es";
                resTexto.style.color = "#f0ad4e";
                showScanResult(data);
                return;
            }

            if (data.result === 'MATCH_PENDING') {
                resTexto.innerText = "🟡 Coincidencia encontrada — compara las fotos y confirma";
                resTexto.style.color = "#f0ad4e";
                showScanResult(data);
                return;
            }

            if (data.result === 'SÍ') {
                resTexto.innerText = "✅ IDENTIDAD VALIDADA Y ACCESO AUTORIZADO";
                resTexto.style.color = "#28a745";
                showScanResult(data);
                offerPrint(printScanBtn, data.data.id);
                if (window.directorySearch) window.directorySearch.reload();
            } else {
                if (printScanBtn) printScanBtn.style.display = 'none';
                resTexto.innerText = "❌ " + data.details;
                resTexto.style.color = "#dc3545";
            }
        } catch (e) {
            resTexto.innerText = "❌ Error de conexión al servidor FastAPI";
            resTexto.style.color = "#dc3545";
        }
    }

    if(escanearBtn) {
        escanearBtn.addEventListener('click', () => {
            resTexto.innerText = "Analizando geometría facial...";
            resTexto.style.color = "#D4AF37";
            hideScanResult();
            if(printScanBtn) printScanBtn.style.display = 'none';

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
                formData.append('event_id', EVENT_ID);
                submitRecognize(formData);
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
        siblingBanner.style.cssText = 'display:none; background:#fff3cd; border:1px solid #ffe69c; color:#664d03; border-radius:10px; padding:10px 12px; font-size:0.82rem; margin-top:6px;';
        idInput.insertAdjacentElement('afterend', siblingBanner);
        idInput.addEventListener('blur', async () => {
            const id = idInput.value.trim();
            siblingBanner.style.display = 'none';
            if (!id) return;
            const res = await fetch(`/api/users/${encodeURIComponent(id)}/sibling-check?event_id=${EVENT_ID}`);
            if (!res.ok) return;
            const data = await res.json();
            if (!data.siblings.length || !data.user) return;
            const who = `${data.user.first_name || ''} ${data.user.last_name || ''}`.trim();
            siblingBanner.innerHTML = `⚠️ <strong></strong> ya asistió a <span class="sib-events"></span> (mismo superevento «<span class="sib-super"></span>»). Sus datos ya están guardados. <button type="button" class="sib-link" style="margin-left:6px; border:none; background:var(--golden-primary,#D4AF37); color:#1a1200; border-radius:14px; padding:4px 12px; font-weight:700; cursor:pointer;">Solo vincular a este evento</button> <span style="color:#8a6d1a;">(o sigue llenando el formulario para actualizar sus datos)</span>`;
            siblingBanner.querySelector('strong').textContent = who || id;
            siblingBanner.querySelector('.sib-events').textContent = data.siblings.map(s => s.event_name).join(', ');
            siblingBanner.querySelector('.sib-super').textContent = data.super_event_name || '';
            siblingBanner.querySelector('.sib-link').addEventListener('click', async () => {
                const fd = new FormData();
                fd.append('event_id', EVENT_ID); fd.append('id', id);
                fd.append('first_name', data.user.first_name || ''); fd.append('last_name', data.user.last_name || '');
                await submitManualRegister(fd, siblingBanner.querySelector('.sib-link'));
            });
            siblingBanner.style.display = 'block';
        });
        regForm.addEventListener('reset', () => setTimeout(() => {
            siblingBanner.style.display = 'none';
            regForm.querySelectorAll('.sig-canvas').forEach(c => c.getContext('2d').clearRect(0, 0, c.width, c.height));
            regForm.querySelectorAll('.sig-wrap').forEach(w => { w._dirty = false; });
        }, 0));

        async function submitManualRegister(formData, btn) {
            try {
                const res = await fetch('/api/register', { method: 'POST', body: formData });
                const data = await res.json();
                if (!res.ok) {
                    showToast(data.detail || "No se pudo registrar", "error");
                    return;
                }
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
                if (data.digital) showToast(`📲 Escarapela digital: ${data.digital.detail}`, 'success');
                if (!data.error) {
                    const registeredId = formData.get('id');
                    try { await window.FieldRender.saveSignatures(regForm, registeredId); }
                    catch (e) { showToast(e.message, 'error'); }
                    regForm.reset();
                    if (window.clearPendingOptionalLabels) window.clearPendingOptionalLabels();
                    if (window.directorySearch) window.directorySearch.reload();
                    if (window.closeRegisterModal) window.closeRegisterModal();
                    if (window.BadgePrint) BadgePrint.maybeAutoPrint(registeredId);
                    const photoSent = formData.get('file');
                    if (photoSent && photoSent.size) showPrint(registeredId);      // registro facial nuevo: «Imprimir» ahí mismo (la auto-impresión ya se disparó arriba si el evento la tiene)
                }
            } catch(err) { showToast("Error de red", "error"); }
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
            setButtonLoading(btn, true, "Guardando...");
            const formData = new FormData(e.target);
            formData.append('event_id', EVENT_ID);

            // Los campos opcionales dinámicos (opcional_1..opcional_30, ver "+ Agregar campo
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

            await submitManualRegister(formData, btn);
            setButtonLoading(btn, false);
        };
    }
});
