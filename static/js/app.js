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

    if(escanearBtn) {
        escanearBtn.addEventListener('click', () => {
            resTexto.innerText = "Analizando geometría facial...";
            resTexto.style.color = "#D4AF37";
            if(profileCard) profileCard.style.display = 'none';

            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);

            canvas.toBlob(async (blob) => {
                const formData = new FormData();
                formData.append('file', blob, 'webcam.jpg');
                formData.append('event_id', EVENT_ID);

                try {
                    const res = await fetch('/api/recognize', { method: 'POST', body: formData });
                    const data = await res.json();

                    if (!res.ok) {
                        resTexto.innerText = "❌ " + (data.detail || "No se pudo procesar");
                        resTexto.style.color = "#dc3545";
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
                        document.getElementById('edit_opt_2').value = data.data.opt_2 || "";

                        if(profileCard) profileCard.style.display = 'flex';
                    } else {
                        resTexto.innerText = "❌ " + data.details;
                        resTexto.style.color = "#dc3545";
                    }
                } catch (e) {
                    resTexto.innerText = "❌ Error de conexión al servidor FastAPI";
                    resTexto.style.color = "#dc3545";
                }
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
        regForm.onsubmit = async (e) => {
            e.preventDefault();
            const btn = e.target.querySelector('button');
            btn.innerText = "Guardando..."; btn.disabled = true;
            const formData = new FormData(e.target);
            formData.append('event_id', EVENT_ID);
            try {
                const res = await fetch('/api/register', { method: 'POST', body: formData });
                const data = await res.json();
                if (!res.ok) {
                    showToast(data.detail || "No se pudo registrar", "error");
                } else {
                    showToast(data.message || data.error, data.error ? "error" : "success");
                    if (!data.error) e.target.reset();
                }
            } catch(err) { showToast("Error de red", "error"); }
            btn.innerText = "Guardar Perfil Biométrico"; btn.disabled = false;
        };
    }
});
