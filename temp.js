
        // Data State
        let buttons = [
            { id: 1, title: 'Tengok Koleksi', instruction: '' },
            { id: 2, title: 'Promosi', instruction: '' },
            { id: 3, title: 'Tanya Soalan', instruction: '' }
        ];

        let mockClusteredData = [];

        // Init
        document.addEventListener('DOMContentLoaded', () => {
            lucide.createIcons();
            
            // Check auth
            if (!sessionStorage.getItem('token')) {
                window.location.href = 'login.html';
                return;
            }

            renderButtons();
            renderChips();
            updatePreview();
            fetchActiveDocument();

            document.getElementById('welcomeMsg').addEventListener('input', updatePreview);
        });

        async function fetchActiveDocument() {
            const urlParams = new URLSearchParams(window.location.search);
            const botId = urlParams.get('bot_id') || urlParams.get('chatbot_id');
            const botQuery = botId ? `?chatbot_id=${botId}` : '';
            
            try {
                const response = await authenticatedFetch(`/api/knowledge/active${botQuery}`);
                if (response.ok) {
                    const data = await response.json();
                    if (data && data.data && data.data.file_name) {
                        document.getElementById('activeDocName').innerText = data.data.file_name;
                        extractDocInfo();
                    } else {
                        document.getElementById('activeDocName').innerText = "No active document found";
                    }
                } else {
                    document.getElementById('activeDocName').innerText = "No active document found";
                }
            } catch (err) {
                console.error("Error fetching active document:", err);
                document.getElementById('activeDocName').innerText = "Error loading document";
            }
        }

        // Builder Logic
        function renderButtons() {
            const container = document.getElementById('buttonsContainer');
            container.innerHTML = '';

            buttons.forEach((btn, idx) => {
                const card = document.createElement('div');
                card.className = 'btn-card';
                card.innerHTML = `
                    <div class="btn-card-header">
                        <input type="text" class="form-control" value="${btn.title}" placeholder="Button Title" oninput="updateBtnTitle(${idx}, this.value)">
                        <button class="btn btn-outline" style="color:var(--danger); border-color:rgba(239,68,68,0.3); padding:0.5rem;" onclick="removeButton(${idx})">
                            <i data-lucide="trash-2"></i>
                        </button>
                    </div>
                    <div class="instruction-box" id="dropzone-${idx}" ondragover="allowDrop(event)" ondragleave="dragLeave(event)" ondrop="drop(event, ${idx})">
                        <div class="instruction-title">
                            <i data-lucide="edit-3"></i> WHAT SHOULD THE AI SAY OR DO WHEN THIS BUTTON IS TAPPED?
                        </div>
                        <textarea class="form-control" style="background:rgba(0,0,0,0.3); border:none; min-height:60px;" placeholder='Type specific answer details (e.g. "Reply with phone..."), or drop an AI info chip.' oninput="updateBtnInstruction(${idx}, this.value)">${btn.instruction}</textarea>
                        <button class="btn btn-outline btn-sm" style="margin-top: 0.5rem; border-color:var(--chip-border); color:var(--chip-text);">
                            + Add Info / Instruction
                        </button>
                    </div>
                `;
                container.appendChild(card);
            });

            document.getElementById('addBtnTrigger').style.display = buttons.length >= 3 ? 'none' : 'flex';
            lucide.createIcons();
            updatePreview();
        }

        function addManualButton() {
            if (buttons.length >= 3) return;
            buttons.push({ id: Date.now(), title: 'New Button', instruction: '' });
            renderButtons();
        }

        function removeButton(idx) {
            buttons.splice(idx, 1);
            renderButtons();
        }

        function updateBtnTitle(idx, val) {
            buttons[idx].title = val;
            updatePreview();
        }

        function updateBtnInstruction(idx, val) {
            buttons[idx].instruction = val;
        }

        // Chips Logic
        function renderChips() {
            // Render Filter Pills
            const pillsContainer = document.getElementById('filterPillsContainer');
            let totalChips = mockClusteredData.reduce((sum, c) => sum + c.count, 0);
            
            let pillsHtml = `<span class="filter-pill active">All (${totalChips})</span>`;
            mockClusteredData.forEach(cluster => {
                pillsHtml += `<span class="filter-pill">${cluster.icon} ${cluster.category} (${cluster.count})</span>`;
            });
            pillsContainer.innerHTML = pillsHtml;

            // Render Accordion
            const container = document.getElementById('chipsContainer');
            container.innerHTML = '';

            mockClusteredData.forEach((cluster, cIdx) => {
                if (cluster.chips.length === 0) return; // Skip empty for demo
                
                const catDiv = document.createElement('div');
                catDiv.className = 'chip-category'; // Collapsed by default
                
                catDiv.innerHTML = `
                    <div class="chip-category-header" onclick="this.parentElement.classList.toggle('open')">
                        <span style="color: #ffbb33; font-weight: 700;">▲ ${cluster.icon} ${cluster.category} (${cluster.count})</span>
                        <button class="btn btn-outline btn-sm" style="color: var(--accent); border-color: rgba(16, 185, 129, 0.3); padding: 2px 8px; font-size: 0.75rem;" onclick="event.stopPropagation(); alert('Create button logic here')">+ Create Button</button>
                    </div>
                    <div class="chip-category-content">
                        ${cluster.chips.map((chip, iIdx) => {
                            const cName = typeof chip === 'string' ? chip : chip.name;
                            const cDetail = typeof chip === 'string' ? '' : chip.detail;
                            const tooltip = cDetail ? cDetail.replace(/"/g, '&quot;') : cName;
                            const dragText = cDetail ? `[Knowledge: ${cName} - ${cDetail.replace(/\n/g, ' ')}]` : cName;
                            const alertText = cDetail ? cDetail.replace(/'/g, "\\'").replace(/\n/g, "\\n") : cName.replace(/'/g, "\\'");
                            return `
                            <div class="info-chip" title="${tooltip}" onclick="alert('${alertText}')" draggable="true" ondragstart="drag(event, '${dragText.replace(/'/g, "\\\'")}')">
                                ${cName}
                            </div>
                            `;
                        }).join('')}
                    </div>
                `;
                container.appendChild(catDiv);
            });
            lucide.createIcons();
        }

        async function extractDocInfo() {
            const urlParams = new URLSearchParams(window.location.search);
            const botId = urlParams.get('bot_id') || urlParams.get('chatbot_id');
            const botQuery = botId ? `?chatbot_id=${botId}` : '';
            
            try {
                // Show loading state
                const btn = document.querySelector('button[onclick="extractDocInfo()"]');
                const originalText = btn.innerHTML;
                btn.innerHTML = `<i data-lucide="loader" class="spin"></i> Extracting...`;
                btn.disabled = true;
                lucide.createIcons();
                
                const response = await authenticatedFetch(`/api/knowledge/graph${botQuery}`);
                if (response.ok) {
                    const resData = await response.json();
                    const nodes = (resData.data && resData.data.nodes) ? resData.data.nodes : [];
                    
                    // Convert nodes to clustered data format
                    const clustered = {};
                    nodes.forEach(node => {
                        const cat = node.group || 'Uncategorized';
                        if (!clustered[cat]) clustered[cat] = { category: cat, icon: "📄", count: 0, chips: [] };
                        clustered[cat].chips.push({
                            name: node.id || node.label || 'Unknown',
                            detail: node.title || ''
                        });
                        clustered[cat].count++;
                    });
                    
                    // Replace mockClusteredData
                    mockClusteredData = Object.values(clustered);
                    
                    // Add an "All [Category]" combined chip to make it easier to drag small datasets
                    mockClusteredData.forEach(cluster => {
                        if (cluster.chips.length > 1) {
                            const combinedDetail = cluster.chips.map(c => c.detail).join(' | ');
                            cluster.chips.unshift({
                                name: `All ${cluster.category}`,
                                detail: combinedDetail
                            });
                        }
                    });
                    
                    if(mockClusteredData.length === 0) {
                        mockClusteredData.push({ category: "No Data Found", icon: "⚠️", count: 0, chips: ["No extracted info found. Did the document finish processing?"] });
                    }
                    
                    renderChips();
                } else {
                    alert("Failed to extract data from backend.");
                }
                
                // Restore button
                btn.innerHTML = originalText;
                btn.disabled = false;
                lucide.createIcons();
                
            } catch (err) {
                console.error("Error extracting PDF info:", err);
                alert("Error extracting PDF info.");
                
                const btn = document.querySelector('button[onclick="extractDocInfo()"]');
                btn.innerHTML = `<i data-lucide="download"></i> Extract Document Info`;
                btn.disabled = false;
                lucide.createIcons();
            }
        }

        // Drag & Drop
        function drag(ev, text) {
            ev.dataTransfer.setData("text/plain", text);
        }

        function allowDrop(ev) {
            ev.preventDefault();
            const dropzone = ev.target.closest('.instruction-box');
            if (dropzone) dropzone.classList.add('drag-over');
        }

        function dragLeave(ev) {
            const dropzone = ev.target.closest('.instruction-box');
            if (dropzone) dropzone.classList.remove('drag-over');
        }

        function drop(ev, btnIdx) {
            ev.preventDefault();
            const dropzone = ev.target.closest('.instruction-box');
            if (dropzone) dropzone.classList.remove('drag-over');

            const text = ev.dataTransfer.getData("text/plain");
            if (text) {
                // Append chip text to instruction
                const currentText = buttons[btnIdx].instruction;
                buttons[btnIdx].instruction = currentText ? currentText + "\n- " + text : "- " + text;
                renderButtons();
            }
        }

        // Preview Logic
        function updatePreview() {
            const msg = document.getElementById('welcomeMsg').value;
            document.getElementById('previewMsg').innerText = msg;

            const btnsContainer = document.getElementById('previewBtns');
            btnsContainer.innerHTML = buttons.map(btn => `
                <div class="wa-btn">${btn.title || 'Untitled'}</div>
            `).join('');
        }
    