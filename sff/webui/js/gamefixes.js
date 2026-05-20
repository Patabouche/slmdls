/**
 * SlimeDeals — Jeux VIP (téléchargement + installation)
 */
window.GameFixes = (function() {
    'use strict';

    var _catalog = [];
    var _progress = {};
    var _initialized = false;
    var _userRank = 'free';
    var _steamLibraries = [];
    var _pendingGame = null;
    var _customInstallPath = '';
    var _activeProgressGameId = null;
    var _partials = {};  // {game_id: {partial_bytes, partial_pct, partial_human}}
    var _installedIds = {};  // {catalog_id: true}
    var _progressModalOpen = false;
    var _vipPage = 1;
    var _vipSearch = '';
    var EL = 'd' + 'iv';

    var _UI_BLOCKLIST = /\b(buzzheavier|steamrip|steam\s*rip|repack|fafda\.to)\b/gi;

    function _tripleAllowed() {
        var r = String(_userRank || '').toLowerCase().replace(/\s+/g, '_');
        return r === 'triple' || r.indexOf('triple') !== -1;
    }

    function _sanitizeUserMessage(msg) {
        if (!msg) return '';
        var s = String(msg);
        s = s.replace(_UI_BLOCKLIST, '');
        s = s.replace(/https?:\/\/\S+/gi, function(url) {
            return /buzzheavier|fafda/i.test(url) ? '' : url;
        });
        s = s.replace(/\s{2,}/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
        return s;
    }

    function _coverUrlsForGame(g) {
        if (!g || typeof Components === 'undefined') return [];
        var canonical = g.header_image || g.image_url || '';
        var appId = String(g.app_id || '').trim();
        var urls = [];
        if (canonical) urls.push(String(canonical).split('?')[0]);
        if (appId) {
            var fromCdn = Components.getCoverUrls(appId);
            if (Array.isArray(fromCdn)) {
                fromCdn.forEach(function(u) {
                    if (u && urls.indexOf(u) === -1) urls.push(u);
                });
            }
        }
        return urls;
    }

    function _applyCoverBackground(coverEl, urls) {
        if (!coverEl) return;
        if (!urls || !urls.length) {
            coverEl.className = 'fixed-game-card-cover fixed-game-card-cover--placeholder';
            coverEl.style.backgroundImage = '';
            coverEl.textContent = '🎮';
            return;
        }
        var idx = 0;
        function tryNext() {
            if (idx >= urls.length) {
                coverEl.className = 'fixed-game-card-cover fixed-game-card-cover--placeholder';
                coverEl.style.backgroundImage = '';
                coverEl.textContent = '🎮';
                return;
            }
            var probe = new Image();
            probe.onload = function() {
                coverEl.className = 'fixed-game-card-cover';
                coverEl.textContent = '';
                coverEl.style.backgroundImage = 'url("' + urls[idx].replace(/"/g, '\\"') + '")';
            };
            probe.onerror = function() {
                idx += 1;
                tryNext();
            };
            probe.src = urls[idx];
        }
        tryNext();
    }

    function _setStatus(msg, isError) {
        var el = document.getElementById('gamefixes-status');
        if (!el) return;
        var clean = _sanitizeUserMessage(msg);
        if (!clean) {
            el.classList.add('hidden');
            el.textContent = '';
            return;
        }
        el.classList.remove('hidden');
        el.textContent = clean;
        el.classList.toggle('gamefixes-status--error', !!isError);
    }

    function _trimDecimal(s) {
        if (s.indexOf('.') >= 0) {
            s = s.replace(/0+$/, '').replace(/\.$/, '');
        }
        return s;
    }

    function _fmtBytes(b) {
        b = Number(b) || 0;
        var GB = 1024 * 1024 * 1024;
        var MB = 1024 * 1024;
        var KB = 1024;
        if (b >= GB) {
            var v = b / GB;
            if (v >= 100) return Math.round(v) + ' Go';
            if (v >= 10) return _trimDecimal(v.toFixed(1)) + ' Go';
            return _trimDecimal(v.toFixed(2)) + ' Go';
        }
        if (b >= MB) {
            var v = b / MB;
            if (v >= 100) return Math.round(v) + ' Mo';
            return _trimDecimal(v.toFixed(1)) + ' Mo';
        }
        if (b >= KB) return Math.round(b / KB) + ' Ko';
        return Math.round(b) + ' o';
    }

    function _fmtProgress(done, total) {
        done = Number(done) || 0;
        total = Number(total) || 0;
        if (total <= 0) return _fmtBytes(done);
        var GB = 1024 * 1024 * 1024;
        var MB = 1024 * 1024;
        function fmtGb(v) {
            var x = v / GB;
            if (x >= 10) return _trimDecimal(x.toFixed(1)) + ' Go';
            if (x >= 1) return _trimDecimal(x.toFixed(1)) + ' Go';
            return _trimDecimal(x.toFixed(2)) + ' Go';
        }
        function fmtMb(v) {
            var x = v / MB;
            if (x >= 100) return Math.round(x) + ' Mo';
            return _trimDecimal(x.toFixed(1)) + ' Mo';
        }
        if (total >= GB) return fmtGb(done) + ' / ' + fmtGb(total);
        if (total >= MB) return fmtMb(done) + ' / ' + fmtMb(total);
        return _fmtBytes(done) + ' / ' + _fmtBytes(total);
    }

    function _getGameById(gameId) {
        for (var i = 0; i < _catalog.length; i++) {
            if (_catalog[i].id === gameId) return _catalog[i];
        }
        return null;
    }

    function _selectedInstallTarget() {
        if (_customInstallPath) return _customInstallPath;
        var sel = document.getElementById('fixed-install-path-select');
        if (!sel || !sel.value) return '';
        return sel.value;
    }

    function _goToLibrary() {
        Components.hideModal('fixed-game-success-modal');
        Components.hideModal('fixed-game-progress-modal');
        _progressModalOpen = false;
        if (window.App && typeof App.navigateTo === 'function') {
            App.navigateTo('library');
        }
    }

    function _showInstallSuccessModal(gameName) {
        var nameEl = document.getElementById('fixed-game-success-name');
        if (nameEl) nameEl.textContent = gameName || 'Le jeu';
        Components.showModal('fixed-game-success-modal');
    }

    function _bindSuccessModal() {
        var root = document.getElementById('fixed-game-success-modal');
        if (!root || root.dataset.bound) return;
        root.dataset.bound = '1';

        function dismiss() {
            Components.hideModal('fixed-game-success-modal');
        }

        var libBtn = document.getElementById('fixed-game-success-library');
        var dismissBtn = document.getElementById('fixed-game-success-dismiss');
        var closeX = document.getElementById('fixed-game-success-close-x');
        var overlay = root.querySelector('.modal-overlay');

        if (libBtn) libBtn.addEventListener('click', _goToLibrary);
        if (dismissBtn) dismissBtn.addEventListener('click', dismiss);
        if (closeX) closeX.addEventListener('click', dismiss);
        if (overlay) overlay.addEventListener('click', dismiss);
    }

    function _loadInstalled(cb) {
        Bridge.callWithCallback('get_fixed_games_installed', function(json) {
            _installedIds = {};
            try {
                var d = JSON.parse(json || '{}');
                (d.installed_ids || []).forEach(function(id) {
                    if (id) _installedIds[id] = true;
                });
            } catch (e) {
                _installedIds = {};
            }
            _renderCards();
            if (typeof cb === 'function') cb();
        });
    }

    function _isGameInstalled(gameId) {
        return !!_installedIds[gameId];
    }

    function _progressModalEls() {
        return {
            modal: document.getElementById('fixed-game-progress-modal'),
            header: document.getElementById('fixed-game-progress-header'),
            title: document.getElementById('fixed-game-progress-title'),
            gameName: document.getElementById('fixed-progress-game-name'),
            bar: document.getElementById('fixed-progress-bar'),
            pct: document.getElementById('fixed-progress-pct'),
            status: document.getElementById('fixed-progress-status'),
            error: document.getElementById('fixed-progress-error'),
            minimizeBtn: document.getElementById('fixed-progress-minimize'),
            closeBtn: document.getElementById('fixed-progress-close'),
            modalX: document.getElementById('fixed-progress-modal-x')
        };
    }

    function _bannerEls() {
        return {
            banner: document.getElementById('fixed-install-banner'),
            game: document.getElementById('fixed-banner-game'),
            pct: document.getElementById('fixed-banner-pct'),
            bar: document.getElementById('fixed-banner-bar'),
            status: document.getElementById('fixed-banner-status'),
            expand: document.getElementById('fixed-banner-expand'),
            dismiss: document.getElementById('fixed-banner-dismiss')
        };
    }

    function _progressModalGameIdFromData(data) {
        var id = data.id || '';
        if (id.indexOf('fixed_game:') === 0) return id.split(':')[1] || '';
        return data.app_id || '';
    }

    function _statusFromProgressData(data) {
        var status = _sanitizeUserMessage(data.status || '');
        if (!status) {
            if (data.phase === 'extract') status = 'Extraction des fichiers du jeu…';
            else if (data.phase === 'download') status = 'Téléchargement en cours…';
            else status = 'Préparation…';
        }
        // Retire les % en double dans les anciens messages backend
        status = status.replace(/\d+\s*%/g, '').replace(/\s{2,}/g, ' ').trim();
        return status;
    }

    function _progressDetailText(prog) {
        if (!prog) return 'En cours…';
        if (prog.doneBytes && prog.totalBytes) {
            return _fmtProgress(prog.doneBytes, prog.totalBytes);
        }
        return _statusFromProgressData({ status: prog.status, phase: prog.phase });
    }

    function _setProgressModalButtons(finished) {
        var els = _progressModalEls();
        if (els.minimizeBtn) els.minimizeBtn.classList.toggle('hidden', !!finished);
        if (els.closeBtn) els.closeBtn.classList.toggle('hidden', !finished);
        if (els.modalX) {
            els.modalX.setAttribute('data-tooltip', finished ? 'Fermer' : 'Réduire');
            els.modalX.setAttribute('aria-label', finished ? 'Fermer' : 'Réduire');
        }
    }

    function _updateInstallBanner(gid) {
        var bel = _bannerEls();
        if (!bel.banner || !gid) return;
        var prog = _progress[gid];
        var game = _getGameById(gid);
        var name = (prog && prog.name) || (game && game.name) || gid;

        if (!prog) {
            bel.banner.classList.add('hidden');
            return;
        }

        bel.banner.classList.remove('hidden');
        bel.banner.classList.remove(
            'fixed-install-banner--ok',
            'fixed-install-banner--fail'
        );

        var pct = Math.max(0, Math.min(100, Number(prog.progress) || 0));

        if (bel.game) bel.game.textContent = name;
        if (bel.pct) bel.pct.textContent = pct + ' %';
        if (bel.bar) bel.bar.style.width = pct + '%';
        if (bel.status) bel.status.textContent = _progressDetailText(prog);

        if (prog.active) {
            if (bel.expand) bel.expand.classList.remove('hidden');
            if (bel.dismiss) bel.dismiss.classList.add('hidden');
        } else {
            if (prog.success) bel.banner.classList.add('fixed-install-banner--ok');
            else bel.banner.classList.add('fixed-install-banner--fail');
            if (bel.expand) bel.expand.classList.add('hidden');
            if (bel.dismiss) bel.dismiss.classList.remove('hidden');
        }
    }

    function _minimizeProgressModal() {
        var prog = _activeProgressGameId && _progress[_activeProgressGameId];
        if (!prog || !prog.active) return;
        _progressModalOpen = false;
        Components.hideModal('fixed-game-progress-modal');
        _updateInstallBanner(_activeProgressGameId);
    }

    function _expandProgressModal() {
        var gid = _activeProgressGameId;
        if (!gid || !_progress[gid]) return;
        var prog = _progress[gid];
        var els = _progressModalEls();
        var pct = Math.max(0, Math.min(100, Number(prog.progress) || 0));

        _progressModalOpen = true;
        if (els.gameName) {
            var game = _getGameById(gid);
            els.gameName.textContent = prog.name || (game && game.name) || gid;
        }
        if (prog.active) {
            _resetProgressModalHeader();
            _setProgressModalButtons(false);
            if (els.bar) els.bar.style.width = pct + '%';
            if (els.pct) els.pct.textContent = pct + ' %';
            if (els.status) els.status.textContent = _progressDetailText(prog);
            if (els.error) {
                els.error.classList.add('hidden');
                els.error.textContent = '';
            }
        } else {
            _finishProgressModal(!!prog.success, prog.status || '');
        }
        var bel = _bannerEls();
        if (bel.banner) bel.banner.classList.add('hidden');
        Components.showModal('fixed-game-progress-modal');
    }

    function _dismissInstallBanner() {
        var gid = _activeProgressGameId;
        var bel = _bannerEls();
        if (bel.banner) bel.banner.classList.add('hidden');
        if (gid && _progress[gid] && !_progress[gid].active) {
            delete _progress[gid];
            _activeProgressGameId = null;
            _renderCards();
        }
    }

    function _applyProgressUpdate(data) {
        var gid = _progressModalGameIdFromData(data);
        if (!gid) return;

        var pct = Math.max(0, Math.min(100, Number(data.progress) || 0));
        var status = _statusFromProgressData(data);
        var game = _getGameById(gid);

        _progress[gid] = {
            active: true,
            progress: pct,
            status: status,
            phase: data.phase || '',
            doneBytes: Number(data.done_bytes) || 0,
            totalBytes: Number(data.total_bytes) || 0,
            name: data.name || (game && game.name) || gid
        };
        _activeProgressGameId = gid;

        if (_progressModalOpen) {
            var els = _progressModalEls();
            if (els.bar) els.bar.style.width = pct + '%';
            if (els.pct) els.pct.textContent = pct + ' %';
            if (els.status) els.status.textContent = _progressDetailText(_progress[gid]);
        } else {
            _updateInstallBanner(gid);
        }
        _patchCardProgress(gid);
    }

    function _patchCardProgress(gid) {
        if (!gid || !_progress[gid] || !_progress[gid].active) return;
        var card = document.querySelector('.fixed-game-card[data-game-id="' + gid + '"]');
        if (!card) {
            _renderCards();
            return;
        }
        var prog = _progress[gid];
        var body = card.querySelector('.fixed-game-card-body');
        if (!body) return;
        var wrap = body.querySelector('.fixed-game-progress');
        if (!wrap) {
            wrap = document.createElement('div');
            wrap.className = 'fixed-game-progress';
            var bar = document.createElement('div');
            bar.className = 'fixed-game-progress-bar';
            wrap.appendChild(bar);
            body.appendChild(wrap);
        }
        var bar = wrap.querySelector('.fixed-game-progress-bar');
        if (bar) bar.style.width = (prog.progress || 0) + '%';
        var lbl = body.querySelector('.fixed-game-progress-label');
        if (!lbl) {
            lbl = document.createElement('p');
            lbl.className = 'fixed-game-progress-label';
            body.appendChild(lbl);
        }
        lbl.textContent = _progressDetailText(prog);
    }

    function _resetProgressModalHeader() {
        var els = _progressModalEls();
        if (!els.header || !els.title) return;
        els.header.classList.remove('fixed-progress-header--ok', 'fixed-progress-header--fail');
        els.title.textContent = 'Installation en cours';
        if (els.closeBtn) els.closeBtn.textContent = 'Fermer';
    }

    function _openProgressModal(game) {
        var els = _progressModalEls();
        if (!els.modal || !game) return;

        _activeProgressGameId = game.id;
        _progressModalOpen = true;
        _resetProgressModalHeader();
        _setProgressModalButtons(false);

        if (els.gameName) els.gameName.textContent = game.name || game.id;
        if (els.bar) els.bar.style.width = '0%';
        if (els.pct) els.pct.textContent = '0 %';
        if (els.status) els.status.textContent = 'Démarrage du téléchargement…';
        if (els.error) {
            els.error.classList.add('hidden');
            els.error.textContent = '';
        }

        _progress[game.id] = {
            active: true,
            progress: 0,
            status: 'Démarrage…',
            name: game.name || game.id
        };

        var bel = _bannerEls();
        if (bel.banner) bel.banner.classList.add('hidden');

        Components.showModal('fixed-game-progress-modal');
    }

    function _finishProgressModal(success, message) {
        var els = _progressModalEls();
        var clean = _sanitizeUserMessage(message);
        var gid = _activeProgressGameId;

        _setProgressModalButtons(true);

        if (gid) {
            _progress[gid] = {
                active: false,
                finished: true,
                success: !!success,
                progress: success ? 100 : (_progress[gid] ? _progress[gid].progress : 0),
                status: clean || (success ? 'Terminé' : 'Échec'),
                name: (_progress[gid] && _progress[gid].name) || gid
            };
        }

        if (success) {
            if (els.header) els.header.classList.add('fixed-progress-header--ok');
            if (els.title) els.title.textContent = 'Installation terminée';
            if (els.bar) els.bar.style.width = '100%';
            if (els.pct) els.pct.textContent = '100 %';
            if (els.status) {
                els.status.textContent =
                    'Installé — retrouve ce jeu dans la Bibliothèque du launcher.';
            }
            if (els.error) {
                els.error.classList.add('hidden');
                els.error.textContent = '';
            }
            if (els.closeBtn) {
                els.closeBtn.textContent = 'Voir dans la bibliothèque';
                els.closeBtn.classList.remove('hidden');
            }
        } else {
            if (els.closeBtn) els.closeBtn.textContent = 'Fermer';
            if (els.header) els.header.classList.add('fixed-progress-header--fail');
            if (els.title) els.title.textContent = 'Installation échouée';
            if (els.status) els.status.textContent = 'Une erreur est survenue.';
            if (els.error) {
                els.error.classList.remove('hidden');
                els.error.textContent = clean || 'Le téléchargement ou l’installation a échoué. Réessaie ou vérifie l’espace disque.';
            }
        }

        if (!_progressModalOpen && gid) {
            _updateInstallBanner(gid);
        }
    }

    function _bindProgressModal() {
        var modalRoot = document.getElementById('fixed-game-progress-modal');
        if (modalRoot && modalRoot.dataset.progressBound) return;
        if (modalRoot) modalRoot.dataset.progressBound = '1';

        function onMinimize() {
            var gid = _activeProgressGameId;
            if (gid && _progress[gid] && _progress[gid].active) {
                _minimizeProgressModal();
            } else {
                Components.hideModal('fixed-game-progress-modal');
                _progressModalOpen = false;
            }
        }

        function onCloseFinished() {
            var gid = _activeProgressGameId;
            var prog = gid && _progress[gid];
            if (prog && prog.success) {
                _goToLibrary();
                return;
            }
            Components.hideModal('fixed-game-progress-modal');
            _progressModalOpen = false;
            _dismissInstallBanner();
        }

        var minimizeBtn = document.getElementById('fixed-progress-minimize');
        var modalX = document.getElementById('fixed-progress-modal-x');
        var closeBtn = document.getElementById('fixed-progress-close');
        var overlay = document.querySelector('#fixed-game-progress-modal .modal-overlay');
        var expandBtn = document.getElementById('fixed-banner-expand');
        var dismissBtn = document.getElementById('fixed-banner-dismiss');

        if (minimizeBtn) {
            minimizeBtn.dataset.bound = '1';
            minimizeBtn.addEventListener('click', onMinimize);
        }
        if (modalX) {
            modalX.dataset.bound = '1';
            modalX.addEventListener('click', function() {
                var gid = _activeProgressGameId;
                if (gid && _progress[gid] && _progress[gid].active) onMinimize();
                else onCloseFinished();
            });
        }
        if (overlay) {
            overlay.dataset.bound = '1';
            overlay.addEventListener('click', function() {
                var gid = _activeProgressGameId;
                if (gid && _progress[gid] && _progress[gid].active) onMinimize();
                else if (gid && _progress[gid] && !_progress[gid].active) onCloseFinished();
            });
        }
        if (closeBtn) {
            closeBtn.dataset.bound = '1';
            closeBtn.addEventListener('click', onCloseFinished);
        }
        if (expandBtn) {
            expandBtn.dataset.bound = '1';
            expandBtn.addEventListener('click', _expandProgressModal);
        }
        if (dismissBtn) {
            dismissBtn.dataset.bound = '1';
            dismissBtn.addEventListener('click', function() {
                if (_progressModalOpen) {
                    Components.hideModal('fixed-game-progress-modal');
                    _progressModalOpen = false;
                }
                _dismissInstallBanner();
            });
        }
    }

    function _refreshDiskCheck() {
        if (!_pendingGame) return;
        var target = _selectedInstallTarget();
        var pathDisplay = document.getElementById('fixed-install-path-display');
        var confirmBtn = document.getElementById('fixed-install-confirm');
        var diskBox = document.getElementById('fixed-install-disk-box');
        var warnEl = document.getElementById('fixed-install-disk-warn');

        if (!target) {
            if (pathDisplay) pathDisplay.textContent = 'Choisis un emplacement ci-dessus.';
            if (confirmBtn) confirmBtn.disabled = true;
            if (diskBox) diskBox.classList.remove('fixed-install-disk-box--ok', 'fixed-install-disk-box--fail');
            return;
        }

        if (pathDisplay) {
            pathDisplay.textContent = 'Installation dans : ' + target + (_customInstallPath
                ? ''
                : ' (steamapps/common)');
        }

        Bridge.callWithCallback('check_fixed_game_install', _pendingGame.id, target, function(json) {
            try {
                var d = JSON.parse(json || '{}');
                var freeInst = document.getElementById('fixed-install-free-install');
                var freeTemp = document.getElementById('fixed-install-free-temp');
                var needEl = document.getElementById('fixed-install-need');
                if (freeInst) freeInst.textContent = d.free_install_human || _fmtBytes(d.free_install_bytes);
                if (freeTemp) freeTemp.textContent = d.free_temp_human || _fmtBytes(d.free_temp_bytes);
                if (needEl) needEl.textContent = d.required_human || _fmtBytes(d.required_with_margin_bytes);
                if (pathDisplay && d.install_path) {
                    pathDisplay.textContent = 'Installation dans : ' + d.install_path;
                }
                if (diskBox) {
                    diskBox.classList.toggle('fixed-install-disk-box--ok', !!d.ok);
                    diskBox.classList.toggle('fixed-install-disk-box--fail', !d.ok);
                }
                if (warnEl) {
                    if (d.ok) {
                        warnEl.classList.add('hidden');
                        warnEl.textContent = '';
                    } else {
                        warnEl.classList.remove('hidden');
                        warnEl.textContent = _sanitizeUserMessage(d.message) || 'Espace disque insuffisant.';
                    }
                }

                // Affichage bloc reprise si un fichier partiel existe
                var resumeBox = document.getElementById('fixed-install-resume-box');
                var resumeHuman = document.getElementById('fixed-install-resume-human');
                var resumePct = document.getElementById('fixed-install-resume-pct');
                var resumeBar = document.getElementById('fixed-install-resume-bar');
                var hasPartial = d.partial_bytes && d.partial_bytes > 0;
                if (resumeBox) resumeBox.classList.toggle('hidden', !hasPartial);
                if (hasPartial) {
                    if (resumeHuman) resumeHuman.textContent = d.partial_human || _fmtBytes(d.partial_bytes);
                    if (resumePct) resumePct.textContent = d.partial_pct || 0;
                    if (resumeBar) resumeBar.style.width = (d.partial_pct || 0) + '%';
                    if (confirmBtn) confirmBtn.textContent = 'Reprendre le téléchargement';
                } else {
                    if (confirmBtn) confirmBtn.textContent = 'Lancer le téléchargement';
                }

                if (confirmBtn) confirmBtn.disabled = !d.ok;
            } catch (e) {
                if (confirmBtn) confirmBtn.disabled = true;
            }
        });
    }

    function _populatePathSelect() {
        var sel = document.getElementById('fixed-install-path-select');
        if (!sel) return;
        sel.innerHTML = '';
        _steamLibraries.forEach(function(lib, idx) {
            var opt = document.createElement('option');
            opt.value = lib;
            opt.textContent = 'Bibliothèque Steam ' + (idx + 1) + ' — ' + lib;
            sel.appendChild(opt);
        });
        if (_steamLibraries.length) {
            sel.selectedIndex = 0;
            _customInstallPath = '';
        }
    }

    function _openInstallModal(gameId) {
        var game = _getGameById(gameId);
        if (!game) return;
        _pendingGame = game;
        _customInstallPath = '';

        var nameEl = document.getElementById('fixed-install-game-name');
        var sizeEl = document.getElementById('fixed-install-size');
        if (nameEl) nameEl.textContent = game.name || game.id;
        if (sizeEl) sizeEl.textContent = game.size_label || '—';

        // Réinitialiser le bloc reprise en attendant la vérification
        var resumeBox = document.getElementById('fixed-install-resume-box');
        if (resumeBox) resumeBox.classList.add('hidden');
        var confirmBtnInit = document.getElementById('fixed-install-confirm');
        if (confirmBtnInit) confirmBtnInit.textContent = 'Lancer le téléchargement';

        Bridge.callWithCallback('get_steam_libraries', function(libsJson) {
            try {
                _steamLibraries = JSON.parse(libsJson || '[]');
            } catch (e) {
                _steamLibraries = [];
            }
            if (!_steamLibraries.length) {
                Components.showToast('error', 'Aucune bibliothèque Steam trouvée. Configure Steam dans les Paramètres.');
                return;
            }
            _populatePathSelect();
            _refreshDiskCheck();
            Components.showModal('fixed-game-install-modal');
        });
    }

    function _confirmInstall() {
        if (!_pendingGame) return;
        var target = _selectedInstallTarget();
        if (!target) return;

        var game = _pendingGame;
        var gameId = game.id;

        Components.hideModal('fixed-game-install-modal');

        _progress[gameId] = { active: true, progress: 2, status: 'Démarrage…' };
        _renderCards();
        _setStatus('');

        _openProgressModal(game);
        Bridge.call('install_fixed_game', gameId, target);
        _pendingGame = null;
    }

    function _bindInstallModal() {
        var sel = document.getElementById('fixed-install-path-select');
        if (sel && !sel.dataset.bound) {
            sel.dataset.bound = '1';
            sel.addEventListener('change', function() {
                _customInstallPath = '';
                _refreshDiskCheck();
            });
        }
        var browse = document.getElementById('fixed-install-browse');
        if (browse && !browse.dataset.bound) {
            browse.dataset.bound = '1';
            browse.addEventListener('click', function() {
                Bridge.callWithCallback('open_file_dialog', function(path) {
                    if (!path) return;
                    _customInstallPath = path;
                    if (sel) sel.selectedIndex = -1;
                    _refreshDiskCheck();
                });
            });
        }
        var confirmBtn = document.getElementById('fixed-install-confirm');
        if (confirmBtn && !confirmBtn.dataset.bound) {
            confirmBtn.dataset.bound = '1';
            confirmBtn.addEventListener('click', function() {
                _confirmInstall();
            });
        }
    }

    function _getFilteredCatalog() {
        var q = (_vipSearch || '').trim().toLowerCase();
        if (!q) return _catalog.slice();
        return _catalog.filter(function(g) {
            var name = (g.name || g.id || '').toLowerCase();
            return name.indexOf(q) !== -1;
        });
    }

    function _renderCards() {
        var grid = document.getElementById('gamefixes-grid');
        if (!grid) return;

        if (!_catalog.length) {
            grid.innerHTML = '<p class="gamefixes-empty">Aucun jeu dans le catalogue pour le moment.</p>';
            Components.renderGridPagination('gamefixes-pagination', null);
            return;
        }

        var filtered = _getFilteredCatalog();
        if (!filtered.length) {
            grid.innerHTML = '<p class="gamefixes-empty">Aucun jeu ne correspond à ta recherche.</p>';
            Components.renderGridPagination('gamefixes-pagination', null);
            return;
        }

        var pageState = Components.paginateSlice(filtered, _vipPage);
        _vipPage = pageState.page;

        grid.innerHTML = '';
        pageState.items.forEach(function(g) {
            var id = g.id || '';
            var name = g.name || id;
            var size = g.size_label || '';
            var tags = Array.isArray(g.tags) ? g.tags : [];
            var prog = _progress[id];
            var isInstalled = _isGameInstalled(id);

            var card = document.createElement(EL);
            card.className = 'fixed-game-card';
            card.setAttribute('data-game-id', id);

            var coverEl = document.createElement(EL);
            coverEl.className = 'fixed-game-card-cover fixed-game-card-cover--placeholder';
            coverEl.textContent = '🎮';
            _applyCoverBackground(coverEl, _coverUrlsForGame(g));
            card.appendChild(coverEl);

            var body = document.createElement(EL);
            body.className = 'fixed-game-card-body';

            var h3 = document.createElement('h3');
            h3.className = 'fixed-game-card-title';
            h3.textContent = name;
            body.appendChild(h3);

            if (size) {
                var sz = document.createElement('p');
                sz.className = 'fixed-game-card-size';
                sz.textContent = size;
                body.appendChild(sz);
            }

            if (tags.length) {
                var tagP = document.createElement('p');
                tagP.className = 'fixed-game-card-tags';
                tags.forEach(function(t) {
                    var sp = document.createElement('span');
                    var label = _sanitizeUserMessage(t) || t;
                    if (/^\(?online\)?$/i.test(String(t || '').trim())) {
                        sp.className = 'fixed-game-tag-online';
                        label = '● ' + (label.replace(/^\(|\)$/g, '') || 'online');
                    }
                    sp.textContent = label;
                    tagP.appendChild(sp);
                });
                body.appendChild(tagP);
            }

            if (isInstalled) {
                var installedBadge = document.createElement('p');
                installedBadge.className = 'fixed-game-installed-badge';
                installedBadge.textContent = '✓ Jeu installé';
                body.appendChild(installedBadge);
            }

            if (prog && prog.active) {
                var wrap = document.createElement(EL);
                wrap.className = 'fixed-game-progress';
                var bar = document.createElement(EL);
                bar.className = 'fixed-game-progress-bar';
                bar.style.width = (prog.progress || 0) + '%';
                wrap.appendChild(bar);
                body.appendChild(wrap);
                var lbl = document.createElement('p');
                lbl.className = 'fixed-game-progress-label';
                lbl.textContent = _progressDetailText(prog);
                body.appendChild(lbl);
            }

            var btn = document.createElement('button');
            btn.type = 'button';
            var isLocked = !_tripleAllowed();
            if (isInstalled) {
                btn.className = 'btn btn-secondary fixed-game-download-btn fixed-game-download-btn--installed';
                btn.setAttribute('data-game-id', id);
                btn.textContent = 'Voir dans la bibliothèque';
                btn.addEventListener('click', function() { _goToLibrary(); });
            } else {
                btn.className = 'btn ' + (isLocked ? 'fixed-game-download-btn--locked' : 'btn-primary') + ' fixed-game-download-btn';
                btn.setAttribute('data-game-id', id);
                if (isLocked) {
                    btn.textContent = '🔒 Triple Monstre requis';
                    btn.setAttribute('data-tooltip', 'Réservé au plan Triple Monstre — clique pour voir les offres');
                } else {
                    btn.textContent = (prog && prog.active) ? 'Installation en cours…' : 'Télécharger et installer';
                    if (prog && prog.active) btn.disabled = true;
                }
                btn.addEventListener('click', function() { _startInstall(id); });
            }
            body.appendChild(btn);

            card.appendChild(body);
            grid.appendChild(card);
        });

        Components.renderGridPagination('gamefixes-pagination', pageState, function(p) {
            _vipPage = p;
            _renderCards();
            if (grid) {
                grid.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });

        _applyPartialsToCards();
    }

    function _startInstall(gameId) {
        if (!gameId) return;
        if (_isGameInstalled(gameId)) {
            _goToLibrary();
            return;
        }
        if (!_tripleAllowed()) {
            Components.showModal('gamefixes-upsell-modal');
            return;
        }
        _bindInstallModal();
        _openInstallModal(gameId);
    }

    function _applyPartialsToCards() {
        Object.keys(_partials).forEach(function(gid) {
            if (_isGameInstalled(gid)) return;
            var p = _partials[gid];
            if (!p || !p.partial_bytes) return;
            var card = document.querySelector('.fixed-game-card[data-game-id="' + gid + '"]');
            if (!card) return;
            var body = card.querySelector('.fixed-game-card-body');
            if (!body) return;

            // Ajouter la mini barre de reprise si pas déjà présente
            if (!card.querySelector('.fixed-resume-bar-wrap')) {
                var barWrap = document.createElement('div');
                barWrap.className = 'fixed-resume-bar-wrap';
                var bar = document.createElement('div');
                bar.className = 'fixed-resume-bar';
                bar.style.width = (p.partial_pct || 0) + '%';
                barWrap.appendChild(bar);

                var lbl = document.createElement('p');
                lbl.className = 'fixed-resume-label';
                lbl.textContent = '⚡ ' + (p.partial_human || '') + ' déjà téléchargés (' + (p.partial_pct || 0) + '%) — reprise disponible';
                body.appendChild(barWrap);
                body.appendChild(lbl);
            }

            // Changer le texte du bouton
            var btn = card.querySelector('.fixed-game-download-btn');
            if (btn && !btn.disabled && !btn.classList.contains('fixed-game-download-btn--locked')) {
                btn.textContent = '⚡ Reprendre (' + (p.partial_pct || 0) + '%)';
                btn.classList.add('fixed-game-download-btn--resume');
            }
        });
    }

    function _loadPartials() {
        Bridge.callWithCallback('get_fixed_games_partials', function(json) {
            try {
                _partials = JSON.parse(json || '{}');
            } catch (e) {
                _partials = {};
            }
            _applyPartialsToCards();
        });
    }

    var _catalogPollTimer = null;
    var _catalogSnapshot = '';

    function _loadCatalog(forceRefresh) {
        Bridge.callWithCallback('get_fixed_games_catalog', function(json) {
            var payload = json || '[]';
            if (!forceRefresh && payload === _catalogSnapshot) {
                return;
            }
            _catalogSnapshot = payload;
            try {
                _catalog = JSON.parse(payload);
            } catch (e) {
                _catalog = [];
            }
            _renderCards();
            _loadPartials();
        }, forceRefresh ? '1' : '0');
    }

    function _startCatalogPoll() {
        _stopCatalogPoll();
        _catalogPollTimer = setInterval(function() {
            _loadCatalog(false);
        }, 60000);
    }

    function _stopCatalogPoll() {
        if (_catalogPollTimer) {
            clearInterval(_catalogPollTimer);
            _catalogPollTimer = null;
        }
    }

    function _refreshRank() {
        Bridge.callWithCallback('get_user_rank', function(json) {
            try {
                var d = JSON.parse(json || '{}');
                _userRank = d.rank || 'free';
            } catch (e) {
                _userRank = 'free';
            }
        });
    }

    function _bindUpsellModal() {
        var btnTarifs = document.getElementById('gamefixes-upsell-tarifs');
        var btnDiscord = document.getElementById('gamefixes-upsell-discord');
        if (btnTarifs && !btnTarifs.dataset.bound) {
            btnTarifs.dataset.bound = '1';
            btnTarifs.addEventListener('click', function() {
                Components.hideModal('gamefixes-upsell-modal');
                Bridge.onReady(function(py) { py.open_url('https://slimedeals.fr/#tarifs'); });
            });
        }
        if (btnDiscord && !btnDiscord.dataset.bound) {
            btnDiscord.dataset.bound = '1';
            btnDiscord.addEventListener('click', function() {
                Components.hideModal('gamefixes-upsell-modal');
                Bridge.onReady(function(py) { py.open_url('https://discord.gg/slimedeals'); });
            });
        }
    }

    function init() {
        if (_initialized) return;
        _initialized = true;
        _bindInstallModal();
        _bindProgressModal();
        _bindUpsellModal();
        _bindSuccessModal();

        var searchInp = document.getElementById('gamefixes-search');
        if (searchInp && !searchInp.dataset.bound) {
            searchInp.dataset.bound = '1';
            searchInp.addEventListener('input', function() {
                _vipSearch = this.value;
                _vipPage = 1;
                _renderCards();
            });
        }

        Bridge.on('download_progress', function(json) {
            try {
                var data = JSON.parse(json);
                var id = data.id || '';
                if (id.indexOf('fixed_game:') !== 0) return;
                var gid = id.split(':')[1] || data.app_id;
                if (!gid) return;
                _applyProgressUpdate(data);
            } catch (e) {}
        });

        Bridge.on('task_finished', function(json) {
            try {
                var data = JSON.parse(json);
                if (data.task !== 'install_fixed_game') return;
                var gid = data.app_id || '';
                var msg = _sanitizeUserMessage(data.message || '');
                _activeProgressGameId = gid || _activeProgressGameId;
                _finishProgressModal(!!data.success, msg);
                if (!_progressModalOpen) {
                    _updateInstallBanner(gid);
                }
                if (data.success) {
                    var game = _getGameById(gid);
                    var gname = (game && game.name) || gid;
                    _loadInstalled(function() {
                        _showInstallSuccessModal(gname);
                    });
                    _setStatus('', false);
                } else {
                    _renderCards();
                    Components.showToast('error', msg || 'Installation échouée.');
                    _setStatus(msg || 'Installation échouée.', true);
                }
            } catch (e) {}
        });
    }

    function onPageEnter() {
        init();
        _refreshRank();
        Bridge.call('sync_launcher_profile');
        _loadCatalog(true);
        _loadInstalled();
        _startCatalogPoll();
        if (_activeProgressGameId && _progress[_activeProgressGameId] && !_progressModalOpen) {
            _updateInstallBanner(_activeProgressGameId);
        }
    }

    function onPageLeave() {
        _stopCatalogPoll();
        if (_progressModalOpen && _activeProgressGameId) {
            var prog = _progress[_activeProgressGameId];
            if (prog && prog.active) _minimizeProgressModal();
        }
    }

    return {
        onPageEnter: onPageEnter,
        onPageLeave: onPageLeave
    };
})();
