(function() {
    'use strict';

    const $ = (id) => document.getElementById(id);
    const settingsUsername = $('settings-username');
    const settingsRenameBtn = $('settings-rename-btn');
    const settingsRenameStatus = $('settings-rename-status');
    const settingsRenamePreview = $('settings-rename-preview');
    const settingsTheme = $('settings-theme');
    const settingsDefaultStatus = $('settings-default-status');
    const settingsCurrentPw = $('settings-current-pw');
    const settingsNewPw = $('settings-new-pw');
    const settingsConfirmPw = $('settings-confirm-pw');
    const settingsPwStatus = $('settings-pw-status');
    const settingsPwBtn = $('settings-pw-btn');
    const pwChangeRedirectBtn = $('pw-change-redirect-btn');

    let currentSettings = {};

    function showToast(message, type) {
        var container = document.getElementById('toast-container');
        if (!container) return;
        var toast = document.createElement('div');
        toast.className = 'toast align-items-center text-bg-' + (type || 'success') + ' border-0 show';
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.setAttribute('aria-atomic', 'true');
        toast.innerHTML = '<div class="d-flex"><div class="toast-body">' + escapeHtml(message) + '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>';
        container.appendChild(toast);
        setTimeout(function() { toast.remove(); }, 4000);
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(text));
        return div.innerHTML;
    }

    function applyTheme(theme) {
        if (theme === 'system') {
            theme = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
        }
        document.documentElement.setAttribute('data-theme', theme);
    }

    pwChangeRedirectBtn.addEventListener('click', function() {
        window.location.href = '/login';
    });

    $('settings-btn').addEventListener('click', function() {
        loadSettings();
        var modal = new bootstrap.Modal($('settingsModal'));
        modal.show();
    });

    function loadSettings() {
        settingsRenameStatus.textContent = '';
        settingsRenamePreview.style.display = 'none';
        settingsRenameBtn.disabled = true;
        settingsPwStatus.textContent = '';

        fetch('/api/settings')
            .then(function(r) { return r.json(); })
            .then(function(resp) {
                if (!resp.success) return;
                currentSettings = resp.data;
                settingsUsername.value = resp.data.username;
                settingsTheme.value = resp.data.theme;
                settingsDefaultStatus.value = resp.data.default_status;
                checkUsernameAvailability(resp.data.username);
            })
            .catch(function() {});
    }

    settingsUsername.addEventListener('input', function() {
        var val = settingsUsername.value.trim();
        if (val === currentSettings.username) {
            settingsRenameBtn.disabled = true;
            settingsRenameStatus.textContent = '';
            settingsRenamePreview.style.display = 'none';
            return;
        }
        checkUsernameAvailability(val);
    });

    function checkUsernameAvailability(username) {
        if (!username || username.length < 3) {
            settingsRenameBtn.disabled = true;
            settingsRenameStatus.textContent = 'Must be at least 3 characters';
            settingsRenameStatus.className = 'small mt-1 text-warning';
            settingsRenamePreview.style.display = 'none';
            return;
        }

        fetch('/api/settings/check-username?username=' + encodeURIComponent(username))
            .then(function(r) { return r.json(); })
            .then(function(resp) {
                if (resp.success && resp.data.available) {
                    settingsRenameBtn.disabled = false;
                    settingsRenameStatus.textContent = 'Available';
                    settingsRenameStatus.className = 'small mt-1 text-success';
                    loadRenamePreview(username);
                } else {
                    settingsRenameBtn.disabled = true;
                    var reason = resp.data ? resp.data.reason : (resp.error ? resp.error.message : 'Unavailable');
                    settingsRenameStatus.textContent = reason;
                    settingsRenameStatus.className = 'small mt-1 text-danger';
                    settingsRenamePreview.style.display = 'none';
                }
            })
            .catch(function() {
                settingsRenameBtn.disabled = true;
            });
    }

    function loadRenamePreview(newUsername) {
        fetch('/api/settings/rename-preview?new_username=' + encodeURIComponent(newUsername))
            .then(function(r) { return r.json(); })
            .then(function(resp) {
                if (!resp.success) return;
                var p = resp.data;
                var parts = [];
                if (p.messages_sent) parts.push(p.messages_sent + ' messages sent');
                if (p.messages_received) parts.push(p.messages_received + ' messages received');
                if (p.messages_replied) parts.push(p.messages_replied + ' replies');
                if (p.groups_owned) parts.push(p.groups_owned + ' group(s) owned');
                if (p.group_memberships) parts.push(p.group_memberships + ' group memberships');
                if (p.invites_sent) parts.push(p.invites_sent + ' invite(s) sent');
                if (p.invites_received) parts.push(p.invites_received + ' invite(s) received');
                if (p.join_requests) parts.push(p.join_requests + ' join request(s)');

                settingsRenamePreview.innerHTML = '<strong>Rename preview:</strong> ' + parts.join(', ') + '. <em>Estimated ' + p.estimated_ms + 'ms</em>';
                settingsRenamePreview.style.display = 'block';
            })
            .catch(function() {});
    }

    settingsRenameBtn.addEventListener('click', function() {
        var newUsername = settingsUsername.value.trim();
        settingsRenameBtn.disabled = true;
        settingsRenameStatus.textContent = 'Renaming...';
        settingsRenameStatus.className = 'small mt-1 text-info';

        fetch('/api/settings/username', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
            body: JSON.stringify({ new_username: newUsername })
        })
        .then(function(r) { return r.json(); })
        .then(function(resp) {
            if (resp.success) {
                settingsRenameStatus.textContent = 'Renamed successfully!';
                settingsRenameStatus.className = 'small mt-1 text-success';
                currentSettings.username = resp.data.username;
                myUsername = resp.data.username;
                var el = document.getElementById('my-username');
                if (el) el.textContent = resp.data.username;
                showToast('Username changed to ' + resp.data.username + '. Some displays may update momentarily.', 'success');
                settingsRenameBtn.disabled = true;
                settingsRenamePreview.style.display = 'none';
            } else {
                settingsRenameStatus.textContent = resp.error ? resp.error.message : 'Rename failed';
                settingsRenameStatus.className = 'small mt-1 text-danger';
                settingsRenameBtn.disabled = false;
            }
        })
        .catch(function() {
            settingsRenameStatus.textContent = 'Network error';
            settingsRenameStatus.className = 'small mt-1 text-danger';
            settingsRenameBtn.disabled = false;
        });
    });

    settingsTheme.addEventListener('change', function() {
        var theme = settingsTheme.value;
        applyTheme(theme);

        fetch('/api/settings/theme', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
            body: JSON.stringify({ theme: theme })
        })
        .then(function(r) { return r.json(); })
        .then(function(resp) {
            if (resp.success) {
                showToast('Theme changed to ' + theme, 'success');
            }
        })
        .catch(function() {});
    });

    settingsDefaultStatus.addEventListener('change', function() {
        var ds = settingsDefaultStatus.value;

        fetch('/api/settings/default-status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
            body: JSON.stringify({ default_status: ds })
        })
        .then(function(r) { return r.json(); })
        .then(function(resp) {
            if (resp.success) {
                showToast('Default status changed to ' + ds, 'success');
            }
        })
        .catch(function() {});
    });

    settingsPwBtn.addEventListener('click', function() {
        var current = settingsCurrentPw.value;
        var newPw = settingsNewPw.value;
        var confirm = settingsConfirmPw.value;

        if (!current || !newPw || !confirm) {
            settingsPwStatus.textContent = 'All password fields are required';
            settingsPwStatus.className = 'small mb-2 text-warning';
            return;
        }

        if (newPw !== confirm) {
            settingsPwStatus.textContent = 'Passwords do not match';
            settingsPwStatus.className = 'small mb-2 text-danger';
            return;
        }

        if (newPw.length < 6) {
            settingsPwStatus.textContent = 'Password must be at least 6 characters';
            settingsPwStatus.className = 'small mb-2 text-danger';
            return;
        }

        settingsPwBtn.disabled = true;
        settingsPwStatus.textContent = 'Changing password...';
        settingsPwStatus.className = 'small mb-2 text-info';

        fetch('/api/settings/password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRFToken() },
            body: JSON.stringify({ current_password: current, new_password: newPw, confirm_password: confirm })
        })
        .then(function(r) { return r.json(); })
        .then(function(resp) {
            if (resp.success && resp.data.requires_relogin) {
                var settingsModal = bootstrap.Modal.getInstance($('settingsModal'));
                if (settingsModal) settingsModal.hide();
                setTimeout(function() {
                    var pwModal = new bootstrap.Modal($('pwChangeConfirmModal'));
                    pwModal.show();
                }, 300);
                settingsPwStatus.textContent = '';
                settingsCurrentPw.value = '';
                settingsNewPw.value = '';
                settingsConfirmPw.value = '';
            } else {
                settingsPwStatus.textContent = resp.error ? resp.error.message : 'Password change failed';
                settingsPwStatus.className = 'small mb-2 text-danger';
                settingsPwBtn.disabled = false;
            }
        })
        .catch(function() {
            settingsPwStatus.textContent = 'Network error';
            settingsPwStatus.className = 'small mb-2 text-danger';
            settingsPwBtn.disabled = false;
        });
    });

    function getCSRFToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }
})();
