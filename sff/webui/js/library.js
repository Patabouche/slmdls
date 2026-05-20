/**
 * SlimeDeals — Library Page
 * Shows installed/downloaded games from AppList + Steam libraries.
 */

window.Library = (function() {
    'use strict';

    var _initialized = false;
    var _pendingDelete = null; // { appId, gamePath, gameName, kind: 'steam'|'sideloaded' }

    function _openDeleteConfirm(payload) {
        _pendingDelete = payload;
        var nameEl = document.getElementById('library-delete-game-name');
        var descEl = document.getElementById('library-delete-desc');
        if (nameEl) nameEl.textContent = payload.gameName || ('App ' + (payload.appId || ''));
        if (descEl) {
            descEl.textContent = payload.kind === 'sideloaded'
                ? 'Le dossier du jeu sera supprimé du disque et retiré de la bibliothèque du launcher. Cette action est irréversible.'
                : 'Steam sera fermé, le jeu sera retiré de ta bibliothèque Steam et supprimé du disque. Cette action est irréversible.';
        }
        Components.showModal('library-delete-modal');
    }

    function _cancelDeleteConfirm() {
        _pendingDelete = null;
        Components.hideModal('library-delete-modal');
    }

    function _confirmDelete() {
        if (!_pendingDelete) return;
        var pending = _pendingDelete;
        _pendingDelete = null;
        Components.hideModal('library-delete-modal');

        if (pending.kind === 'sideloaded') {
            var delPath = (pending.gamePath || '').trim();
            var delName = pending.gameName || 'ce jeu';
            if (!delPath) {
                Components.showToast('error', 'Chemin introuvable.');
                return;
            }
            Bridge.callWithCallback('delete_sideloaded_game', delPath, function(raw) {
                var o = {};
                try { o = JSON.parse(raw || '{}'); } catch (e) {}
                if (o.ok) {
                    Components.showToast('success', delName + ' supprimé.');
                    Library.refresh();
                } else {
                    Components.showToast('error', o.message || 'Suppression impossible.');
                }
            });
            return;
        }

        Bridge.call('delete_game', pending.appId, pending.gamePath, 'full');
    }

    /** Aligné sur App._normLauncherRank / plan FREE */
    function _normLauncherRank(r) {
        var s = String(r == null || r === '' ? 'free' : r).trim().toLowerCase().replace(/\s+/g, '_');
        if (!s || s === 'none' || s === 'null') return 'free';
        return s;
    }

    function _isStrictlyFreePlan(rank) {
        return _normLauncherRank(rank) === 'free';
    }

    var _TR_LIB = {
        triple_monstre: 1, triplemonstre: 1, triple_monster: 1, triplemonster: 1,
        triple: 1, tm: 1, unlimited: 1, role_unlimited: 1, vip: 1, premium: 1
    };
    var _P24_LIB = {
        '24hpass': 1, '24h_pass': 1, pass_24h: 1, pass24h: 1, hpass24: 1,
        day_pass_24h: 1, pass_24hpass: 1
    };
    var _MR_LIB = {
        monstre: 1, monster: 1, plan_monstre: 1, role_monstre: 1,
        double_monstre: 1, deux_monstres: 1, pass_monstre: 1
    };

    function _launcherRankBucketLib(rank) {
        var r = _normLauncherRank(rank);
        if (r === 'free') return 'free';
        if (_TR_LIB[r]) return 'triple';
        if (_P24_LIB[r]) return 'pass24h';
        if (_MR_LIB[r]) return 'monstre';
        return 'monstre';
    }

    function _onlineFixAllowedLib(rank) {
        return _launcherRankBucketLib(rank) === 'triple';
    }
    var _onlineFixFreeModalBound = false;
    function ensureOnlineFixFreeModalBindings() {
        if (_onlineFixFreeModalBound) return;
        var btnT = document.getElementById('library-onlinefix-tarifs');
        var btnA = document.getElementById('library-onlinefix-avis');
        if (!btnT || !btnA) return;
        _onlineFixFreeModalBound = true;
        var msgEl = document.getElementById('library-onlinefix-free-msg');
        if (msgEl && !msgEl.getAttribute('data-default-inner')) {
            msgEl.setAttribute('data-default-inner', msgEl.innerHTML);
        }
        btnT.addEventListener('click', function() {
            Bridge.call('open_url', 'https://slimedeals.fr/#tarifs');
        });
        btnA.addEventListener('click', function() {
            Bridge.onReady(function(py) {
                if (typeof py.discord_avis_url !== 'function') {
                    Bridge.call('open_url', 'https://discord.gg/c2pRJKjvgE');
                    return;
                }
                py.discord_avis_url(function(url) {
                    Bridge.call('open_url', url && url.indexOf('http') === 0 ? url : 'https://discord.gg/c2pRJKjvgE');
                });
            });
        });
    }

    function _showOnlineFixFreeUpsell() {
        ensureOnlineFixFreeModalBindings();
        var msgEl = document.getElementById('library-onlinefix-free-msg');
        var def = msgEl && msgEl.getAttribute('data-default-inner');
        if (msgEl && def) {
            msgEl.innerHTML = def;
        }
        Components.showModal('library-onlinefix-free-modal');
    }

    function init() {
        if (_initialized) return;
        _initialized = true;

        var refreshBtn = document.getElementById('library-refresh');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', _refreshLibrary);
        }

        var searchInp = document.getElementById('library-search');
        if (searchInp) {
            searchInp.addEventListener('input', function() {
                _libraryPage = 1;
                _applyLibraryFilter(this.value.trim().toLowerCase());
            });
        }

        var driveSelect = document.getElementById('library-drive-select');
        if (driveSelect) {
            driveSelect.addEventListener('change', function() {
                _updateDiskInfo(this.value);
            });
        }
        new Components.CustomSelect('library-drive-select', 'library-drive-select-ui');
        ensureOnlineFixFreeModalBindings();

        Bridge.on('task_finished', function(json) {
            try {
                var data = JSON.parse(json);
                if (data.task === 'library_loaded' && Array.isArray(data.games)) {
                    _renderLibrary(data.games);
                }
                if (data.task === 'delete_game') {
                    if (data.success) {
                        var msg = data.message || 'Jeu supprimé.';
                        Components.showToast('success', msg);
                        _refreshLibrary();
                    } else {
                        Components.showToast('error', data.message || 'Erreur lors de la suppression.');
                    }
                }
                if (data.task === 'update_check') {
                    _onUpdateCheckResult(data);
                }
                if (data.task === 'lure_fix') {
                    _onLureFixResult(data);
                }
            } catch(e) {}
        });

        var grid = document.getElementById('library-grid');
        if (grid) {
            grid.addEventListener('click', function(e) {
                var btn = e.target.closest('[data-action]');
                if (btn) {
                    var action = btn.dataset.action;
                    var appId = btn.dataset.appid;
                    if (action === 'fix') {
                        FixGame.preSelect(appId);
                        App.navigateTo('fixgame');
                    } else if (action === 'launch_locked') {
                        Components.showToast(
                            'error',
                            btn.dataset.lockmsg || 'Abonnement requis pour lancer ce jeu.'
                        );
                    } else if (action === 'launch_missing') {
                        Components.showToast(
                            'error',
                            btn.dataset.missingmsg || 'Fichiers du jeu absents sur le disque.'
                        );
                    } else if (action === 'delete_sideloaded') {
                        var sideloadPath = (btn.dataset.gamepath || '').trim();
                        if (!sideloadPath) {
                            Components.showToast('error', 'Chemin introuvable.');
                            return;
                        }
                        _openDeleteConfirm({
                            appId: appId || '',
                            gamePath: sideloadPath,
                            gameName: btn.dataset.gamename || 'ce jeu',
                            kind: 'sideloaded'
                        });
                    } else if (action === 'delete') {
                        _openDeleteConfirm({
                            appId: appId,
                            gamePath: btn.dataset.gamepath || '',
                            gameName: btn.dataset.gamename || ('App ' + appId),
                            kind: 'steam'
                        });
                    } else if (action === 'check_update') {
                        btn.disabled = true;
                        btn.textContent = 'Vérification...';
                        btn.dataset.checking = appId;
                        Bridge.call('check_game_update', appId);
                    } else if (action === 'lure_fix') {
                        btn.disabled = true;
                        btn.textContent = 'Patching...';
                        btn.dataset.lurefixing = appId;
                        Bridge.call('lure_fix_acf', appId);
                    } else if (action === 'launch_admin') {
                        var gpath = (btn.dataset.gamepath || '').trim();
                        if (!gpath) {
                            Components.showToast('error', 'Chemin du jeu manquant — rafraîchis la bibliothèque.');
                            return;
                        }
                        Bridge.callWithCallback('launch_game_as_admin', gpath, function(raw) {
                            var o;
                            try {
                                o = JSON.parse(raw || '{}');
                            } catch (e1) {
                                o = {};
                            }
                            if (o.ok) {
                                Components.showToast('success', (o.message || 'OK') + (o.exe ? '\n' + o.exe : ''));
                            } else {
                                Components.showToast('error', o.message || 'Lancement impossible');
                            }
                        });
                    } else if (action === 'multiplayer') {
                        Bridge.onReady(function(py) {
                            py.get_user_rank(function(jsonStr) {
                                var d, rnk;
                                try {
                                    d = JSON.parse(jsonStr);
                                    rnk = d.rank || 'free';
                                } catch (e) {
                                    rnk = 'free';
                                }
                                if (!_onlineFixAllowedLib(rnk)) {
                                    _showOnlineFixFreeUpsell();
                                } else {
                                    Bridge.call('run_game_action', appId, action);
                                }
                            });
                        });
                    } else {
                        Bridge.call('run_game_action', appId, action);
                    }
                }
            });
        }

        var btnConfirmDelete = document.getElementById('library-delete-confirm');
        if (btnConfirmDelete) {
            btnConfirmDelete.addEventListener('click', _confirmDelete);
        }

        ['library-delete-cancel', 'library-delete-cancel-footer'].forEach(function(id) {
            var btn = document.getElementById(id);
            if (btn) {
                btn.addEventListener('click', _cancelDeleteConfirm);
            }
        });
    }

    function onPageEnter() {
        init();
        _refreshLibrary();
        _refreshDiskInfo();
    }

    function _refreshDiskInfo() {
        Bridge.callSync('get_steam_libraries', function(json) {
            var paths = [];
            try { paths = JSON.parse(json || '[]'); } catch(e) {}
            var seen = {};
            var drives = [];
            paths.forEach(function(p) {
                if (!p) return;
                var root = (p.length >= 3 && p[1] === ':') ? p.slice(0, 3) : '/';
                var label = (p.length >= 3 && p[1] === ':') ? p[0].toUpperCase() + ':' : 'System';
                if (!seen[root]) {
                    seen[root] = true;
                    drives.push({ root: root, label: label });
                }
            });
            if (!drives.length) {
                Bridge.callWithCallback('get_setting', 'steam_path', function(steamPath) {
                    if (!steamPath) return;
                    var root = (steamPath.length >= 3 && steamPath[1] === ':') ? steamPath.slice(0, 3) : '/';
                    var label = (steamPath.length >= 3 && steamPath[1] === ':') ? steamPath[0].toUpperCase() + ':' : 'System';
                    _populateDriveSelect([{ root: root, label: label }]);
                    _updateDiskInfo(root);
                });
                return;
            }
            _populateDriveSelect(drives);
            _updateDiskInfo(drives[0].root);
        });
    }

    function _populateDriveSelect(drives) {
        var sel = document.getElementById('library-drive-select');
        if (!sel) return;
        sel.innerHTML = '';
        drives.forEach(function(d) {
            var opt = document.createElement('option');
            opt.value = d.root;
            opt.textContent = d.label;
            sel.appendChild(opt);
        });
        var ui = document.getElementById('library-drive-select-ui');
        if (ui) {
            if (drives.length > 1) {
                ui.classList.remove('hidden');
            } else {
                ui.classList.add('hidden');
            }
        }
    }

    function _updateDiskInfo(drivePath) {
        Bridge.callWithCallback('get_disk_usage', drivePath, function(json) {
            var el = document.getElementById('library-disk-info');
            if (!el) return;
            try {
                var d = JSON.parse(json || '{}');
                if (d.error || !d.total) { el.textContent = ''; return; }
                el.textContent = _fmtBytes(d.free) + ' libre sur ' + _fmtBytes(d.total);
            } catch(e) {}
        });
    }

    function _fmtBytes(b) {
        if (b >= 1e12) return (b / 1e12).toFixed(1) + ' TB';
        if (b >= 1e9) return (b / 1e9).toFixed(1) + ' GB';
        if (b >= 1e6) return (b / 1e6).toFixed(1) + ' MB';
        return (b / 1e3).toFixed(0) + ' KB';
    }

    function _refreshLibrary() {
        Bridge.call('load_library');
    }

    var _libraryGames = [];
    var _libraryPage = 1;

    function _renderLibrary(games) {
        _libraryGames = games || [];
        _libraryPage = 1;
        var searchInp = document.getElementById('library-search');
        var filter = searchInp ? searchInp.value.trim().toLowerCase() : '';
        _applyLibraryFilter(filter);
    }

    function _isPepiteGame(game) {
        return !!(game && (game.source === 'fixed' || game.is_fixed === true));
    }

    function _isLockedGame(game) {
        return !!(game && game.locked);
    }

    function _isGhostGame(game) {
        return !!(game && game.files_missing);
    }

    function _applyLibraryFilter(filter) {
        var games = _libraryGames;
        var grid = document.getElementById('library-grid');
        var empty = document.getElementById('library-empty');
        if (!grid) return;
        if (filter) {
            games = games.filter(function(g) {
                return (g.name || '').toLowerCase().indexOf(filter) !== -1;
            });
        }

        var pageState = Components.paginateSlice(games, _libraryPage);
        _libraryPage = pageState.page;

        if (grid) grid.innerHTML = '';

        if (games.length === 0) {
            if (grid) grid.classList.add('hidden');
            if (empty) empty.classList.remove('hidden');
            Components.renderGridPagination('library-pagination', null);
            return;
        }

        if (grid) grid.classList.remove('hidden');
        if (empty) empty.classList.add('hidden');

        pageState.items.forEach(function(game, index) {
            var isLocked = _isLockedGame(game);
            var isGhost = !isLocked && _isGhostGame(game);
            game.installed = !isLocked && !isGhost;
            var isPepite = !isLocked && !isGhost && _isPepiteGame(game);
            var card = Components.createGameCard(game, {
                index: index,
                forceShowImage: true,
                hideInstalledBadge: isPepite || isLocked || isGhost
            });
            if (isLocked) {
                card.classList.add('game-card--locked');
            } else if (isGhost) {
                card.classList.add('game-card--ghost');
            }
            if (isPepite) {
                card.classList.add('game-card--pepite');
                card.dataset.source = 'fixed';
            }

            if (isLocked) {
                var lockBadge = document.createElement('div');
                lockBadge.className = 'lib-locked-badge';
                lockBadge.title = game.lock_reason || 'Abonnement requis';
                lockBadge.textContent = game.lock_label || 'Sans abonnement';
                card.style.position = 'relative';
                card.appendChild(lockBadge);
            } else if (isGhost) {
                var ghostBadge = document.createElement('div');
                ghostBadge.className = 'lib-ghost-badge';
                ghostBadge.title = 'Visible dans Steam mais fichiers absents sur le disque';
                ghostBadge.textContent = 'Fichiers manquants';
                card.style.position = 'relative';
                card.appendChild(ghostBadge);
            } else if (isPepite) {
                var badge = document.createElement('div');
                badge.className = 'lib-pepites-badge';
                badge.title = 'Jeu VIP';
                badge.textContent = '(VIP)';
                card.style.position = 'relative';
                card.appendChild(badge);
            }

            // Add library-specific actions
            var safeName = (game.name || '').replace(/"/g, '&quot;');
            var safePath = (game.path || '').replace(/"/g, '&quot;');
            var lockMsg = (game.lock_reason || 'Abonnement requis pour lancer ce jeu.')
                .replace(/"/g, '&quot;');
            var missingMsg = 'Les fichiers de ce jeu ne sont plus sur le disque. Réinstalle-le ou supprime-le pour le retirer de Steam.'
                .replace(/"/g, '&quot;');
            var actions = card.querySelector('.game-card-actions');
            if (actions) {
                actions.classList.add('lib-card-actions');
                if (isLocked) {
                    actions.innerHTML =
                        '<p class="lib-locked-msg">' + (game.lock_reason || 'Abonnement requis pour lancer ce jeu.') + '</p>' +
                        '<div class="lib-actions-primary">' +
                            '<button type="button" class="lib-btn lib-btn--launch lib-btn--locked" data-action="launch_locked" data-lockmsg="' + lockMsg + '" data-tooltip="Renouvelle ton abonnement pour relancer">' +
                                '<svg viewBox="0 0 24 24" fill="currentColor" width="12" height="12"><path d="M8 5v14l11-7z"/></svg> Lancer' +
                            '</button>' +
                        '</div>';
                } else if (isGhost) {
                    actions.innerHTML =
                        '<p class="lib-ghost-msg">Ce jeu apparaît dans Steam mais son dossier d\'installation est absent. Tu peux le supprimer pour le retirer de Steam, ou le réinstaller depuis l\'accueil.</p>' +
                        '<div class="lib-actions-primary">' +
                            '<button type="button" class="lib-btn lib-btn--launch lib-btn--ghost" data-action="launch_missing" data-missingmsg="' + missingMsg + '" data-tooltip="Fichiers absents">' +
                                '<svg viewBox="0 0 24 24" fill="currentColor" width="12" height="12"><path d="M8 5v14l11-7z"/></svg> Lancer' +
                            '</button>' +
                        '</div>' +
                        '<div class="lib-actions-tools">' +
                            '<button class="lib-btn lib-btn--delete" data-action="delete" data-appid="' + game.app_id + '" data-gamepath="' + safePath + '" data-gamename="' + safeName + '" data-tooltip="Retirer de Steam et supprimer les traces SlimeDeals"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" width="12" height="12"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg></button>' +
                        '</div>';
                } else if (isPepite) {
                    actions.innerHTML =
                        '<div class="lib-actions-primary">' +
                            '<button type="button" class="lib-btn lib-btn--launch lib-btn--launch-pepites" data-action="launch_admin" data-gamepath="' + safePath + '" data-tooltip="Lancer le jeu">' +
                                '<svg viewBox="0 0 24 24" fill="currentColor" width="12" height="12"><path d="M8 5v14l11-7z"/></svg> Lancer' +
                            '</button>' +
                        '</div>' +
                        '<div class="lib-actions-tools">' +
                            '<button class="lib-btn lib-btn--delete" data-action="delete_sideloaded" data-gamepath="' + safePath + '" data-gamename="' + safeName + '" data-tooltip="Supprimer ce jeu"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" width="12" height="12"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg></button>' +
                        '</div>';
                } else {
                    actions.innerHTML =
                        '<div class="lib-actions-primary">' +
                            '<button type="button" class="lib-btn lib-btn--launch" data-action="launch_admin" data-gamepath="' + safePath + '" data-tooltip="Lance le jeu en mode administrateur">' +
                                '<svg viewBox="0 0 24 24" fill="currentColor" width="12" height="12"><path d="M8 5v14l11-7z"/></svg> Lancer' +
                            '</button>' +
                            '<button class="lib-btn lib-btn--fix" data-action="fix" data-appid="' + game.app_id + '" data-tooltip="Applique les correctifs Steam">' +
                                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="11" height="11"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg> Fix' +
                            '</button>' +
                        '</div>' +
                        '<div class="lib-actions-tools">' +
                            '<button class="lib-btn lib-btn--online" data-action="multiplayer" data-appid="' + game.app_id + '" data-tooltip="Patches multijoueur en ligne">Online Fix</button>' +
                            '<button class="lib-btn lib-btn--dlc" data-action="dlc_check" data-appid="' + game.app_id + '" data-tooltip="Vérifier et déverrouiller les DLCs">DLC</button>' +
                            '<button class="lib-btn lib-btn--workshop" data-action="workshop" data-appid="' + game.app_id + '" data-tooltip="Télécharger des mods Workshop">Workshop</button>' +
                            '<button class="lib-btn lib-btn--lure" data-action="lure_fix" data-appid="' + game.app_id + '" data-tooltip="Patch ACF — stoppe les invites de mise à jour">Lure Fix</button>' +
                            '<button class="lib-btn lib-btn--update" data-action="check_update" data-appid="' + game.app_id + '" data-tooltip="Télécharger les derniers manifests">Update</button>' +
                            '<button class="lib-btn lib-btn--delete" data-action="delete" data-appid="' + game.app_id + '" data-gamepath="' + safePath + '" data-gamename="' + safeName + '" data-tooltip="Supprimer ce jeu"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" width="12" height="12"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg></button>' +
                        '</div>';
                }
            }

            if (grid) grid.appendChild(card);
        });

        Components.renderGridPagination('library-pagination', pageState, function(p) {
            _libraryPage = p;
            _applyLibraryFilter(filter);
            if (grid) {
                grid.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    }

    function _onUpdateCheckResult(data) {
        var grid = document.getElementById('library-grid');
        if (grid) {
            var btns = grid.querySelectorAll('[data-action="check_update"]');
            btns.forEach(function(b) {
                if (b.dataset.checking) {
                    b.disabled = false;
                    b.textContent = 'Mettre à jour';
                    delete b.dataset.checking;
                }
            });
        }
        if (data.up_to_date) {
            Components.showToast('success', 'Déjà à jour (build ' + (data.installed_buildid || '') + ')');
        } else if (data.updated) {
            Components.showToast('success', 'Mis à jour vers le build ' + (data.cm_buildid || ''));
        } else if (data.error) {
            Components.showToast('error', data.error);
        }
    }

    function _onLureFixResult(data) {
        var grid = document.getElementById('library-grid');
        if (grid) {
            var btns = grid.querySelectorAll('[data-action="lure_fix"]');
            btns.forEach(function(b) {
                if (b.dataset.lurefixing) {
                    b.disabled = false;
                    b.textContent = 'Lure Fix';
                    delete b.dataset.lurefixing;
                }
            });
        }
        if (data.success) {
            Components.showToast('success', data.message || 'ACF patché. Redémarrez Steam.');
        } else {
            Components.showToast('error', data.message || 'Lure fix échoué');
        }
    }

    return {
        init: init,
        onPageEnter: onPageEnter,
        ensureOnlineFixFreeModalBindings: ensureOnlineFixFreeModalBindings
    };
})();
