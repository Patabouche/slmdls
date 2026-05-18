/* Notification MAJ launcher — lien slimedeals.fr (pas d'install auto) */
(function(global) {
    'use strict';

    var DEFAULT_URL = 'https://slimedeals.fr/launcher';
    var _bound = false;
    var _lastUrl = DEFAULT_URL;

    function _openDownloadPage() {
        if (typeof Bridge !== 'undefined' && Bridge.call) {
            Bridge.call('open_url', _lastUrl);
        } else {
            window.open(_lastUrl, '_blank', 'noopener,noreferrer');
        }
    }

    function _bindOnce() {
        if (_bound) return;
        _bound = true;
        var btn = document.getElementById('launcher-update-download-btn');
        if (btn) {
            btn.addEventListener('click', function() {
                _openDownloadPage();
            });
        }
    }

    function show(opts) {
        opts = opts || {};
        _lastUrl = (opts.url || DEFAULT_URL).trim() || DEFAULT_URL;
        var cur = document.getElementById('launcher-update-current');
        var rem = document.getElementById('launcher-update-remote');
        if (cur) cur.textContent = opts.current || '—';
        if (rem) rem.textContent = opts.remote || '—';
        _bindOnce();
        if (typeof Components !== 'undefined' && Components.showModal) {
            Components.showModal('launcher-update-modal');
        }
    }

    global.SlimeDealsLauncherUpdate = { show: show };
})(window);
