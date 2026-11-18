
        lucide.createIcons();
        requireLogin();

        const urlParams = new URLSearchParams(window.location.search);
        const rawBotId = urlParams.get('bot_id');
        const botId = (rawBotId && rawBotId !== 'null') ? rawBotId : (sessionStorage.getItem('selectedBotId') || "");
        const botQuery = botId ? `?bot_id=${botId}` : "";
        let attachments = [];

        // Always navigate with the correct bot_id regardless of URL state
        function goToTab(page) {
            const id = botId || sessionStorage.getItem('selectedBotId') || '';
            window.location.href = id ? `${page}?bot_id=${id}` : page;
        }

        if (botId) {
            fetchAttachments();
            fetchMetaTemplates();
        } else {
            document.getElementById('attachments-grid').innerHTML = '<div class="loading-state">No bot selected. Please go back and choose a bot.</div>';
        }

        async function fetchAttachments() {
            try {
                const response = await authenticatedFetch(`/api/media-attachments?chatbot_id=${botId}`);
                const data = await response.json();

                if (data.status === "success") {
                    attachments = data.data;
                    renderAttachments();
                } else {
                    showToast(data.message || "Failed to load attachments", "error");
                }
            } catch (error) {
                console.error("Error fetching attachments:", error);
                showToast("Connection error", "error");
            }
        }

        let metaTemplates = [];
        
        async function fetchMetaTemplates() {
            try {
                const response = await authenticatedFetch(`/api/meta-templates?chatbot_id=${botId}`);
                const data = await response.json();
                if (data.status === "success") {
                    metaTemplates = data.data.filter(t => t.status === 'APPROVED');
                    const select = document.getElementById('att-meta-template');
                    
                    // Keep the first empty option
                    const firstOption = select.options[0];
                    select.innerHTML = "";
                    select.appendChild(firstOption);
                    
                    metaTemplates.forEach(t => {
                        const opt = document.createElement('option');
                        opt.value = t.name;
                        opt.textContent = `${t.name} (${t.language})`;
                        // Store language as a data attribute so we can auto-fill it
                        opt.setAttribute('data-lang', t.language);
                        select.appendChild(opt);
                    });
                }
            } catch (e) {
                console.error("Error fetching meta templates", e);
            }
        }
        
        // Auto-fill language when a template is selected
        document.addEventListener('DOMContentLoaded', () => {
            const select = document.getElementById('att-meta-template');
            if (select) {
                select.addEventListener('change', (e) => {
                    const selectedOpt = e.target.options[e.target.selectedIndex];
                    const lang = selectedOpt.getAttribute('data-lang');
                    if (lang) {
                        document.getElementById('att-meta-language').value = lang;
                    }
                });
            }
        });


        function renderAttachments() {
            const grid = document.getElementById("attachments-grid");

            if (attachments.length === 0) {
                grid.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">
                            <i data-lucide="image-plus" style="width: 48px; height: 48px;"></i>
                        </div>
                        <h2>No Media Attachments</h2>
                        <p>Automatically send rich media like images and PDFs when the AI detects specific keywords in user messages.</p>
                        <button class="create-btn" onclick="openModal('create')">
                            <i data-lucide="plus"></i> Add Attachment
                        </button>
                    </div>
                `;
                lucide.createIcons();
                return;
            }
            
            grid.innerHTML = "";
            
            attachments.forEach(att => {
                const keywordTags = att.keywords 
                    ? att.keywords.map(k => `<span class="keyword-tag">${escapeHtml(k)}</span>`).join("")
                    : "";
                    
                let iconName = "image";
                if (att.media_type === "video") iconName = "video";
                if (att.media_type === "document") iconName = "file-text";
                
                const card = document.createElement("div");
                card.className = "glass-card";
                card.innerHTML = `
                    <div class="att-header">
                        <div class="att-icon">
                            <i data-lucide="${iconName}"></i>
                        </div>
                        <span class="badge ${att.is_active ? 'active-badge' : 'inactive-badge'}">
                            ${att.is_active ? 'Active' : 'Inactive'}
                        </span>
                    </div>
                    
                    <h3 class="att-title">${escapeHtml(att.label)}</h3>
                    <a href="${escapeHtml(att.media_url)}" target="_blank" class="att-url" title="${escapeHtml(att.media_url)}">
                        <i data-lucide="external-link" style="width: 14px; height: 14px;"></i>
                        View Media
                    </a>
                    
                    <div class="att-meta">
                        <div class="meta-row">
                            <span class="meta-label">Keywords</span>
                            <span class="meta-value keywords-container">${keywordTags || "<em>None</em>"}</span>
                        </div>
                        ${att.meta_template_name ? `
                        <div class="meta-row" style="margin-top: 8px;">
                            <span class="meta-label">Template</span>
                            <span class="meta-value">${escapeHtml(att.meta_template_name)} (${escapeHtml(att.meta_language_code || 'en_US')})</span>
                        </div>
                        ` : ""}
                    </div>
                    
                    <div class="att-actions">
                        <button class="action-btn edit-btn" onclick="openModal('edit', ${att.id})">
                            <i data-lucide="edit-2" style="width: 16px; height: 16px;"></i> Edit
                        </button>
                        <button class="action-btn delete-btn" onclick="openDeleteModal(${att.id})">
                            <i data-lucide="trash-2" style="width: 16px; height: 16px;"></i> Delete
                        </button>
                    </div>
                `;
                
                grid.appendChild(card);
            });
            
            lucide.createIcons();
        }

        function openModal(mode, id = null) {
            const modal = document.getElementById("att-modal");
            const title = document.getElementById("modal-title");
            
            if (mode === "create") {
                title.textContent = "Add Attachment";
                document.getElementById("att-id").value = "";
                document.getElementById("att-label").value = "";
                document.getElementById("att-type").value = "image";
                document.getElementById("att-url").value = "";
                document.getElementById("att-keywords").value = "";
                document.getElementById("att-caption").value = "";
                document.getElementById("att-meta-template").value = "";
                document.getElementById("att-meta-language").value = "en_US";
                document.getElementById("att-active").checked = true;
            } else if (mode === "edit" && id) {
                title.textContent = "Edit Attachment";
                const att = attachments.find(a => a.id === id);
                if (att) {
                    document.getElementById("att-id").value = att.id;
                    document.getElementById("att-label").value = att.label;
                    document.getElementById("att-type").value = att.media_type;
                    document.getElementById("att-url").value = att.media_url;
                    document.getElementById("att-keywords").value = (att.keywords || []).join(", ");
                    document.getElementById("att-caption").value = att.caption || "";
                    document.getElementById("att-meta-template").value = att.meta_template_name || "";
                    document.getElementById("att-meta-language").value = att.meta_language_code || "en_US";
                    document.getElementById("att-active").checked = att.is_active;
                }
            }
            
            modal.classList.add("show");
        }
        
        function openDeleteModal(id) {
            document.getElementById("delete-id").value = id;
            document.getElementById("delete-modal").classList.add("show");
        }
        
        function closeModal(modalId) {
            document.getElementById(modalId).classList.remove("show");
        }

        async function saveAttachment() {
            const id = document.getElementById("att-id").value;
            const label = document.getElementById("att-label").value.trim();
            const mediaType = document.getElementById("att-type").value;
            const mediaUrl = document.getElementById("att-url").value.trim();
            const keywordsStr = document.getElementById("att-keywords").value;
            const caption = document.getElementById("att-caption").value.trim();
            const metaTemplate = document.getElementById("att-meta-template").value.trim();
            const metaLanguage = document.getElementById("att-meta-language").value.trim() || "en_US";
            const isActive = document.getElementById("att-active").checked;
            
            if (!label || !mediaUrl) {
                showToast("Label and Media URL are required", "error");
                return;
            }
            
            const keywords = keywordsStr.split(",")
                .map(k => k.trim())
                .filter(k => k.length > 0);
                
            const payload = {
                label,
                media_type: mediaType,
                media_url: mediaUrl,
                keywords,
                caption,
                meta_template_name: metaTemplate,
                meta_language_code: metaLanguage,
                is_active: isActive
            };
            
            const btn = document.getElementById("save-btn");
            btn.innerHTML = '<i data-lucide="loader-2" class="lucide-spin"></i> Saving...';
            btn.disabled = true;
            lucide.createIcons();
            
            try {
                let url = `/api/media-attachments?chatbot_id=${botId}`;
                let method = "POST";
                
                if (id) {
                    url = `/api/media-attachments/${id}?chatbot_id=${botId}`;
                    method = "PUT";
                }
                
                const response = await authenticatedFetch(url, {
                    method: method,
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                
                const data = await response.json();
                
                if (data.status === "success") {
                    showToast(id ? "Attachment updated!" : "Attachment created!");
                    closeModal("att-modal");
                    fetchAttachments();
            fetchMetaTemplates();
                } else {
                    showToast(data.message || "Failed to save", "error");
                }
            } catch (error) {
                console.error("Error saving:", error);
                showToast("Connection error", "error");
            } finally {
                btn.innerHTML = "Save";
                btn.disabled = false;
            }
        }
        
        async function confirmDelete() {
            const id = document.getElementById("delete-id").value;
            if (!id) return;
            
            try {
                const response = await authenticatedFetch(`/ api / media - attachments / ${ id }?chatbot_id = ${ botId }`, {
                    method: "DELETE"
                });
                
                const data = await response.json();
                
                if (data.status === "success") {
                    showToast("Attachment deleted");
                    closeModal("delete-modal");
                    fetchAttachments();
            fetchMetaTemplates();
                } else {
                    showToast(data.message || "Failed to delete", "error");
                }
            } catch (error) {
                console.error("Error deleting:", error);
                showToast("Connection error", "error");
            }
        }
        
        function escapeHtml(unsafe) {
            if (!unsafe) return "";
            return (unsafe + "")
                 .replace(/&/g, "&amp;")
                 .replace(/</g, "&lt;")
                 .replace(/>/g, "&gt;")
                 .replace(/"/g, "&quot;")
                 .replace(/'/g, "&#039;");
        }
        
        // Drag and Drop Logic
        const attDropzone = document.getElementById('att-dropzone');
        const attFileInput = document.getElementById('att-file-upload');
        
        if (attDropzone && attFileInput) {
            attDropzone.addEventListener('click', () => attFileInput.click());
            
            ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
                attDropzone.addEventListener(eventName, preventDefaults, false);
            });

            function preventDefaults(e) {
                e.preventDefault();
                e.stopPropagation();
            }
            
            ['dragenter', 'dragover'].forEach(eventName => {
                attDropzone.addEventListener(eventName, () => {
                    attDropzone.style.background = 'rgba(255,255,255,0.1)';
                    attDropzone.style.borderColor = 'var(--accent)';
                }, false);
            });
            
            ['dragleave', 'drop'].forEach(eventName => {
                attDropzone.addEventListener(eventName, () => {
                    attDropzone.style.background = 'rgba(255,255,255,0.05)';
                    attDropzone.style.borderColor = 'rgba(255,255,255,0.2)';
                }, false);
            });
            
            attDropzone.addEventListener('drop', (e) => {
                if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                    const file = e.dataTransfer.files[0];
                    uploadMediaFile(file);
                }
            });
            
            attFileInput.addEventListener('change', function(e) {
                if (e.target.files && e.target.files.length > 0) {
                    uploadMediaFile(e.target.files[0]);
                }
            });
            
            async function uploadMediaFile(file) {
                if (!file) return;
                
                const formData = new FormData();
                formData.append('media_file', file);
                
                const originalHtml = attDropzone.innerHTML;
                attDropzone.innerHTML = '<i data-lucide="loader-2" class="lucide-spin" style="font-size: 2em; margin-bottom: 10px; color: var(--accent);"></i><div style="font-weight: 500;">Uploading...</div>';
                attDropzone.style.opacity = '0.7';
                if (typeof lucide !== 'undefined') lucide.createIcons();
                
                try {
                    const botIdParam = typeof botId !== 'undefined' ? botId : currentChatbotId;
                    const response = await authenticatedFetch(`/api/media-attachments/upload?chatbot_id=${botIdParam}`, {
                        method: 'POST',
                        body: formData
                    });
                    
                    const data = await response.json();
                    if (data.status === 'success') {
                        document.getElementById('att-url').value = data.data.public_url;
                        showToast('File uploaded successfully!', 'success');
                    } else {
                        showToast(data.message || 'Upload failed', 'error');
                    }
                } catch (err) {
                    console.error(err);
                    showToast('Upload failed', 'error');
                } finally {
                    attDropzone.innerHTML = originalHtml;
                    attDropzone.style.opacity = '1';
                    attFileInput.value = ''; // Reset input
                    if (typeof lucide !== 'undefined') lucide.createIcons();
                }
            }
        }

        // Meta Template Popup Logic
        function openMetaTemplateModal() {
            // Pre-fill some fields based on the current attachment if possible
            const currentName = document.getElementById('att-meta-template').value;
            if (!currentName) {
                const label = document.getElementById('att-label').value;
                if (label) {
                    document.getElementById('meta-tpl-name').value = label.toLowerCase().replace(/[^a-z0-9]/g, '_') + '_tpl';
                }
            }
            
            const currentMediaType = document.getElementById('att-type').value;
            let metaType = "IMAGE";
            if (currentMediaType === "video") metaType = "VIDEO";
            if (currentMediaType === "document") metaType = "DOCUMENT";
            document.getElementById('meta-tpl-type').value = metaType;
            
            const currentCaption = document.getElementById('att-caption').value;
            document.getElementById('meta-tpl-body').value = currentCaption || "Here is your requested media attachment.";

            document.getElementById('meta-tpl-modal').classList.add('show');
        }

        function closeMetaTemplateModal() {
            document.getElementById('meta-tpl-modal').classList.remove('show');
        }

        async function saveNewMetaTemplate() {
            const name = document.getElementById('meta-tpl-name').value.trim();
            const language = document.getElementById('meta-tpl-language').value.trim() || 'en_US';
            const mediaType = document.getElementById('meta-tpl-type').value;
            const bodyText = document.getElementById('meta-tpl-body').value.trim();
            
            // Try to use the current media URL if one is uploaded
            const mediaUrl = document.getElementById('att-url').value.trim();

            if (!name || !bodyText) {
                showToast("Template Name and Body Text are required.", "error");
                return;
            }

            const btn = document.getElementById('meta-tpl-save-btn');
            btn.innerHTML = '<i data-lucide="loader-2" class="lucide-spin"></i> Submitting...';
            btn.disabled = true;
            lucide.createIcons();

            try {
                const payload = {
                    name: name,
                    language: language,
                    category: "MARKETING",
                    media_type: mediaType,
                    body_text: bodyText,
                    media_url: mediaUrl || undefined
                };

                const response = await authenticatedFetch(`/api/meta-templates?chatbot_id=${botId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const data = await response.json();
                if (data.status === 'success') {
                    showToast("Template submitted to Meta successfully!", "success");
                    closeMetaTemplateModal();
                    
                    // Refresh the dropdown and select the new one
                    await fetchMetaTemplates();
                    document.getElementById('att-meta-template').value = name;
                } else {
                    showToast(data.message || "Failed to submit template", "error");
                }
            } catch (error) {
                console.error("Error submitting meta template:", error);
                showToast("Connection error", "error");
            } finally {
                btn.innerHTML = "Submit to Meta";
                btn.disabled = false;
            }
        }

    