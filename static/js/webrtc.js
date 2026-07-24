class WebRTCManager {
    constructor() {
        this.config = { 'iceServers': [] };
        this.peerConnection = null;
        this.localStream = null;
        this.callTarget = '';
        this.isCaller = false;
        this.callTimerInterval = null;
        this.callSeconds = 0;
        this.isLocked = false;
        
        this.iceQueue = [];
        
        // Group call variables
        this.isInGroupCall = false;
        this.groupCallName = '';
        this.groupPeerConnections = {}; // username -> RTCPeerConnection
        
        this.ensureDOMExists();
        this.loadWebRTCConfig();
    }

    async loadWebRTCConfig() {
        try {
            const res = await fetch('/api/webrtc_config');
            const data = await res.json();
            if(data.success && data.data.iceServers) {
                this.config = { 'iceServers': data.data.iceServers };
                console.log("Loaded WebRTC ICE configuration:", this.config);
            }
        } catch(e) {
            console.error("Failed to load WebRTC config, using fallback STUN/TURN:", e);
            this.config = {
                'iceServers': [
                    { 'urls': 'stun:stun.l.google.com:19302' },
                    { 'urls': 'stun:stun1.l.google.com:19302' },
                    { 'urls': 'turn:openrelay.metered.ca:80', 'username': 'openrelayproject', 'credential': 'openrelayproject' },
                    { 'urls': 'turn:openrelay.metered.ca:443', 'username': 'openrelayproject', 'credential': 'openrelayproject' },
                    { 'urls': 'turns:openrelay.metered.ca:443?transport=tcp', 'username': 'openrelayproject', 'credential': 'openrelayproject' }
                ]
            };
        }
    }


    isInCall() {
        return this.callTarget !== '' || this.peerConnection !== null;
    }
    
    // Dynamic Getters to ensure we always get active, non-null DOM elements
    get callSound() { return document.getElementById('call-sound'); }
    get ringSound() { return document.getElementById('ring-sound'); }
    get screen() { return document.getElementById('active-call-screen'); }
    get title() { return document.getElementById('call-title'); }
    get timer() { return document.getElementById('call-timer'); }
    get acceptBtn() { return document.getElementById('accept-call-btn'); }
    get rejectBtn() { return document.getElementById('reject-call-btn'); }
    get endBtn() { return document.getElementById('end-call-btn'); }
    get muteBtn() { return document.getElementById('mute-call-btn'); }
    get remoteAudio() { return document.getElementById('remote-audio'); }
    
    ensureDOMExists() {
        let oldScreen = document.getElementById('active-call-screen');
        if(oldScreen) oldScreen.remove();

        let oldAudio = document.getElementById('remote-audio');
        if(oldAudio) oldAudio.remove();

        // Place the screen INSIDE the chat area, right above the footer, making it extremely NVDA friendly
        const screenHtml = `
        <div id="active-call-screen" tabindex="-1" role="region" aria-label="Active Call Screen" class="d-none" style="display:none; flex-direction:column; align-items:center; justify-content:center; padding: 20px; background: #1e293b; border-top: 2px solid #3b82f6; border-bottom: 2px solid #3b82f6;">
            <h2 id="call-title" aria-live="assertive" style="color:white; margin-bottom:1rem; font-weight:bold; font-size: 1.5rem;">Call Screen</h2>
            <h4 id="call-timer" aria-live="polite" style="color:#94a3b8; margin-bottom:1.5rem; font-weight:bold; font-family: monospace; font-size: 1.2rem;">00:00</h4>
            <div style="display:flex; gap:1.5rem; justify-content:center;" role="group" aria-label="Call Controls">
                <button id="accept-call-btn" onclick="window.webrtcManager.acceptCall()" style="background:#22c55e; color:white; border:none; border-radius:50%; width:60px; height:60px; font-size:1.5rem; cursor:pointer; display:none;">
                    <span class="visually-hidden">Answer Call</span>📞
                </button>
                <button id="reject-call-btn" onclick="window.webrtcManager.rejectCall()" style="background:#ef4444; color:white; border:none; border-radius:50%; width:60px; height:60px; font-size:1.5rem; cursor:pointer; display:none;">
                    <span class="visually-hidden">Reject Call</span>❌
                </button>
                <button id="mute-call-btn" onclick="window.webrtcManager.toggleMute()" style="background:#64748b; color:white; border:none; border-radius:50%; width:60px; height:60px; font-size:1.5rem; cursor:pointer; display:none;">
                    <span class="visually-hidden">Mute Microphone</span>🔇
                </button>
                <button id="end-call-btn" onclick="window.webrtcManager.endCall(true)" style="background:#ef4444; color:white; border:none; border-radius:50%; width:60px; height:60px; font-size:1.5rem; cursor:pointer; display:none;">
                    <span class="visually-hidden">End Call</span>❌
                </button>
            </div>
        </div>`;
        
        const chatFooter = document.querySelector('.chat-footer');
        const chatMain = document.querySelector('.main-chat');
        if(chatMain && chatFooter) {
            chatMain.insertBefore(document.createRange().createContextualFragment(screenHtml), chatFooter);
        } else {
            document.body.insertAdjacentHTML('beforeend', screenHtml);
        }

        // Add remote-audio directly to body to avoid container visibility rendering bugs
        const audioHtml = `<audio id="remote-audio" autoplay playsinline style="position: absolute; left: -9999px; top: -9999px; width: 1px; height: 1px;"></audio>`;
        document.body.insertAdjacentHTML('beforeend', audioHtml);
    }
    
    stopSounds() {
        try {
            const callSnd = this.callSound;
            if(callSnd) { 
                callSnd.pause(); 
                callSnd.currentTime = 0; 
            }
        } catch(e) {
            console.warn("Failed to stop callSound:", e);
        }
        try {
            const ringSnd = this.ringSound;
            if(ringSnd) { 
                ringSnd.pause(); 
                ringSnd.currentTime = 0; 
            }
        } catch(e) {
            console.warn("Failed to stop ringSound:", e);
        }
    }

    // --- UI STATE CONTROLLERS ---
    
    showCallingUI(target) {
        const scr = this.screen;
        if(!scr) return;
        scr.classList.remove('d-none');
        scr.style.display = 'flex';
        scr.focus(); // Focus for NVDA
        
        if(this.title) this.title.innerText = `Calling ${target}...`;
        if(this.timer) this.timer.innerText = "00:00";
        
        if(this.acceptBtn) this.acceptBtn.style.display = 'none';
        if(this.rejectBtn) this.rejectBtn.style.display = 'none';
        if(this.endBtn) this.endBtn.style.display = 'inline-block';
        if(this.muteBtn) this.muteBtn.style.display = 'inline-block';
        
        this.stopSounds();
        const callSnd = this.callSound;
        if(callSnd) callSnd.play().catch(e => console.log("Audio play blocked", e));
        
        const layout = document.querySelector('.chat-layout');
        if (layout) {
            layout.classList.add('active-chat');
        }
    }
    
    showRingingUI(caller) {
        const scr = this.screen;
        if(!scr) return;
        scr.classList.remove('d-none');
        scr.style.display = 'flex';
        scr.focus(); // Focus for NVDA
        
        if(this.title) this.title.innerText = `Incoming call from ${caller}`;
        if(this.timer) this.timer.innerText = "00:00";
        
        if(this.acceptBtn) this.acceptBtn.style.display = 'inline-block';
        if(this.rejectBtn) this.rejectBtn.style.display = 'inline-block';
        if(this.endBtn) this.endBtn.style.display = 'none';
        if(this.muteBtn) this.muteBtn.style.display = 'none';
        
        this.stopSounds();
        const ringSnd = this.ringSound;
        if(ringSnd) ringSnd.play().catch(e => console.log("Audio play blocked", e));
        
        const layout = document.querySelector('.chat-layout');
        if (layout) {
            layout.classList.add('active-chat');
        }
    }
    
    showConnectingUI() {
        this.stopSounds();
        if(this.title) this.title.innerText = "Connecting...";
        if(this.acceptBtn) this.acceptBtn.style.display = 'none';
        if(this.rejectBtn) this.rejectBtn.style.display = 'none';
        if(this.endBtn) this.endBtn.style.display = 'inline-block';
        if(this.muteBtn) this.muteBtn.style.display = 'inline-block';
    }

    showInCallUI(target) {
        this.stopSounds();
        if(this.title) this.title.innerText = `Active call with ${target}`;
        
        if(this.acceptBtn) this.acceptBtn.style.display = 'none';
        if(this.rejectBtn) this.rejectBtn.style.display = 'none';
        if(this.endBtn) this.endBtn.style.display = 'inline-block';
        if(this.muteBtn) this.muteBtn.style.display = 'inline-block';
        
        this.startTimer();
    }
    
    showErrorUI(errorMessage) {
        this.stopSounds();
        if(this.title) this.title.innerText = errorMessage;
        
        if(this.acceptBtn) this.acceptBtn.style.display = 'none';
        if(this.rejectBtn) this.rejectBtn.style.display = 'none';
        if(this.endBtn) this.endBtn.style.display = 'inline-block';
        if(this.muteBtn) this.muteBtn.style.display = 'none';
    }
    
    hideCallUI() {
        this.stopSounds();
        const scr = this.screen;
        if(scr) {
            scr.style.display = 'none';
            scr.classList.add('d-none');
        }
    }
    
    // --- CORE LOGIC ---
    
    async getAudioStream() {
        if (this.localStream) {
            try {
                this.localStream.getTracks().forEach(t => t.stop());
            } catch(e) {}
            this.localStream = null;
        }
        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
            try {
                return await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
            } catch(e1) {
                return await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
            }
        } else if (navigator.getUserMedia) {
            return new Promise((resolve, reject) => {
                navigator.getUserMedia({ audio: true, video: false }, resolve, reject);
            });
        } else if (navigator.webkitGetUserMedia) {
            return new Promise((resolve, reject) => {
                navigator.webkitGetUserMedia({ audio: true, video: false }, resolve, reject);
            });
        } else {
            throw new Error("Browser does not support getUserMedia over insecure HTTP connection");
        }
    }

    async startCall(target) {
        if(this.isInCall()) {
            alert("You are already in an active call!");
            return;
        }
        if(this.isLocked) return;
        this.isLocked = true;
        
        this.callTarget = target;
        this.isCaller = true;
        this.iceQueue = [];
        
        this.showCallingUI(target);
        
        const audioEl = this.remoteAudio;
        if(audioEl) {
            audioEl.play().catch(e => console.log("Audio unlocked for caller:", e));
        }
        
        try {
            this.localStream = await this.getAudioStream();
            this.setupPeerConnection(target);
            
            const offer = await this.peerConnection.createOffer();
            await this.peerConnection.setLocalDescription(offer);
            
            socket.emit('webrtc_signaling', {
                to: target,
                from: myUsername,
                type: 'offer',
                offer: offer,
                sdp: offer.sdp
            });
            
            this.isLocked = false;
        } catch(err) {
            console.error("WebRTC Error:", err);
            this.cleanup();
            const msg = err.name === 'NotAllowedError' ? 'Error: Please grant microphone access' : `Error: ${err.message || 'Call failed'}`;
            this.showErrorUI(msg);
        }
    }
    
    handleSignaling(data) {
        if(data.type === 'offer') {
            if(this.isInCall()) {
                console.log("Busy: rejecting offer from", data.from);
                socket.emit('webrtc_signaling', {
                    to: data.from,
                    from: myUsername,
                    type: 'busy'
                });
                return;
            }
            this.callTarget = data.from;
            this.isCaller = false;
            const sdpContent = data.sdp || (data.offer ? data.offer.sdp : '');
            this.incomingOffer = data.offer || { type: 'offer', sdp: sdpContent };
            this.incomingSdp = sdpContent;
            this.iceQueue = [];
            
            // Switch view to caller's chat to ensure they see the call screen
            if (typeof window.selectUser === 'function') {
                window.selectUser(data.from);
            }
            
            this.showRingingUI(data.from);
            
        } else if(data.type === 'accepted') {
            // INSTANT feedback from receiver that they clicked Accept
            this.showConnectingUI();

        } else if(data.type === 'answer') {
            if(this.peerConnection) {
                const sdpContent = data.sdp || (data.answer ? data.answer.sdp : '');
                const answerDesc = new RTCSessionDescription({ type: 'answer', sdp: sdpContent });
                this.peerConnection.setRemoteDescription(answerDesc)
                .then(() => {
                    this.showInCallUI(this.callTarget);
                    this.processIceQueue();
                }).catch(e => console.error("WebRTC Answer Error:", e));
            }
            
        } else if(data.type === 'ice_candidate' || data.type === 'candidate') {
            const cand = data.candidate;
            if(cand) {
                if (typeof cand === 'string') {
                    this.iceQueue.push({ candidate: cand, sdpMid: data.sdpMid || '0', sdpMLineIndex: data.sdpMLineIndex || 0 });
                } else {
                    this.iceQueue.push(cand);
                }
            }
            this.processIceQueue();
            
        } else if(data.type === 'reject') {
            this.showErrorUI("Call rejected");
            if (this.isCaller) {
                this.saveCallLog('rejected', 0);
            }
            this.cleanup();
            setTimeout(() => this.hideCallUI(), 3000);
            
        } else if(data.type === 'busy') {
            this.showErrorUI(`${data.from} is busy in another call`);
            if (this.isCaller) {
                this.saveCallLog('busy', 0);
            }
            this.cleanup();
            setTimeout(() => this.hideCallUI(), 3000);
            
        } else if(data.type === 'end_call') {
            this.showErrorUI("Call ended");
            if (this.isCaller) {
                const status = this.callSeconds > 0 ? 'completed' : 'missed';
                this.saveCallLog(status, this.callSeconds);
            }
            this.cleanup();
            setTimeout(() => this.hideCallUI(), 3000);
        }
    }
    
    processIceQueue() {
        if(this.peerConnection && this.peerConnection.remoteDescription) {
            while(this.iceQueue.length > 0) {
                const candidate = this.iceQueue.shift();
                if(candidate) {
                    this.peerConnection.addIceCandidate(new RTCIceCandidate(candidate))
                        .catch(e => console.error("ICE processing error:", e));
                }
            }
        }
    }
    
    async acceptCall() {
        if(this.isLocked) return;
        this.isLocked = true;
        
        this.stopSounds(); // Immediate Stop
        this.showConnectingUI(); // Local update
        
        const audioEl = this.remoteAudio;
        if(audioEl) {
            audioEl.play().catch(e => console.log("Audio unlocked for receiver:", e));
        }
        
        // Save target name locally before any potential cleanup resets it
        const target = this.callTarget;
        
        // INSTANTLY notify the caller to stop ringing
        socket.emit('webrtc_signaling', {
            to: target,
            from: myUsername,
            type: 'accepted'
        });
        
        try {
            this.localStream = await this.getAudioStream();
            this.setupPeerConnection(target);
            
            const offerSdpText = typeof this.incomingOffer === 'string' ? this.incomingOffer : (this.incomingOffer && this.incomingOffer.sdp ? this.incomingOffer.sdp : (this.incomingSdp || ''));
            if (!offerSdpText) {
                throw new Error("Missing SDP offer string from remote peer");
            }
            const offerDesc = new RTCSessionDescription({ type: 'offer', sdp: offerSdpText });
            await this.peerConnection.setRemoteDescription(offerDesc);
            
            const answer = await this.peerConnection.createAnswer();
            await this.peerConnection.setLocalDescription(answer);
            
            socket.emit('webrtc_signaling', {
                to: target,
                from: myUsername,
                type: 'answer',
                answer: answer,
                sdp: answer.sdp
            });
            
            this.showInCallUI(target);
            this.processIceQueue();
            this.isLocked = false;
        } catch(err) {
            console.error("WebRTC Accept Error:", err);
            this.cleanup();
            const msg = err.name === 'NotAllowedError' ? 'Error: Cannot access microphone' : `Error: ${err.message || 'Call accept failed'}`;
            this.showErrorUI(msg);
            if(target) {
                socket.emit('webrtc_signaling', { type: 'reject', to: target });
            }
        }
    }
    
    rejectCall() {
        this.stopSounds();
        if(this.callTarget) {
            socket.emit('webrtc_signaling', { type: 'reject', to: this.callTarget });
        }
        this.cleanup();
        this.hideCallUI();
    }
    
    endCall(notifyRemote = false) {
        this.stopSounds();
        if (this.isCaller) {
            const status = this.callSeconds > 0 ? 'completed' : 'missed';
            this.saveCallLog(status, this.callSeconds);
        }
        if(notifyRemote && this.callTarget) {
            socket.emit('webrtc_signaling', { type: 'end_call', to: this.callTarget });
        }
        this.cleanup();
        this.hideCallUI();
    }
    
    setupPeerConnection(target) {
        this.peerConnection = new RTCPeerConnection(this.config);
        
        this.peerConnection.onconnectionstatechange = (event) => {
            if (!this.peerConnection) return;
            console.log("WebRTC Connection State changed to:", this.peerConnection.connectionState);
            if (this.peerConnection.connectionState === 'disconnected' || 
                this.peerConnection.connectionState === 'failed' || 
                this.peerConnection.connectionState === 'closed') {
                this.showErrorUI("Call disconnected");
                if (this.isCaller) {
                    this.saveCallLog('completed', this.callSeconds);
                }
                this.cleanup();
                setTimeout(() => this.hideCallUI(), 3000);
            }
        };
        this.peerConnection.oniceconnectionstatechange = (event) => {
            console.log("WebRTC ICE Connection State changed to:", this.peerConnection.iceConnectionState);
        };
        
        this.localStream.getTracks().forEach(track => {
            this.peerConnection.addTrack(track, this.localStream);
        });
        
        this.peerConnection.ontrack = (event) => {
            console.log("OnTrack: remote track received", event);
            const audioEl = this.remoteAudio;
            if(audioEl) {
                if (event.streams && event.streams[0]) {
                    audioEl.srcObject = event.streams[0];
                } else {
                    const newStream = new MediaStream();
                    newStream.addTrack(event.track);
                    audioEl.srcObject = newStream;
                }
                audioEl.play().catch(e => console.error("Remote audio play blocked:", e));
            }
        };
        
        this.peerConnection.onicecandidate = (event) => {
            if(event.candidate) {
                socket.emit('webrtc_signaling', {
                    to: target,
                    from: myUsername,
                    type: 'ice_candidate',
                    candidate: event.candidate,
                    sdp: event.candidate.candidate,
                    sdpMid: event.candidate.sdpMid,
                    sdpMLineIndex: event.candidate.sdpMLineIndex
                });
            }
        };
    }
    
    toggleMute() {
        if(this.localStream) {
            const track = this.localStream.getAudioTracks()[0];
            if(track) {
                track.enabled = !track.enabled;
                const muteBtnEl = this.muteBtn;
                if(muteBtnEl) {
                    muteBtnEl.style.background = track.enabled ? '#64748b' : '#ef4444';
                    muteBtnEl.innerHTML = track.enabled ? '<span class="visually-hidden">Mute Microphone</span>🔇' : '<span class="visually-hidden">Unmute Microphone</span>🎤';
                }
            }
        }
    }
    
    startTimer() {
        clearInterval(this.callTimerInterval);
        this.callSeconds = 0;
        this.callTimerInterval = setInterval(() => {
            this.callSeconds++;
            const m = String(Math.floor(this.callSeconds / 60)).padStart(2, '0');
            const s = String(this.callSeconds % 60).padStart(2, '0');
            const timerEl = this.timer;
            if(timerEl) {
                timerEl.innerText = `${m}:${s}`;
                timerEl.setAttribute('aria-label', `Call duration: ${m} minutes and ${s} seconds`);
            }
        }, 1000);
    }
    
    // --- GROUP VOICE CALL FEATURES ---

    async startGroupCall(groupName) {
        if (this.isInCall() || this.isInGroupCall) {
            alert("You are already in an active call!");
            return;
        }
        if (!confirm(`Do you want to start a group call for "${groupName}"?`)) return;
        
        this.isInGroupCall = true;
        this.groupCallName = groupName;
        this.showCallingUI(`Group: ${groupName}`);
        
        try {
            this.localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
            this.showInCallUI(`Group: ${groupName}`);
            
            // Notify server that we started group call
            socket.emit('group_call_start', { group_name: groupName });
            socket.emit('group_call_join', { group_name: groupName });
        } catch(err) {
            console.error("Group WebRTC Error:", err);
            this.cleanup();
            this.showErrorUI("Error: Please grant microphone access");
        }
    }

    handleGroupCallIncoming(data) {
        if (this.isInCall() || this.isInGroupCall) return; // Busy
        
        this.groupCallName = data.group_name;
        this.showRingingUI(`Group: ${data.group_name} (by ${data.caller})`);
        
        const acceptBtnEl = this.acceptBtn;
        const rejectBtnEl = this.rejectBtn;
        
        if (acceptBtnEl) {
            acceptBtnEl.onclick = () => {
                if(confirm("Join this group voice call?")) {
                    this.acceptGroupCall();
                }
            };
        }
        if (rejectBtnEl) {
            rejectBtnEl.onclick = () => {
                if(confirm("Reject this group call?")) {
                    this.rejectGroupCall();
                }
            };
        }
    }

    async acceptGroupCall() {
        this.stopSounds();
        this.showConnectingUI();
        
        this.isInGroupCall = true;
        
        try {
            this.localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
            this.showInCallUI(`Group: ${this.groupCallName}`);
            
            this.restoreCallButtonHandlers();
            
            socket.emit('group_call_join', { group_name: this.groupCallName });
        } catch(err) {
            console.error("Group Call Accept Error:", err);
            this.restoreCallButtonHandlers();
            this.cleanup();
            this.showErrorUI("Error: Cannot access microphone");
        }
    }

    rejectGroupCall() {
        this.restoreCallButtonHandlers();
        this.cleanup();
        this.hideCallUI();
    }

    restoreCallButtonHandlers() {
        const acceptBtnEl = this.acceptBtn;
        const rejectBtnEl = this.rejectBtn;
        if (acceptBtnEl) acceptBtnEl.onclick = () => window.webrtcManager.acceptCall();
        if (rejectBtnEl) rejectBtnEl.onclick = () => window.webrtcManager.rejectCall();
    }

    async handleGroupUserJoined(data) {
        const username = data.username;
        console.log("User joined group call:", username);
        if (this.groupPeerConnections[username]) return;
        
        const pc = new RTCPeerConnection(this.config);
        this.groupPeerConnections[username] = pc;
        
        if (this.localStream) {
            this.localStream.getTracks().forEach(track => {
                pc.addTrack(track, this.localStream);
            });
        }
        
        pc.onicecandidate = (event) => {
            if (event.candidate) {
                socket.emit('group_call_signaling', {
                    to: username,
                    type: 'ice_candidate',
                    candidate: event.candidate
                });
            }
        };
        
        pc.ontrack = (event) => {
            console.log("Group track received from", username);
            const audioId = `remote-audio-${username}`;
            let audioEl = document.getElementById(audioId);
            if (!audioEl) {
                audioEl = document.createElement('audio');
                audioEl.id = audioId;
                audioEl.autoplay = true;
                audioEl.playsinline = true;
                audioEl.style.display = 'none';
                document.body.appendChild(audioEl);
            }
            if (event.streams && event.streams[0]) {
                audioEl.srcObject = event.streams[0];
            } else {
                const newStream = new MediaStream();
                newStream.addTrack(event.track);
                audioEl.srcObject = newStream;
            }
            audioEl.play().catch(e => console.error("Group remote audio play blocked:", e));
        };
        
        try {
            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);
            socket.emit('group_call_signaling', {
                to: username,
                type: 'offer',
                offer: offer
            });
        } catch(e) {
            console.error("Error creating group offer to", username, e);
        }
    }

    async handleGroupSignaling(data) {
        const fromUser = data.from;
        let pc = this.groupPeerConnections[fromUser];
        
        if (data.type === 'offer') {
            if (!pc) {
                pc = new RTCPeerConnection(this.config);
                this.groupPeerConnections[fromUser] = pc;
                
                if (this.localStream) {
                    this.localStream.getTracks().forEach(track => {
                        pc.addTrack(track, this.localStream);
                    });
                }
                
                pc.onicecandidate = (event) => {
                    if (event.candidate) {
                        socket.emit('group_call_signaling', {
                            to: fromUser,
                            type: 'ice_candidate',
                            candidate: event.candidate
                        });
                    }
                };
                
                pc.ontrack = (event) => {
                    console.log("Group track received from", fromUser);
                    const audioId = `remote-audio-${fromUser}`;
                    let audioEl = document.getElementById(audioId);
                    if (!audioEl) {
                        audioEl = document.createElement('audio');
                        audioEl.id = audioId;
                        audioEl.autoplay = true;
                        audioEl.playsinline = true;
                        audioEl.style.display = 'none';
                        document.body.appendChild(audioEl);
                    }
                    if (event.streams && event.streams[0]) {
                        audioEl.srcObject = event.streams[0];
                    } else {
                        const newStream = new MediaStream();
                        newStream.addTrack(event.track);
                        audioEl.srcObject = newStream;
                    }
                    audioEl.play().catch(e => console.error("Group remote audio play blocked:", e));
                };
            }
            
            try {
                await pc.setRemoteDescription(new RTCSessionDescription(data.offer));
                const answer = await pc.createAnswer();
                await pc.setLocalDescription(answer);
                socket.emit('group_call_signaling', {
                    to: fromUser,
                    type: 'answer',
                    answer: answer
                });
            } catch(e) {
                console.error("Error handling group offer from", fromUser, e);
            }
            
        } else if (data.type === 'answer') {
            if (pc) {
                try {
                    await pc.setRemoteDescription(new RTCSessionDescription(data.answer));
                } catch(e) {
                    console.error("Error setting group remote description from", fromUser, e);
                }
            }
        } else if (data.type === 'ice_candidate') {
            if (pc) {
                try {
                    await pc.addIceCandidate(new RTCIceCandidate(data.candidate));
                } catch(e) {
                    console.error("Error adding group ICE candidate from", fromUser, e);
                }
            }
        }
    }

    handleGroupUserLeft(data) {
        const username = data.username;
        console.log("User left group call:", username);
        const pc = this.groupPeerConnections[username];
        if (pc) {
            try {
                pc.close();
            } catch(e) {}
            delete this.groupPeerConnections[username];
        }
        const audioEl = document.getElementById(`remote-audio-${username}`);
        if (audioEl) audioEl.remove();
    }

    async saveCallLog(status, duration) {
        if (!this.isCaller) return;
        const target = this.callTarget;
        if (!target) return;
        
        console.log(`[DEBUG CALL LOG] Saving call log: status=${status}, duration=${duration}, target=${target}`);
        try {
            const res = await fetch('/api/calls/log', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    recipient: target,
                    status: status,
                    duration: duration
                })
            });
            const data = await res.json();
            if (data.success) {
                console.log("[DEBUG CALL LOG] Call log saved successfully:", data.data.message);
            }
        } catch(e) {
            console.error("[DEBUG CALL LOG] Failed to save call log:", e);
        }
    }

    cleanup() {
        this.stopSounds();
        if(this.peerConnection) {
            try {
                this.peerConnection.close();
            } catch(e) {
                console.error("Error closing peerConnection:", e);
            }
            this.peerConnection = null;
        }
        
        // Clean up group connections
        if (this.groupPeerConnections) {
            Object.keys(this.groupPeerConnections).forEach(username => {
                try {
                    this.groupPeerConnections[username].close();
                } catch(e) {
                    console.error("Error closing group peer connection for", username, e);
                }
                const audioEl = document.getElementById(`remote-audio-${username}`);
                if (audioEl) audioEl.remove();
            });
            this.groupPeerConnections = {};
        }
        
        if (this.isInGroupCall && this.groupCallName) {
            socket.emit('group_call_leave', { group_name: this.groupCallName });
        }
        this.isInGroupCall = false;
        this.groupCallName = '';

        if(this.localStream) {
            try {
                this.localStream.getTracks().forEach(track => track.stop());
            } catch(e) {
                console.error("Error stopping local tracks:", e);
            }
            this.localStream = null;
        }
        clearInterval(this.callTimerInterval);
        const timerEl = this.timer;
        if(timerEl) timerEl.innerText = "00:00";
        this.isCaller = false;
        this.callTarget = '';
        this.isLocked = false;
        this.iceQueue = [];
    }
}

// Ensure execution globally
window.webrtcManager = new WebRTCManager();

window.startDirectCall = function(target) {
    if(target === myUsername) return;
    if(window.webrtcManager) window.webrtcManager.startCall(target);
};

if(document.getElementById('voice-call-btn')) {
    document.getElementById('voice-call-btn').onclick = () => {
        if(!currentTarget || currentTarget === 'All') return;
        window.startDirectCall(currentTarget);
    };
}

if(document.getElementById('group-call-btn')) {
    document.getElementById('group-call-btn').onclick = () => {
        if(!currentTarget || currentTarget === 'All') return;
        if(window.webrtcManager) window.webrtcManager.startGroupCall(currentTarget);
    };
}
