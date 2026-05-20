/**
 * SlimeDeals — Main App Router & Sidebar Navigation
 * Handles page switching, platform detection, and global initialization.
 */

window.App = (function() {
    'use strict';

    var _currentPage = 'home';
    var _platform = 'win32';
    var _outsideMode = false;

    /** Aligné sur web_bridge : FREE + rangs Monstre + rangs Triple Monstre */
    function _normLauncherRank(r) {
        var s = String(r == null || r === '' ? 'free' : r).trim().toLowerCase().replace(/\s+/g, '_');
        if (!s || s === 'none' || s === 'null') return 'free';
        return s;
    }

    var _TR_HOME = {
        triple_monstre: 1, triplemonstre: 1, triple_monster: 1, triplemonster: 1,
        triple: 1, tm: 1, unlimited: 1, role_unlimited: 1, vip: 1, premium: 1
    };
    var _MR_HOME = {
        monstre: 1, monster: 1, plan_monstre: 1, role_monstre: 1,
        double_monstre: 1, deux_monstres: 1, pass_monstre: 1
    };
    var _P24_HOME = {
        '24hpass': 1, '24h_pass': 1, pass_24h: 1, pass24h: 1, hpass24: 1,
        day_pass_24h: 1, pass_24hpass: 1
    };

    /** Masque la section Lua accueil pour FREE / Monstre / 24H PASS / Triple (aligne launcher_ranks). */
    function _rankHidesHomeLuaSection(rank) {
        var r = _normLauncherRank(rank);
        if (r === 'free') return true;
        if (_TR_HOME[r]) return true;
        if (_P24_HOME[r]) return true;
        if (_MR_HOME[r]) return true;
        return false;
    }

    /** Plan catalogue FREE seul (rang normalise === free) */
    function _isStrictlyFreePlan(rank) {
        return _normLauncherRank(rank) === 'free';
    }

    function _launcherRankBucketHome(rank) {
        var r = _normLauncherRank(rank);
        if (r === 'free') return 'free';
        if (_TR_HOME[r]) return 'triple';
        if (_P24_HOME[r]) return 'pass24h';
        if (_MR_HOME[r]) return 'monstre';
        return 'monstre';
    }

    function _tripleExclusiveToolsAllowed(rank) {
        return _launcherRankBucketHome(rank) === 'triple';
    }

    function _cloudSavesNavAllowed(rank) {
        return _launcherRankBucketHome(rank) === 'triple';
    }

    var _bprgFreeUpsellBound = false;
    function _bindBprgFreeUpsellModal() {
        if (_bprgFreeUpsellBound) return;
        var btnT = document.getElementById('bprg-upsell-tarifs');
        var btnA = document.getElementById('bprg-upsell-avis');
        var btnF = document.getElementById('bprg-upsell-free-sub');
        if (!btnT || !btnA || !btnF) return;
        _bprgFreeUpsellBound = true;
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
        btnF.addEventListener('click', function() {
            Bridge.onReady(function(py) {
                if (typeof py.discord_free_subscribe_url !== 'function') {
                    Bridge.call('open_url', 'https://discord.gg/c2pRJKjvgE');
                    return;
                }
                py.discord_free_subscribe_url(function(url) {
                    Bridge.call('open_url', url && url.indexOf('http') === 0 ? url : 'https://discord.gg/c2pRJKjvgE');
                });
            });
        });
    }

    function _configureCloudSavesUpsellForRank(bucket) {
        var lead = document.getElementById('cloudsaves-free-upsell-lead');
        if (!lead) return;
        if (bucket === 'monstre' || bucket === 'pass24h') {
            lead.innerHTML = 'Tu es sur un <strong>palier sans sauvegardes cloud</strong> (Monstre ou 24H PASS). Les <strong>sauvegardes cloud</strong> (Google Drive) sont reservees au <strong>Triple Monstre</strong> — passe au palier superieur pour activer cette page.';
        } else {
            lead.innerHTML = 'Tu es sur le <strong>plan FREE</strong>. Les <strong>sauvegardes cloud</strong> (Google Drive) sont reservees au <strong>Triple Monstre</strong>.';
        }
    }

    var _cloudSavesFreeUpsellBound = false;
    function _bindCloudSavesFreeUpsellModal() {
        if (_cloudSavesFreeUpsellBound) return;
        var btnT = document.getElementById('cloudsaves-free-upsell-tarifs');
        var btnA = document.getElementById('cloudsaves-free-upsell-avis');
        var btnF = document.getElementById('cloudsaves-free-upsell-free-sub');
        if (!btnT || !btnA || !btnF) return;
        _cloudSavesFreeUpsellBound = true;
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
        btnF.addEventListener('click', function() {
            Bridge.onReady(function(py) {
                if (typeof py.discord_free_subscribe_url !== 'function') {
                    Bridge.call('open_url', 'https://discord.gg/c2pRJKjvgE');
                    return;
                }
                py.discord_free_subscribe_url(function(url) {
                    Bridge.call('open_url', url && url.indexOf('http') === 0 ? url : 'https://discord.gg/c2pRJKjvgE');
                });
            });
        });
    }

    function _bindSubscriptionsPage() {
        var btnT    = document.getElementById('subscriptions-open-tarifs');
        var btnTStd = document.getElementById('subscriptions-open-tarifs-std');
        var btnLife = document.getElementById('subscriptions-open-lifetime');
        var btnD    = document.getElementById('subscriptions-open-discord');
        var btnDRef = document.getElementById('subscriptions-open-discord-ref');
        if (btnTStd) btnTStd.addEventListener('click', function() { Bridge.call('open_url', 'https://slimedeals.fr/#tarifs'); });
        if (btnDRef) btnDRef.addEventListener('click', function() { Bridge.call('open_url', 'https://discord.gg/c2pRJKjvgE'); });
        if (btnLife) {
            btnLife.addEventListener('click', function() {
                Bridge.call('open_url', 'https://slimedeals.fr/abonnement-logiciel?plan=triple_lifetime');
            });
        }
        if (btnT) {
            btnT.addEventListener('click', function() {
                Bridge.call('open_url', 'https://slimedeals.fr/#tarifs');
            });
        }
        if (btnD) {
            btnD.addEventListener('click', function() {
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
    }

    function _applyHomeLuaSectionForRank(rank) {
        var sec = document.getElementById('section-lua-manifest');
        if (!sec) return;
        sec.style.display = _rankHidesHomeLuaSection(rank) ? 'none' : '';
    }

    function init() {
        Components.initModals();
        new Components.CustomSelect('home-game-select', 'home-game-select-ui');
        new Components.CustomSelect('fixgame-game-select', 'fixgame-game-select-ui');
        new Components.CustomSelect('store-sort', 'store-sort-ui');
        new Components.CustomSelect('setting-gl-version', 'setting-gl-version-ui');
        new Components.CustomSelect('profile-select', 'profile-select-ui');
        new Components.CustomSelect('setting-language', 'setting-language-ui');
        Tooltips.init();
        _bindBprgFreeUpsellModal();
        _bindCloudSavesFreeUpsellModal();
        _bindSubscriptionsPage();
        _initSidebar();
        _initLogPanel();
        _initGlobalListeners();

        Bridge.onReady(function(py) {
            // Detect platform
            py.get_platform(function(platform) {
                _platform = platform || 'win32';
                document.body.classList.add('platform-' + _platform);
                // Hide Windows-only elements on Linux
                if (_platform !== 'win32') {
                    document.querySelectorAll('.platform-win').forEach(function(el) {
                        el.style.display = 'none';
                    });
                }
            });

            // Thème fixé à dark — chargement backend ignoré
            py.get_setting('theme', function(themeId) {
                if (false && themeId) {
                    document.documentElement.setAttribute('data-theme', themeId);
                    localStorage.setItem('theme', themeId);
                    var _photoMap = {
                        'dawn': 'img/themes/dawn.jpg',
                        'dusk': 'img/themes/dusk.jpg',
                        'flow': 'img/themes/flow.jpg',
                        'lake': 'img/themes/lake.jpg',
                        'midnight-city': 'img/themes/midnightcity.jpg',
                        'snow': 'img/themes/snow.jpg'
                    };
                    var _bgImg = _photoMap[themeId] ? 'url(' + _photoMap[themeId] + ')' : '';
                    document.body.style.backgroundImage = _bgImg;
                    document.body.style.backgroundSize = _bgImg ? 'cover' : '';
                    document.body.style.backgroundPosition = _bgImg ? 'center' : '';
                }
            });

            // Apply saved language for live i18n
            py.get_setting('language', function(lang) {
                if (window.I18n) I18n.applyLanguage(lang || 'en');
            });

            // Check for stored API key
            py.get_stored_api_key(function(apiKey) {
                if (apiKey) {
                    Store.onApiKeyAvailable(apiKey);
                }
            });

            // Populate game dropdown on Home page
            _populateGameDropdown();
            setInterval(_populateGameDropdown, 10 * 60 * 1000);

            // Refresh button beside game dropdown
            var homeRefreshBtn = document.getElementById('home-game-refresh');
            if (homeRefreshBtn) homeRefreshBtn.addEventListener('click', _populateGameDropdown);

            // Listen to global signals
            Bridge.on('task_finished', function(json) {
                try {
                    var result = JSON.parse(json);
                    if (result.task === 'multiplayer') {
                        if (result.free_plan_denied) {
                            var libMsg = document.getElementById('library-onlinefix-free-msg');
                            if (libMsg && !libMsg.getAttribute('data-default-inner')) {
                                libMsg.setAttribute('data-default-inner', libMsg.innerHTML);
                            }
                            if (libMsg && result.message) {
                                libMsg.textContent = result.message;
                            } else if (libMsg) {
                                var defInner = libMsg.getAttribute('data-default-inner');
                                if (defInner) libMsg.innerHTML = defInner;
                            }
                            if (window.Library && typeof Library.ensureOnlineFixFreeModalBindings === 'function') {
                                Library.ensureOnlineFixFreeModalBindings();
                            }
                            Components.showModal('library-onlinefix-free-modal');
                        } else {
                            var hdr = document.getElementById('multiplayer-result-header');
                            var ttl = document.getElementById('multiplayer-result-title');
                            var msgEl = document.getElementById('multiplayer-result-msg');
                            if (hdr) {
                                hdr.classList.remove('modal-sd-header-ok', 'modal-sd-header-fail');
                                hdr.classList.add(result.success ? 'modal-sd-header-ok' : 'modal-sd-header-fail');
                                hdr.style.background = '';
                            }
                            if (ttl) {
                                ttl.textContent = result.success
                                    ? 'Mod online installé'
                                    : (result.cancelled ? 'Multijoueur annulé' : 'Mode online introuvable');
                            }
                            if (msgEl) {
                                msgEl.textContent = result.message || '';
                            }
                            Components.showModal('multiplayer-result-modal');
                        }
                    } else if (result.message) {
                        Components.showToast(
                            result.success ? 'success' : 'error',
                            result.message
                        );
                    }
                    if (result.task === 'download_fastest' && result.success) {
                        Components.showModal('restart-after-download-modal');
                        _populateGameDropdown();
                    }
                    if (result.task === 'download_ddmod' && result.success) {
                        _populateGameDropdown();
                    }
                    if (result.task === 'auto_gl_setup') {
                        var runBtn = document.getElementById('gl-setup-run');
                        if (runBtn) runBtn.disabled = false;
                        if (result.success && result.applist_path) {
                            var folderInp = document.getElementById('setting-applist-folder');
                            if (folderInp) {
                                folderInp.value = result.applist_path;
                            }
                        }
                    }
                } catch(e) {}
            });

            Bridge.on('log_message', function(msg) {
                _appendLog(msg);
                _appendHomeLog(msg);
            });

            py.get_user_rank(function(jsonStr) {
                var d, r;
                try {
                    d = JSON.parse(jsonStr);
                    r = d.rank;
                } catch (e) {
                    r = 'free';
                }
                _applyHomeLuaSectionForRank(r);
            });

            Bridge.on('launcher_profile_synced', function(jsonStr) {
                try {
                    var d = JSON.parse(jsonStr);
                    if (d && d.ok && d.rank != null) {
                        _applyHomeLuaSectionForRank(d.rank);
                    }
                } catch (e) {}
            });
        });

        // Navigate to saved page or home (sauvegardes cloud : Triple Monstre uniquement)
        var savedPage = localStorage.getItem('currentPage');
        if (savedPage) {
            if (savedPage === 'cloudsaves') {
                Bridge.onReady(function(py) {
                    py.get_user_rank(function(jsonStr) {
                        var rnk = 'free';
                        try {
                            var d = JSON.parse(jsonStr || '{}');
                            rnk = d.rank || 'free';
                        } catch (e) {}
                        if (!_cloudSavesNavAllowed(rnk)) {
                            localStorage.setItem('currentPage', 'home');
                            navigateTo('home');
                        } else {
                            navigateTo('cloudsaves');
                        }
                    });
                });
            } else {
                navigateTo(savedPage);
            }
        }

        // Thème fixé à dark — toujours forcer
        document.documentElement.setAttribute('data-theme', 'dark');
        localStorage.removeItem('theme');
    }

    function _initSidebar() {
        document.querySelectorAll('.nav-item[data-page], .hnsc-card[data-page]').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var page = this.dataset.page;
                if (page === 'tutoriel') {
                    Bridge.onReady(function(py) {
                        py.open_url('https://slimedeals.fr/tutoriel');
                    });
                    return;
                }
                if (page === 'free-games') {
                    navigateTo('store');
                    return;
                }
                navigateTo(page);
            });
        });
    }

    function navigateTo(pageId) {
        if (pageId === 'cloudsaves') {
            Bridge.onReady(function(py) {
                py.get_user_rank(function(jsonStr) {
                    var rnk = 'free';
                    try {
                        var d = JSON.parse(jsonStr || '{}');
                        rnk = d.rank || 'free';
                    } catch (e) {}
                    if (!_cloudSavesNavAllowed(rnk)) {
                        _bindCloudSavesFreeUpsellModal();
                        _configureCloudSavesUpsellForRank(_launcherRankBucketHome(rnk));
                        Components.showModal('cloudsaves-free-upsell-modal');
                        return;
                    }
                    _navigateToImpl(pageId);
                });
            });
            return;
        }
        _navigateToImpl(pageId);
    }

    function _navigateToImpl(pageId) {
        if (_currentPage === 'gamefixes' && pageId !== 'gamefixes' &&
            window.GameFixes && typeof GameFixes.onPageLeave === 'function') {
            GameFixes.onPageLeave();
        }
        // Hide all pages
        document.querySelectorAll('.page').forEach(function(page) {
            page.classList.remove('active');
        });

        // Show target page
        var target = document.getElementById('page-' + pageId);
        if (target) {
            target.classList.add('active');
        }

        // Update sidebar active state
        document.querySelectorAll('.nav-item[data-page]').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.page === pageId);
        });

        _currentPage = pageId;
        localStorage.setItem('currentPage', pageId);

        // Trigger page-specific init if needed
        switch(pageId) {
            case 'store': Store.onPageEnter(); break;
            case 'library': Library.onPageEnter(); break;
            case 'downloads': Downloads.onPageEnter(); break;
            case 'fixgame': FixGame.onPageEnter(); break;
            case 'tools': Tools.onPageEnter(); break;
            case 'cloudsaves': CloudSaves.onPageEnter(); break;
            case 'settings': Settings.onPageEnter(); break;
            case 'gamefixes': if (window.GameFixes) GameFixes.onPageEnter(); break;
        }

        // Stagger animation on visible cards after page transition
        if (target) {
            var cards = target.querySelectorAll('.game-card, .action-card, .fixedgame-card, .free-catalog-card');
            cards.forEach(function(card, i) {
                card.style.animationDelay = (i * 0.04) + 's';
                card.classList.remove('stagger-in');
                void card.offsetWidth;
                card.classList.add('stagger-in');
                setTimeout(function() {
                    card.classList.remove('stagger-in');
                    card.style.animationDelay = '';
                }, 600 + i * 40);
            });
        }
    }

    var _logMinLevel = 20; // INFO by default

    function _initLogPanel() {
        // Sidebar Logs button opens the native GlobalLogWindow (independent OS window)
        var logsBtn = document.getElementById('btn-logs');
        if (logsBtn) {
            logsBtn.addEventListener('click', function() {
                Bridge.call('open_log_window');
            });
        }

        // Home page mini-log Clear button
        var homeLogClear = document.getElementById('home-log-clear');
        if (homeLogClear) {
            homeLogClear.addEventListener('click', function() {
                var content = document.getElementById('home-log-content');
                if (content) content.innerHTML = '';
            });
        }

        // Home page mini-log Copy button — uses bridge to avoid clipboard API issues in QWebEngine
        var homeLogCopy = document.getElementById('home-log-copy');
        if (homeLogCopy) {
            homeLogCopy.addEventListener('click', function() {
                var content = document.getElementById('home-log-content');
                if (content) {
                    var text = content.innerText || content.textContent || '';
                    Bridge.call('copy_to_clipboard', text);
                    Components.showToast('success', 'Journal copié dans le presse-papiers');
                }
            });
        }
    }

    function _appendLog(msg) {
        var content = document.getElementById('log-panel-content');
        if (!content) return;

        // Parse level from message format: "[LEVEL] message" or "name — [LEVEL] message"
        var level = 20; // default INFO
        var levelClass = 'log-info';
        var levelTag = 'INFO';
        if (msg.indexOf('[DEBU') !== -1) { level = 10; levelClass = 'log-debug'; levelTag = 'DEBG'; }
        else if (msg.indexOf('[WARN') !== -1) { level = 30; levelClass = 'log-warning'; levelTag = 'WARN'; }
        else if (msg.indexOf('[ERRO') !== -1 || msg.indexOf('[CRIT') !== -1) { level = 40; levelClass = 'log-error'; levelTag = 'ERR '; }

        var now = new Date();
        var ts = ('0' + now.getHours()).slice(-2) + ':' + ('0' + now.getMinutes()).slice(-2) + ':' + ('0' + now.getSeconds()).slice(-2);

        var line = document.createElement('div');
        line.className = 'log-line ' + levelClass;
        line.dataset.level = level;
        line.innerHTML = '<span class="log-ts">' + ts + '</span> <span class="log-tag">[' + levelTag + ']</span> ' + _escapeLogHtml(msg);

        if (level < _logMinLevel) {
            line.style.display = 'none';
        }

        content.appendChild(line);
        while (content.children.length > 300) {
            content.removeChild(content.firstChild);
        }
        content.scrollTop = content.scrollHeight;
    }

    function _appendHomeLog(msg) {
        var content = document.getElementById('home-log-content');
        if (!content) return;

        var levelClass = 'log-info';
        var levelTag = 'INFO';
        if (msg.indexOf('[DEBU') !== -1) { levelClass = 'log-debug'; levelTag = 'DEBG'; }
        else if (msg.indexOf('[WARN') !== -1) { levelClass = 'log-warning'; levelTag = 'WARN'; }
        else if (msg.indexOf('[ERRO') !== -1 || msg.indexOf('[CRIT') !== -1) { levelClass = 'log-error'; levelTag = 'ERR '; }

        var now = new Date();
        var ts = ('0' + now.getHours()).slice(-2) + ':' + ('0' + now.getMinutes()).slice(-2) + ':' + ('0' + now.getSeconds()).slice(-2);

        var line = document.createElement('div');
        line.className = 'log-line ' + levelClass;
        line.innerHTML = '<span class="log-ts">' + ts + '</span> ' + _escapeLogHtml(msg);

        content.appendChild(line);
        // Keep last 200 lines to avoid memory growth
        while (content.children.length > 200) {
            content.removeChild(content.firstChild);
        }
        content.scrollTop = content.scrollHeight;
    }

    function _escapeLogHtml(str) {
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function _applyLogLevelFilter() {
        var content = document.getElementById('log-panel-content');
        if (!content) return;
        var lines = content.querySelectorAll('.log-line');
        for (var i = 0; i < lines.length; i++) {
            var lineLevel = parseInt(lines[i].dataset.level, 10) || 20;
            lines[i].style.display = lineLevel >= _logMinLevel ? '' : 'none';
        }
    }

    function _initGlobalListeners() {
        // Game source toggle (Steam vs outside)
        var srcSteam   = document.getElementById('game-source-steam');
        var srcOutside = document.getElementById('game-source-outside');
        if (srcSteam) srcSteam.addEventListener('change', function() {
            _outsideMode = false;
            document.getElementById('steam-mode-row').style.display   = '';
            document.getElementById('outside-mode-row').style.display  = 'none';
        });
        if (srcOutside) srcOutside.addEventListener('change', function() {
            _outsideMode = true;
            document.getElementById('steam-mode-row').style.display   = 'none';
            document.getElementById('outside-mode-row').style.display  = '';
        });

        // Home game search filter
        var homeSearch = document.getElementById('home-game-search');
        if (homeSearch) {
            homeSearch.addEventListener('input', function() {
                _filterGameDropdown(this.value.trim().toLowerCase());
            });
        }

        // Browse button — opens native folder picker via bridge
        var browseBtn = document.getElementById('outside-path-browse');
        if (browseBtn) browseBtn.addEventListener('click', function() {
            Bridge.callSync('browse_game_folder', function(path) {
                if (path) document.getElementById('outside-path-display').value = path;
            });
        });

        // Repair Steam UI button
        var repairSteamBtn = document.getElementById('btn-repair-steam-ui');
        function _closeSteamUiRepairModal() {
            Components.hideModal('steam-ui-repair-modal');
        }
        ['steam-ui-repair-cancel', 'steam-ui-repair-cancel-footer'].forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.addEventListener('click', _closeSteamUiRepairModal);
        });
        var repairConfirm = document.getElementById('steam-ui-repair-confirm');
        if (repairConfirm) {
            repairConfirm.addEventListener('click', function() {
                _closeSteamUiRepairModal();
                Components.showToast('info', 'Réparation Steam en cours…');
                Bridge.call('repair_steam_ui');
            });
        }
        if (repairSteamBtn) {
            repairSteamBtn.addEventListener('click', function() {
                Components.showModal('steam-ui-repair-modal');
            });
        }

        // Restart Steam button
        var restartBtn = document.getElementById('btn-restart-steam');
        if (restartBtn) {
            restartBtn.addEventListener('click', function() {
                if (confirm('Restart Steam?')) {
                    Bridge.call('restart_steam');
                    Components.showToast('info', 'Redémarrage de Steam...');
                }
            });
        }

        // Global download button handler (delegated)
        document.addEventListener('click', function(e) {
            var dlBtn = e.target.closest('.btn-download');
            if (dlBtn) {
                e.preventDefault();
                var appId = dlBtn.dataset.appid;
                var name = dlBtn.dataset.name || ('App ' + appId);
                Components.showDownloadModal(appId, name, _platform);
            }
        });

        // Radio change — afficher ligne fichier local et dossier manifest
        document.querySelectorAll('input[name="dl-source"]').forEach(function(r) {
            r.addEventListener('change', function() {
                var localRow = document.getElementById('dl-local-row');
                var mfRow = document.getElementById('dl-manifest-folder-row');
                if (localRow) localRow.style.display = this.value === 'local' ? 'block' : 'none';
                if (mfRow && this.value !== 'local') mfRow.style.display = 'none';
            });
        });

        // Download modal — browse local lua/zip file
        var dlLocalBrowse = document.getElementById('dl-local-lua-browse');
        if (dlLocalBrowse) {
            dlLocalBrowse.addEventListener('click', function() {
                Bridge.callSync('open_lua_file_dialog', function(path) {
                    if (path) {
                        var inp = document.getElementById('dl-local-lua-path');
                        if (inp) inp.value = path;
                        var mfRow = document.getElementById('dl-manifest-folder-row');
                        if (mfRow) {
                            var ext = path.split('.').pop().toLowerCase();
                            mfRow.style.display = (ext === 'lua') ? 'block' : 'none';
                        }
                    }
                });
            });
        }

        // Download modal — browse manifest folder
        var dlMfBrowse = document.getElementById('dl-manifest-folder-browse');
        if (dlMfBrowse) {
            dlMfBrowse.addEventListener('click', function() {
                Bridge.callSync('open_manifest_folder_dialog', function(path) {
                    if (path) {
                        var inp = document.getElementById('dl-manifest-folder-path');
                        if (inp) inp.value = path;
                    }
                });
            });
        }

        // Download modal — fastest
        var dlFastest = document.getElementById('dl-fastest');
        if (dlFastest) {
            dlFastest.addEventListener('click', function() {
                var appId = this.dataset.appid;
                var sourceEl = document.querySelector('input[name="dl-source"]:checked');
                var source = sourceEl ? sourceEl.value : 'twentytwocloud';
                var localPath = '';
                if (source === 'local') {
                    localPath = (document.getElementById('dl-local-lua-path') || {}).value || '';
                    if (!localPath) {
                        Components.showToast('warning', 'Veuillez sélectionner un fichier .lua ou .zip local d\'abord.');
                        return;
                    }
                }
                Components.hideModal('download-modal');
                _startDownload(appId, 'fastest', source, '0', localPath);
            });
        }

        // Download modal — older version
        var dlOlder = document.getElementById('dl-older');
        if (dlOlder) {
            dlOlder.addEventListener('click', function() {
                var appId = this.dataset.appid;
                Components.hideModal('download-modal');
                _showVersionPicker(appId);
            });
        }

        // Download modal — direct DDMod
        var dlDdmod = document.getElementById('dl-ddmod');
        if (dlDdmod) {
            dlDdmod.addEventListener('click', function() {
                var appId = this.dataset.appid;
                var sourceEl = document.querySelector('input[name="dl-source"]:checked');
                var source = sourceEl ? sourceEl.value : 'twentytwocloud';
                var luaPath = '';
                var manifestFolder = '';
                if (source === 'local') {
                    luaPath = (document.getElementById('dl-local-lua-path') || {}).value || '';
                    if (!luaPath) {
                        Components.showToast('warning', 'Veuillez sélectionner un fichier .lua ou .zip local d\'abord.');
                        return;
                    }
                    manifestFolder = (document.getElementById('dl-manifest-folder-path') || {}).value || '';
                }
                Components.hideModal('download-modal');
                _startDdmodDownload(appId, source, luaPath, manifestFolder);
            });
        }

        // DDMod choose modal (home tab) — Through Steam button
        var ddmodChooseSteam = document.getElementById('ddmod-choose-steam');
        if (ddmodChooseSteam) {
            ddmodChooseSteam.addEventListener('click', function() {
                var appId = this.dataset.appid || '';
                Components.hideModal('ddmod-choose-modal');
                Bridge.call('run_game_action', appId, 'download_games');
            });
        }

        // DDMod choose modal (home tab) — Via DDMod button
        var ddmodChooseDdmod = document.getElementById('ddmod-choose-ddmod');
        if (ddmodChooseDdmod) {
            ddmodChooseDdmod.addEventListener('click', function() {
                var appId = this.dataset.appid || '';
                Components.hideModal('ddmod-choose-modal');
                _openDdmodHomeModal(appId);
            });
        }

        // DDMod home modal — source radio change
        document.querySelectorAll('input[name="ddmod-home-source"]').forEach(function(r) {
            r.addEventListener('change', function() {
                var localRow = document.getElementById('ddmod-home-local-row');
                var recentRow = document.getElementById('ddmod-home-recent-row');
                var mfRow = document.getElementById('ddmod-home-manifest-row');
                if (localRow) localRow.style.display = this.value === 'local' ? 'block' : 'none';
                if (recentRow) recentRow.style.display = this.value === 'recent' ? 'block' : 'none';
                if (mfRow && this.value !== 'local') mfRow.style.display = 'none';
            });
        });

        // DDMod home modal — browse local lua/zip file
        var ddmodHomeBrowse = document.getElementById('ddmod-home-local-browse');
        if (ddmodHomeBrowse) {
            ddmodHomeBrowse.addEventListener('click', function() {
                Bridge.callSync('open_lua_file_dialog', function(path) {
                    if (path) {
                        var inp = document.getElementById('ddmod-home-local-path');
                        if (inp) inp.value = path;
                        var mfRow = document.getElementById('ddmod-home-manifest-row');
                        if (mfRow) {
                            var ext = path.split('.').pop().toLowerCase();
                            mfRow.style.display = (ext === 'lua') ? 'block' : 'none';
                        }
                    }
                });
            });
        }

        // DDMod home modal — browse manifest folder
        var ddmodHomeMfBrowse = document.getElementById('ddmod-home-manifest-browse');
        if (ddmodHomeMfBrowse) {
            ddmodHomeMfBrowse.addEventListener('click', function() {
                Bridge.callSync('open_manifest_folder_dialog', function(path) {
                    if (path) {
                        var inp = document.getElementById('ddmod-home-manifest-path');
                        if (inp) inp.value = path;
                    }
                });
            });
        }

        // DDMod home modal — Download button
        var ddmodHomeDownload = document.getElementById('ddmod-home-download');
        if (ddmodHomeDownload) {
            ddmodHomeDownload.addEventListener('click', function() {
                var appId = (document.getElementById('ddmod-home-appid') || {}).value || '';
                if (!appId) {
                    Components.showToast('warning', 'Veuillez entrer un App ID.');
                    return;
                }
                var sourceEl = document.querySelector('input[name="ddmod-home-source"]:checked');
                var source = sourceEl ? sourceEl.value : 'twentytwocloud';
                var luaPath = '';
                var manifestFolder = '';
                if (source === 'local') {
                    luaPath = (document.getElementById('ddmod-home-local-path') || {}).value || '';
                    if (!luaPath) {
                        Components.showToast('warning', 'Veuillez sélectionner un fichier .lua ou .zip local d\'abord.');
                        return;
                    }
                    manifestFolder = (document.getElementById('ddmod-home-manifest-path') || {}).value || '';
                } else if (source === 'recent') {
                    luaPath = (document.getElementById('ddmod-home-recent-select') || {}).value || '';
                    if (!luaPath) {
                        Components.showToast('warning', 'Veuillez sélectionner un fichier récent.');
                        return;
                    }
                    source = 'local';
                }
                Components.hideModal('ddmod-home-modal');
                _startDdmodDownload(appId, source, luaPath, manifestFolder);
            });
        }

        // Version picker — download selected
        var versionDl = document.getElementById('version-download');
        if (versionDl) {
            versionDl.addEventListener('click', function() {
                _downloadSelectedVersion();
            });
        }

        // Home page action cards
        document.querySelectorAll('.action-card[data-action]').forEach(function(card) {
            card.addEventListener('click', function() {
                var action = this.dataset.action;
                _handleHomeAction(action);
            });
        });

        // Update Manifests modal — wire Run + Select-All + Restart-after-download buttons
        var umRunBtn = document.getElementById('update-manifests-run');
        if (umRunBtn) {
            umRunBtn.addEventListener('click', function() {
                var excludes = [];
                document.querySelectorAll('#um-game-list input[type="checkbox"]:not(:checked)').forEach(function(cb) {
                    if (cb.dataset.appid) excludes.push(cb.dataset.appid);
                });
                Bridge.call('set_setting', 'manifest_update_excludes', excludes.join(','));
                Components.hideModal('update-manifests-modal');
                Components.showToast('info', 'Mise à jour des jeux…');
                Bridge.call('run_game_action', '', 'update_manifests');
            });
        }

        var umToggleBtn = document.getElementById('um-toggle-all');
        if (umToggleBtn) {
            umToggleBtn.addEventListener('click', function() {
                var checkboxes = document.querySelectorAll('#um-game-list input[type="checkbox"]');
                var allChecked = Array.prototype.every.call(checkboxes, function(cb) { return cb.checked; });
                checkboxes.forEach(function(cb) { cb.checked = !allChecked; });
                umToggleBtn.textContent = allChecked ? 'Tout sélectionner' : 'Tout désélectionner';
            });
        }

        var rsDlBtn = document.getElementById('restart-after-dl-run');
        if (rsDlBtn) {
            rsDlBtn.addEventListener('click', function() {
                Components.hideModal('restart-after-download-modal');
                Bridge.call('restart_steam');
            });
        }
    }

    function _startDdmodDownload(appId, source, luaPath, manifestFolder) {
        Bridge.callSync('get_steam_libraries', function(json) {
            var libs;
            try { libs = JSON.parse(json || '[]'); } catch(e) { libs = []; }
            if (libs.length === 0) {
                Components.showToast('error', 'Aucune bibliothèque Steam trouvée. Vérifiez le chemin Steam dans les Paramètres.');
                return;
            }
            var mf = manifestFolder || '';
            if (libs.length === 1) {
                Bridge.call('set_active_library', libs[0]);
                Components.showToast('info', 'Démarrage du téléchargement DDMod pour l\'App ' + appId + '...');
                Bridge.call('download_game_ddmod', appId, source, luaPath || '', mf);
            } else {
                Components.showLibraryModal(libs, function(selectedLib) {
                    Bridge.call('set_active_library', selectedLib);
                    Components.showToast('info', 'Démarrage du téléchargement DDMod pour l\'App ' + appId + '...');
                    Bridge.call('download_game_ddmod', appId, source, luaPath || '', mf);
                });
            }
        });
    }

    function _openDdmodHomeModal(appId) {
        var appIdInp = document.getElementById('ddmod-home-appid');
        if (appIdInp) appIdInp.value = appId || '';
        var localRow = document.getElementById('ddmod-home-local-row');
        var recentRow = document.getElementById('ddmod-home-recent-row');
        var mfRow = document.getElementById('ddmod-home-manifest-row');
        var mfInp = document.getElementById('ddmod-home-manifest-path');
        if (localRow) localRow.style.display = 'none';
        if (recentRow) recentRow.style.display = 'none';
        if (mfRow) mfRow.style.display = 'none';
        if (mfInp) mfInp.value = '';
        var firstRadio = document.querySelector('input[name="ddmod-home-source"][value="twentytwocloud"]');
        if (firstRadio) firstRadio.checked = true;

        Bridge.callSync('get_recent_lua_files', function(json) {
            var files;
            try { files = JSON.parse(json || '[]'); } catch(e) { files = []; }
            var sel = document.getElementById('ddmod-home-recent-select');
            if (sel) {
                sel.innerHTML = '<option value="">-- select a recent file --</option>';
                files.forEach(function(f) {
                    var opt = document.createElement('option');
                    opt.value = f.path;
                    opt.textContent = f.name;
                    sel.appendChild(opt);
                });
                var recentRadio = document.querySelector('input[name="ddmod-home-source"][value="recent"]');
                if (recentRadio) recentRadio.disabled = files.length === 0;
            }
        });

        Components.showModal('ddmod-home-modal');
    }

    function _startDownload(appId, mode, source, requestUpdate, localLuaPath) {
        // First, ask for library selection
        Bridge.callSync('get_steam_libraries', function(json) {
            var libs;
            try { libs = JSON.parse(json || '[]'); } catch(e) { libs = []; }

            if (libs.length === 0) {
                Components.showToast('error', 'Aucune bibliothèque Steam trouvée. Vérifiez le chemin Steam dans les Paramètres.');
                return;
            }

            if (libs.length === 1) {
                Bridge.call('set_active_library', libs[0]);
                _executeDownload(appId, mode, source, requestUpdate, localLuaPath);
            } else {
                Components.showLibraryModal(libs, function(selectedLib) {
                    Bridge.call('set_active_library', selectedLib);
                    _executeDownload(appId, mode, source, requestUpdate, localLuaPath);
                });
            }
        });
    }

    function _executeDownload(appId, mode, source, requestUpdate, localLuaPath) {
        Components.showToast('info', 'Démarrage du téléchargement pour l\'App ' + appId + '...');
        if (mode === 'fastest') {
            var src = source || 'twentytwocloud';
            Bridge.call('download_game_with_source', appId, src, requestUpdate || '0', localLuaPath || '');
        }
    }

    function _showVersionPicker(appId) {
        Components.showModal('version-modal');
        var loading = document.getElementById('version-loading');
        var table = document.getElementById('version-table');
        var tbody = document.getElementById('version-tbody');
        var dlBtn = document.getElementById('version-download');

        if (loading) loading.classList.remove('hidden');
        if (table) table.classList.add('hidden');
        if (dlBtn) { dlBtn.disabled = true; dlBtn.dataset.appid = appId; }

        var handler = function(json) {
            Bridge.off('depot_history_results', handler);
            if (loading) loading.classList.add('hidden');
            if (table) table.classList.remove('hidden');

            try {
                var groups = JSON.parse(json);
                if (!tbody) return;
                tbody.innerHTML = '';

                // Source color map
                var sourceColors = {
                    'SteamDB': '#c084fc',
                    'Steam CM': '#60a5fa'
                };

                groups.forEach(function(group, gi) {
                    var groupId = 'vg-' + gi;
                    var entries = group.entries || [];
                    var srcColor = sourceColors[group.source] || '#ccc';

                    // Version group header row (collapsible, starts collapsed)
                    var hdr = document.createElement('tr');
                    hdr.className = 'version-group-header';
                    hdr.dataset.group = groupId;
                    hdr.dataset.collapsed = 'true';
                    hdr.style.cssText = 'background:rgba(255,255,255,0.07);cursor:pointer;user-select:none;';
                    hdr.innerHTML =
                        '<td colspan="5" style="font-weight:600;padding:6px 8px;">' +
                        '<span class="vg-chevron" style="display:inline-block;width:16px;margin-right:4px;transition:transform 0.2s;">&#9654;</span>' +
                        '<span style="color:' + srcColor + ';">' + Components.escapeHtml(group.label) + '</span>' +
                        '</td>' +
                        '<td style="text-align:center;" onclick="event.stopPropagation();">' +
                        '<input type="checkbox" class="version-group-check" data-group="' + groupId + '" title="Select all depots in this version">' +
                        '</td>';
                    tbody.appendChild(hdr);

                    // Individual depot rows (hidden by default)
                    entries.forEach(function(entry) {
                        var tr = document.createElement('tr');
                        tr.className = 'version-depot-row';
                        tr.dataset.group = groupId;
                        tr.style.display = 'none';
                        var srcCellColor = sourceColors[group.source] || '';
                        tr.innerHTML =
                            '<td>' + Components.escapeHtml(entry.depot_id) + '</td>' +
                            '<td style="font-family:monospace;font-size:0.85em;">' + Components.escapeHtml(entry.manifest_id) + '</td>' +
                            '<td>' + Components.escapeHtml(group.date === '0000-00-00' ? 'Unknown' : group.date) + '</td>' +
                            '<td>' + Components.escapeHtml(group.branch || '') + '</td>' +
                            '<td style="color:' + srcCellColor + ';">' + Components.escapeHtml(group.source || '') + '</td>' +
                            '<td style="text-align:center;">' +
                            '<input type="checkbox" class="version-check" data-group="' + groupId + '" data-depot="' + Components.escapeHtml(entry.depot_id) + '" data-manifest="' + Components.escapeHtml(entry.manifest_id) + '">' +
                            '</td>';
                        tbody.appendChild(tr);
                    });
                });

                // Click header to expand/collapse depot rows
                tbody.addEventListener('click', function(e) {
                    var hdr = e.target.closest('.version-group-header');
                    if (!hdr) return;
                    // Don't toggle when clicking the checkbox
                    if (e.target.tagName === 'INPUT') return;
                    var gid = hdr.dataset.group;
                    var isCollapsed = hdr.dataset.collapsed === 'true';
                    var rows = tbody.querySelectorAll('.version-depot-row[data-group="' + gid + '"]');
                    var chevron = hdr.querySelector('.vg-chevron');
                    if (isCollapsed) {
                        rows.forEach(function(r) { r.style.display = ''; });
                        hdr.dataset.collapsed = 'false';
                        if (chevron) chevron.style.transform = 'rotate(90deg)';
                    } else {
                        rows.forEach(function(r) { r.style.display = 'none'; });
                        hdr.dataset.collapsed = 'true';
                        if (chevron) chevron.style.transform = '';
                    }
                });

                // Group header checkbox: toggle all depots in that group
                tbody.addEventListener('change', function(e) {
                    if (e.target.classList.contains('version-group-check')) {
                        var gid = e.target.dataset.group;
                        tbody.querySelectorAll('.version-check[data-group="' + gid + '"]').forEach(function(cb) {
                            cb.checked = e.target.checked;
                        });
                    }
                    var checked = tbody.querySelectorAll('.version-check:checked');
                    if (dlBtn) dlBtn.disabled = checked.length === 0;
                });

            } catch(e) {
                Components.showToast('error', 'Impossible de charger l\'historique des versions');
            }
        };
        Bridge.on('depot_history_results', handler);
        Bridge.call('fetch_depot_history', appId, false);
    }

    function _downloadSelectedVersion() {
        var dlBtn = document.getElementById('version-download');
        var appId = dlBtn ? dlBtn.dataset.appid : '';
        var tbody = document.getElementById('version-tbody');
        if (!tbody || !appId) return;

        var manifest_override = {};
        tbody.querySelectorAll('.version-check:checked').forEach(function(cb) {
            manifest_override[cb.dataset.depot] = cb.dataset.manifest;
        });

        Components.hideModal('version-modal');

        // Library selection + version download
        Bridge.callSync('get_steam_libraries', function(json) {
            var libs;
            try { libs = JSON.parse(json || '[]'); } catch(e) { libs = []; }

            var doDownload = function() {
                Bridge.call('download_game_version', appId, JSON.stringify(manifest_override));
                Components.showToast('info', 'Téléchargement d\'une version spécifique de l\'App ' + appId + '...');
            };

            if (libs.length <= 1) {
                if (libs.length === 1) Bridge.call('set_active_library', libs[0]);
                doDownload();
            } else {
                Components.showLibraryModal(libs, function(selectedLib) {
                    Bridge.call('set_active_library', selectedLib);
                    doDownload();
                });
            }
        });
    }

    function _filterGameDropdown(filter) {
        var dropdown = document.querySelector('#home-game-select-ui .custom-select-dropdown');
        if (!dropdown) return;
        var items = dropdown.querySelectorAll('.custom-select-option');
        items.forEach(function(item) {
            var text = (item.textContent || '').toLowerCase();
            item.style.display = (filter && text.indexOf(filter) === -1) ? 'none' : '';
        });
    }

    function _populateGameDropdown() {
        Bridge.callSync('get_game_list', function(json) {
            var games;
            try { games = JSON.parse(json || '[]'); } catch(e) { games = []; }
            var select = document.getElementById('home-game-select');
            if (!select) return;
            // Keep the placeholder option
            select.innerHTML = '<option value="">-- Select a game --</option>';
            games.forEach(function(game) {
                var opt = document.createElement('option');
                opt.value = game.app_id;
                opt.textContent = game.name + ' (' + game.app_id + ')';
                select.appendChild(opt);
            });
            // Re-apply active search filter after dropdown rebuilds
            var searchInp = document.getElementById('home-game-search');
            if (searchInp && searchInp.value.trim()) {
                var filterVal = searchInp.value.trim().toLowerCase();
                setTimeout(function() { _filterGameDropdown(filterVal); }, 60);
            }
        });
    }

    function _getSelectedGameId() {
        var select = document.getElementById('home-game-select');
        return select ? select.value : '';
    }

    var _hvWarningInitialised = false;
    function _initHvWarningModal() {
        if (_hvWarningInitialised) return;
        _hvWarningInitialised = true;

        var cancelBtn = document.getElementById('hv-warning-cancel');
        var okBtn     = document.getElementById('hv-warning-ok');
        var discordA  = document.getElementById('hv-discord-btn');

        if (cancelBtn) {
            cancelBtn.addEventListener('click', function() {
                _hvClearCountdown();
                Components.hideModal('hv-warning-modal');
            });
        }
        if (okBtn) {
            okBtn.addEventListener('click', function() {
                if (this.disabled) return;
                _hvClearCountdown();
                Components.hideModal('hv-warning-modal');
                var appId   = this.dataset.pendingAppId   || '';
                var outside = this.dataset.pendingOutside === '1';
                var path    = this.dataset.pendingPath    || '';
                var oAppId  = this.dataset.pendingOAppId  || '0';
                Bridge.call('set_setting', 'hv_first_use_warned', 'true');
                Bridge.call('open_url', 'https://discord.gg/denuvowo');
                if (outside) {
                    Bridge.call('run_game_action_outside', path, oAppId, 'hv_fix');
                } else {
                    Bridge.call('run_game_action', appId, 'hv_fix');
                }
            });
        }
        if (discordA) {
            discordA.addEventListener('click', function(e) {
                e.preventDefault();
                Bridge.call('open_url', 'https://discord.gg/denuvowo');
            });
        }
    }

    var _hvCountdownTimer = null;
    function _hvClearCountdown() {
        if (_hvCountdownTimer !== null) {
            clearInterval(_hvCountdownTimer);
            _hvCountdownTimer = null;
        }
    }

    function _showHvWarning(onConfirmArgs) {
        _initHvWarningModal();
        var okBtn  = document.getElementById('hv-warning-ok');
        var cdSpan = document.getElementById('hv-countdown');
        if (!okBtn || !cdSpan) return false;

        // Store context for the OK handler
        okBtn.disabled = true;
        okBtn.dataset.pendingAppId   = onConfirmArgs.appId   || '';
        okBtn.dataset.pendingOutside = onConfirmArgs.outside ? '1' : '0';
        okBtn.dataset.pendingPath    = onConfirmArgs.path    || '';
        okBtn.dataset.pendingOAppId  = onConfirmArgs.oAppId  || '0';

        var secs = 20;
        cdSpan.textContent = secs;
        okBtn.innerHTML = 'I Understand \u2014 Continue (<span id="hv-countdown">' + secs + '</span>s)';

        _hvClearCountdown();
        _hvCountdownTimer = setInterval(function() {
            secs--;
            var span = document.getElementById('hv-countdown');
            if (span) span.textContent = secs;
            if (secs <= 0) {
                _hvClearCountdown();
                okBtn.disabled = false;
                okBtn.innerHTML = 'I Understand \u2014 Continue';
            }
        }, 1000);

        Components.showModal('hv-warning-modal');
        return true;
    }

    function _handleHomeAction(action) {
        // Show game-picker dialog before running update_manifests
        if (action === 'update_manifests') {
            var listEl = document.getElementById('um-game-list');
            var countEl = document.getElementById('um-count');
            var toggleBtn = document.getElementById('um-toggle-all');
            if (listEl) listEl.innerHTML = '<span style="opacity:0.5;font-size:13px;">Loading games...</span>';
            if (countEl) countEl.textContent = 'Loading...';
            if (toggleBtn) toggleBtn.textContent = 'Deselect All';
            Components.showModal('update-manifests-modal');
            Bridge.callSync('get_applist_games', function(json) {
                var games;
                try { games = JSON.parse(json || '[]'); } catch(e) { games = []; }
                if (!listEl) return;
                if (games.length === 0) {
                    listEl.innerHTML = '<span style="opacity:0.5;font-size:13px;">No saved Lua files found.</span>';
                    if (countEl) countEl.textContent = '0 games';
                    return;
                }
                Bridge.callWithCallback('get_setting', 'manifest_update_excludes', function(excludeVal) {
                    var excludedSet = new Set(
                        (excludeVal || '').split(',').map(function(x) { return x.trim(); }).filter(Boolean)
                    );
                    var html = '';
                    games.forEach(function(g) {
                        var safe = (g.name || g.app_id).replace(/</g, '&lt;').replace(/>/g, '&gt;');
                        var isExcluded = excludedSet.has(String(g.app_id));
                        html += '<label style="display:flex;align-items:center;gap:8px;padding:5px 2px;cursor:pointer;font-size:13px;">'
                            + '<input type="checkbox" data-appid="' + g.app_id + '"'
                            + (isExcluded ? '' : ' checked')
                            + ' style="accent-color:var(--accent,#e94560);">'
                            + '<span>' + safe + ' <span style="opacity:0.45;font-size:11px;">' + g.app_id + '</span></span>'
                            + '</label>';
                    });
                    listEl.innerHTML = html;
                    if (countEl) countEl.textContent = games.length + ' game' + (games.length !== 1 ? 's' : '');
                });
            });
            return;
        }

        // HyperVisor action — check first-use warning
        if (action === 'hv_fix') {
            // Resolve the game/path context first, then decide whether to show warning
            var hvAppId    = '';
            var hvOutside  = false;
            var hvPath     = '';
            var hvOAppId   = '0';
            if (_outsideMode) {
                hvPath    = (document.getElementById('outside-path-display') || {}).value || '';
                hvOAppId  = (document.getElementById('outside-appid') || {}).value || '0';
                if (!hvPath) {
                    Components.showToast('warning', 'Veuillez sélectionner un dossier de jeu d\'abord.');
                    return;
                }
                hvOutside = true;
            } else {
                hvAppId = _getSelectedGameId();
                if (!hvAppId) {
                    Components.showToast('warning', 'Veuillez sélectionner un jeu dans la liste d\'abord.');
                    return;
                }
            }
            var confirmArgs = { appId: hvAppId, outside: hvOutside, path: hvPath, oAppId: hvOAppId };
            Bridge.callWithCallback('get_setting', 'hv_first_use_warned', function(val) {
                var warned = val === 'True' || val === 'true' || val === '1';
                if (!warned) {
                    _showHvWarning(confirmArgs);
                } else {
                    if (hvOutside) {
                        Bridge.call('run_game_action_outside', hvPath, hvOAppId, 'hv_fix');
                    } else {
                        Bridge.call('run_game_action', hvAppId, 'hv_fix');
                    }
                }
            });
            return;
        }

        if (action === 'download_games') {
            var homeAppId = _getSelectedGameId() || '';
            var chooseSteamBtn = document.getElementById('ddmod-choose-steam');
            var chooseDdmodBtn = document.getElementById('ddmod-choose-ddmod');
            if (chooseSteamBtn) chooseSteamBtn.dataset.appid = homeAppId;
            if (chooseDdmodBtn) chooseDdmodBtn.dataset.appid = homeAppId;
            Components.showModal('ddmod-choose-modal');
            return;
        }

        if (action === 'auto_gl_setup') {
            _initGlSetupModal();
            Bridge.callWithCallback('get_setting', 'steam_path', function(steamPath) {
                var steamExeInp = document.getElementById('gl-steam-exe');
                if (steamExeInp && steamPath && !steamExeInp.value) {
                    steamExeInp.value = steamPath.replace(/[\\/]$/, '') + '\\steam.exe';
                }
            });
            Components.showModal('gl-setup-modal');
            return;
        }

        if (action === 'slimedeals_bprg') {
            Bridge.onReady(function(py) {
                py.get_user_rank(function(jsonStr) {
                    var d, rnk;
                    try {
                        d = JSON.parse(jsonStr);
                        rnk = d.rank || 'free';
                    } catch (e) {
                        rnk = 'free';
                    }
                    if (!_tripleExclusiveToolsAllowed(rnk)) {
                        Components.showModal('bprg-free-upsell-modal');
                        return;
                    }
                    Bridge.call('launch_slimedeals_bprg');
                });
            });
            return;
        }

        // Non-game actions don't need a game selected
        var nonGameActions = [
            'download_games', 'download_manifests', 'recent_lua', 'update_manifests',
            'mute_toggle', 'remove_game', 'context_menu', 'applist_menu', 'offline_fix',
            'check_updates', 'scan_library', 'analytics', 'auto_gl_setup', 'slimedeals_bprg'
        ];
        // Outside-Steam game action
        if (_outsideMode && nonGameActions.indexOf(action) === -1) {
            var gamePath     = (document.getElementById('outside-path-display') || {}).value || '';
            var outsideAppId = (document.getElementById('outside-appid') || {}).value || '0';
            if (!gamePath) {
                Components.showToast('warning', 'Veuillez sélectionner un dossier de jeu d\'abord.');
                return;
            }
            Bridge.call('run_game_action_outside', gamePath, outsideAppId || '0', action);
            return;
        }

        // Steam game action
        var appId = _getSelectedGameId();
        if (nonGameActions.indexOf(action) === -1 && !appId) {
            Components.showToast('warning', 'Veuillez sélectionner un jeu dans la liste d\'abord.');
            return;
        }
        Bridge.call('run_game_action', appId || '', action);
    }

    var _glSetupInitialized = false;
    function _initGlSetupModal() {
        if (_glSetupInitialized) return;
        _glSetupInitialized = true;

        var archiveBrowse = document.getElementById('gl-archive-browse');
        if (archiveBrowse) {
            archiveBrowse.addEventListener('click', function() {
                Bridge.callSync('open_archive_dialog', function(path) {
                    if (path) {
                        var inp = document.getElementById('gl-archive-path');
                        if (inp) inp.value = path;
                    }
                });
            });
        }

        var steamBrowse = document.getElementById('gl-steam-browse');
        if (steamBrowse) {
            steamBrowse.addEventListener('click', function() {
                Bridge.callSync('open_exe_file_dialog', function(path) {
                    if (path) {
                        var inp = document.getElementById('gl-steam-exe');
                        if (inp) inp.value = path;
                    }
                });
            });
        }

        var runBtn = document.getElementById('gl-setup-run');
        if (runBtn) {
            runBtn.addEventListener('click', function() {
                var archivePath = (document.getElementById('gl-archive-path') || {}).value || '';
                var steamExe = (document.getElementById('gl-steam-exe') || {}).value || '';
                var methodEl = document.querySelector('input[name="gl-method"]:checked');
                var method = methodEl ? methodEl.value : 'A';
                if (!archivePath) {
                    Components.showToast('warning', 'Veuillez sélectionner l\'archive GreenLuma d\'abord');
                    return;
                }
                runBtn.disabled = true;
                Components.hideModal('gl-setup-modal');
                Bridge.call('auto_gl_setup_action', JSON.stringify({
                    method: method,
                    archive_path: archivePath,
                    steam_exe: steamExe
                }));
            });
        }
    }

    function getPlatform() {
        return _platform;
    }

    return {
        init: init,
        navigateTo: navigateTo,
        getPlatform: getPlatform
    };
})();

// Boot the app when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    App.init();
});
