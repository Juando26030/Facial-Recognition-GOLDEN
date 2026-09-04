document.addEventListener("DOMContentLoaded", () => {
    
    // 1. Lógica de Pestañas (Tabs)
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

    // 2. Inicializar Cámara
    const video = document.getElementById('video');
    const canvas = document.getElementById('canvas');
    if(video) {
        navigator.mediaDevices.getUserMedia({ video: true })
            .then(stream => { video.srcObject = stream; })
            .catch(err => console.error("Sin acceso a cámara", err));
    }

    // 3. Biometría en Vivo
    const escanearBtn = document.getElementById('escanearBtn');
    const profileCard = document.getElementById('profileCard');
    const resTexto = document.getElementById('resultadoTexto');

    if(escanearBtn) {
        escanearBtn.addEventListener('click', () => {
            resTexto.innerText = "Analizando geometría facial...";
            resTexto.style.color = "#D4AF37"; 
            profileCard.style.display = 'none';

            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
            
            canvas.toBlob(async (blob) => {
                const formData = new FormData();
                formData.append('file', blob, 'webcam.jpg');
                
                try {
                    const res = await fetch('/recognize', { method: 'POST', body: formData });
                    const data = await res.json();
                    
                    if(data.result === 'SÍ') {
                        resTexto.innerText = "✅ IDENTIDAD VALIDADA";
                        resTexto.style.color = "#28a745";
                        
                        document.getElementById('p_nombre').innerText = data.data.nombre || "N/A";
                        document.getElementById('p_empresa').innerText = data.data.empresa || "Golden Logísticas";
                        document.getElementById('p_id').innerText = data.data.id || "N/A";
                        document.getElementById('p_cargo').innerText = data.data.cargo || "N/A";
                        
                        profileCard.style.display = 'flex';
                    } else {
                        resTexto.innerText = "❌ " + data.details;
                        resTexto.style.color = "#dc3545";
                    }
                } catch (e) {
                    resTexto.innerText = "❌ Error de conexión al servidor SaaS";
                    resTexto.style.color = "#dc3545";
                }
            }, 'image/jpeg');
        });
    }

    // 4. Formulario de Registro Individual
    const regForm = document.getElementById('regForm');
    if(regForm) {
        regForm.onsubmit = async (e) => {
            e.preventDefault();
            const btn = e.target.querySelector('button');
            btn.innerText = "Guardando..."; btn.disabled = true;
            try {
                const res = await fetch('/register', { method: 'POST', body: new FormData(e.target) });
                const data = await res.json();
                alert(data.message || data.error);
                e.target.reset();
            } catch(err) { alert("Error de red"); }
            btn.innerText = "Guardar Perfil Biométrico"; btn.disabled = false;
        };
    }

    // 5. Formulario de Carga Masiva
    const bulkForm = document.getElementById('bulkForm');
    if(bulkForm) {
        bulkForm.onsubmit = async (e) => {
            e.preventDefault();
            const btn = e.target.querySelector('button');
            btn.innerText = "Sincronizando Tenant..."; btn.disabled = true;
            try {
                const res = await fetch('/bulk_register', { method: 'POST', body: new FormData(e.target) });
                const data = await res.json();
                alert(data.message || data.error);
                e.target.reset();
            } catch(err) { alert("Error de red"); }
            btn.innerText = "Sincronizar Lote Masivo"; btn.disabled = false;
        };
    }
});