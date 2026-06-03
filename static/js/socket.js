const socket = io();
let myUsername = '';
let currentTarget = 'All';

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
        
        const dateZero = new Date(date.getFullYear(), date.getMonth(), date.getDate());
        const nowZero = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const diffTime = nowZero.getTime() - dateZero.getTime();
        const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
        
        const timeStr = date.toLocaleTimeString(undefined, {
            hour: '2-digit',
            minute: '2-digit'
        });
        
        if (diffDays <= 0) {
            return `Today at ${timeStr}`;
        } else if (diffDays === 1) {
            return `Yesterday at ${timeStr}`;
        } else if (diffDays < 7) {
            const dayName = date.toLocaleDateString(undefined, { weekday: 'long' });
            return `${dayName} at ${timeStr}`;
        } else {
            const dateStr = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
            return `${dateStr} at ${timeStr}`;
        }
    } catch(e) {
        return 'Never';
    }
}

window.selectUser = function(targetName, element) {
    document.querySelectorAll('.user-item').forEach(el => el.classList.remove('active'));
    if(element) element.classList.add('active');
    
    currentTarget = targetName;
    const cTitle = document.getElementById('current-chat-title');
    if(cTitle) cTitle.innerText = targetName === 'All' ? '📢 Broadcast Room' : targetName;
    
    const vcBtn = document.getElementById('voice-call-btn');
    if(vcBtn) vcBtn.style.display = targetName === 'All' ? 'none' : 'flex';
    
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
        myUsername = data.username;
        window.myUsername = myUsername;
        const myUserEl = document.getElementById('my-username');
        if(myUserEl) myUserEl.innerText = myUsername;
        socket.emit('register', { username: myUsername });
        if (typeof window.loadHistory === 'function') {
            window.loadHistory();
        }
        if (typeof window.loadGroupsList === 'function') {
            window.loadGroupsList();
        }
    }
});

socket.on('user_list', (data) => {
    window.allUsersList = data.users || [];
    const ul = document.getElementById('users-list');
    if(!ul) return;
    ul.innerHTML = '';
    
    data.users.forEach(u => {
        if(u.name === myUsername) return;
        
        const div = document.createElement('div');
        div.className = `user-item ${currentTarget === u.name ? 'active' : ''}`;
        div.setAttribute('role', 'listitem');
        div.setAttribute('data-target', u.name);

        
        const statusText = u.status === 'Available' ? 'Online' : `Offline. Last seen: ${formatLastSeenRelative(u.last_seen)}`;
        const unreadText = u.unread_count > 0 ? `, ${u.unread_count} unread messages` : '';
        
        // Left side button: opens chat (pointer events disabled to let click register on parent div)
        const chatBtn = document.createElement('button');
        chatBtn.className = 'user-chat-btn';
        chatBtn.setAttribute('aria-label', `Chat with ${u.name}. Status: ${statusText}${unreadText}`);
        chatBtn.style.pointerEvents = 'none';
        
        let userDetailsHtml = `<div style="font-weight: 600;">${u.name}</div>`;
        if (u.status !== 'Available') {
            userDetailsHtml += `<div style="font-size: 0.75rem; color: var(--text-secondary);"><span class="visually-hidden">Status: Offline. </span>Last seen: ${formatLastSeenRelative(u.last_seen)}</div>`;
        } else {
            userDetailsHtml += `<div style="font-size: 0.75rem; color: #22c55e;"><span class="visually-hidden">Status: </span>Online</div>`;
        }
        
        let badgeHtml = '';
        if(u.unread_count > 0) {
            badgeHtml = `<span class="badge bg-danger rounded-pill" style="margin-right: 8px;">${u.unread_count}<span class="visually-hidden"> unread messages</span></span>`;
        }
        
        chatBtn.innerHTML = `
            <div class="status-dot ${u.status === 'Available' ? 'online' : 'offline'}" aria-hidden="true"></div>
            <div style="flex-grow: 1; display: flex; flex-direction: column; text-align: left;">
                ${userDetailsHtml}
            </div>
            ${badgeHtml}
        `;
        
        // Right side: Direct Call Button
        const callBtn = document.createElement('button');
        callBtn.className = 'direct-call-btn';
        callBtn.innerHTML = '📞';
        callBtn.title = `Call ${u.name}`;
        callBtn.setAttribute('aria-label', `Call ${u.name}`);
        callBtn.onclick = (e) => {
            e.stopPropagation();
            if(typeof window.startDirectCall === 'function') {
                window.startDirectCall(u.name);
            }
        };
        
        div.appendChild(chatBtn);
        div.appendChild(callBtn);
        
        // Make the entire user-item row clickable for touch/mobile devices
        div.onclick = () => window.selectUser(u.name, div);
        ul.appendChild(div);
    });
    
    // Re-apply search filter if active
    const searchInput = document.getElementById('user-search-input');
    if (searchInput && searchInput.value) {
        searchInput.dispatchEvent(new Event('input'));
    }
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
        if(data.to !== 'All' && data.sender !== myUsername) {
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

// --- CUSTOM GROUPS SYSTEM INTERACTION ---

window.allGroupsList = [];

async function loadGroupsList() {
    try {
        const res = await fetch('/api/groups');
        const data = await res.json();
        if (data.success) {
            window.allGroupsList = data.groups || [];
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
                        <div style="font-weight: 600; color: white; text-overflow: ellipsis; white-space: nowrap; overflow: hidden;">👥 ${g.name}</div>
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
    
    document.querySelectorAll('.user-item').forEach(el => el.classList.remove('active'));
    if (element) element.classList.add('active');
    
    currentTarget = groupName;
    const cTitle = document.getElementById('current-chat-title');
    if(cTitle) cTitle.innerText = `👥 ${groupName}`;
    
    // Call buttons
    const vcBtn = document.getElementById('voice-call-btn');
    const gcBtn = document.getElementById('group-call-btn');
    if(vcBtn) vcBtn.style.display = 'none';
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
            modalTextEl.innerHTML = `<strong>${data.invited_by}</strong> is inviting you to join group <strong>"${data.group_name}"</strong>.<br><br>هل تريد قبول دعوة <strong>${data.invited_by}</strong> للانضمام إلى مجموعة <strong>"${data.group_name}"</strong>؟`;
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
