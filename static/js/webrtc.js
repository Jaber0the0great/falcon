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
        this.isVideoCall = false;
        
        this.iceQueue = [];
        this.lastConfigFetch = 0;
        
        // Group call variables
        this.isInGroupCall = false;
        this.groupCallName = '';
        this.groupPeerConnections = {}; // username -> RTCPeerConnection
        
        this.ensureDOMExists();
        this.loadWebRTCConfig();
    }

    async loadWebRTCConfig(force = false) {
        const now = Date.now();
        if (!force && this.config.iceServers && this.config.iceServers.length > 0 && (now - this.lastConfigFetch < 300000)) {
            return this.config;
        }
        try {
            const res = await fetch('/api/webrtc_config');
            const data = await res.json();
            if(data.success && data.data.iceServers) {
                this.config = { 'iceServers': data.data.iceServers };
                this.lastConfigFetch = now;
                console.log("Loaded WebRTC ICE configuration:", this.config);
            }
        } catch(e) {
            console.error("Failed to load WebRTC config, using fallback STUN/TURN:", e);
            this.config = {
                'iceServers': [
                    { 'urls': 'stun:falconchat.duckdns.org:3478' },
                    { 'urls': 'stun:193.122.83.255:3478' }
                ]
            };
        }
        return this.config;
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
    get videoBtn() { return document.getElementById('video-toggle-btn'); }
    get screenShareBtn() { return document.getElementById('screenshare-call-btn'); }
    get minimizeBtn() { return document.getElementById('call-minimize-btn'); }
    get fullscreenBtn() { return document.getElementById('call-fullscreen-btn'); }
    get audioPlaceholder() { return document.getElementById('call-audio-placeholder'); }
    get localVideoWrapper() { return document.getElementById('local-video-wrapper'); }
    get statusLabel() { return document.getElementById('call-status-label'); }
    
    ensureDOMExists() {
        let oldScreen = document.getElementById('active-call-screen');
        if(oldScreen) oldScreen.remove();

        let oldAudio = document.getElementById('remote-audio');
        if(oldAudio) oldAudio.remove();

        // Place the screen INSIDE the chat area, right above the footer
        const screenHtml = `
        <div id="active-call-screen" tabindex="-1" role="dialog" aria-modal="true" aria-label="Active Call Screen" class="d-none" style="display:none;">
            <!-- Top Floating Header Bar -->
            <div class="call-header-bar">
                <div class="call-user-info">
                    <div class="call-avatar" id="call-avatar-icon">👤</div>
                    <div class="call-meta">
                        <h3 id="call-title" class="call-username">Connecting...</h3>
                        <div class="call-submeta">
                            <span id="call-timer" class="call-duration" aria-hidden="true">00:00</span>
                            <span class="call-quality-badge" id="call-quality-badge">🔒 Encrypted</span>
                        </div>
                    </div>
                </div>
                <div class="call-window-actions">
                    <button id="call-minimize-btn" onclick="window.webrtcManager.toggleMinimizeCall()" class="call-win-btn" title="Minimize Floating Window" type="button" aria-label="Minimize Floating Window">
                        <i class="bi bi-dash-lg" id="minimize-icon" aria-hidden="true"></i>
                    </button>
                    <button id="call-fullscreen-btn" onclick="window.webrtcManager.toggleFullscreenCall()" class="call-win-btn" title="Toggle Fullscreen" type="button" aria-label="Toggle Fullscreen">
                        <i class="bi bi-arrows-fullscreen" aria-hidden="true"></i>
                    </button>
                </div>
            </div>

            <!-- Central Media Stage -->
            <div class="call-media-stage" id="call-media-stage">
                <!-- Audio Wave Placeholder / Ringing Radar -->
                <div class="call-audio-placeholder" id="call-audio-placeholder">
                    <div class="radar-pulse-ring ring-1"></div>
                    <div class="radar-pulse-ring ring-2"></div>
                    <div class="radar-pulse-ring ring-3"></div>
                    <div class="call-center-avatar">
                        <span id="call-center-avatar-text" style="font-size: 3.2rem;">📞</span>
                    </div>
                    <div class="call-status-label" id="call-status-label">Calling...</div>
                </div>

                <!-- Remote Video Element -->
                <video id="remote-video" autoplay playsinline></video>

                <!-- Local Video Floating Wrapper -->
                <div class="local-video-wrapper" id="local-video-wrapper">
                    <video id="local-video" autoplay playsinline muted></video>
                    <div class="local-video-overlay"><span>You</span></div>
                </div>
            </div>

            <!-- Bottom Floating Action Bar -->
            <div class="call-controls-bar" role="group" aria-label="Call Controls">
                <button id="accept-call-btn" onclick="window.webrtcManager.acceptCall()" class="call-btn btn-accept" style="display:none;" title="Answer Call" aria-label="Answer Call" type="button">
                    <i class="bi bi-telephone-fill" aria-hidden="true"></i>
                </button>
                <button id="reject-call-btn" onclick="window.webrtcManager.rejectCall()" class="call-btn btn-reject" style="display:none;" title="Decline Call" aria-label="Decline Call" type="button">
                    <i class="bi bi-telephone-x-fill" aria-hidden="true"></i>
                </button>
                <button id="mute-call-btn" onclick="window.webrtcManager.toggleMute()" class="call-btn btn-secondary" style="display:none;" title="Mute Microphone" aria-label="Mute Microphone" type="button">
                    <i class="bi bi-mic-fill" id="mute-icon" aria-hidden="true"></i>
                </button>
                <button id="video-toggle-btn" onclick="window.webrtcManager.toggleVideo()" class="call-btn btn-secondary" style="display:none;" title="Turn On Camera" aria-label="Turn On Camera" type="button">
                    <i class="bi bi-camera-video-fill" id="video-icon" aria-hidden="true"></i>
                </button>
                <button id="screenshare-call-btn" onclick="window.webrtcManager.toggleScreenShare()" class="call-btn btn-secondary" style="display:none;" title="Share Screen" aria-label="Share Screen" type="button">
                    <i class="bi bi-display" id="screenshare-icon" aria-hidden="true"></i>
                </button>
                <button id="end-call-btn" onclick="window.webrtcManager.endCall(true)" class="call-btn btn-end" style="display:none;" title="End Call" aria-label="End Call" type="button">
                    <i class="bi bi-telephone-fill" style="transform: rotate(135deg); display: inline-block;" aria-hidden="true"></i>
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
        
        this.setupKeyboardShortcuts();
    }

    setupKeyboardShortcuts() {
        if (this._keyboardListenerAttached) return;
        this._keyboardListenerAttached = true;
        
        window.addEventListener('keydown', (e) => {
            if (!this.isInCall()) return;
            const activeEl = document.activeElement;
            if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.isContentEditable)) {
                return; // User is typing message
            }
            if (e.key === 'm' || e.key === 'M') {
                e.preventDefault();
                this.toggleMute();
            } else if (e.key === 'v' || e.key === 'V') {
                e.preventDefault();
                this.toggleVideo();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                this.endCall(true);
            }
        });
    }

    toggleMinimizeCall() {
        const scr = this.screen;
        if (!scr) return;
        scr.classList.toggle('minimized-call');
        const minIcon = document.getElementById('minimize-icon');
        if (minIcon) {
            if (scr.classList.contains('minimized-call')) {
                minIcon.className = 'bi bi-arrows-angle-expand';
            } else {
                minIcon.className = 'bi bi-dash-lg';
            }
        }
    }

    toggleFullscreenCall() {
        const scr = this.screen;
        if (!scr) return;
        if (!document.fullscreenElement) {
            if (scr.requestFullscreen) scr.requestFullscreen();
            else if (scr.webkitRequestFullscreen) scr.webkitRequestFullscreen();
        } else {
            if (document.exitFullscreen) document.exitFullscreen();
        }
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
        scr.classList.remove('minimized-call');
        scr.style.display = 'flex';
        scr.focus();
        
        if(this.title) this.title.innerText = target;
        if(this.statusLabel) this.statusLabel.innerText = "Calling...";
        if(this.timer) this.timer.innerText = "00:00";
        
        const avatarIcon = document.getElementById('call-center-avatar-text');
        if(avatarIcon) avatarIcon.innerText = this.isVideoCall ? '📹' : '📞';
        
        const placeholder = this.audioPlaceholder;
        if(placeholder) placeholder.style.display = 'flex';
        
        if(this.remoteVideo) this.remoteVideo.style.display = 'none';
        if(this.localVideoWrapper) this.localVideoWrapper.style.display = this.isVideoCall ? 'block' : 'none';
        
        if(this.acceptBtn) this.acceptBtn.style.display = 'none';
        if(this.rejectBtn) this.rejectBtn.style.display = 'none';
        if(this.endBtn) this.endBtn.style.display = 'flex';
        if(this.muteBtn) this.muteBtn.style.display = 'flex';
        if(this.videoBtn) this.videoBtn.style.display = 'flex';
        if(this.screenShareBtn) this.screenShareBtn.style.display = 'flex';
        
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
        scr.classList.remove('minimized-call');
        scr.style.display = 'flex';
        scr.focus();
        
        if(this.title) this.title.innerText = caller;
        if(this.statusLabel) this.statusLabel.innerText = "Incoming call...";
        if(this.timer) this.timer.innerText = "00:00";
        
        const placeholder = this.audioPlaceholder;
        if(placeholder) placeholder.style.display = 'flex';
        
        if(this.remoteVideo) this.remoteVideo.style.display = 'none';
        if(this.localVideoWrapper) this.localVideoWrapper.style.display = 'none';
        
        if(this.acceptBtn) this.acceptBtn.style.display = 'flex';
        if(this.rejectBtn) this.rejectBtn.style.display = 'flex';
        if(this.endBtn) this.endBtn.style.display = 'none';
        if(this.muteBtn) this.muteBtn.style.display = 'none';
        if(this.videoBtn) this.videoBtn.style.display = 'none';
        if(this.screenShareBtn) this.screenShareBtn.style.display = 'none';
        
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
        if(this.statusLabel) this.statusLabel.innerText = "Connecting...";
        if(this.acceptBtn) this.acceptBtn.style.display = 'none';
        if(this.rejectBtn) this.rejectBtn.style.display = 'none';
        if(this.endBtn) this.endBtn.style.display = 'flex';
        if(this.muteBtn) this.muteBtn.style.display = 'flex';
        if(this.videoBtn) this.videoBtn.style.display = 'flex';
        if(this.screenShareBtn) this.screenShareBtn.style.display = 'flex';
    }

    showInCallUI(target) {
        this.stopSounds();
        if(this.title) this.title.innerText = target;
        if(this.statusLabel) this.statusLabel.innerText = "Connected (HD)";
        
        const placeholder = this.audioPlaceholder;
        if (this.isVideoCall) {
            if(placeholder) placeholder.style.display = 'none';
            if(this.remoteVideo) this.remoteVideo.style.display = 'block';
            if(this.localVideoWrapper) this.localVideoWrapper.style.display = 'block';
        } else {
            if(placeholder) placeholder.style.display = 'flex';
        }
        
        if(this.acceptBtn) this.acceptBtn.style.display = 'none';
        if(this.rejectBtn) this.rejectBtn.style.display = 'none';
        if(this.endBtn) this.endBtn.style.display = 'flex';
        if(this.muteBtn) this.muteBtn.style.display = 'flex';
        if(this.videoBtn) this.videoBtn.style.display = 'flex';
        if(this.screenShareBtn) this.screenShareBtn.style.display = 'flex';
        
        this.startTimer();
        this.startAudioHealthMonitor();
    }
    
    showErrorUI(errorMessage) {
        this.stopSounds();
        if(this.statusLabel) this.statusLabel.innerText = errorMessage;
        
        if(this.acceptBtn) this.acceptBtn.style.display = 'none';
        if(this.rejectBtn) this.rejectBtn.style.display = 'none';
        if(this.endBtn) this.endBtn.style.display = 'flex';
        if(this.muteBtn) this.muteBtn.style.display = 'none';
        if(this.videoBtn) this.videoBtn.style.display = 'none';
        if(this.screenShareBtn) this.screenShareBtn.style.display = 'none';
    }
    
    hideCallUI() {
        this.stopSounds();
        const scr = this.screen;
        if(scr) {
            scr.style.display = 'none';
            scr.classList.add('d-none');
            scr.classList.remove('minimized-call');
        }
    }
    
    // --- CORE LOGIC
    async getAudioStream() {
        if(this.localStream) {
            try { this.localStream.getTracks().forEach(t => t.stop()); } catch(e) {}
            this.localStream = null;
        }
        
        const audioConstraints = {
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            },
            video: false
        };

        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
            try {
                return await navigator.mediaDevices.getUserMedia(audioConstraints);
            } catch(e) {
                return await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
            }
        } else if (navigator.getUserMedia) {
            return new Promise((resolve, reject) => {
                navigator.getUserMedia(audioConstraints, resolve, reject);
            });
        } else if (navigator.webkitGetUserMedia) {
            return new Promise((resolve, reject) => {
                navigator.webkitGetUserMedia(audioConstraints, resolve, reject);
            });
        } else {
            throw new Error("Browser does not support microphone access over this connection");
        }
    }

    async getVideoStream(withAudio = true) {
        if(this.localStream) {
            try { this.localStream.getTracks().forEach(t => t.stop()); } catch(e) {}
            this.localStream = null;
        }
        
        const constraints = {
            audio: withAudio ? {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            } : false,
            video: {
                width: { ideal: 1280 },
                height: { ideal: 720 },
                facingMode: 'user'
            }
        };

        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
            return await navigator.mediaDevices.getUserMedia(constraints);
        } else {
            throw new Error("Browser does not support camera access");
        }
    }

    async startCall(target) {
        if(this.isInCall()) {
            alert("You are already in an active call!");
            return;
        }
        if(this.isLocked) return;
        this.isLocked = true;
        this.isVideoCall = false;
        
        this.callTarget = target;
        this.isCaller = true;
        this.iceQueue = [];
        
        this.showCallingUI(target);
        
        const audioEl = this.remoteAudio;
        if(audioEl) {
            audioEl.play().catch(e => console.log("Audio unlocked for caller:", e));
        }
        
        try {
            await this.loadWebRTCConfig(true);
            this.localStream = await this.getAudioStream();
            this.setupPeerConnection(target);
            
            const offer = await this.peerConnection.createOffer({
                offerToReceiveAudio: true,
                offerToReceiveVideo: true
            });
            await this.peerConnection.setLocalDescription(offer);
            
            socket.emit('webrtc_signaling', {
                to: target,
                from: myUsername,
                type: 'offer',
                offer: offer,
                sdp: offer.sdp,
                isVideo: false
            });
            
            this.isLocked = false;
        } catch(err) {
            console.error("WebRTC Error:", err);
            this.cleanup();
            const msg = err.name === 'NotAllowedError' ? 'Error: Please grant microphone access' : `Error: ${err.message || 'Call failed'}`;
            this.showErrorUI(msg);
        }
    }

    async startVideoCall(target) {
        if(this.isInCall()) {
            alert("You are already in an active call!");
            return;
        }
        if(this.isLocked) return;
        this.isLocked = true;
        this.isVideoCall = true;
        
        this.callTarget = target;
        this.isCaller = true;
        this.iceQueue = [];
        
        this.showCallingUI(target);
        
        const audioEl = this.remoteAudio;
        if(audioEl) {
            audioEl.play().catch(e => console.log("Audio unlocked for caller:", e));
        }
        
        try {
            await this.loadWebRTCConfig(true);
            this.localStream = await this.getVideoStream(true);
            
            const localVid = this.localVideo;
            if(localVid) {
                localVid.srcObject = this.localStream;
                localVid.style.display = 'block';
            }
            
            const videoToggle = this.videoBtn;
            if(videoToggle) {
                videoToggle.style.background = '#3b82f6';
            }
            
            this.setupPeerConnection(target);
            
            const offer = await this.peerConnection.createOffer({
                offerToReceiveAudio: true,
                offerToReceiveVideo: true
            });
            await this.peerConnection.setLocalDescription(offer);
            
            socket.emit('webrtc_signaling', {
                to: target,
                from: myUsername,
                type: 'offer',
                offer: offer,
                sdp: offer.sdp,
                isVideo: true
            });
            
            this.isLocked = false;
        } catch(err) {
            console.error("WebRTC Video Error:", err);
            this.cleanup();
            const msg = err.name === 'NotAllowedError' ? 'Error: Please grant camera & microphone access' : `Error: ${err.message || 'Video call failed'}`;
            this.showErrorUI(msg);
        }
    }

    async toggleVideo() {
        if (!this.peerConnection) return;
        
        let videoTrack = this.localStream ? this.localStream.getVideoTracks()[0] : null;
        const videoBtnEl = this.videoBtn;
        const localVid = this.localVideo;
        
        if (videoTrack) {
            videoTrack.enabled = !videoTrack.enabled;
            const isEnabled = videoTrack.enabled;
            if (videoBtnEl) {
                videoBtnEl.style.background = isEnabled ? '#3b82f6' : '#64748b';
                const vLabel = isEnabled ? "Turn Off Camera" : "Turn On Camera";
                videoBtnEl.title = vLabel;
                videoBtnEl.setAttribute('aria-label', vLabel);
                videoBtnEl.setAttribute('aria-pressed', isEnabled.toString());
            }
            if (localVid) {
                localVid.style.display = isEnabled ? 'block' : 'none';
            }
            if (isEnabled) {
                this.isVideoCall = true;
            } else {
                const remoteActive = this.remoteVideo && this.remoteVideo.style.display === 'block';
                if (!remoteActive) {
                    this.isVideoCall = false;
                    const avatarEl = document.getElementById('webrtc-avatar-container');
                    if (avatarEl) avatarEl.style.display = 'flex';
                }
            }
            if (this.callTarget) {
                socket.emit('webrtc_signaling', {
                    to: this.callTarget,
                    from: myUsername,
                    type: 'video_toggle',
                    isVideoOn: isEnabled
                });
            }
        } else {
            try {
                const camStream = await navigator.mediaDevices.getUserMedia({
                    video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' }
                });
                const newVideoTrack = camStream.getVideoTracks()[0];
                if (!newVideoTrack) return;
                
                if (this.localStream) {
                    this.localStream.addTrack(newVideoTrack);
                } else {
                    this.localStream = camStream;
                }
                
                if (localVid) {
                    localVid.srcObject = this.localStream;
                    localVid.style.display = 'block';
                }
                
                this.isVideoCall = true;
                
                const sender = this.peerConnection.getSenders().find(s => s.track && s.track.kind === 'video');
                if (sender) {
                    await sender.replaceTrack(newVideoTrack);
                } else {
                    this.peerConnection.addTrack(newVideoTrack, this.localStream);
                }
                
                if (videoBtnEl) {
                    videoBtnEl.style.background = '#3b82f6';
                    videoBtnEl.title = "Turn Off Camera";
                    videoBtnEl.setAttribute('aria-label', "Turn Off Camera");
                    videoBtnEl.setAttribute('aria-pressed', "true");
                }

                if (this.callTarget) {
                    socket.emit('webrtc_signaling', {
                        to: this.callTarget,
                        from: myUsername,
                        type: 'video_toggle',
                        isVideoOn: true
                    });
                }
            } catch(e) {
                console.error("Failed to start camera:", e);
                alert("Cannot access camera: " + (e.message || 'Permission denied'));
            }
        }
    }

    async toggleScreenShare() {
        if (!this.peerConnection) return;
        const screenBtnEl = this.screenShareBtn;
        const localVid = this.localVideo;
        
        if (this.isScreenSharing) {
            if (this.screenStream) {
                this.screenStream.getTracks().forEach(t => t.stop());
                this.screenStream = null;
            }
            this.isScreenSharing = false;
            if (screenBtnEl) {
                screenBtnEl.style.background = '#64748b';
                screenBtnEl.title = "Share Screen";
                screenBtnEl.setAttribute('aria-label', "Share Screen");
                screenBtnEl.setAttribute('aria-pressed', "false");
            }
            
            const videoTrack = this.localStream ? this.localStream.getVideoTracks()[0] : null;
            const sender = this.peerConnection.getSenders().find(s => s.track && s.track.kind === 'video');
            if (sender) {
                await sender.replaceTrack(videoTrack || null);
            }
            if (localVid) {
                if (videoTrack && videoTrack.enabled) {
                    localVid.srcObject = this.localStream;
                    localVid.style.display = 'block';
                } else {
                    localVid.style.display = 'none';
                }
            }
        } else {
            try {
                if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
                    alert("Screen sharing is not supported by your browser");
                    return;
                }
                const displayStream = await navigator.mediaDevices.getDisplayMedia({
                    video: { cursor: "always" },
                    audio: false
                });
                const screenTrack = displayStream.getVideoTracks()[0];
                if (!screenTrack) return;
                
                this.isScreenSharing = true;
                this.screenStream = displayStream;
                if (screenBtnEl) {
                    screenBtnEl.style.background = '#22c55e';
                    screenBtnEl.title = "Stop Screen Sharing";
                    screenBtnEl.setAttribute('aria-label', "Stop Screen Sharing");
                    screenBtnEl.setAttribute('aria-pressed', "true");
                }
                
                if (localVid) {
                    localVid.srcObject = displayStream;
                    localVid.style.display = 'block';
                }
                
                const sender = this.peerConnection.getSenders().find(s => s.track && s.track.kind === 'video');
                if (sender) {
                    await sender.replaceTrack(screenTrack);
                } else {
                    this.peerConnection.addTrack(screenTrack, displayStream);
                }
                
                screenTrack.onended = () => {
                    this.toggleScreenShare();
                };
            } catch(e) {
                console.warn("Screen sharing cancelled or denied:", e);
            }
        }
    }
    
    toggleMute() {
        if(this.localStream) {
            const track = this.localStream.getAudioTracks()[0];
            if(track) {
                track.enabled = !track.enabled;
                const muteBtnEl = this.muteBtn;
                const muteIcon = document.getElementById('mute-icon');
                if(muteBtnEl) {
                    const label = track.enabled ? 'Mute Microphone' : 'Unmute Microphone';
                    muteBtnEl.title = label;
                    muteBtnEl.setAttribute('aria-label', label);
                    muteBtnEl.setAttribute('aria-pressed', (!track.enabled).toString());
                    if (track.enabled) {
                        muteBtnEl.classList.remove('muted-state');
                        muteBtnEl.style.background = 'rgba(255, 255, 255, 0.12)';
                        if (muteIcon) muteIcon.className = 'bi bi-mic-fill';
                    } else {
                        muteBtnEl.classList.add('muted-state');
                        muteBtnEl.style.background = 'linear-gradient(135deg, #ef4444, #b91c1c)';
                        if (muteIcon) muteIcon.className = 'bi bi-mic-mute-fill';
                    }
                }
            }
        }
    }
    
    handleSignaling(data) {
        if(data.type === 'offer') {
            if(this.isInCall() && this.callTarget === data.from) {
                console.log("Received renegotiation / ICE restart offer during active call from:", data.from);
                const sdpStr = data.sdp || (data.offer ? data.offer.sdp : '');
                if (sdpStr && this.peerConnection) {
                    this.peerConnection.setRemoteDescription(new RTCSessionDescription({ type: 'offer', sdp: sdpStr }))
                    .then(() => this.peerConnection.createAnswer())
                    .then(answer => {
                        return this.peerConnection.setLocalDescription(answer).then(() => answer);
                    })
                    .then(answer => {
                        socket.emit('webrtc_signaling', {
                            to: data.from,
                            from: myUsername,
                            type: 'answer',
                            answer: answer,
                            sdp: answer.sdp
                        });
                        this.processIceQueue();
                    })
                    .catch(e => console.error("Error handling renegotiation offer:", e));
                }
                return;
            }
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
            
        } else if(data.type === 'video_toggle') {
            const remoteVideoOn = !!data.isVideoOn;
            console.log("Remote video toggle received:", remoteVideoOn);
            const remoteVid = this.remoteVideo;
            const avatarEl = document.getElementById('webrtc-avatar-container');
            if (remoteVideoOn) {
                this.isVideoCall = true;
                if (remoteVid) remoteVid.style.display = 'block';
                if (avatarEl) avatarEl.style.display = 'none';
            } else {
                if (remoteVid) remoteVid.style.display = 'none';
                const localVideoActive = this.localStream && this.localStream.getVideoTracks().some(t => t.enabled);
                if (!localVideoActive) {
                    this.isVideoCall = false;
                    if (avatarEl) avatarEl.style.display = 'flex';
                }
            }
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
        this.stopSounds();
        this.showConnectingUI();
        
        const audioEl = this.remoteAudio;
        if(audioEl) {
            audioEl.play().catch(e => console.log("Audio unlocked for receiver:", e));
        }
        
        const target = this.callTarget;
        socket.emit('webrtc_signaling', {
            to: target,
            from: myUsername,
            type: 'accepted'
        });
        
        try {
            await this.loadWebRTCConfig(true);
            this.localStream = await this.getAudioStream();
            this.setupPeerConnection(target);
            
            const sdpOffer = typeof this.incomingOffer === 'string' ? this.incomingOffer : (this.incomingOffer && this.incomingOffer.sdp ? this.incomingOffer.sdp : (this.incomingSdp || ''));
            if(!sdpOffer) {
                throw new Error("Missing SDP offer string from remote peer");
            }
            const offerDesc = new RTCSessionDescription({ type: 'offer', sdp: sdpOffer });
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
        const iceServers = (this.config && this.config.iceServers && this.config.iceServers.length > 0)
            ? this.config.iceServers
            : [
                { urls: 'stun:falconchat.duckdns.org:3478' },
                { urls: 'stun:193.122.83.255:3478' }
            ];

        this.peerConnection = new RTCPeerConnection({
            iceServers: iceServers,
            sdpSemantics: 'unified-plan',
            bundlePolicy: 'max-bundle',
            rtcpMuxPolicy: 'require'
        });
        
        this.peerConnection.onconnectionstatechange = (event) => {
            if (!this.peerConnection) return;
            const state = this.peerConnection.connectionState;
            console.log("WebRTC Connection State changed to:", state);
            if (state === 'connected') {
                this.showInCallUI(this.callTarget);
            } else if (state === 'disconnected' || state === 'failed' || state === 'closed') {
                this.showErrorUI("Call disconnected");
                if (this.isCaller) {
                    this.saveCallLog('completed', this.callSeconds);
                }
                this.cleanup();
                setTimeout(() => this.hideCallUI(), 3000);
            }
        };
        
        this.peerConnection.oniceconnectionstatechange = (event) => {
            if (!this.peerConnection) return;
            const iceState = this.peerConnection.iceConnectionState;
            console.log("WebRTC ICE Connection State changed to:", iceState);
            if (iceState === 'failed') {
                console.warn("ICE connection failed, triggering ICE restart...");
                if (this.isCaller && typeof this.peerConnection.restartIce === 'function') {
                    this.peerConnection.restartIce();
                }
            }
        };
        
        if (this.localStream) {
            this.localStream.getTracks().forEach(track => {
                this.peerConnection.addTrack(track, this.localStream);
            });
        }

        // Ensure audio transceiver direction is sendrecv
        try {
            this.peerConnection.getTransceivers().forEach(transceiver => {
                if (transceiver.receiver && transceiver.receiver.track && transceiver.receiver.track.kind === 'audio') {
                    transceiver.direction = 'sendrecv';
                }
            });
        } catch(e) {
            console.warn("Could not set transceiver direction:", e);
        }
        
        this.peerConnection.ontrack = (event) => {
            console.log("OnTrack: remote track received", event.track.kind, event);
            if (event.track.kind === 'audio') {
                const audioEl = this.remoteAudio || document.getElementById('remote-audio');
                if(audioEl) {
                    audioEl.muted = false;
                    audioEl.volume = 1.0;
                    if (event.streams && event.streams[0]) {
                        audioEl.srcObject = event.streams[0];
                    } else {
                        const newStream = new MediaStream([event.track]);
                        audioEl.srcObject = newStream;
                    }
                    const playPromise = audioEl.play();
                    if (playPromise !== undefined) {
                        playPromise.then(() => {
                            console.log("Remote audio is playing successfully");
                        }).catch(e => {
                            console.warn("Remote audio play blocked by browser autoplay policy, attaching interaction unlocker:", e);
                            const unlock = () => {
                                audioEl.play().catch(_ => {});
                                document.removeEventListener('click', unlock);
                                document.removeEventListener('touchstart', unlock);
                                document.removeEventListener('keydown', unlock);
                            };
                            document.addEventListener('click', unlock, { once: true });
                            document.addEventListener('touchstart', unlock, { once: true });
                            document.addEventListener('keydown', unlock, { once: true });
                        });
                    }
                }
            } else if (event.track.kind === 'video') {
                const remoteVid = document.getElementById('remote-video');
                if (remoteVid) {
                    if (event.streams && event.streams[0]) {
                        remoteVid.srcObject = event.streams[0];
                    } else {
                        const newStream = new MediaStream([event.track]);
                        remoteVid.srcObject = newStream;
                    }
                    remoteVid.play().catch(e => console.error("Remote video play blocked:", e));
                }
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
            }
        }, 1000);
    }

    startAudioHealthMonitor() {
        if (this._audioHealthTimer) clearTimeout(this._audioHealthTimer);
        this._hasRecoveredAudio = false;
        
        this._audioHealthTimer = setTimeout(() => {
            if (!this.isInCall() || this._hasRecoveredAudio || !this.peerConnection) return;
            
            this.peerConnection.getStats().then(stats => {
                let bytesRecv = 0;
                stats.forEach(report => {
                    if (report.type === 'inbound-rtp' && (report.kind === 'audio' || report.mediaType === 'audio')) {
                        bytesRecv += (report.bytesReceived || 0);
                    }
                });
                console.log("Web Audio Inbound Stats check: bytesReceived =", bytesRecv);
                if (bytesRecv === 0 && this.isInCall() && !this._hasRecoveredAudio) {
                    this._hasRecoveredAudio = true;
                    console.warn("Zero audio flow detected after 4s! Executing auto-recovery mechanism...");
                    
                    const audioEl = this.remoteAudio || document.getElementById('remote-audio');
                    if (audioEl) {
                        audioEl.muted = false;
                        audioEl.volume = 1.0;
                        audioEl.play().catch(e => console.log("Health check audio play retry:", e));
                    }
                    
                    if (this.isCaller && typeof this.peerConnection.restartIce === 'function') {
                        this.peerConnection.restartIce();
                    }
                } else {
                    console.log("Web Audio flow confirmed healthy");
                }
            }).catch(e => console.warn("Stats check error:", e));
        }, 4000);
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
        if (this.screenStream) {
            try { this.screenStream.getTracks().forEach(t => t.stop()); } catch(e) {}
            this.screenStream = null;
        }
        this.isScreenSharing = false;
        this.isVideoCall = false;
        
        const localVid = this.localVideo;
        if (localVid) {
            localVid.srcObject = null;
            localVid.style.display = 'none';
        }
        const remoteVid = this.remoteVideo;
        if (remoteVid) {
            remoteVid.srcObject = null;
            remoteVid.style.display = 'none';
        }
        if (this.videoBtn) {
            this.videoBtn.style.background = '#64748b';
            this.videoBtn.title = "Turn On Camera";
            this.videoBtn.setAttribute('aria-label', "Turn On Camera");
            this.videoBtn.setAttribute('aria-pressed', "false");
        }
        if (this.muteBtn) {
            this.muteBtn.classList.remove('muted-state');
            this.muteBtn.style.background = 'rgba(255, 255, 255, 0.12)';
            this.muteBtn.title = "Mute Microphone";
            this.muteBtn.setAttribute('aria-label', "Mute Microphone");
            this.muteBtn.setAttribute('aria-pressed', "false");
            const muteIcon = document.getElementById('mute-icon');
            if (muteIcon) muteIcon.className = 'bi bi-mic-fill';
        }
        if (this.screenShareBtn) {
            this.screenShareBtn.style.background = '#64748b';
            this.screenShareBtn.title = "Share Screen";
            this.screenShareBtn.setAttribute('aria-label', "Share Screen");
            this.screenShareBtn.setAttribute('aria-pressed', "false");
        }

        if (this._audioHealthTimer) {
            clearTimeout(this._audioHealthTimer);
            this._audioHealthTimer = null;
        }
        this._hasRecoveredAudio = false;
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

window.startDirectVideoCall = function(target) {
    if(target === myUsername) return;
    if(window.webrtcManager) window.webrtcManager.startVideoCall(target);
};

if(document.getElementById('voice-call-btn')) {
    document.getElementById('voice-call-btn').onclick = () => {
        if(!currentTarget || currentTarget === 'All') return;
        window.startDirectCall(currentTarget);
    };
}

if(document.getElementById('video-call-btn')) {
    document.getElementById('video-call-btn').onclick = () => {
        if(!currentTarget || currentTarget === 'All') return;
        window.startDirectVideoCall(currentTarget);
    };
}

if(document.getElementById('group-call-btn')) {
    document.getElementById('group-call-btn').onclick = () => {
        if(!currentTarget || currentTarget === 'All') return;
        if(window.webrtcManager) window.webrtcManager.startGroupCall(currentTarget);
    };
}

