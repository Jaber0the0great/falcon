(function() {
    'use strict';

    var originalFetch = window.fetch;

    function isSameOrigin(url) {
        try {
            var parsed = new URL(url, window.location.origin);
            return parsed.origin === window.location.origin;
        } catch (e) {
            return true;
        }
    }

    function getEffectiveMethod(input, init) {
        if (init && init.method) {
            return init.method.toUpperCase();
        }
        if (input && typeof input.method === 'string') {
            return input.method.toUpperCase();
        }
        return 'GET';
    }

    function headerExists(headers, name) {
        if (!headers) return false;
        if (typeof Headers !== 'undefined' && headers instanceof Headers) {
            return headers.has(name);
        }
        if (Array.isArray(headers)) {
            for (var i = 0; i < headers.length; i++) {
                if (headers[i][0] === name) return true;
            }
            return false;
        }
        return name in headers;
    }

    function setHeader(headers, name, value) {
        if (typeof Headers !== 'undefined' && headers instanceof Headers) {
            headers.set(name, value);
            return headers;
        }
        if (Array.isArray(headers)) {
            headers.push([name, value]);
            return headers;
        }
        headers[name] = value;
        return headers;
    }

    function csrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : null;
    }

    window.fetch = function(input, init) {
        var url = (typeof input === 'string') ? input :
                  (input && typeof input.url === 'string') ? input.url :
                  String(input);

        if (isSameOrigin(url)) {
            var method = getEffectiveMethod(input, init);
            if (method === 'POST' || method === 'PUT' || method === 'PATCH' || method === 'DELETE') {
                var token = csrfToken();
                if (token) {
                    if (!init) {
                        init = { headers: { 'X-CSRFToken': token } };
                    } else {
                        var h = init.headers;
                        if (!headerExists(h, 'X-CSRFToken')) {
                            init.headers = setHeader(h || {}, 'X-CSRFToken', token);
                        }
                    }
                }
            }
        }

        return originalFetch.call(this, input, init);
    };

    window.escapeHtml = function(str) {
        if (!str) return '';
        return str.replace(/[&<>"']/g, function(m) {
            return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[m];
        });
    };
})();
