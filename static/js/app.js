document.addEventListener("DOMContentLoaded", () => {
    
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

    async function loadLiveDirectory() {
        const tbody = document.getElementById('directoryTableBody');
        tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;">Cargando base de datos...</td></tr>';
        
        try {
            const res = await fetch('/api/users');
            const users = await res.json();
            
            tbody.innerHTML = '';
            users.forEach(user => {
                const tr = document.createElement('tr');
                
                if (user.status === 'Registrado') {
                    tr.classList.add('row-registrado');
                } else if (user.status === 'Nuevo') {
                    tr.classList.add('row-nuevo');
                } else {
                    tr.classList.add('row-noregistrado');
                }
                
                const tds = {}; 
                
                // Mapeo estructurado independiente en celdas
                const fieldsOrder = ['id', 'first_name', 'last_name', 'role', 'company', 'phone', 'email', 'opt_1', 'opt_2'];
                
                fieldsOrder.forEach(field => {
                    const td = document.createElement('td');
                    td.innerText = user[field] || '';
                    tr.appendChild(td);
                    tds[field] = td;
                });
                
                const statusTd = document.createElement('td');
                statusTd.innerText = user.status;
                statusTd.style.fontWeight = "bold";
                tr.appendChild(statusTd);

                const actionTd = document.createElement('td');
                actionTd.className = "action-cell";

                const actionBtn = document.createElement('button');
                actionBtn.innerText = "Editar";
                actionBtn.className = "golden-btn btn-table-action";

                const deleteBtn = document.createElement('button');
                deleteBtn.innerText = "Eliminar";
                deleteBtn.className = "btn-table-delete";
                deleteBtn.style.display = "none"; 
                
                let isEditing = false;
                
                actionBtn.addEventListener('click', async () => {
                    const editableFields = ['first_name', 'last_name', 'role', 'company', 'phone', 'email', 'opt_1', 'opt_2'];

                    if (!isEditing) {
                        isEditing = true;
                        actionBtn.innerText = "Guardar";
                        actionBtn.classList.add('btn-save'); 
                        deleteBtn.style.display = "inline-block"; 
                        
                        editableFields.forEach(field => {
                            tds[field].contentEditable = "true";
                            tds[field].classList.add('editable-cell-active');
                        });
                        tds['first_name'].focus();
                    } else {
                        actionBtn.innerText = "Guardando...";
                        actionBtn.disabled = true;
                        deleteBtn.style.display = "none";
                        
                        const payload = {};
                        editableFields.forEach(field => {
                            payload[field] = tds[field].innerText.trim();
                            tds[field].contentEditable = "false";
                            tds[field].classList.remove('editable-cell-active');
                        });
                        
                        try {
                            const updateRes = await fetch(`/api/users/${user.id}`, {
                                method: 'PATCH',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(payload)
                            });
                            
                            if(updateRes.ok) {
                                actionBtn.innerText = "Editar";
                                actionBtn.classList.remove('btn-save');
                                isEditing = false;
                            } else {
                                alert("Error al guardar cambios en SQL");
                                actionBtn.innerText = "Guardar";
                            }
                        } catch (error) {
                            alert("Error de red");
                            actionBtn.innerText = "Guardar";
                        }
                        actionBtn.disabled = false;
                    }
                });

                deleteBtn.addEventListener('click', async () => {
                    const fullName = `${user.first_name || ''} ${user.last_name || ''}`.trim();
                    const isConfirmed = confirm(`⚠️ CUIDADO: Estás a punto de borrar el registro de asistencia de ${fullName}.\n\nEsto devolverá a la persona al estado "No registrado" y borrará sus logs de hoy, pero NO lo eliminará de la base de datos principal.`);
                    
                    if (isConfirmed) {
                        try {
                            const delRes = await fetch(`/api/users/${user.id}/logs`, { method: 'DELETE' });
                            if (delRes.ok) {
                                alert("Registro de asistencia eliminado.");
                                
                                tr.className = 'row-noregistrado';
                                statusTd.innerText = "No registrado";
                                
                                actionBtn.innerText = "Editar";
                                actionBtn.classList.remove('btn-save');
                                deleteBtn.style.display = "none";
                                isEditing = false;
                                
                                const editableFields = ['first_name', 'last_name', 'role', 'company', 'phone', 'email', 'opt_1', 'opt_2'];
                                editableFields.forEach(field => {
                                    tds[field].contentEditable = "false";
                                    tds[field].classList.remove('editable-cell-active');
                                });
                            } else {
                                alert("Error al eliminar el registro.");
                            }
                        } catch (e) {
                            alert("Error de red al intentar borrar.");
                        }
                    }
                });
                
                actionTd.appendChild(actionBtn);
                actionTd.appendChild(deleteBtn);
                tr.appendChild(actionTd);
                tbody.appendChild(tr);
            });
        } catch (err) {
            tbody.innerHTML = '<tr><td colspan="11" style="text-align:center; color:red;">Error conectando al servidor</td></tr>';
        }
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
                
                try {
                    const res = await fetch('/api/recognize', { method: 'POST', body: formData });
                    const data = await res.json();
                    
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
            const autorizacion = confirm("⚠️ ATENCIÓN: Esta persona ya se encuentra registrada en el sistema.\n\n¿Estás completamente seguro de que deseas sobrescribir sus datos?");
            if (!autorizacion) return; 

            const btn = e.target.querySelector('button');
            btn.innerText = "Guardando..."; btn.disabled = true;

            const payload = Object.fromEntries(new FormData(e.target).entries());
            
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
            } catch (err) { alert("❌ Error de red."); }
            btn.innerText = "Guardar y Autorizar Acceso"; btn.disabled = false;
        };
    }

    const exportBtn = document.getElementById('exportBtn');
    if(exportBtn) {
        exportBtn.addEventListener('click', () => window.location.href = '/api/report' );
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