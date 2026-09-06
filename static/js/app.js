document.addEventListener("DOMContentLoaded", () => {
    
    const tabs = document.querySelectorAll('.tab');
    const sections = document.querySelectorAll('.section');
    
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            sections.forEach(s => s.classList.remove('active'));
            
            tab.classList.add('active');
            document.getElementById(tab.dataset.tab).classList.add('active');
        });
    });

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
                
                try {
                    const res = await fetch('/api/recognize', { method: 'POST', body: formData });
                    const data = await res.json();
                    
                    if(data.result === 'SÍ') {
                        resTexto.innerText = "✅ IDENTIDAD VALIDADA";
                        resTexto.style.color = "#28a745";
                        
                        document.getElementById('edit_id').value = data.data.id || "";
                        document.getElementById('edit_nombre').value = data.data.nombre || "";
                        document.getElementById('edit_empresa').value = data.data.empresa || "";
                        document.getElementById('edit_telefono').value = data.data.telefono || "";
                        
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

            const autorizacion = confirm("⚠️ ATENCIÓN: Esta persona ya se encuentra registrada en el sistema.\n\n¿Estás completamente seguro de que deseas sobrescribir sus datos?");
            if (!autorizacion) {
                return; 
            }

            const btn = e.target.querySelector('button');
            btn.innerText = "Guardando..."; 
            btn.disabled = true;

            const formData = new FormData(e.target);
            const payload = Object.fromEntries(formData.entries());
            
            try {
                const res = await fetch(`/api/users/${payload.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                if(res.ok) {
                    alert("✅ Perfil actualizado y log registrado en SQL.");
                    profileCard.style.display = 'none';
                    resTexto.innerText = "✅ ACCESO AUTORIZADO Y GUARDADO";
                    resTexto.style.color = "#28a745";
                } else {
                    const errorData = await res.json();
                    alert("❌ Error: " + (errorData.error || "No se pudo actualizar"));
                }
            } catch (err) {
                alert("❌ Error de red al comunicar con SQL.");
            }
            
            btn.innerText = "Guardar y Autorizar Acceso"; 
            btn.disabled = false;
        };
    }

    const exportBtn = document.getElementById('exportBtn');
    if(exportBtn) {
        exportBtn.addEventListener('click', () => {
            window.location.href = '/api/report';
        });
    }

    const regForm = document.getElementById('regForm');
    if(regForm) {
        regForm.onsubmit = async (e) => {
            e.preventDefault();
            const btn = e.target.querySelector('button');
            btn.innerText = "Guardando..."; btn.disabled = true;
            try {
                const res = await fetch('/api/register', { method: 'POST', body: new FormData(e.target) });
                const data = await res.json();
                alert(data.message || data.error);
                e.target.reset();
            } catch(err) { alert("Error de red"); }
            btn.innerText = "Guardar Perfil Biométrico"; btn.disabled = false;
        };
    }

    const bulkForm = document.getElementById('bulkForm');
    if(bulkForm) {
        bulkForm.onsubmit = async (e) => {
            e.preventDefault();
            const btn = e.target.querySelector('button');
            btn.innerText = "Sincronizando Tenant a SQL..."; btn.disabled = true;
            try {
                const res = await fetch('/api/bulk_register', { method: 'POST', body: new FormData(e.target) });
                const data = await res.json();
                alert(data.message || data.error);
                e.target.reset();
            } catch(err) { alert("Error de red"); }
            btn.innerText = "Sincronizar Lote Masivo"; btn.disabled = false;
        };
    }
});