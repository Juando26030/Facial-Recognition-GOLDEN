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
        return GoldenDirectory.load('directoryTableBody', { showAccredit: false });
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
    function offerPrint(btn, userId) {
        if (!btn) return;
        btn.style.display = 'block';
        btn.onclick = () => BadgePrint.openPrintWindow(userId);
        if (window.BadgePrint) BadgePrint.maybeAutoPrint(userId);
    }

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
                const confirmado = await confirmDuplicateRegistration(data.data);
                if (confirmado) {
                    formData.set('force', 'true');
                    await submitRecognize(formData);
                }
                return;
            }

            if(data.result === 'SÍ') {
                resTexto.innerText = "✅ IDENTIDAD VALIDADA";
                resTexto.style.color = "#28a745";

                document.getElementById('edit_id').value = data.data.id || "";
                document.getElementById('edit_first_name').value = data.data.first_name || "";
                document.getElementById('edit_last_name').value = data.data.last_name || "";
                document.getElementById('edit_role').value = data.data.role || "";
                document.getElementById('edit_company').value = data.data.company || "";
                document.getElementById('edit_phone').value = data.data.phone || "";
                document.getElementById('edit_email').value = data.data.email || "";
                document.getElementById('edit_opt_1').value = data.data.opt_1 || "";

                if(profileCard) profileCard.style.display = 'flex';
                offerPrint(printScanBtn, data.data.id);
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
            const autorizacion = await showConfirm("⚠️ ATENCIÓN: Esta persona ya se encuentra registrada en el sistema.<br><br>¿Estás completamente seguro de que deseas sobrescribir sus datos?");
            if (!autorizacion) return;

            const btn = e.target.querySelector('button');
            btn.innerText = "Guardando..."; btn.disabled = true;

            const payload = Object.fromEntries(new FormData(e.target).entries());

            try {
                const res = await fetch(withEvent(`/api/users/${payload.id}`), {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if(res.ok) {
                    showToast("Perfil actualizado y log registrado", "success");
                    profileCard.style.display = 'none';
                    resTexto.innerText = "✅ ACCESO AUTORIZADO Y GUARDADO";
                    resTexto.style.color = "#28a745";
                    if (window.directorySearch) window.directorySearch.reload();
                } else {
                    const errorData = await res.json();
                    showToast(errorData.error || "No se pudo actualizar", "error");
                }
            } catch (err) { showToast("Error de red", "error"); }
            btn.innerText = "Guardar y Autorizar Acceso"; btn.disabled = false;
        };
    }

    const exportBtn = document.getElementById('exportBtn');
    if(exportBtn) {
        exportBtn.addEventListener('click', () => window.location.href = withEvent('/api/report') );
    }

    const regForm = document.getElementById('regForm');
    if(regForm) {
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
                    const confirmado = await confirmDuplicateRegistration(data.data);
                    if (confirmado) {
                        formData.set('force', 'true');
                        await submitManualRegister(formData, btn);
                    }
                    return;
                }
                showToast(data.message || data.error, data.error ? "error" : "success");
                if (!data.error) {
                    const registeredId = formData.get('id');
                    regForm.reset();
                    if (window.clearPendingOptionalLabels) window.clearPendingOptionalLabels();
                    if (window.directorySearch) window.directorySearch.reload();
                    offerPrint(printManualBtn, registeredId);
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
            const originalLabel = btn.innerText;
            btn.innerText = "Guardando..."; btn.disabled = true;
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

            const pending = window.getPendingOptionalLabels ? window.getPendingOptionalLabels() : {};
            if (Object.keys(pending).length) formData.append('field_labels', JSON.stringify(pending));

            await submitManualRegister(formData, btn);
            btn.innerText = originalLabel; btn.disabled = false;
        };
    }
});
