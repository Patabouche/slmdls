/* Mise à jour obligatoire du launcher — lien slimedeals.fr (pas d'install auto, pas de « Plus tard ») */
(function(global) {
    'use strict';

    var DEFAULT_URL = 'https://slimedeals.fr/launcher';
    var MODAL_ID = 'launcher-update-modal';
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

    function _lockUi() {
        global.__SLIMEDEALS_LAUNCHER_UPDATE_REQUIRED__ = true;
        document.body.classList.add('sd-launcher-update-blocked');
        var modal = document.getElementById(MODAL_ID);
        if (modal) {
            modal.classList.add('launcher-update-mandatory');
            modal.classList.remove('hidden');
        }
        document.body.classList.add('sd-modal-open');
    }

    function show(opts) {
        opts = opts || {};
        _lastUrl = (opts.url || DEFAULT_URL).trim() || DEFAULT_URL;
        var cur = document.getElementById('launcher-update-current');
        var rem = document.getElementById('launcher-update-remote');
        if (cur) cur.textContent = opts.current || '—';
        if (rem) rem.textContent = opts.remote || '—';
        _bindOnce();
        _lockUi();
        var modal = document.getElementById(MODAL_ID);
        if (modal) {
            var content = modal.querySelector('.modal-content');
            if (content) {
                content.classList.remove('modal-sd-enter');
                void content.offsetWidth;
                content.classList.add('modal-sd-enter');
            }
        }
    }

    global.SlimeDealsLauncherUpdate = { show: show };
})(window);
