window.messagesCache = window.messagesCache || {};
window.isSelectionMode = window.isSelectionMode || false;
window.selectedMessageIds = window.selectedMessageIds || new Set();

function formatSize(bytes) {
    if(!bytes) return "";
    if (bytes < 1024) return bytes + " B";
    else if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
    else return (bytes / 1048576).toFixed(1) + " MB";
}

function buildMessageHtml(packet) {
    if (!packet.msg_id) return "";
    window.messagesCache[packet.msg_id] = packet;
    
    const isMine = packet.sender === myUsername;
    let contentHtml = '';

    // --- Reply bubble: shown at the bottom of the bubble if this message is a reply ---
    let replyBubbleHtml = '';
    if (packet.reply_to && packet.reply_content) {
        const _sepIdx = packet.reply_content.indexOf(': ');
        const _rSender = _sepIdx > -1 ? packet.reply_content.substring(0, _sepIdx) : '';
        const _rText   = _sepIdx > -1 ? packet.reply_content.substring(_sepIdx + 2) : packet.reply_content;
        replyBubbleHtml = `<div class="reply-bubble" onclick="window.scrollToMsg('${packet.reply_to}')" title="Jump to original message" style="font-size: 0.8rem; padding: 4px 8px !important; margin: 4px 0 0 0 !important; background: rgba(0,0,0,0.15); border-left: 3px solid var(--accent); border-radius: 4px; cursor: pointer; display: block !important; width: 100%;"><span class="reply-bubble-text" style="color: rgba(255,255,255,0.7); display: inline !important; white-space: normal !important; text-overflow: clip !important; overflow: visible !important;">replying to <strong>${_rSender || 'Message'}</strong>: ${_rText}</span></div>`;
    }
    
    if(packet.type === 'text') {
        contentHtml = packet.content;
    } else if(packet.type === 'file') {
        const isImg = packet.name.match(/\.(jpeg|jpg|gif|png|bmp)$/i);
        const isAudio = packet.name.match(/\.(webm|mp3|wav|ogg|m4a)$/i);
        
        if(isImg && packet.data) {
            contentHtml = `
            <div style="position: relative; display: inline-block; max-width: 100%;">
                <img src="data:image/png;base64,${packet.data}" style="max-width:100%; border-radius:8px; margin-bottom: 5px;" alt="Attached Image">
                <div style="display: flex; gap: 5px; margin-top: 5px;">
                    <a href="/api/download/${packet.name}" target="_blank" class="btn btn-sm btn-outline-info" style="font-size: 0.8rem; padding: 2px 6px;">
                        <i class="bi bi-eye"></i> View
                    </a>
                    <a href="/api/download/${packet.name}" download="${packet.name}" class="btn btn-sm btn-outline-success" style="font-size: 0.8rem; padding: 2px 6px;">
                        <i class="bi bi-download"></i> Save
                    </a>
                </div>
            </div>`;
        } else if (isAudio) {
            contentHtml = `
            <div class="audio-container d-flex align-items-center gap-2" style="max-width: 100%;">
                <audio controls src="/api/download/${packet.name}" style="height: 40px; outline: none;"></audio>
                <a href="/api/download/${packet.name}" download="${packet.name}" class="btn btn-sm btn-success" title="Save Audio" style="border-radius: 50%; padding: 4px 8px;" aria-label="Save Audio Message">
                    <i class="bi bi-download"></i>
                </a>
            </div>`;
        } else {
            const displayName = packet.name.substring(packet.name.indexOf('_') + 1);
            contentHtml = `
            <div style="display:flex; align-items:center; justify-content: space-between; gap: 15px; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 8px;">
                <div style="display:flex; align-items:center; gap: 10px; overflow: hidden;">
                    <div style="font-size: 1.5rem; flex-shrink: 0;">📄</div>
                    <div style="overflow: hidden;">
                        <div style="color: #f8fafc; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; overflow: hidden;" title="${displayName}">${displayName}</div>
                        <div style="font-size: 0.75rem; color: rgba(255,255,255,0.7);">${formatSize(packet.size)}</div>
                    </div>
                </div>
                <div style="display:flex; gap: 5px; flex-shrink: 0;">
                    <a href="/api/download/${packet.name}" target="_blank" class="btn btn-sm btn-primary" title="Open" style="border-radius: 4px; padding: 4px 8px; font-size: 0.8rem;">
                        <i class="bi bi-eye"></i>
                    </a>
                    <a href="/api/download/${packet.name}" download="${packet.name}" class="btn btn-sm btn-success" title="Download & Save" style="border-radius: 4px; padding: 4px 8px; font-size: 0.8rem;">
                        <i class="bi bi-download"></i> Save
                    </a>
                </div>
            </div>`;
        }
    } else if(packet.type === 'call_log') {
        const isMine = packet.sender === myUsername;
        let logText = '';
        let icon = '';
        
        if (isMine) {
            if (packet.content === 'completed') {
                icon = '📞';
                const mins = Math.floor(packet.duration / 60);
                const secs = packet.duration % 60;
                const durStr = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
                logText = `Outgoing Call (${durStr})`;
            } else if (packet.content === 'busy') {
                icon = '🚫';
                logText = `Outgoing Call (Busy)`;
            } else {
                icon = '📞';
                logText = `Outgoing Call (No Answer)`;
            }
        } else {
            if (packet.content === 'completed') {
                icon = '📞';
                const mins = Math.floor(packet.duration / 60);
                const secs = packet.duration % 60;
                const durStr = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
                logText = `Incoming Call (${durStr})`;
            } else if (packet.content === 'rejected') {
                icon = '🚫';
                logText = `Declined Call`;
            } else if (packet.content === 'busy') {
                icon = '🚫';
                logText = `Missed Call (Busy)`;
            } else {
                icon = '🚫';
                logText = `Missed Call`;
            }
        }
        
        contentHtml = `
        <div class="call-log-bubble d-flex align-items-center gap-2" style="background: rgba(0,0,0,0.15); padding: 8px 12px; border-radius: 8px; font-weight: 500;">
            <span style="font-size: 1.25rem;">${icon}</span>
            <div style="display: flex; flex-direction: column; text-align: left;">
                <span style="color: #f8fafc; font-size: 0.9rem;">${logText}</span>
            </div>
        </div>`;
    }
    
    let statusHtml = '';
    if(isMine && packet.to !== 'All' && packet.type !== 'system' && packet.type !== 'call_log') {
        let sText = packet.status === 'sent' ? '✓' : '✓✓';
        let sColor = packet.status === 'read' ? '#38bdf8' : 'rgba(255,255,255,0.6)';
        statusHtml = `<span id="status-${packet.msg_id}" style="color: ${sColor}; margin-left: 5px; font-size: 0.75rem;"><span class="visually-hidden">Status: ${packet.status}</span>${sText}</span>`;
    }
    
    // Sender name is rendered inline inside message-main-content

    // --- Reactions bar ---
    let reactionsInnerHtml = '';
    if (packet.reactions && packet.reactions !== '{}' && packet.reactions !== 'null') {
        try {
            const _reacts = JSON.parse(packet.reactions);
            const _entries = Object.entries(_reacts).filter(([, u]) => u && u.length > 0);
            if (_entries.length > 0) {
                const _safeToStr = String(packet.to || '').replace(/'/g, "\\'");
                reactionsInnerHtml = _entries.map(([emoji, users]) =>
                    `<button class="reaction-chip ${users.includes(myUsername) ? 'my-reaction' : ''}" onclick="window.reactTo('${packet.msg_id}','${emoji}','${_safeToStr}')" title="${users.join(', ')}">${emoji} <span>${users.length}</span></button>`
                ).join('');
            }
        } catch(e) {}
    }
    
    // Options menu content
    let dropdownItemsHtml = `
        <li><button class="dropdown-item" type="button" onclick="enableSelectionMode('${packet.msg_id}')"><i class="bi bi-check2-square me-2 text-primary"></i> Select (تحديد)</button></li>
    `;
    if (packet.type !== 'call_log' && packet.type !== 'system') {
        dropdownItemsHtml += `<li><button class="dropdown-item" type="button" onclick="window.openReplyTo('${packet.msg_id}')"><i class="bi bi-reply-fill me-2 text-warning"></i> Reply (رد)</button></li>`;
        
        let myReactions = new Set();
        if (packet.reactions && packet.reactions !== '{}' && packet.reactions !== 'null') {
            try {
                const _reacts = JSON.parse(packet.reactions);
                for (const [emoji, users] of Object.entries(_reacts)) {
                    if (users && users.includes(myUsername)) {
                        myReactions.add(emoji);
                    }
                }
            } catch(e) {}
        }
        
        const emojisList = ['👍', '❤️', '😂', '😮', '😢', '😡', '🔥', '👏'];
        let submenuItems = '';
        emojisList.forEach(emoji => {
            const isChecked = myReactions.has(emoji);
            const toEscaped = String(packet.to || '').replace(/'/g, "\\'");
            submenuItems += `
                <li>
                    <button class="dropdown-item d-flex justify-content-between align-items-center" type="button" onclick="window.reactTo('${packet.msg_id}', '${emoji}', '${toEscaped}')">
                        <span>${emoji}</span>
                        <span class="text-success small ms-2">${isChecked ? '✓' : ''}</span>
                    </button>
                </li>
            `;
        });
        
        dropdownItemsHtml += `
        <li class="dropdown-submenu position-relative">
            <button class="dropdown-item dropdown-toggle d-flex justify-content-between align-items-center" type="button">
                <span><i class="bi bi-emoji-smile me-2 text-info"></i> React (تفاعل)</span>
            </button>
            <ul class="dropdown-menu dropdown-menu-dark shadow-lg" style="min-width: 120px;">
                ${submenuItems}
            </ul>
        </li>`;
    }
    if (packet.type !== 'call_log') {
        dropdownItemsHtml += `<li><button class="dropdown-item" type="button" onclick="openForwardModal('${packet.msg_id}')"><i class="bi bi-share me-2 text-success"></i> Forward (توجيه)</button></li>`;
    }
    
    if(packet.type === 'text') {
        dropdownItemsHtml += `<li><button class="dropdown-item" type="button" onclick="copyMessageText('${packet.msg_id}')"><i class="bi bi-clipboard me-2 text-info"></i> Copy (نسخ)</button></li>`;
    }
    if(packet.type === 'file') {
        dropdownItemsHtml += `<li><a class="dropdown-item" href="/api/download/${packet.name}" download="${packet.name}"><i class="bi bi-download me-2 text-info"></i> Save (حفظ)</a></li>`;
    }
    dropdownItemsHtml += `<li><button class="dropdown-item text-danger" type="button" onclick="deleteSingleMessage('${packet.msg_id}')"><i class="bi bi-trash me-2"></i> Delete (حذف)</button></li>`;
    
    return `
    <div class="message-row d-flex align-items-center mb-3" style="width: 100%; justify-content: ${isMine ? 'flex-end' : 'flex-start'}; gap: 10px;">
        <div class="selection-checkbox-container" style="display: ${window.isSelectionMode ? 'block' : 'none'}; order: -1; flex-shrink: 0;">
            <input type="checkbox" class="message-select-checkbox form-check-input" style="width: 22px; height: 22px; cursor: pointer; accent-color: var(--accent);" data-msg-id="${packet.msg_id}" ${window.selectedMessageIds.has(packet.msg_id) ? 'checked' : ''} onchange="onMessageSelectedChange('${packet.msg_id}', this.checked)">
        </div>
        <div class="message-bubble ${isMine ? 'msg-mine' : 'msg-other'} position-relative" id="msg-container-${packet.msg_id}" style="overflow: visible; max-width: 65%;"><div class="message-main-content">${isMine ? '' : `<strong class="message-sender-name" style="color: var(--accent); margin-right: 5px; font-size: 0.95rem;">${packet.sender}:</strong>`}<span class="message-body">${contentHtml}</span><span class="msg-time" style="font-size: 0.7rem; color: rgba(255,255,255,0.6); margin: 0 0 0 8px !important; display: inline-block !important; text-align: left !important; vertical-align: baseline !important;">${packet.time || ''}${statusHtml}</span></div>${replyBubbleHtml}<!-- Context dropdown --><div class="dropdown position-absolute" style="top: 5px; right: 5px; z-index: 5;"><button class="msg-menu-btn btn btn-link text-white p-0" style="opacity: 0; line-height: 1; transition: opacity 0.2s;" type="button" data-bs-toggle="dropdown" aria-expanded="false" aria-label="Message options"><i class="bi bi-three-dots-vertical" style="font-size: 1.1rem;"></i></button><ul class="dropdown-menu dropdown-menu-dark dropdown-menu-end shadow-lg" style="border: 1px solid rgba(255,255,255,0.15); background-color: #1e293b; z-index: 1050;">${dropdownItemsHtml}</ul></div><div id="reactions-${packet.msg_id}" class="reaction-bar-container">${reactionsInnerHtml}</div></div>
    </div>`;
}

async function loadHistory() {
    if (typeof window.disableSelectionMode === 'function') {
        window.disableSelectionMode();
    }
    window.messagesCache = {};
    const res = await fetch(`/api/history?target=${currentTarget}`);
    const data = await res.json();
    const mc = document.getElementById('messages-container');
    if(!mc) return;
    
    if(data.success) {
        let htmlStr = '';
        data.messages.forEach(packet => {
            htmlStr += buildMessageHtml(packet);
        });
        mc.innerHTML = htmlStr;
        mc.scrollTop = mc.scrollHeight;
    } else {
        mc.innerHTML = '';
    }
}
window.loadHistory = loadHistory;

window.appendMessage = function(packet) {
    const mc = document.getElementById('messages-container');
    if(!mc) return;
    const existing = document.getElementById(`msg-container-${packet.msg_id}`);
    if(existing) return; // Prevent duplicate appends!
    
    mc.insertAdjacentHTML('beforeend', buildMessageHtml(packet));
    mc.scrollTop = mc.scrollHeight;

    // Play sound only for the sender's OWN messages (first time only, not on server echo)
    // Sound is played here in appendMessage which is called directly on send (before server echo)
    // The server echo will hit the `if(existing) return` guard above, so sound won't double-fire
    if (packet.sender === myUsername) {
        const sendSound = document.getElementById('sound-receive-private');
        if (sendSound) {
            sendSound.currentTime = 0;
            sendSound.play().catch(e => console.log("Audio play blocked", e));
        }
    }
};


if(document.getElementById('send-btn')) {
    const msgInput = document.getElementById('message-input');
    const sendBtn = document.getElementById('send-btn');
    const voiceBtn = document.getElementById('voice-msg-btn');

    function toggleSendVoiceBtns() {
        if (!msgInput || !sendBtn || !voiceBtn) return;
        if (msgInput.value.trim().length > 0) {
            sendBtn.style.setProperty('display', 'flex', 'important');
            voiceBtn.style.setProperty('display', 'none', 'important');
        } else {
            sendBtn.style.setProperty('display', 'none', 'important');
            voiceBtn.style.setProperty('display', 'flex', 'important');
        }
    }

    // Initialize visibility on page load
    toggleSendVoiceBtns();

    if (msgInput) {
        msgInput.addEventListener('input', toggleSendVoiceBtns);
    }

    document.getElementById('send-btn').onclick = () => {
        const i = document.getElementById('message-input');
        if(!i.value.trim()) return;
        
        const packet = {
            type: 'text',
            to: currentTarget,
            content: i.value,
            time: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}),
            msg_id: crypto.randomUUID(),
            status: 'sent',
            sender: myUsername,
            reply_to: window.currentReplyTo ? window.currentReplyTo.msg_id : null,
            reply_content: window.currentReplyTo ? (window.currentReplyTo.sender + ': ' + window.currentReplyTo.preview) : null,
        };
        
        socket.emit('send_message', packet);
        // Instant visual feedback for sender
        window.appendMessage(packet);
        i.value = '';
        if (window.currentReplyTo) window.cancelReply();
        toggleSendVoiceBtns();
    };

    document.getElementById('message-input').addEventListener('keypress', (e) => {
        if(e.key === 'Enter') {
            document.getElementById('send-btn').click();
            toggleSendVoiceBtns();
        }
    });

    document.getElementById('logout-btn').onclick = async () => {
        await fetch('/auth/logout', {method: 'POST'});
        window.location.href = '/login';
    };

    if(document.getElementById('back-to-sidebar-btn')) {
        document.getElementById('back-to-sidebar-btn').onclick = () => {
            const layout = document.querySelector('.chat-layout');
            if (layout) {
                layout.classList.remove('active-chat');
            }
            if (typeof window.disableSelectionMode === 'function') {
                window.disableSelectionMode();
            }
        };
    }

    document.getElementById('attach-btn').onclick = () => document.getElementById('file-input').click();

    document.getElementById('file-input').onchange = async (e) => {
        const file = e.target.files[0];
        if(!file) return;
        const fd = new FormData();
        fd.append('file', file);
        
        const res = await fetch('/api/upload', {method: 'POST', body: fd});
        const data = await res.json();
        
        if(data.success) {
            const packet = {
                type: 'file',
                to: currentTarget,
                name: data.filename,
                size: data.size,
                time: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}),
                msg_id: crypto.randomUUID(),
                status: 'sent',
                sender: myUsername,
                reply_to: window.currentReplyTo ? window.currentReplyTo.msg_id : null,
                reply_content: window.currentReplyTo ? (window.currentReplyTo.sender + ': ' + window.currentReplyTo.preview) : null,
            };
            socket.emit('send_message', packet);
            window.appendMessage(packet);
            if (window.currentReplyTo) window.cancelReply();
        }
    };
    
    // Stable Voice Recording with Anti-Double-Click Lock
    let mediaRecorder;
    let audioChunks = [];
    let isRecording = false;
    let localStreamRef = null;
    let isStartingRecording = false;

    document.getElementById('voice-msg-btn').onclick = async () => {
        if (isStartingRecording) return;
        
        if (!isRecording) {
            isStartingRecording = true;
            try {
                localStreamRef = await navigator.mediaDevices.getUserMedia({ audio: true });
                mediaRecorder = new MediaRecorder(localStreamRef);
                
                audioChunks = [];
                mediaRecorder.ondataavailable = e => { if(e.data.size > 0) audioChunks.push(e.data); };

                mediaRecorder.onstop = async () => {
                    if(localStreamRef) {
                        localStreamRef.getTracks().forEach(track => track.stop());
                        localStreamRef = null;
                    }
                    
                    if(audioChunks.length === 0) return;
                    
                    const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                    const fd = new FormData();
                    fd.append('file', audioBlob, 'voice_message.webm');
                    
                    const res = await fetch('/api/upload', {method: 'POST', body: fd});
                    const data = await res.json();
                    
                    if(data.success) {
                        const packet = {
                            type: 'file',
                            to: currentTarget,
                            name: data.filename,
                            size: data.size,
                            time: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}),
                            msg_id: crypto.randomUUID(),
                            status: 'sent',
                            sender: myUsername,
                            reply_to: window.currentReplyTo ? window.currentReplyTo.msg_id : null,
                            reply_content: window.currentReplyTo ? (window.currentReplyTo.sender + ': ' + window.currentReplyTo.preview) : null,
                        };
                        socket.emit('send_message', packet);
                        window.appendMessage(packet);
                        if (window.currentReplyTo) window.cancelReply();
                    }
                };
                
                mediaRecorder.start();
                isRecording = true;
                isStartingRecording = false;
                document.getElementById('voice-msg-btn').innerHTML = '⏹️';
                
            } catch(err) {
                isStartingRecording = false;
                alert("Microphone permission denied or hardware is in use.");
                console.error(err);
            }
        } else {
            if(mediaRecorder) mediaRecorder.stop();
            isRecording = false;
            document.getElementById('voice-msg-btn').innerHTML = '🎙️';
        }
    };

    // Emoji Picker Panel Logic
    const emojiBtn = document.getElementById('emoji-btn');
    const emojiPicker = document.getElementById('emoji-picker-container');
    
    if (emojiBtn && emojiPicker) {
        emojiBtn.onclick = (e) => {
            e.stopPropagation();
            if (emojiPicker.style.display === 'none') {
                emojiPicker.style.display = 'flex';
                setTimeout(() => {
                    document.addEventListener('click', closeEmojiPickerOutside);
                }, 10);
            } else {
                emojiPicker.style.display = 'none';
                document.removeEventListener('click', closeEmojiPickerOutside);
            }
        };
    }
    
    function closeEmojiPickerOutside(e) {
        if (emojiPicker && !emojiPicker.contains(e.target) && e.target !== emojiBtn) {
            emojiPicker.style.display = 'none';
            document.removeEventListener('click', closeEmojiPickerOutside);
        }
    }
    
    // Tab switching inside Emoji Picker
    const tabBtns = document.querySelectorAll('.emoji-tab-btn');
    tabBtns.forEach(btn => {
        btn.onclick = () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            const cat = btn.getAttribute('data-category');
            const categories = document.querySelectorAll('.emoji-category');
            categories.forEach(c => {
                if (c.id === `cat-${cat}`) {
                    c.classList.remove('d-none');
                } else {
                    c.classList.add('d-none');
                }
            });
        };
    });
    
    // Emoji selection
    const emojiGridItems = document.querySelectorAll('.emoji-item');
    emojiGridItems.forEach(item => {
        item.onclick = (e) => {
            const emoji = item.innerText;
            if (msgInput) {
                const startPos = msgInput.selectionStart;
                const endPos = msgInput.selectionEnd;
                const beforeText = msgInput.value.substring(0, startPos);
                const afterText = msgInput.value.substring(endPos);
                msgInput.value = beforeText + emoji + afterText;
                msgInput.selectionStart = msgInput.selectionEnd = startPos + emoji.length;
                msgInput.focus();
                
                // Update send/voice visibility
                toggleSendVoiceBtns();
            }
        };
    });
}

// --- MESSAGE ACTIONS & SELECTION HELPERS ---

window.copyMessageText = function(msgId) {
    const m = window.messagesCache[msgId];
    if (!m) return;
    
    let textToCopy = '';
    if (m.type === 'text') {
        textToCopy = m.content;
    } else if (m.type === 'file') {
        textToCopy = window.location.origin + `/api/download/${m.name}`;
    }
    
    if (textToCopy) {
        navigator.clipboard.writeText(textToCopy).then(() => {
            showToast("Copied to clipboard!");
        }).catch(err => {
            console.error("Failed to copy:", err);
        });
    }
};

window.deleteSingleMessage = function(msgId) {
    const m = window.messagesCache[msgId];
    if (!m) return;
    
    window.activeDeleteId = msgId;
    window.activeDeleteIds = null;
    
    const isMine = m.sender === myUsername;
    const modalText = document.getElementById('delete-confirm-text');
    const deleteMeBtn = document.getElementById('btn-delete-me-only');
    const deleteEveryoneBtn = document.getElementById('btn-delete-everyone');
    
    if (isMine) {
        modalText.innerText = "How do you want to delete this message?";
        if (deleteEveryoneBtn) deleteEveryoneBtn.style.display = 'inline-block';
    } else {
        modalText.innerText = "This message was sent by someone else. You can only delete it for yourself.";
        if (deleteEveryoneBtn) deleteEveryoneBtn.style.display = 'none';
    }
    
    // Set up click handlers for confirmation
    if (deleteMeBtn) {
        deleteMeBtn.onclick = () => window.confirmDelete('me');
    }
    if (deleteEveryoneBtn) {
        deleteEveryoneBtn.onclick = () => window.confirmDelete('everyone');
    }
    
    const deleteModal = new bootstrap.Modal(document.getElementById('deleteConfirmModal'));
    deleteModal.show();
};

window.confirmDelete = function(deleteType) {
    const deleteModalEl = document.getElementById('deleteConfirmModal');
    const deleteModal = bootstrap.Modal.getInstance(deleteModalEl);
    
    if (window.activeDeleteId) {
        socket.emit('delete_message', {
            msg_id: window.activeDeleteId,
            to: currentTarget,
            delete_type: deleteType
        });
        window.activeDeleteId = null;
    } else if (window.activeDeleteIds) {
        window.activeDeleteIds.forEach(id => {
            const m = window.messagesCache[id];
            const type = (deleteType === 'everyone' && m && m.sender === myUsername) ? 'everyone' : 'me';
            socket.emit('delete_message', {
                msg_id: id,
                to: currentTarget,
                delete_type: type
            });
        });
        window.activeDeleteIds = null;
        window.disableSelectionMode();
    }
    
    if (deleteModal) deleteModal.hide();
};

window.openForwardModal = function(msgId) {
    window.activeForwardId = msgId;
    window.activeForwardIds = null;
    
    populateForwardTargets();
    const fModal = new bootstrap.Modal(document.getElementById('forwardModal'));
    fModal.show();
};

window.enableSelectionMode = function(msgId) {
    window.isSelectionMode = true;
    window.selectedMessageIds = new Set();
    if (msgId) {
        window.selectedMessageIds.add(msgId);
    }
    
    // Show checkbox containers
    document.querySelectorAll('.selection-checkbox-container').forEach(el => {
        el.style.display = 'block';
    });
    
    // Sync checkboxes
    document.querySelectorAll('.message-select-checkbox').forEach(chk => {
        const id = chk.getAttribute('data-msg-id');
        chk.checked = window.selectedMessageIds.has(id);
    });
    
    // Show selection bar
    const bar = document.getElementById('selection-bar');
    if (bar) bar.style.display = 'flex';
    
    // Hide footer
    const footer = document.querySelector('.chat-footer');
    if (footer) footer.style.display = 'none';
    
    updateSelectionUI();
};

window.disableSelectionMode = function() {
    window.isSelectionMode = false;
    window.selectedMessageIds = new Set();
    
    // Hide checkbox containers
    document.querySelectorAll('.selection-checkbox-container').forEach(el => {
        el.style.display = 'none';
    });
    
    // Uncheck and reset row highlights
    document.querySelectorAll('.message-select-checkbox').forEach(chk => {
        chk.checked = false;
        const row = chk.closest('.message-row');
        if (row) {
            row.style.background = 'transparent';
        }
    });
    
    // Hide selection bar
    const bar = document.getElementById('selection-bar');
    if (bar) bar.style.display = 'none';
    
    // Show footer
    const footer = document.querySelector('.chat-footer');
    if (footer) footer.style.display = 'flex';
};

window.onMessageSelectedChange = function(msgId, isChecked) {
    if (isChecked) {
        window.selectedMessageIds.add(msgId);
    } else {
        window.selectedMessageIds.delete(msgId);
    }
    
    const el = document.getElementById(`msg-container-${msgId}`);
    if (el) {
        const row = el.closest('.message-row');
        if (row) {
            row.style.background = isChecked ? 'rgba(59, 130, 246, 0.15)' : 'transparent';
        }
    }
    
    updateSelectionUI();
};

function updateSelectionUI() {
    const countEl = document.getElementById('selection-count');
    if (countEl) {
        countEl.innerText = `${window.selectedMessageIds.size} selected`;
    }
    
    const totalCheckboxes = document.querySelectorAll('.message-select-checkbox').length;
    const selectedCount = window.selectedMessageIds.size;
    
    const selectAllBtn = document.getElementById('btn-select-all');
    const deselectAllBtn = document.getElementById('btn-deselect-all');
    
    if (selectedCount === totalCheckboxes && totalCheckboxes > 0) {
        if (selectAllBtn) selectAllBtn.style.display = 'none';
        if (deselectAllBtn) deselectAllBtn.style.display = 'inline-block';
    } else {
        if (selectAllBtn) selectAllBtn.style.display = 'inline-block';
        if (deselectAllBtn) deselectAllBtn.style.display = 'none';
    }
}
window.updateSelectionUI = updateSelectionUI;


window.selectAllMessages = function() {
    window.selectedMessageIds = new Set();
    document.querySelectorAll('.message-select-checkbox').forEach(chk => {
        const id = chk.getAttribute('data-msg-id');
        chk.checked = true;
        window.selectedMessageIds.add(id);
        const row = chk.closest('.message-row');
        if (row) {
            row.style.background = 'rgba(59, 130, 246, 0.15)';
        }
    });
    updateSelectionUI();
};

window.deselectAllMessages = function() {
    window.selectedMessageIds = new Set();
    document.querySelectorAll('.message-select-checkbox').forEach(chk => {
        chk.checked = false;
        const row = chk.closest('.message-row');
        if (row) {
            row.style.background = 'transparent';
        }
    });
    updateSelectionUI();
};

window.copySelectedMessages = function() {
    if (window.selectedMessageIds.size === 0) return;
    const textArr = [];
    window.selectedMessageIds.forEach(id => {
        const m = window.messagesCache[id];
        if (m && m.type === 'text') {
            textArr.push(`${m.sender}: ${m.content}`);
        }
    });
    if (textArr.length === 0) {
        alert("No text messages selected to copy!");
        return;
    }
    const text = textArr.join('\n');
    navigator.clipboard.writeText(text).then(() => {
        showToast("Selected messages copied!");
        window.disableSelectionMode();
    });
};

window.deleteSelectedMessages = function() {
    if (window.selectedMessageIds.size === 0) return;
    
    let hasOwnMessages = false;
    window.selectedMessageIds.forEach(id => {
        const m = window.messagesCache[id];
        if (m && m.sender === myUsername) {
            hasOwnMessages = true;
        }
    });
    
    window.activeDeleteId = null;
    window.activeDeleteIds = Array.from(window.selectedMessageIds);
    
    const modalText = document.getElementById('delete-confirm-text');
    const deleteMeBtn = document.getElementById('btn-delete-me-only');
    const deleteEveryoneBtn = document.getElementById('btn-delete-everyone');
    
    if (hasOwnMessages) {
        modalText.innerText = `You have selected ${window.activeDeleteIds.length} message(s), some of which you sent. How do you want to delete them? (Received messages will always be deleted for you only).`;
        if (deleteEveryoneBtn) deleteEveryoneBtn.style.display = 'inline-block';
    } else {
        modalText.innerText = `Delete these ${window.activeDeleteIds.length} selected message(s) for yourself?`;
        if (deleteEveryoneBtn) deleteEveryoneBtn.style.display = 'none';
    }
    
    if (deleteMeBtn) {
        deleteMeBtn.onclick = () => window.confirmDelete('me');
    }
    if (deleteEveryoneBtn) {
        deleteEveryoneBtn.onclick = () => window.confirmDelete('everyone');
    }
    
    const deleteModal = new bootstrap.Modal(document.getElementById('deleteConfirmModal'));
    deleteModal.show();
};

window.openForwardModalForSelected = function() {
    if (window.selectedMessageIds.size === 0) return;
    window.activeForwardId = null;
    window.activeForwardIds = Array.from(window.selectedMessageIds);
    
    populateForwardTargets();
    const fModal = new bootstrap.Modal(document.getElementById('forwardModal'));
    fModal.show();
};

window.forwardMessagesToTarget = function(targetUser) {
    const fModalEl = document.getElementById('forwardModal');
    const fModal = bootstrap.Modal.getInstance(fModalEl);
    
    let idsToForward = [];
    if (window.activeForwardId) {
        idsToForward = [window.activeForwardId];
        window.activeForwardId = null;
    } else if (window.activeForwardIds) {
        idsToForward = window.activeForwardIds;
        window.activeForwardIds = null;
        window.disableSelectionMode();
    }
    
    idsToForward.forEach(id => {
        const original = window.messagesCache[id];
        if (!original) return;
        
        const packet = {
            type: original.type,
            to: targetUser,
            content: original.content || '',
            name: original.name || '',
            size: original.size || '',
            data: original.data || '',
            time: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}),
            msg_id: crypto.randomUUID(),
            status: 'sent',
            sender: myUsername
        };
        
        socket.emit('send_message', packet);
        if (targetUser === currentTarget) {
            window.appendMessage(packet);
        }
    });
    
    if (fModal) fModal.hide();
    showToast("Messages forwarded!");
};

function populateForwardTargets() {
    const listEl = document.getElementById('forward-targets-list');
    if (!listEl) return;
    listEl.innerHTML = '';
    
    // Broadcast Room
    const allItem = document.createElement('button');
    allItem.className = 'list-group-item list-group-item-action bg-dark text-white border-secondary d-flex align-items-center justify-content-between py-3';
    allItem.innerHTML = '<span>📢 Broadcast Room</span><span class="btn btn-sm btn-primary">Select</span>';
    allItem.onclick = () => window.forwardMessagesToTarget('All');
    listEl.appendChild(allItem);
    
    // Active Users
    if (window.allUsersList) {
        window.allUsersList.forEach(u => {
            if (u.name === myUsername) return;
            const item = document.createElement('button');
            item.className = 'list-group-item list-group-item-action bg-dark text-white border-secondary d-flex align-items-center justify-content-between py-2';
            
            const statusDot = `<span class="badge ${u.status === 'Available' ? 'bg-success' : 'bg-secondary'} rounded-pill me-2">${u.status === 'Available' ? 'Online' : 'Offline'}</span>`;
            item.innerHTML = `
                <div>
                    <strong>${u.name}</strong>
                    <div style="font-size: 0.75rem; color: #94a3b8;">${statusDot}</div>
                </div>
                <span class="btn btn-sm btn-primary">Select</span>
            `;
            item.onclick = () => window.forwardMessagesToTarget(u.name);
            listEl.appendChild(item);
        });
    }
}

function showToast(message) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    
    const toastId = 'toast-' + Date.now();
    const html = `
    <div id="${toastId}" class="toast align-items-center text-white bg-success border-0 shadow-lg" role="alert" aria-live="assertive" aria-atomic="true" style="backdrop-filter: blur(10px); background-color: rgba(25, 135, 84, 0.9) !important;">
        <div class="d-flex">
            <div class="toast-body">
                <i class="bi bi-info-circle me-2"></i> ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    </div>`;
    
    container.insertAdjacentHTML('beforeend', html);
    const toastEl = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastEl, { delay: 2500 });
    toast.show();
    
    toastEl.addEventListener('hidden.bs.toast', () => {
        toastEl.remove();
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// REPLY HELPERS
// ─────────────────────────────────────────────────────────────────────────────

/** Open reply mode: show the preview bar and store the reference */
window.openReplyTo = function(msgId) {
    const m = window.messagesCache[msgId];
    if (!m) return;
    const preview = m.type === 'text'
        ? (m.content || '').substring(0, 120)
        : '📎 Attachment';
    window.currentReplyTo = { msg_id: msgId, sender: m.sender, preview };
    const senderEl = document.getElementById('reply-preview-sender');
    const textEl   = document.getElementById('reply-preview-text');
    const bar      = document.getElementById('reply-preview-bar');
    if (senderEl) senderEl.innerText = m.sender;
    if (textEl)   textEl.innerText   = preview;
    if (bar)      bar.style.display  = 'flex';
    const input = document.getElementById('message-input');
    if (input) input.focus();
};

/** Cancel reply mode */
window.cancelReply = function() {
    window.currentReplyTo = null;
    const bar = document.getElementById('reply-preview-bar');
    if (bar) bar.style.display = 'none';
};

/** Scroll to and flash-highlight a message by its msg_id */
window.scrollToMsg = function(msgId) {
    const el = document.getElementById('msg-container-' + msgId);
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.remove('highlight-flash');
    // Force reflow to restart animation
    void el.offsetWidth;
    el.classList.add('highlight-flash');
    setTimeout(() => el.classList.remove('highlight-flash'), 1900);
};

// ─────────────────────────────────────────────────────────────────────────────
// REACTION HELPERS
// ─────────────────────────────────────────────────────────────────────────────

/** Show or reposition the floating reaction emoji picker near a message */
/** Called by clicking an existing reaction chip on a message */
window.reactTo = function(msgId, emoji, to) {
    socket.emit('reaction', { msg_id: msgId, emoji: emoji, to: to });
};

/** Live-update the reaction bar for a specific message (called on reaction_update event) */
window.applyReactions = function(msgId, reactionsJson) {
    // Update cache
    const cached = window.messagesCache[msgId];
    if (cached) cached.reactions = reactionsJson;

    const container = document.getElementById('reactions-' + msgId);
    if (!container) return;

    let innerHtml = '';
    try {
        const reacts  = JSON.parse(reactionsJson || '{}');
        const entries = Object.entries(reacts).filter(([, u]) => u && u.length > 0);
        if (entries.length > 0) {
            const _to = cached ? String(cached.to || '').replace(/'/g, "\\'") : currentTarget;
            innerHtml = entries.map(([emoji, users]) =>
                `<button class="reaction-chip ${users.includes(myUsername) ? 'my-reaction' : ''}" onclick="window.reactTo('${msgId}','${emoji}','${_to}')" title="${users.join(', ')}">${emoji} <span>${users.length}</span></button>`
            ).join('');
        }
    } catch(e) { console.error('applyReactions error:', e); }

    container.innerHTML = innerHtml;
};

// ─────────────────────────────────────────────────────────────────────────────
// GROUPS MANAGEMENT LOGIC
// ─────────────────────────────────────────────────────────────────────────────

// Binding group creation trigger (shows inline screen above footer, like calls)
if (document.getElementById('btn-create-group-modal')) {
    document.getElementById('btn-create-group-modal').onclick = () => {
        try {
            const nameInput = document.getElementById('create-group-name');
            const descInput = document.getElementById('create-group-desc');
            if (nameInput) nameInput.value = '';
            if (descInput) descInput.value = '';
            
            // Hide the footer
            const footer = document.querySelector('.chat-footer');
            if (footer) {
                footer.style.display = 'none';
            }
            
            // Populate members selection list
            const usersListEl = document.getElementById('create-group-users-list');
            if (usersListEl) {
                usersListEl.innerHTML = '';
                const users = window.allUsersList || [];
                const currentMyUsername = window.myUsername || (typeof myUsername !== 'undefined' ? myUsername : '');
                
                if (users.length > 0) {
                    users.forEach(u => {
                        if (u.name === currentMyUsername) return;
                        
                        const labelId = `chk-user-${u.name}`;
                        const isOnline = u.status === 'Available';
                        const statusBadge = `<span class="badge ${isOnline ? 'bg-success' : 'bg-secondary'} rounded-pill ms-2" style="font-size: 0.7rem;">${isOnline ? 'Online' : 'Offline'}</span>`;
                        
                        const item = document.createElement('div');
                        item.className = 'list-group-item d-flex align-items-center justify-content-between bg-dark text-white border-secondary py-2 px-3';
                        item.innerHTML = `
                            <div class="d-flex align-items-center" style="width: 100%;">
                                <input class="form-check-input create-group-user-checkbox me-2" type="checkbox" value="${u.name}" id="${labelId}" style="width: 18px; height: 18px; cursor: pointer; accent-color: var(--accent);">
                                <label class="form-check-label text-white flex-grow-1" for="${labelId}" style="cursor: pointer; font-weight: 500;">
                                    👤 ${u.name} ${statusBadge}
                                </label>
                            </div>
                        `;
                        usersListEl.appendChild(item);
                    });
                } else {
                    usersListEl.innerHTML = '<div class="text-muted p-2 small text-center">No other users available</div>';
                }
            }
            
            // Show the banner
            const createScreen = document.getElementById('create-group-screen');
            if (createScreen) {
                createScreen.classList.remove('d-none');
                createScreen.style.display = 'flex';
                createScreen.focus(); // Focus for NVDA screen reader
            }
            
            // Ensure chat container is visible on mobile
            const layout = document.querySelector('.chat-layout');
            if (layout) {
                layout.classList.add('active-chat');
            }
        } catch (err) {
            console.error("Error showing group creation screen:", err);
            // Restore footer
            const footer = document.querySelector('.chat-footer');
            if (footer) {
                footer.style.display = 'flex';
            }
            alert("Error: " + err.message);
        }
    };
}

// Cancel group creation
if (document.getElementById('btn-cancel-create-group')) {
    document.getElementById('btn-cancel-create-group').onclick = () => {
        const createScreen = document.getElementById('create-group-screen');
        const footer = document.querySelector('.chat-footer');
        
        if (createScreen) {
            createScreen.style.display = 'none';
            createScreen.classList.add('d-none');
        }
        if (footer) {
            footer.style.display = 'flex';
        }
        
        // Return focus to active chat title for screen reader
        const cTitle = document.getElementById('current-chat-title');
        if (cTitle) {
            cTitle.focus();
        }
    };
}

// Confirming group creation
if (document.getElementById('btn-submit-create-group')) {
    document.getElementById('btn-submit-create-group').onclick = async () => {
        const nameInput = document.getElementById('create-group-name');
        const descInput = document.getElementById('create-group-desc');
        const name = nameInput ? nameInput.value.trim() : '';
        const desc = descInput ? descInput.value.trim() : '';
        
        if (!name) {
            alert("Group name cannot be empty!");
            return;
        }
        
        // Get selected members
        const checkboxes = document.querySelectorAll('.create-group-user-checkbox:checked');
        const selectedMembers = Array.from(checkboxes).map(chk => chk.value);
        
        if (!confirm(`Are you sure you want to create group "${name}"?`)) {
            return;
        }
        
        try {
            const res = await fetch('/api/groups/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name, description: desc, members: selectedMembers })
            });
            const data = await res.json();
            if (data.success) {
                if (nameInput) nameInput.value = '';
                if (descInput) descInput.value = '';
                
                const createScreen = document.getElementById('create-group-screen');
                const footer = document.querySelector('.chat-footer');
                if (createScreen) {
                    createScreen.style.display = 'none';
                    createScreen.classList.add('d-none');
                }
                if (footer) {
                    footer.style.display = 'flex';
                }
                
                showToast("Group created successfully!");
                if (typeof window.loadGroupsList === 'function') {
                    await window.loadGroupsList();
                }
                
                // Automatically open the newly created group chat!
                const item = document.querySelector(`.user-item[data-target="${name}"]`);
                if (item && typeof window.selectGroup === 'function') {
                    window.selectGroup(name, item);
                } else {
                    window.selectUser('All');
                }
                
                // Return focus to active chat title for screen reader
                const cTitle = document.getElementById('current-chat-title');
                if (cTitle) {
                    cTitle.focus();
                }
            } else {
                alert("Error: " + data.error);
            }
        } catch(e) {
            console.error(e);
            alert("Failed to create group.");
        }
    };
}

// Request to join group
window.requestJoinGroup = async function(groupName) {
    if (!confirm(`Do you want to request to join group "${groupName}"?`)) return;
    
    try {
        const res = await fetch('/api/groups/request_join', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_name: groupName })
        });
        const data = await res.json();
        if (data.success) {
            showToast("Join request sent successfully!");
            if (typeof window.loadGroupsList === 'function') {
                window.loadGroupsList();
            }
            if (currentTarget === groupName && typeof window.selectGroup === 'function') {
                const item = document.querySelector(`.user-item[data-target="${groupName}"]`);
                window.selectGroup(groupName, item);
            }
        } else {
            alert("Error: " + data.error);
        }
    } catch(e) {
        console.error(e);
    }
};

// Accept group invitation
window.acceptGroupInvite = async function(groupName, skipConfirm = false) {
    if (!skipConfirm && !confirm(`Do you want to accept the invitation to join "${groupName}"?`)) return;
    
    try {
        const res = await fetch('/api/groups/invite/respond', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_name: groupName, action: 'accept' })
        });
        const data = await res.json();
        if (data.success) {
            showToast("Invitation accepted!");
            if (typeof window.loadGroupsList === 'function') {
                await window.loadGroupsList();
            }
            if (currentTarget === groupName && typeof window.selectGroup === 'function') {
                const item = document.querySelector(`.user-item[data-target="${groupName}"]`);
                window.selectGroup(groupName, item);
            }
        } else {
            alert("Error: " + data.error);
        }
    } catch(e) {
        console.error(e);
    }
};

// Reject group invitation
window.rejectGroupInvite = async function(groupName, skipConfirm = false) {
    if (!skipConfirm && !confirm(`Do you want to reject the invitation to join "${groupName}"?`)) return;
    
    try {
        const res = await fetch('/api/groups/invite/respond', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_name: groupName, action: 'reject' })
        });
        const data = await res.json();
        if (data.success) {
            showToast("Invitation rejected.");
            if (typeof window.loadGroupsList === 'function') {
                await window.loadGroupsList();
            }
            if (currentTarget === groupName && typeof window.selectGroup === 'function') {
                const item = document.querySelector(`.user-item[data-target="${groupName}"]`);
                window.selectGroup(groupName, item);
            }
        } else {
            alert("Error: " + data.error);
        }
    } catch(e) {
        console.error(e);
    }
};

// Preview Invitation (Offline case button in list)
window.previewInvite = function(groupName) {
    if (confirm(`You have a pending invitation to join group "${groupName}". Accept? (Press Cancel to reject)`)) {
        window.acceptGroupInvite(groupName);
    } else {
        if (confirm(`Do you want to reject the invitation to join group "${groupName}"?`)) {
            window.rejectGroupInvite(groupName);
        }
    }
};

// Load Group Administration Panels Data
window.loadGroupAdminData = async function(groupName) {
    const group = window.allGroupsList.find(item => item.name === groupName);
    if (!group || !group.is_owner) return;
    
    // Fetch pending join requests
    try {
        const resReq = await fetch(`/api/groups/requests?group_name=${groupName}`);
        const dataReq = await resReq.json();
        const reqList = document.getElementById('group-requests-list');
        if (reqList && dataReq.success) {
            reqList.innerHTML = '';
            if (dataReq.requests.length === 0) {
                reqList.innerHTML = '<div class="small text-muted p-1">No requests</div>';
            } else {
                dataReq.requests.forEach(username => {
                    const item = document.createElement('div');
                    item.className = 'list-group-item bg-dark text-white border-secondary d-flex align-items-center justify-content-between p-1';
                    item.innerHTML = `
                        <span class="small">${username}</span>
                        <div>
                            <button class="btn btn-xs btn-success py-0 px-1" onclick="window.respondToJoinRequest('${groupName}', '${username}', 'accept')" style="font-size:0.75rem;">Accept</button>
                            <button class="btn btn-xs btn-danger py-0 px-1" onclick="window.respondToJoinRequest('${groupName}', '${username}', 'reject')" style="font-size:0.75rem;">Reject</button>
                        </div>
                    `;
                    reqList.appendChild(item);
                });
            }
        }
    } catch(e) {
        console.error(e);
    }
    
    // Fetch members list
    try {
        const resMem = await fetch(`/api/groups/members?group_name=${groupName}`);
        const dataMem = await resMem.json();
        const memList = document.getElementById('group-members-list');
        if (memList && dataMem.success) {
            window.currentGroupMembers = dataMem.members || [];
            memList.innerHTML = '';
            dataMem.members.forEach(username => {
                const item = document.createElement('div');
                item.className = 'list-group-item bg-dark text-white border-secondary d-flex align-items-center justify-content-between p-1';
                
                let kickBtnHtml = '';
                if (username !== group.owner) {
                    kickBtnHtml = `<button class="btn btn-xs btn-danger py-0 px-1" onclick="window.kickGroupMember('${groupName}', '${username}')" style="font-size:0.75rem;">Kick</button>`;
                } else {
                    kickBtnHtml = `<span class="badge bg-info text-dark" style="font-size:0.7rem;">Owner</span>`;
                }
                
                item.innerHTML = `
                    <span class="small">${username}</span>
                    ${kickBtnHtml}
                `;
                memList.appendChild(item);
            });
        }
    } catch(e) {
        console.error(e);
    }
};

// Accept/Reject Join Request
window.respondToJoinRequest = async function(groupName, username, action) {
    if (!confirm(`Are you sure you want to ${action} ${username}'s request to join?`)) return;
    
    try {
        const res = await fetch('/api/groups/requests/respond', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_name: groupName, username: username, action: action })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Join request ${action}ed.`);
            window.loadGroupAdminData(groupName);
        } else {
            alert("Error: " + data.error);
        }
    } catch(e) {
        console.error(e);
    }
};

// Kick group member
window.kickGroupMember = async function(groupName, username) {
    if (!confirm(`Are you sure you want to kick "${username}" from this group?`)) return;
    
    try {
        const res = await fetch('/api/groups/kick', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_name: groupName, username: username })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`${username} was kicked.`);
            window.loadGroupAdminData(groupName);
        } else {
            alert("Error: " + data.error);
        }
    } catch(e) {
        console.error(e);
    }
};

// Owner delete group
if (document.getElementById('btn-delete-group')) {
    document.getElementById('btn-delete-group').onclick = async () => {
        const groupName = currentTarget;
        if (!groupName || groupName === 'All') return;
        
        if (!confirm(`WARNING: Are you sure you want to delete group "${groupName}"? All messages will be permanently deleted.`)) return;
        
        try {
            const res = await fetch('/api/groups/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ group_name: groupName })
            });
            const data = await res.json();
            if (data.success) {
                showToast("Group deleted.");
                if (typeof window.loadGroupsList === 'function') {
                    await window.loadGroupsList();
                }
                window.selectUser('All');
            } else {
                alert("Error: " + data.error);
            }
        } catch(e) {
            console.error(e);
        }
    };
}

// Member leave group
if (document.getElementById('leave-group-btn')) {
    document.getElementById('leave-group-btn').onclick = async () => {
        const groupName = currentTarget;
        if (!groupName || groupName === 'All') return;
        
        if (!confirm(`Are you sure you want to leave the group "${groupName}"?`)) return;
        
        try {
            const res = await fetch('/api/groups/leave', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ group_name: groupName })
            });
            const data = await res.json();
            if (data.success) {
                showToast("You left the group.");
                if (typeof window.loadGroupsList === 'function') {
                    await window.loadGroupsList();
                }
                window.selectUser('All');
            } else {
                alert("Error: " + data.error);
            }
        } catch(e) {
            console.error(e);
        }
    };
}

// Open Choose Users Modal for Group Invitation
if (document.getElementById('btn-open-invite-modal')) {
    document.getElementById('btn-open-invite-modal').onclick = () => {
        try {
            const listEl = document.getElementById('invite-members-modal-list');
            if (!listEl) return;
            
            listEl.innerHTML = '';
            const members = window.currentGroupMembers || [];
            const nonMembers = (window.allUsersList || []).filter(u => !members.includes(u.name) && u.name !== window.myUsername);
            
            if (nonMembers.length === 0) {
                listEl.innerHTML = '<div class="text-muted p-2 small text-center">All users are already members of this group.</div>';
            } else {
                nonMembers.forEach(u => {
                    const labelId = `invite-chk-user-${u.name}`;
                    const isOnline = u.status === 'Available';
                    const statusBadge = `<span class="badge ${isOnline ? 'bg-success' : 'bg-secondary'} rounded-pill ms-2" style="font-size: 0.7rem;">${isOnline ? 'Online' : 'Offline'}</span>`;
                    
                    const item = document.createElement('div');
                    item.className = 'list-group-item d-flex align-items-center justify-content-between bg-dark text-white border-secondary py-2 px-3';
                    item.innerHTML = `
                        <div class="d-flex align-items-center" style="width: 100%;">
                            <input class="form-check-input invite-member-checkbox me-2" type="checkbox" value="${u.name}" id="${labelId}" style="width: 18px; height: 18px; cursor: pointer; accent-color: var(--accent);">
                            <label class="form-check-label text-white flex-grow-1" for="${labelId}" style="cursor: pointer; font-weight: 500;">
                                👤 ${u.name} ${statusBadge}
                            </label>
                        </div>
                    `;
                    listEl.appendChild(item);
                });
            }
            
            const nameEl = document.getElementById('invite-group-modal-name');
            if (nameEl) nameEl.innerText = currentTarget;
            
            const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('groupInviteMembersModal'));
            modal.show();
        } catch (e) {
            console.error("Error opening invite modal:", e);
        }
    };
}

// Submit Batch Invitations
if (document.getElementById('btn-submit-invites')) {
    document.getElementById('btn-submit-invites').onclick = async () => {
        const checkboxes = document.querySelectorAll('.invite-member-checkbox:checked');
        const selectedUsers = Array.from(checkboxes).map(chk => chk.value);
        if (selectedUsers.length === 0) {
            alert("Please select at least one user to invite!");
            return;
        }
        
        try {
            const res = await fetch('/api/groups/invite', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ group_name: currentTarget, usernames: selectedUsers })
            });
            const data = await res.json();
            if (data.success) {
                showToast("Invitations sent successfully!");
                const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('groupInviteMembersModal'));
                modal.hide();
                if (typeof window.loadGroupAdminData === 'function') {
                    window.loadGroupAdminData(currentTarget);
                }
            } else {
                alert("Error: " + data.error);
            }
        } catch(e) {
            console.error("Error sending invites:", e);
            alert("Error: " + e.message);
        }
    };
}

// Real-time Sidebar Search Filter (Real Search)
if (document.getElementById('user-search-input')) {
    document.getElementById('user-search-input').oninput = function() {
        const query = this.value.toLowerCase().trim();
        
        // Filter rooms list
        document.querySelectorAll('#rooms-list .user-item').forEach(item => {
            const target = item.getAttribute('data-target') || '';
            const text = item.textContent.toLowerCase();
            if (text.includes(query) || target.toLowerCase().includes(query)) {
                item.style.setProperty('display', 'flex', 'important');
            } else {
                item.style.setProperty('display', 'none', 'important');
            }
        });
        
        // Filter users list
        document.querySelectorAll('#users-list .user-item').forEach(item => {
            const target = item.getAttribute('data-target') || '';
            const text = item.textContent.toLowerCase();
            if (text.includes(query) || target.toLowerCase().includes(query)) {
                item.style.setProperty('display', 'flex', 'important');
            } else {
                item.style.setProperty('display', 'none', 'important');
            }
        });
    };
}

