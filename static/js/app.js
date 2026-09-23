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
    if(video) {
        navigator.mediaDevices.getUserMedia({ video: true })
            .then(stream => { video.srcObject = stream; })
            .catch(err => console.error("Sin acceso a cámara", err));
    }

    const escanearBtn = document.getElementById('escanearBtn');
    const profileCard = document.getElementById('profileCard');
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

    function fillProfileCard(data) {
        document.getElementById('edit_id').value = data.id || "";
        document.getElementById('edit_first_name').value = data.first_name || "";
        document.getElementById('edit_last_name').value = data.last_name || "";
        document.getElementById('edit_role').value = data.role || "";
        document.getElementById('edit_entity').value = data.entity || "";
        document.getElementById('edit_phone').value = data.phone || "";
        document.getElementById('edit_email').value = data.email || "";
        document.getElementById('edit_opt_1').value = data.opt_1 || "";
    }

    // Sprint 2.2 Fase B (2026-09-16): un match facial ya NO acredita solo — salvo que el evento
    // tenga "Modo autoregistro" activado, /api/recognize devuelve result:"MATCH_PENDING" (sin
    // crear ningún log todavía) y hay que guardar el MISMO FormData (con la foto) para poder
    // reenviarlo con confirm=true cuando el digitador de verdad confirme en "Guardar y Autorizar
    // Acceso" — reconocer de nuevo desde cero exigiría volver a tomar la foto.
    let pendingRecognizeFormData = null;

    async function submitRecognize(formData) {
        try {
            const res = await fetch('/api/recognize', { method: 'POST', body: formData });
            const data = await res.json();

            if (!res.ok) {
                resTexto.innerText = "❌ " + (data.detail || "No se pudo procesar");
                resTexto.style.color = "#dc3545";
                return;
            }

            if (data.result === 'DUPLICADO') {
                resTexto.innerText = "⚠️ Ya registrado(a) en este evento";
                resTexto.style.color = "#f0ad4e";
                const confirmado = await confirmDuplicateRegistration(data.data, data.times_registered);
                if (confirmado) {
                    formData.set('force', 'true');
                    await submitRecognize(formData);
                }
                return;
            }

            if (data.result === 'MATCH_PENDING') {
                resTexto.innerText = "🟡 Coincidencia encontrada — confirma para autorizar el acceso";
                resTexto.style.color = "#f0ad4e";
                pendingRecognizeFormData = formData;
                fillProfileCard(data.data);
                if (profileCard) profileCard.style.display = 'flex';
                return;
            }

            if(data.result === 'SÍ') {
                resTexto.innerText = "✅ IDENTIDAD VALIDADA Y ACCESO AUTORIZADO";
                resTexto.style.color = "#28a745";
                pendingRecognizeFormData = null;

                fillProfileCard(data.data);

                if(profileCard) profileCard.style.display = 'flex';
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
            if(profileCard) profileCard.style.display = 'none';
            if(printScanBtn) printScanBtn.style.display = 'none';
            pendingRecognizeFormData = null;

            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);

            canvas.toBlob((blob) => {
                const formData = new FormData();
                formData.append('file', blob, 'webcam.jpg');
                formData.append('event_id', EVENT_ID);
                submitRecognize(formData);
            }, 'image/jpeg');
        });
    }

    const liveEditForm = document.getElementById('liveEditForm');
    if(liveEditForm) {
        liveEditForm.onsubmit = async (e) => {
            e.preventDefault();

            // El aviso de "sobrescribir datos" solo tiene sentido cuando la persona YA estaba
            // acreditada de antes (modo autoregistro, o un "SÍ" directo) — si el match está
            // pendiente, el propio clic en "Guardar y Autorizar Acceso" ES la confirmación.
            if (!pendingRecognizeFormData) {
                const autorizacion = await showConfirm("⚠️ ATENCIÓN: Esta persona ya se encuentra registrada en el sistema.<br><br>¿Estás completamente seguro de que deseas sobrescribir sus datos?");
                if (!autorizacion) return;
            }

            const btn = e.target.querySelector('button');
            setButtonLoading(btn, true, "Guardando...");

            try {
                if (pendingRecognizeFormData) {
                    pendingRecognizeFormData.set('confirm', 'true');
                    const confirmRes = await fetch('/api/recognize', { method: 'POST', body: pendingRecognizeFormData });
                    const confirmData = await confirmRes.json();
                    if (!confirmRes.ok || confirmData.result !== 'SÍ') {
                        showToast(confirmData.detail || confirmData.details || "No se pudo autorizar el acceso", "error");
                        setButtonLoading(btn, false);
                        return;
                    }
                    pendingRecognizeFormData = null;
                    offerPrint(printScanBtn, confirmData.data.id);
                }

                const payload = Object.fromEntries(new FormData(e.target).entries());
                const res = await fetch(withEvent(`/api/users/${payload.id}`), {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if(res.ok) {
                    showToast("Perfil actualizado y acceso autorizado", "success");
                    profileCard.style.display = 'none';
                    resTexto.innerText = "✅ ACCESO AUTORIZADO Y GUARDADO";
                    resTexto.style.color = "#28a745";
                    if (window.directorySearch) window.directorySearch.reload();
                } else {
                    const errorData = await res.json();
                    showToast(errorData.error || "No se pudo actualizar", "error");
                }
            } catch (err) { showToast("Error de red", "error"); }
            setButtonLoading(btn, false);
        };
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

            const pending = window.getPendingOptionalLabels ? window.getPendingOptionalLabels() : {};
            if (Object.keys(pending).length) formData.append('field_labels', JSON.stringify(pending));

            await submitManualRegister(formData, btn);
            setButtonLoading(btn, false);
        };
    }
});
