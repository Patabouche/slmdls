/**
 * SlimeDeals — Store Page
 * - Plan FREE  → catalogue de 4 jeux (1 choix définitif)
 * - Triple Monstre → recherche TwentyTwoCloud libre
 */

window.Store = (function () {
    'use strict';

    var _currentAppId  = null;
    var _initialized   = false;
    var _userRank      = null;   // 'free' | 'triple_monstre'
    var _freeClaimed   = null;   // null | app_id string

    var FREE_CATALOG = [
        {
            app_id : '2416450',
            name   : 'MOUSE: P.I. For Hire',
            url    : 'https://store.steampowered.com/app/2416450/MOUSE_PI_For_Hire/',
        },
        {
            app_id : '284160',
            name   : 'BeamNG.drive',
            url    : 'https://store.steampowered.com/app/284160/BeamNGdrive/',
        },
        {
            app_id : '3241660',
            name   : 'R.E.P.O.',
            url    : 'https://store.steampowered.com/app/3241660/REPO/',
        },
        {
            app_id : '1943950',
            name   : 'Escape the Backrooms',
            url    : 'https://store.steampowered.com/app/1943950/Escape_the_Backrooms/',
        },
    ];

    function _steamHeader(appId) {
        return 'https://cdn.cloudflare.steamstatic.com/steam/apps/' + appId + '/header.jpg';
    }

    // ── Rank detection ────────────────────────────────────────────────────────

    function _loadRankAndDisplay() {
        var loadEl = document.getElementById('store-rank-loading');
        if (loadEl) loadEl.classList.remove('hidden');

        Bridge.onReady(function(py) {
            py.get_user_rank(function(jsonStr) {
                var d;
                try { d = JSON.parse(jsonStr); } catch(e) { d = {rank:'free', free_claimed: null}; }
                _userRank    = d.rank || 'free';
                _freeClaimed = d.free_claimed || null;
                if (loadEl) loadEl.classList.add('hidden');
                _renderStore();
            });
        });
    }

    function _renderStore() {
        var freeSection    = document.getElementById('store-free-section');
        var premiumSection = document.getElementById('store-premium-section');
        var subtitle       = document.getElementById('store-subtitle');

        if (_userRank === 'triple_monstre') {
            if (freeSection)    freeSection.classList.add('hidden');
            if (premiumSection) premiumSection.classList.remove('hidden');
            if (subtitle) subtitle.textContent = 'Colle un lien Steam — Triple Monstre, jeux illimités';
            _initPremiumListeners();
        } else {
            if (premiumSection) premiumSection.classList.add('hidden');
            if (freeSection)    freeSection.classList.remove('hidden');
            if (subtitle) subtitle.textContent = 'Plan FREE — choisis un jeu parmi le catalogue';
            _renderFreeCatalog();
            _bindFreePlanGuide();
        }
    }

    var _freePlanGuideBound = false;
    var _discordAvisUrl = 'https://discord.gg/slimedeals';

    function _bindFreePlanGuide() {
        if (_freePlanGuideBound) return;
        var btnT = document.getElementById('free-cta-tarifs');
        var btnA = document.getElementById('free-cta-avis');
        if (!btnT || !btnA) return;
        _freePlanGuideBound = true;
        btnT.addEventListener('click', function (e) {
            e.preventDefault();
            Bridge.call('open_url', 'https://slimedeals.fr/#tarifs');
        });
        btnA.addEventListener('click', function (e) {
            e.preventDefault();
            Bridge.call('open_url', _discordAvisUrl);
        });
        Bridge.onReady(function (py) {
            if (typeof py.discord_avis_url !== 'function') return;
            py.discord_avis_url(function (url) {
                if (url && typeof url === 'string' && url.indexOf('http') === 0) {
                    _discordAvisUrl = url;
                }
            });
        });
    }

    // ── FREE catalog ──────────────────────────────────────────────────────────

    function _renderFreeCatalog() {
        var grid = document.getElementById('free-catalog-grid');
        if (!grid) return;
        grid.innerHTML = '';

        var hasClaimed  = !!_freeClaimed;
        var badge       = document.getElementById('free-plan-claimed-badge');
        var alreadyMsg  = document.getElementById('free-already-claimed-msg');

        if (badge)      badge.classList.toggle('hidden', !hasClaimed);
        if (alreadyMsg) alreadyMsg.classList.toggle('hidden', !hasClaimed);

        FREE_CATALOG.forEach(function(game) {
            var isMine  = hasClaimed && _freeClaimed === game.app_id;
            var isOther = hasClaimed && _freeClaimed !== game.app_id;

            var card = document.createElement('div');
            card.className = 'free-catalog-card' +
                (isMine  ? ' is-claimed'       : '') +
                (isOther ? ' is-other-claimed' : '');

            var ribbon = '<div class="free-catalog-card-claimed-ribbon">Ton choix</div>';

            var btnLabel, btnDisabled;
            if (isMine) {
                btnLabel    = '✅ Installé / réclamé';
                btnDisabled = 'disabled';
            } else if (isOther) {
                btnLabel    = 'Non disponible';
                btnDisabled = 'disabled';
            } else {
                btnLabel    = '⬇ Choisir ce jeu';
                btnDisabled = '';
            }

            card.innerHTML =
                ribbon +
                '<img src="' + _steamHeader(game.app_id) + '" alt="' + game.name + '" loading="lazy">' +
                '<div class="free-catalog-card-body">' +
                    '<div class="free-catalog-card-name">' + game.name + '</div>' +
                    '<button class="free-catalog-card-btn" data-appid="' + game.app_id + '" ' + btnDisabled + '>' +
                        btnLabel +
                    '</button>' +
                '</div>';

            if (!hasClaimed) {
                card.addEventListener('click', function(e) {
                    var btn = e.target.closest('button.free-catalog-card-btn');
                    if (btn) _claimFreeGame(game.app_id, game.name);
                });
            }

            grid.appendChild(card);
        });
    }

    function _claimFreeGame(appId, gameName) {
        // Confirm
        if (!confirm('Confirmer la sélection de "' + gameName + '" ?\nCe choix est définitif et ne peut pas être changé.')) return;

        // Disable all buttons during processing
        var allBtns = document.querySelectorAll('.free-catalog-card-btn');
        allBtns.forEach(function(b) { b.disabled = true; b.textContent = 'Traitement…'; });

        Bridge.onReady(function(py) {
            py.record_free_claim(appId, function(jsonStr) {
                var result;
                try { result = JSON.parse(jsonStr); } catch(e) { result = {ok: false, error: 'Erreur interne'}; }

                if (result.ok) {
                    _freeClaimed = String(appId);
                    // Laisser le disque enregistrer auth.json avant le téléchargement (évite faux refus plan FREE)
                    setTimeout(function () {
                        Bridge.call('download_game_with_source', String(appId), 'twentytwocloud', '0');
                    }, 0);
                    if (typeof showToast === 'function') {
                        showToast('Téléchargement de ' + gameName + ' lancé !', 'success');
                    }
                    _renderFreeCatalog();
                } else if (result.error === 'already_claimed') {
                    _freeClaimed = result.app_id || appId;
                    _renderFreeCatalog();
                } else {
                    // Restore buttons on error
                    allBtns.forEach(function(b) { b.disabled = false; b.textContent = '⬇ Choisir ce jeu'; });
                    if (typeof showToast === 'function') {
                        showToast('Erreur : ' + (result.error || 'Impossible de valider.'), 'error');
                    }
                }
            });
        });
    }

    // ── Premium TwentyTwoCloud ─────────────────────────────────────────────────

    function _extractAppId(input) {
        input = (input || '').trim();
        var m = input.match(/store\.steampowered\.com\/app\/(\d+)/i);
        if (m) return m[1];
        if (/^\d+$/.test(input)) return input;
        return null;
    }

    function _setLoading(on) {
        var l = document.getElementById('ttc-loading');
        var r = document.getElementById('ttc-result');
        var e = document.getElementById('ttc-error');
        if (l) l.classList.toggle('hidden', !on);
        if (r) r.classList.add('hidden');
        if (e) e.classList.add('hidden');
    }

    function _showError(msg) {
        var l = document.getElementById('ttc-loading');
        var e = document.getElementById('ttc-error');
        var m = document.getElementById('ttc-error-msg');
        if (l) l.classList.add('hidden');
        if (e) e.classList.remove('hidden');
        if (m) m.textContent = msg || 'Erreur inconnue.';
    }

    function _showResult(data) {
        var l = document.getElementById('ttc-loading');
        var r = document.getElementById('ttc-result');
        if (l) l.classList.add('hidden');
        if (!r) return;

        document.getElementById('ttc-game-name').textContent   = data.name || ('App ' + data.app_id);
        document.getElementById('ttc-app-id-badge').textContent = 'App ID : ' + data.app_id;

        var img = document.getElementById('ttc-header-img');
        if (img) { img.src = data.header_image || ''; img.style.display = ''; }

        var status = document.getElementById('ttc-status-badge');
        if (status) {
            if (data.available) {
                status.textContent = '✓ Disponible';
                status.className   = 'ttc-status available';
            } else {
                status.textContent = '✗ Introuvable';
                status.className   = 'ttc-status unavailable';
            }
        }

        var dlBtn    = document.getElementById('ttc-download-btn');
        var depotBtn = document.getElementById('ttc-depot-btn');
        if (dlBtn)    dlBtn.disabled = !data.available;
        if (depotBtn) depotBtn.dataset.appid = data.app_id;

        _resetProgress();
        r.classList.remove('hidden');
        _currentAppId = data.app_id;
    }

    function _resetProgress() {
        var wrap  = document.getElementById('ttc-progress-wrap');
        var fill  = document.getElementById('ttc-progress-fill');
        var label = document.getElementById('ttc-progress-label');
        if (wrap)  wrap.classList.add('hidden');
        if (fill)  fill.style.width = '0%';
        if (label) label.textContent = 'Démarrage…';
    }

    function _showProgress(status, progress) {
        var wrap  = document.getElementById('ttc-progress-wrap');
        var fill  = document.getElementById('ttc-progress-fill');
        var label = document.getElementById('ttc-progress-label');
        if (wrap)  wrap.classList.remove('hidden');
        if (fill)  fill.style.width = (progress || 0) + '%';
        if (label) label.textContent = status || '…';
    }

    function _doSearch() {
        var input = document.getElementById('ttc-url-input');
        if (!input) return;
        var appId = _extractAppId(input.value);
        if (!appId) {
            _showError('Lien Steam invalide ou App ID introuvable. Exemple : https://store.steampowered.com/app/1971870/');
            return;
        }
        _setLoading(true);
        Bridge.call('lookup_ttc_game', appId);
    }

    var _premiumListenersAttached = false;
    function _initPremiumListeners() {
        if (_premiumListenersAttached) return;
        _premiumListenersAttached = true;

        var searchBtn = document.getElementById('ttc-search-btn');
        var urlInput  = document.getElementById('ttc-url-input');
        var dlBtn     = document.getElementById('ttc-download-btn');
        var depotBtn  = document.getElementById('ttc-depot-btn');

        if (searchBtn) searchBtn.addEventListener('click', _doSearch);
        if (urlInput)  urlInput.addEventListener('keydown', function(e) { if (e.key === 'Enter') _doSearch(); });

        if (dlBtn) {
            dlBtn.addEventListener('click', function() {
                if (!_currentAppId) return;
                _resetProgress();
                _showProgress('Démarrage du téléchargement…', 5);
                Bridge.call('download_game_with_source', _currentAppId, 'twentytwocloud', '0');
            });
        }
        if (depotBtn) {
            depotBtn.addEventListener('click', function() {
                var appId = depotBtn.dataset.appid || _currentAppId;
                if (!appId) return;
                Bridge.call('run_game_action', appId, 'download_games');
            });
        }

        Bridge.on('ttc_game_info', function(jsonStr) {
            var data;
            try { data = JSON.parse(jsonStr); } catch(e) {
                _showError('Réponse invalide du serveur.'); return;
            }
            _showResult(data);
        });
        Bridge.on('download_progress', function(jsonStr) {
            var d; try { d = JSON.parse(jsonStr); } catch(e) { return; }
            _showProgress(d.status, d.progress);
        });
        Bridge.on('task_finished', function(jsonStr) {
            var d; try { d = JSON.parse(jsonStr); } catch(e) { return; }
            if (d.task !== 'download_fastest') return;
            if (d.success) { _showProgress('✅ Installation terminée !', 100); }
            else           { _showProgress('❌ Échec du téléchargement.', 0); }
        });
    }

    // ── Public API ────────────────────────────────────────────────────────────

    function init() {
        if (_initialized) return;
        _initialized = true;
    }

    function onPageEnter() {
        init();
        _loadRankAndDisplay();
        // Focus input only if premium section ends up visible
        setTimeout(function() {
            var input = document.getElementById('ttc-url-input');
            var premSec = document.getElementById('store-premium-section');
            if (input && premSec && !premSec.classList.contains('hidden')) input.focus();
        }, 200);
    }

    function onApiKeyAvailable(_key) { /* conservé pour compatibilité */ }

    return { init: init, onPageEnter: onPageEnter, onApiKeyAvailable: onApiKeyAvailable };
})();
