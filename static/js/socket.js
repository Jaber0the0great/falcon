const socket = io();
let myUsername = '';
let currentTarget = 'All';

function statusPriority(status) {
    if (status === 'Available' || status === 'Online') return 4;
    if (status === 'Busy') return 3;
    if (status === 'Away') return 2;
    return 1;
}

function statusDotClass(status) {
    if (status === 'Available' || status === 'Online') return 'online';
    if (status === 'Busy') return 'busy';
    if (status === 'Away') return 'away';
    return 'offline';
}

function statusDisplayText(status) {
    if (status === 'Available' || status === 'Online') return 'Online';
    if (status === 'Busy') return 'Busy';
    if (status === 'Away') return 'Away';
    return 'Offline';
}

function statusDisplayColor(status) {
    if (status === 'Available' || status === 'Online') return '#22c55e';
    if (status === 'Busy') return '#f97316';
    if (status === 'Away') return '#eab308';
    return '#64748b';
}

function formatLastSeenRelative(isoStr) {
    if(!isoStr) return 'Never';
    try {
        let cleanStr = isoStr;
        if (typeof cleanStr === 'string' && !cleanStr.endsWith('Z') && !cleanStr.includes('+') && !cleanStr.includes('-')) {
            cleanStr += 'Z';
        }
        const date = new Date(cleanStr);
        if(isNaN(date.getTime())) return 'Never';
        
        const now = new Date();
        const diffMs = now.getTime() - date.getTime();
        const diffSec = Math.floor(diffMs / 1000);
        
        const dateZero = new Date(date.getFullYear(), date.getMonth(), date.getDate());
        const nowZero = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const diffDays = Math.floor((nowZero.getTime() - dateZero.getTime()) / (1000 * 60 * 60 * 24));
        
        const timeStr = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
        
        if (diffDays === 0) {
            return `Today at ${timeStr}`;
        }
        
        if (diffDays === 1) {
            return `Yesterday at ${timeStr}`;
        }
        if (diffDays < 7) {
            return `${date.toLocaleDateString(undefined, { weekday: 'long' })} at ${timeStr}`;
        }
        return `${date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })} at ${timeStr}`;
    } catch(e) {
        return 'Never';
    }
}

function lastSeenTooltip(isoStr) {
    if(!isoStr) return '';
    try {
        let cleanStr = isoStr;
        if (typeof cleanStr === 'string' && !cleanStr.endsWith('Z') && !cleanStr.includes('+') && !cleanStr.includes('-')) {
            cleanStr += 'Z';
        }
        const date = new Date(cleanStr);
        if(isNaN(date.getTime())) return '';
        return date.toLocaleString(undefined, {
            year: 'numeric', month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
    } catch(e) {
        return '';
    }
}

window.selectUser = function(targetName, element) {
    // Stop typing for previous conversation
    stopTypingForCurrent();
    // Hide any incoming typing indicator
    const typingEl = document.getElementById('typing-indicator');
    if (typingEl) { typingEl.classList.add('hidden'); typingEl.style.display = ''; }
    if (_typingTimeout) clearTimeout(_typingTimeout);
    _shownTypingUser = null;

    document.querySelectorAll('.user-item').forEach(el => el.classList.remove('active'));
    if(element) element.classList.add('active');
    
    currentTarget = targetName;
    const cTitle = document.getElementById('current-chat-title');
    if(cTitle) cTitle.innerText = targetName === 'All' ? '📢 Broadcast Room' : targetName;
    
    const vcBtn = document.getElementById('voice-call-btn');
    const vidBtn = document.getElementById('video-call-btn');
    const gcBtn = document.getElementById('group-call-btn');
    if(vcBtn) vcBtn.style.display = targetName === 'All' ? 'none' : 'flex';
    if(vidBtn) vidBtn.style.display = targetName === 'All' ? 'none' : 'flex';
    if(gcBtn) gcBtn.style.display = 'none';
    
    if (typeof window.loadHistory === 'function') {
        window.loadHistory();
    }
    
    if(targetName !== 'All') {
        socket.emit('mark_all_read', { sender: targetName });
    }
    
    const layout = document.querySelector('.chat-layout');
    if (layout) {
        layout.classList.add('active-chat');
    }
};

// Request notification permission on first user click if not already granted
if (window.Notification) {
    document.addEventListener('click', function reqNotificationPermission() {
        if (Notification.permission === "default") {
            Notification.requestPermission().then(permission => {
                console.log("Notification permission requested on click:", permission);
            });
        }
        document.removeEventListener('click', reqNotificationPermission);
    }, { once: true });
}

socket.on('connect', async () => {
    // Request notification permission if not yet decided
    if (window.Notification && Notification.permission === "default") {
        Notification.requestPermission().then(permission => {
            console.log("Notification permission requested on connection:", permission);
        });
    }

    const res = await fetch('/api/user_info');
    const data = await res.json();
    if(data.success) {
        myUsername = data.data.username;
        window.myUsername = myUsername;
        const myUserEl = document.getElementById('my-username');
        if(myUserEl) myUserEl.innerText = myUsername;
        socket.emit('register', { username: myUsername });

        // Start client-side heartbeat
        if (window._heartbeatInterval) clearInterval(window._heartbeatInterval);
        window._heartbeatInterval = setInterval(() => {
            socket.emit('heartbeat');
        }, 60000);

        // Restore sidebar header status dot & selector from own user data
        const checkSelf = () => {
            if (window.allUsersList) {
                const self = window.allUsersList.find(u => u.name === myUsername);
                if (self) {
                    const dot = document.getElementById('my-status-dot');
                    if (dot) dot.className = 'my-status-dot ' + statusDotClass(self.status);
                    const sel = document.getElementById('status-selector');
                    if (sel) sel.value = self.status;
                }
                return;
            }
            setTimeout(checkSelf, 200);
        };
        checkSelf();

        if (typeof window.loadHistory === 'function') {
            window.loadHistory();
        }
        if (typeof window.loadGroupsList === 'function') {
            window.loadGroupsList();
        }
    }
});

// Status selector change handler
document.addEventListener('change', (e) => {
    if (e.target && e.target.id === 'status-selector') {
        const newStatus = e.target.value;
        socket.emit('status_update', { status: newStatus });
        // Optimistic UI update
        const dot = document.getElementById('my-status-dot');
        if (dot) dot.className = 'my-status-dot ' + statusDotClass(newStatus);
    }
});

// Typing indicator — input handler (delegated)
document.addEventListener('input', (e) => {
    if (e.target && e.target.id === 'message-input') {
        handleInputTyping();
    }
});

// Stop typing on send button click
document.addEventListener('click', (e) => {
    const btn = e.target.closest('#send-btn');
    if (btn) {
        stopTypingForCurrent();
    }
});

// Stop typing on Enter key in message input
document.addEventListener('keydown', (e) => {
    if (e.target && e.target.id === 'message-input' && e.key === 'Enter' && !e.shiftKey) {
        // Small delay to let the send handler fire first
        setTimeout(stopTypingForCurrent, 50);
    }
});

socket.on('user_list', (data) => {
    window.allUsersList = data.users || [];
    
    // Sort users: Available > Busy > Away > Offline, then unread first, then alphabetical
    if (data.users && data.users.length > 0) {
        data.users.sort((a, b) => {
            const pa = statusPriority(a.status);
            const pb = statusPriority(b.status);
            if (pa !== pb) return pb - pa;
            // Within same status: unread conversations first
            const aUnread = (a.unread_count || 0) > 0 ? 0 : 1;
            const bUnread = (b.unread_count || 0) > 0 ? 0 : 1;
            if (aUnread !== bUnread) return aUnread - bUnread;
            // Then alphabetical
            return a.name.localeCompare(b.name);
        });
    }
    
    renderUserList();

    // Re-apply search filter if active
    const searchInput = document.getElementById('user-search-input');
    if (searchInput && searchInput.value) {
        searchInput.dispatchEvent(new Event('input'));
    }
});

function renderUserList() {
    const ul = document.getElementById('users-list');
    if(!ul) return;
    ul.innerHTML = '';
    
    const onlineUsers = [];
    const offlineUsers = [];
    
    (window.allUsersList || []).forEach(u => {
        if(u.name === myUsername) return;
        const prio = statusPriority(u.status);
        if (prio > 1) {
            onlineUsers.push(u);
        } else {
            offlineUsers.push(u);
        }
    });
    
    // Update the self status dot and selector
    const selfUser = (window.allUsersList || []).find(u => u.name === myUsername);
    if (selfUser) {
        const dot = document.getElementById('my-status-dot');
        if (dot) {
            dot.className = 'my-status-dot ' + statusDotClass(selfUser.status);
        }
        const sel = document.getElementById('status-selector');
        if (sel && sel.value !== selfUser.status) {
            sel.value = selfUser.status;
        }
    }
    
    // Render online users
    onlineUsers.forEach(u => {
        const dotCls = statusDotClass(u.status);
        const dispText = statusDisplayText(u.status);
        const dispColor = statusDisplayColor(u.status);
        const isActive = currentTarget === u.name;
        
        const html = `
        <div class="user-item ${isActive ? 'active' : ''}" data-target="${u.name}" role="listitem">
            <button class="user-chat-btn" aria-label="Chat with ${escapeHtml(u.name)}. Status: ${dispText}" style="pointer-events: none;">
                <div class="status-dot ${dotCls}" aria-hidden="true"></div>
                <div style="flex-grow: 1; display: flex; flex-direction: column; text-align: left;">
                    <div style="font-weight: 600;">${escapeHtml(u.name)}</div>
                    <div style="font-size: 0.75rem; color: ${dispColor};">${dispText}</div>
                </div>
                ${u.unread_count > 0 ? `<span class="badge bg-danger rounded-pill" style="margin-right: 8px;">${u.unread_count}<span class="visually-hidden"> unread messages</span></span>` : ''}
            </button>
            <button class="direct-call-btn" title="Call ${escapeHtml(u.name)}" aria-label="Call ${escapeHtml(u.name)}">📞</button>
        </div>`;
        
        const temp = document.createElement('div');
        temp.innerHTML = html;
        const div = temp.firstElementChild;
        
        const callBtn = div.querySelector('.direct-call-btn');
        callBtn.onclick = (e) => {
            e.stopPropagation();
            if(typeof window.startDirectCall === 'function') window.startDirectCall(u.name);
        };
        
        div.onclick = () => window.selectUser(u.name, div);
        ul.appendChild(div);
    });
    
    // Render offline users directly in the list
    offlineUsers.forEach(u => {
        const isActive = currentTarget === u.name;
        const lastSeen = formatLastSeenRelative(u.last_seen);
        const tooltip = lastSeenTooltip(u.last_seen);
        
        const html = `
        <div class="user-item ${isActive ? 'active' : ''}" data-target="${u.name}" role="listitem">
            <button class="user-chat-btn" aria-label="Chat with ${escapeHtml(u.name)}. Status: Offline. Last seen: ${lastSeen}" style="pointer-events: none;">
                <div class="status-dot offline" aria-hidden="true"></div>
                <div style="flex-grow: 1; display: flex; flex-direction: column; text-align: left;">
                    <div style="font-weight: 600;">${escapeHtml(u.name)}</div>
                    <div class="last-seen-label"${tooltip ? ` title="${tooltip}"` : ''}>Last seen: ${lastSeen}</div>
                </div>
                ${u.unread_count > 0 ? `<span class="badge bg-danger rounded-pill" style="margin-right: 8px;">${u.unread_count}<span class="visually-hidden"> unread messages</span></span>` : ''}
            </button>
            <button class="direct-call-btn" title="Call ${escapeHtml(u.name)}" aria-label="Call ${escapeHtml(u.name)}">📞</button>
        </div>`;
        
        const temp = document.createElement('div');
        temp.innerHTML = html;
        const div = temp.firstElementChild;
        
        const callBtn = div.querySelector('.direct-call-btn');
        callBtn.onclick = (e) => {
            e.stopPropagation();
            if(typeof window.startDirectCall === 'function') window.startDirectCall(u.name);
        };
        
        div.onclick = () => window.selectUser(u.name, div);
        ul.appendChild(div);
    });
}

// ── Typing indicator state ──────────────────────────────────────
let _typingState = {
    lastStart: 0,
    stopTimer: null,
    currentConv: null,
};

function getConversationType(conv) {
    if (conv === 'All' || !conv) return null;
    if (window.allGroupsList && window.allGroupsList.some(g => g.name === conv)) return 'group';
    return 'private';
}

function sendTypingStart(conv, type) {
    if (!conv || !type) return;
    socket.emit('typing_start', { to: conv, type: type });
}

function sendTypingStop(conv, type) {
    if (!conv || !type) return;
    socket.emit('typing_stop', { to: conv, type: type });
    _typingState.currentConv = null;
}

function handleInputTyping() {
    const conv = currentTarget;
    const type = getConversationType(conv);
    if (!type) return;

    // Throttle: emit typing_start at most every 2s
    const now = Date.now();
    if (now - _typingState.lastStart >= 2000) {
        sendTypingStart(conv, type);
        _typingState.lastStart = now;
    }

    // Debounce: emit typing_stop after 1s of no keystrokes
    if (_typingState.stopTimer) clearTimeout(_typingState.stopTimer);
    _typingState.currentConv = conv;
    _typingState.stopTimer = setTimeout(() => {
        if (_typingState.currentConv === conv) {
            sendTypingStop(conv, type);
        }
    }, 1000);
}

function stopTypingForCurrent() {
    const conv = _typingState.currentConv;
    if (conv) {
        const type = getConversationType(conv);
        if (type) sendTypingStop(conv, type);
    }
    if (_typingState.stopTimer) {
        clearTimeout(_typingState.stopTimer);
        _typingState.stopTimer = null;
    }
    _typingState.currentConv = null;
}

// ── Typing indicator UI ─────────────────────────────────────────
let _typingTimeout = null;
let _shownTypingUser = null;

socket.on('user_typing', (data) => {
    const { username, conversation, type } = data;
    // Show only if we're viewing this conversation
    if (type === 'private' && conversation !== currentTarget) return;
    if (type === 'group' && conversation !== currentTarget) return;
    if (username === myUsername) return;

    const typingEl = document.getElementById('typing-indicator');
    const textEl = document.getElementById('typing-text');
    if (!typingEl || !textEl) return;

    _shownTypingUser = username;
    let label;
    if (type === 'group') {
        label = `${escapeHtml(username)} is typing<span class="typing-dots"></span>`;
    } else {
        label = `typing<span class="typing-dots"></span>`;
    }
    textEl.innerHTML = label;
    typingEl.style.display = 'block';
    typingEl.classList.remove('hidden');

    // Auto-hide after 4s if no refresh
    if (_typingTimeout) clearTimeout(_typingTimeout);
    _typingTimeout = setTimeout(() => {
        typingEl.classList.add('hidden');
        _shownTypingUser = null;
    }, 4000);
});

socket.on('user_typing_stop', (data) => {
    const { username, conversation, type } = data;
    if (type === 'private' && conversation !== currentTarget) return;
    if (type === 'group' && conversation !== currentTarget) return;
    if (username !== _shownTypingUser) return;

    const typingEl = document.getElementById('typing-indicator');
    if (!typingEl) return;
    typingEl.classList.add('hidden');
    if (_typingTimeout) clearTimeout(_typingTimeout);
    _shownTypingUser = null;
});

// Handle incremental presence updates — update single user then re-render
socket.on('user_update', (data) => {
    const { username, status, last_seen } = data;
    if (!window.allUsersList) return;
    const idx = window.allUsersList.findIndex(u => u.name === username);
    if (idx === -1) return;

    const prevStatus = window.allUsersList[idx].status;
    window.allUsersList[idx].status = status;
    window.allUsersList[idx].last_seen = last_seen;

    // Re-sort if status actually changed (sort priority may differ)
    if (prevStatus !== status) {
        window.allUsersList.sort((a, b) => {
            const pa = statusPriority(a.status);
            const pb = statusPriority(b.status);
            if (pa !== pb) return pb - pa;
            const aUnread = (a.unread_count || 0) > 0 ? 0 : 1;
            const bUnread = (b.unread_count || 0) > 0 ? 0 : 1;
            if (aUnread !== bUnread) return aUnread - bUnread;
            return a.name.localeCompare(b.name);
        });
    }

    renderUserList();
});

socket.on('user_rename', (data) => {
    const { old_username, new_username } = data;
    if (!window.allUsersList) return;

    // If it's the current user, update myUsername and sidebar
    if (old_username === myUsername) {
        myUsername = new_username;
        const el = document.getElementById('my-username');
        if (el) el.textContent = new_username;
    }

    // Update the name in the user list
    const idx = window.allUsersList.findIndex(u => u.name === old_username);
    if (idx !== -1) {
        window.allUsersList[idx].name = new_username;
    }

    // Re-sort (name may have changed order within same status group)
    window.allUsersList.sort((a, b) => {
        const pa = statusPriority(a.status);
        const pb = statusPriority(b.status);
        if (pa !== pb) return pb - pa;
        const aUnread = (a.unread_count || 0) > 0 ? 0 : 1;
        const bUnread = (b.unread_count || 0) > 0 ? 0 : 1;
        if (aUnread !== bUnread) return aUnread - bUnread;
        return a.name.localeCompare(b.name);
    });

    renderUserList();
});

function showBrowserNotification(data) {
    if (!window.Notification || Notification.permission !== "granted") return;
    
    let title = "";
    let body = "";
    
    if (data.to === 'All') {
        title = `FalconChat - Broadcast Room`;
        body = `${data.sender}: ${data.type === 'text' ? data.content : 'Sent an attachment'}`;
    } else {
        title = `FalconChat - ${data.sender}`;
        body = data.type === 'text' ? data.content : 'Sent an attachment';
    }
    
    try {
        const notification = new Notification(title, {
            body: body,
            icon: '/static/favicon.ico'
        });
        
        notification.onclick = function() {
            window.focus();
            if (typeof window.selectUser === 'function') {
                const target = data.to === 'All' ? 'All' : data.sender;
                const userItem = document.querySelector(`.user-item[data-target="${target}"]`);
                window.selectUser(target, userItem);
            }
        };
    } catch(e) {
        console.error("Failed to show notification:", e);
    }
}

socket.on('new_message', (data) => {
    if(data.sender !== myUsername && data.type !== 'ack' && data.sender !== 'Server') {
        // Check if user is active/focused on the tab
        const isPageFocused = document.hasFocus() && !document.hidden;
        
        if (!isPageFocused) {
            // Unfocused: Play global notification sound and show browser notification
            const globalSound = document.getElementById('sound-receive-global');
            if (globalSound) {
                globalSound.currentTime = 0;
                globalSound.play().catch(e => console.log("Audio play blocked", e));
            }
            showBrowserNotification(data);
        } else {
            // Focused: Play specific sounds based on group vs private message
            if (data.to === myUsername) {
                // Private receive: play send_message sound
                const privateSound = document.getElementById('sound-send');
                if (privateSound) {
                    privateSound.currentTime = 0;
                    privateSound.play().catch(e => console.log("Audio play blocked", e));
                }
            } else {
                // Group receive sound (custom group or Broadcast 'All')
                const groupSound = document.getElementById('sound-receive-group');
                if (groupSound) {
                    groupSound.currentTime = 0;
                    groupSound.play().catch(e => console.log("Audio play blocked", e));
                }
            }
        }
    }


    if(
        (data.to === currentTarget) || 
        (data.sender === currentTarget && data.to === myUsername)
    ) {
        if(typeof window.appendMessage === 'function') {
            window.appendMessage(data);
        } else if (typeof window.loadHistory === 'function') {
            window.loadHistory();
        }
        if(data.to !== 'All' && data.sender !== myUsername && !window.isGroupName(data.to)) {
            socket.emit('message_read', {msg_id: data.msg_id, to: data.sender});
        }
    }
});

socket.on('message_status', (data) => {
    const st = document.getElementById(`status-${data.msg_id}`);
    if(st) {
        if(data.status === 'read') {
            st.innerHTML = '<span class="visually-hidden">Status: read</span>✓✓';
            st.style.color = '#38bdf8'; // light blue
        } else if(data.status === 'delivered') {
            st.innerHTML = '<span class="visually-hidden">Status: delivered</span>✓✓';
            st.style.color = 'rgba(255,255,255,0.6)';
        } else if(data.status === 'sent') {
            st.innerHTML = '<span class="visually-hidden">Status: sent</span>✓';
            st.style.color = 'rgba(255,255,255,0.6)';
        }
    }
});

socket.on('message_deleted', (data) => {
    const el = document.getElementById(`msg-container-${data.msg_id}`);
    if(el) {
        const row = el.closest('.message-row');
        if(row) {
            row.remove();
        } else {
            el.remove();
        }
    }
    if (window.selectedMessageIds) {
        window.selectedMessageIds.delete(data.msg_id);
        if (typeof window.updateSelectionUI === 'function') {
            window.updateSelectionUI();
        }
    }
    if (window.totalMessagesForCurrentTarget !== null) {
        window.totalMessagesForCurrentTarget = Math.max(0, window.totalMessagesForCurrentTarget - 1);
    }
});

// Live reaction updates — server broadcasts reaction_update after a toggle
socket.on('reaction_update', (data) => {
    if (typeof window.applyReactions === 'function') {
        window.applyReactions(data.msg_id, data.reactions);
    }
});

// Route ALL WebRTC signaling purely to the Manager Class
socket.on('webrtc_signaling', (data) => {
    if(window.webrtcManager) {
        window.webrtcManager.handleSignaling(data);
    }
});

// Presence notifications for users joining or leaving
socket.on('system', (data) => {
    if (data && data.content) {
        let text = data.content;
        // Ignore notifications about oneself
        if (text.includes(myUsername)) return;
        
        // Translate to user-friendly Arabic
        text = text.replace('joined.', 'متصل الآن 🟢');
        text = text.replace('left.', 'غير متصل 🔴');
        
        if (typeof showToast === 'function') {
            showToast(text);
        }
    }
});

// --- CUSTOM GROUPS SYSTEM INTERACTION ---

window.allGroupsList = [];

window.isGroupName = function(name) {
    if (!name || name === 'All') return false;
    return !!(window.allGroupsList && window.allGroupsList.some(g => g.name === name));
};

async function loadGroupsList() {
    try {
        const res = await fetch('/api/groups');
        const data = await res.json();
        if (data.success) {
            window.allGroupsList = (data.data ? data.data.groups : data.groups) || [];
            renderRoomsList();
        }
    } catch(e) {
        console.error("Failed to load groups:", e);
    }
}
window.loadGroupsList = loadGroupsList;

function renderRoomsList() {
    const rl = document.getElementById('rooms-list');
    if (!rl) return;
    
    // Broadcast Room
    let html = `
    <div class="user-item ${currentTarget === 'All' ? 'active' : ''}" data-target="All" role="listitem" onclick="selectUser('All', this)">
        <button class="user-chat-btn" aria-label="Broadcast Room. Status: Online" style="pointer-events: none;">
            <div class="status-dot online" aria-hidden="true"></div>
            <div style="flex-grow: 1; font-weight: 600;">📢 Broadcast Room</div>
        </button>
    </div>`;
    
    // Custom Groups
    window.allGroupsList.forEach(g => {
        let actionBtnHtml = '';
        let statusText = 'Not member';
        
        if (g.is_member) {
            statusText = g.is_owner ? 'Owner (المالك)' : 'Member (عضو)';
        } else if (g.has_invite) {
            statusText = 'Invited (مدعو)';
            actionBtnHtml = `
                <button class="btn btn-xs btn-success me-1 px-2 py-0" onclick="event.stopPropagation(); window.previewInvite('${g.name}')" style="font-size: 0.75rem;">
                    Preview Invite (معاينة الدعوة)
                </button>
            `;
        } else if (g.has_request) {
            statusText = 'Pending request';
            actionBtnHtml = `
                <span class="badge bg-warning text-dark" style="font-size: 0.75rem;">Pending (معلق)</span>
            `;
        } else {
            statusText = 'Public group';
            actionBtnHtml = `
                <button class="btn btn-xs btn-primary me-1 px-2 py-0" onclick="event.stopPropagation(); window.requestJoinGroup('${g.name}')" style="font-size: 0.75rem;">
                    Request Join (طلب انضمام)
                </button>
            `;
        }
        
        const activeClass = currentTarget === g.name ? 'active' : '';
        
        html += `
        <div class="user-item ${activeClass}" data-target="${g.name}" role="listitem" onclick="window.selectGroup('${g.name}', this)">
            <div class="user-chat-btn" style="flex-grow: 1; display: flex; align-items: center; justify-content: space-between; width: 100%;">
                <div style="display: flex; align-items: center; overflow: hidden; flex-grow: 1;">
                    <div class="status-dot ${g.is_member ? 'online' : 'offline'}" aria-hidden="true"></div>
                    <div style="display: flex; flex-direction: column; text-align: left; overflow: hidden;">
                        <div style="font-weight: 600; color: white; text-overflow: ellipsis; white-space: nowrap; overflow: hidden;">👥 ${escapeHtml(g.name)}</div>
                        <div style="font-size: 0.75rem; color: var(--text-secondary);">${statusText}</div>
                    </div>
                </div>
                <div style="flex-shrink: 0; margin-left: 5px;">
                    ${actionBtnHtml}
                </div>
            </div>
        </div>`;
    });
    
    rl.innerHTML = html;
    
    // Re-apply search filter if active
    const searchInput = document.getElementById('user-search-input');
    if (searchInput && searchInput.value) {
        searchInput.dispatchEvent(new Event('input'));
    }
}

window.selectGroup = function(groupName, element) {
    const g = window.allGroupsList.find(item => item.name === groupName);
    if (!g) return;

    // Stop typing for previous conversation
    stopTypingForCurrent();
    // Hide any incoming typing indicator
    const typingEl = document.getElementById('typing-indicator');
    if (typingEl) { typingEl.classList.add('hidden'); typingEl.style.display = ''; }
    if (_typingTimeout) clearTimeout(_typingTimeout);
    _shownTypingUser = null;
    
    document.querySelectorAll('.user-item').forEach(el => el.classList.remove('active'));
    if (element) element.classList.add('active');
    
    currentTarget = groupName;
    const cTitle = document.getElementById('current-chat-title');
    if(cTitle) cTitle.innerText = `👥 ${groupName}`;
    
    // Call buttons
    const vcBtn = document.getElementById('voice-call-btn');
    const vidBtn = document.getElementById('video-call-btn');
    const gcBtn = document.getElementById('group-call-btn');
    if(vcBtn) vcBtn.style.display = 'none';
    if(vidBtn) vidBtn.style.display = 'none';
    if(gcBtn) gcBtn.style.display = g.is_member ? 'flex' : 'none';
    
    const leaveBtn = document.getElementById('leave-group-btn');
    if(leaveBtn) leaveBtn.style.display = (g.is_member && !g.is_owner) ? 'inline-block' : 'none';
    
    const adminPanel = document.getElementById('group-admin-panel');
    const nonMemberScreen = document.getElementById('group-non-member-screen');
    const msgContainer = document.getElementById('messages-container');
    const footer = document.querySelector('.chat-footer');
    
    if (g.is_member) {
        if(nonMemberScreen) { nonMemberScreen.style.display = 'none'; nonMemberScreen.classList.add('d-none'); }
        if(msgContainer) msgContainer.style.display = 'flex';
        if(footer) footer.style.display = 'flex';
        
        if (g.is_owner) {
            if(adminPanel) adminPanel.style.display = 'block';
            if (typeof window.loadGroupAdminData === 'function') {
                window.loadGroupAdminData(groupName);
            }
        } else {
            if(adminPanel) adminPanel.style.display = 'none';
        }
        
        if (typeof window.loadHistory === 'function') {
            window.loadHistory();
        }
        
        socket.emit('join_room_request', { group_name: groupName });
    } else {
        if(adminPanel) adminPanel.style.display = 'none';
        if(msgContainer) msgContainer.style.display = 'none';
        if(footer) footer.style.display = 'none';
        
        if(nonMemberScreen) {
            nonMemberScreen.classList.remove('d-none');
            nonMemberScreen.style.display = 'flex';
            document.getElementById('non-member-group-title').innerText = `👥 ${groupName}`;
            
            const actionsContainer = document.getElementById('non-member-actions-container');
            actionsContainer.innerHTML = '';
            
            if (g.has_invite) {
                document.getElementById('non-member-group-status-text').innerText = "You have been invited to join this group.";
                actionsContainer.innerHTML = `
                    <button class="btn btn-success me-2" onclick="window.acceptGroupInvite('${groupName}')">Accept Invite (قبول الدعوة)</button>
                    <button class="btn btn-danger" onclick="window.rejectGroupInvite('${groupName}')">Reject (رفض)</button>
                `;
            } else if (g.has_request) {
                document.getElementById('non-member-group-status-text').innerText = "Your request to join this group is pending approval from the owner.";
                actionsContainer.innerHTML = `
                    <button class="btn btn-warning" disabled>Join Request Pending (طلب معلق)</button>
                `;
            } else {
                document.getElementById('non-member-group-status-text').innerText = "You are not a member of this group. Submit a join request to participate.";
                actionsContainer.innerHTML = `
                    <button class="btn btn-primary" onclick="window.requestJoinGroup('${groupName}')">Request Join (طلب انضمام)</button>
                `;
            }
        }
    }
    
    const layout = document.querySelector('.chat-layout');
    if (layout) {
        layout.classList.add('active-chat');
    }
};

socket.on('join_group_room', (data) => {
    socket.emit('join_room_request', { group_name: data.group_name });
    if (typeof window.loadGroupsList === 'function') {
        window.loadGroupsList();
    }
});

socket.on('leave_group_room', (data) => {
    socket.emit('leave_room_request', { group_name: data.group_name });
    if (typeof window.loadGroupsList === 'function') {
        window.loadGroupsList();
    }
});

socket.on('group_deleted', (data) => {
    if (currentTarget === data.group_name) {
        window.selectUser('All');
    }
    if (typeof window.loadGroupsList === 'function') {
        window.loadGroupsList();
    }
});

socket.on('group_invite_received', (data) => {
    const groupSound = document.getElementById('sound-receive-group');
    if (groupSound) {
        groupSound.currentTime = 0;
        groupSound.play().catch(e => console.log("Audio play blocked", e));
    }
    if (typeof showToast === 'function') {
        showToast(`You received an invitation to join group ${data.group_name}!`);
    }
    if (typeof window.loadGroupsList === 'function') {
        window.loadGroupsList();
    }
    
    // Show premium interactive modal
    const inviteModalEl = document.getElementById('groupInviteModal');
    if (inviteModalEl) {
        const inviteModal = bootstrap.Modal.getOrCreateInstance(inviteModalEl);
        const modalTextEl = document.getElementById('group-invite-modal-text');
        if (modalTextEl) {
            modalTextEl.innerHTML = `<strong>${escapeHtml(data.invited_by)}</strong> is inviting you to join group <strong>"${escapeHtml(data.group_name)}"</strong>.<br><br>هل تريد قبول دعوة <strong>${escapeHtml(data.invited_by)}</strong> للانضمام إلى مجموعة <strong>"${escapeHtml(data.group_name)}"</strong>؟`;
        }
        
        const btnAccept = document.getElementById('btn-accept-invite');
        const btnDecline = document.getElementById('btn-decline-invite');
        
        if (btnAccept) {
            btnAccept.onclick = () => {
                window.acceptGroupInvite(data.group_name, true);
                inviteModal.hide();
            };
        }
        if (btnDecline) {
            btnDecline.onclick = () => {
                window.rejectGroupInvite(data.group_name, true);
                inviteModal.hide();
            };
        }
        
        inviteModal.show();
    }
});

socket.on('group_list_updated', (data) => {
    if (typeof window.loadGroupsList === 'function') {
        window.loadGroupsList();
    }
});

socket.on('group_request_received', (data) => {
    const groupSound = document.getElementById('sound-receive-group');
    if (groupSound) {
        groupSound.currentTime = 0;
        groupSound.play().catch(e => console.log("Audio play blocked", e));
    }
    if (typeof showToast === 'function') {
        showToast(`${data.username} requested to join group ${data.group_name}!`);
    }
    if (currentTarget === data.group_name && typeof window.loadGroupAdminData === 'function') {
        window.loadGroupAdminData(data.group_name);
    }
});

// Listen to group calls signaling
socket.on('group_call_incoming', (data) => {
    if(window.webrtcManager) {
        window.webrtcManager.handleGroupCallIncoming(data);
    }
});

socket.on('user_joined_group_call', (data) => {
    if(window.webrtcManager) {
        window.webrtcManager.handleGroupUserJoined(data);
    }
});

socket.on('user_left_group_call', (data) => {
    if(window.webrtcManager) {
        window.webrtcManager.handleGroupUserLeft(data);
    }
});

socket.on('group_call_signaling', (data) => {
    if(window.webrtcManager) {
        window.webrtcManager.handleGroupSignaling(data);
    }
});
