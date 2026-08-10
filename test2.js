
        lucide.createIcons();
        
        var id = document.getElementById("drawflow");
        const editor = new Drawflow(id);
        editor.reroute = true;
        editor.start();

        function updateNodeCounterAndGuide() {
            const data = editor.export();
            let nodeCount = 0;
            if (data && data.drawflow && data.drawflow.Home && data.drawflow.Home.data) {
                nodeCount = Object.keys(data.drawflow.Home.data).length;
            }
            
            // Guide visibility
            const guide = document.getElementById('empty-canvas-guide');
            if (guide) guide.style.opacity = nodeCount > 0 ? '0' : '1';
            
            // Counter update
            const counter = document.getElementById('node-counter');
            if (counter) counter.innerText = `${nodeCount} node${nodeCount === 1 ? '' : 's'} added`;
        }
        
        editor.on('nodeCreated', updateNodeCounterAndGuide);
        editor.on('nodeRemoved', updateNodeCounterAndGuide);
        editor.on('import', updateNodeCounterAndGuide);
        
        editor.on('zoom', function(zoom) {
            const zlevel = document.getElementById('zoom-level');
            if (zlevel) {
                // Drawflow zoom is typically 1 (default). 
                zlevel.innerText = Math.round(zoom * 100) + '%';
            }
        });

        function filterNodes() {
            const query = document.getElementById('node-search-input').value.toLowerCase();
            const nodes = document.querySelectorAll('.drag-node');
            nodes.forEach(node => {
                const title = node.innerText.toLowerCase();
                node.style.display = title.includes(query) ? 'flex' : 'none';
            });
            
            // Hide section headers if all nodes under them are hidden (optional refinement)
            // For now just filtering the nodes themselves is good enough
        }

        let selectedNodeId = null;

        // Node Definitions Data Structure
        const nodeDefinitions = {
            trigger: {
                title: "Trigger Keyword",
                icon: "play",
                color: "#f59e0b",
                desc: "Starts the automation flow",
                inputs: 0, outputs: 1,
                data: { keyword: "" },
                fields: [
                    { name: "keyword", label: "Trigger Keyword (Exact Match)", type: "text", placeholder: "e.g. Menu", hint: "The bot will start this flow when a customer sends a message matching this exact word." }
                ]
            },
            send_message: {
                title: "Text Message",
                icon: "message-square",
                color: "var(--primary)",
                desc: "Sends a simple WhatsApp text",
                inputs: 1, outputs: 1,
                data: { text: "" },
                fields: [
                    { name: "text", label: "Message Content", type: "textarea", placeholder: "Enter your message here...", hint: "Type the message you want the bot to send to the customer." }
                ]
            },
            interactive_buttons: {
                title: "Interactive Buttons",
                icon: "square",
                color: "var(--primary)",
                desc: "Sends up to 3 clickable buttons",
                inputs: 1, outputs: 3,
                data: { body_text: "", btn_1: "", btn_2: "", btn_3: "" },
                fields: [
                    { name: "body_text", label: "Main Text", type: "textarea", placeholder: "Choose an option below:", hint: "The main message text displayed above the buttons." },
                    { name: "btn_1", label: "Button 1 Label", type: "text", hint: "Text for the first button (max 20 chars)." },
                    { name: "btn_2", label: "Button 2 Label", type: "text" },
                    { name: "btn_3", label: "Button 3 Label", type: "text" }
                ]
            },
            condition: {
                title: "Condition (If/Else)",
                icon: "git-branch",
                color: "#10b981",
                desc: "Branch flow based on data",
                inputs: 1, outputs: 2,
                data: { tag_condition: "" },
                fields: [
                    { name: "tag_condition", label: "If Customer Tag Contains:", type: "text", placeholder: "e.g. VIP", hint: "Routes to the top output if the customer has this tag, otherwise routes to the bottom output." }
                ]
            },
            tag_customer: {
                title: "Tag Customer",
                icon: "tag",
                color: "#6366f1",
                desc: "Adds a label/tag to contact",
                inputs: 1, outputs: 1,
                data: { tag: "" },
                fields: [
                    { name: "tag", label: "Tag Name", type: "text", placeholder: "e.g. VIP, Hot Lead", hint: "Customers passing through this node will have this tag applied to their CRM profile." }
                ]
            },
            flow_end: {
                title: "Flow End",
                icon: "stop-circle",
                color: "#1e293b",
                desc: "Ends the flow or jumps to another node",
                inputs: 1, outputs: 0,
                data: { action: "end" },
                fields: [
                    { name: "action", label: "End Action", type: "text", placeholder: "e.g. End flow", hint: "The flow can jump to another node if available, otherwise it will end here." }
                ]
            },
            human_handoff: {
                title: "Human Handoff",
                icon: "user",
                color: "#ef4444",
                desc: "Pause bot and alert agent",
                inputs: 1, outputs: 0,
                data: { handoff_msg: "" },
                fields: [
                    { name: "handoff_msg", label: "Internal Alert Message:", type: "text", placeholder: "Agent needed!", hint: "Stops the bot and sends an internal notification to your team." }
                ]
            },
            ai_generate: {
                title: "AI RAG Agent",
                icon: "brain",
                color: "#a855f7",
                desc: "Route to knowledge base AI",
                inputs: 1, outputs: 1,
                data: { system_prompt: "" },
                fields: [
                    { name: "system_prompt", label: "System Prompt Override (Optional)", type: "textarea", placeholder: "You are a helpful assistant...", hint: "Overrides the default AI behavior. Leave blank to use the bot's default settings." }
                ]
            }
        };

        // Render HTML for node on canvas
        function getNodeHTML(type, data) {
            const def = nodeDefinitions[type];
            return `
                <div class="node-inner">
                    <div class="icon" style="color: ${def.color}; background: ${def.color}22;">
                        <i data-lucide="${def.icon}"></i>
                    </div>
                    <div class="details">
                        <div class="title">${def.title}</div>
                        <div class="subtitle">${def.desc}</div>
                    </div>
                </div>
                <div class="node-footer">
                    Click to configure settings
                </div>
            `;
        }

        function addNodeToDrawFlow(name, pos_x, pos_y) {
            if(editor.editor_mode === 'fixed') return false;
            pos_x = pos_x * ( editor.precanvas.clientWidth / (editor.precanvas.clientWidth * editor.zoom)) - (editor.precanvas.getBoundingClientRect().x * ( editor.precanvas.clientWidth / (editor.precanvas.clientWidth * editor.zoom)));
            pos_y = pos_y * ( editor.precanvas.clientHeight / (editor.precanvas.clientHeight * editor.zoom)) - (editor.precanvas.getBoundingClientRect().y * ( editor.precanvas.clientHeight / (editor.precanvas.clientHeight * editor.zoom)));

            const def = nodeDefinitions[name];
            if(!def) return;
            
            // Clone default data
            const data = JSON.parse(JSON.stringify(def.data));
            
            editor.addNode(name, def.inputs, def.outputs, pos_x, pos_y, name, data, getNodeHTML(name, data));
            setTimeout(() => lucide.createIcons(), 10);
        }

        function allowDrop(ev) { ev.preventDefault(); }
        function drag(ev) { 
            const node = ev.target.closest('.drag-node');
            if(node) ev.dataTransfer.setData("node", node.getAttribute('data-node')); 
        }
        function drop(ev) {
            ev.preventDefault();
            const data = ev.dataTransfer.getData("node");
            if(data) addNodeToDrawFlow(data, ev.clientX, ev.clientY);
        }

        // Configuration Panel Logic
        editor.on('nodeSelected', function(id) {
            selectedNodeId = id;
            const node = editor.getNodeFromId(id);
            const def = nodeDefinitions[node.name];
            
            document.getElementById("config-panel").classList.add("open");
            document.getElementById("config-title").innerText = def.title + " Settings";
            
            let formHtml = '';
            def.fields.forEach(f => {
                const val = node.data[f.name] || '';
                const hintHtml = f.hint ? `<div style="font-size: 0.75rem; color: var(--text-dim); margin-top: 4px; line-height: 1.3;">${f.hint}</div>` : '';
                
                if(f.type === 'textarea') {
                    formHtml += `<div class="form-group"><label>${f.label}</label><textarea id="field_${f.name}" placeholder="${f.placeholder || ''}" onchange="updateNodeData('${f.name}')">${val}</textarea>${hintHtml}</div>`;
                } else {
                    formHtml += `<div class="form-group"><label>${f.label}</label><input type="text" id="field_${f.name}" placeholder="${f.placeholder || ''}" value="${val}" onchange="updateNodeData('${f.name}')">${hintHtml}</div>`;
                }
            });
            
            document.getElementById("config-form").innerHTML = formHtml;
        });

        editor.on('nodeUnselected', function(id) {
            if(selectedNodeId == id) closeConfigPanel();
        });

        function closeConfigPanel() {
            document.getElementById("config-panel").classList.remove("open");
            selectedNodeId = null;
        }

        window.updateNodeData = function(fieldName) {
            if(!selectedNodeId) return;
            const val = document.getElementById("field_"+fieldName).value;
            const node = editor.getNodeFromId(selectedNodeId);
            node.data[fieldName] = val;
            editor.updateNodeDataFromId(selectedNodeId, node.data);
            console.log("Updated Node", selectedNodeId, fieldName, val);
        }

        function showAlert(title, msg) {
            document.getElementById("alertTitle").innerText = title;
            document.getElementById("alertMessage").innerText = msg;
            document.getElementById("alertModal").style.display = 'flex';
        }

        async function saveFlow(action) {
            const data = editor.export();
            const urlParams = new URLSearchParams(window.location.search);
            const botId = urlParams.get("bot_id") || sessionStorage.getItem("selectedBotId");
            const flowId = urlParams.get("flow_id");

            if (!botId) { showAlert("Error", "Please select a chatbot first!"); return; }
            
            try {
                const response = await authenticatedFetch('/api/dashboard/flows?action=' + action, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ chatbot_id: botId, flow_id: flowId, name: 'Main Flow', flow_data: data })
                });

                if (response && response.ok) {
                    showAlert("Success", action === 'publish' ? "Flow published live successfully!" : "Draft saved successfully.");
                } else {
                    showAlert("Error", "Failed to save flow. Check server logs.");
                }
            } catch (error) {
                showAlert("Error", "Error saving flow: " + error);
            }
        }

        async function loadFlow() {
            const urlParams = new URLSearchParams(window.location.search);
            const botId = urlParams.get("bot_id") || sessionStorage.getItem("selectedBotId");
            const flowId = urlParams.get("flow_id");
            if (!botId) return;

            try {
                let url = '/api/dashboard/flows?chatbot_id=' + botId;
                if (flowId) { url += '&flow_id=' + flowId; }
                const response = await authenticatedFetch(url, { method: 'GET' });
                const json = await response.json();
                
                // For V3, load draft_data if it exists, fallback to flow_data for backward compat
                if (json && json.data) {
                    let flowData = json.data.draft_data || json.data.flow_data;
                    if (flowData) {
                        if (typeof flowData === 'string') flowData = JSON.parse(flowData);
                        editor.clear();
                        editor.import(flowData);
                        setTimeout(() => lucide.createIcons(), 100);
                    }
                }
            } catch (e) {
                console.error("Failed to load flow data", e);
            }
        }

        setTimeout(() => loadFlow(), 500);

        function autoGenerateFlow() {
            showAlert("Auto-Generate", "AI is analyzing your PDFs... (Feature simulated in this preview)");
        }

        function goBackToManager() {
            const urlParams = new URLSearchParams(window.location.search);
            const botId = urlParams.get("bot_id") || sessionStorage.getItem("selectedBotId");
            window.location.href = 'flows.html' + (botId ? '?bot_id=' + botId : '');
        }
    