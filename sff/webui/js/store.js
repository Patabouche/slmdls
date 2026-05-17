/**
 * SlimeDeals — Store Page
 * - Plan FREE  -> catalogue gratuit (jeux listés) + recherche Steam (install réservée abonnés)
 * - Monstre / Triple Monstre -> recherche + installation
 */

window.Store = (function () {
    'use strict';

    var _currentAppId  = null;
    var _initialized   = false;
    var _userRank      = null;   // valeur brute serveur (ex. free, triple_monstre, « TRIPLE MONSTRE »)
    var _freeClaimed   = null;   // null | app_id string
    var _monstreSlotsUsed = null;
    var _monstreSlotsMax = null;
    /** Pendant installation catalogue FREE : attendre task_finished download_fastest pour ce app_id. */
    var _freeCatalogInstallPending = null;
    var _freeCatalogTaskListenerBound = false;
    /** Réponse async begin_free_catalog_install (Worker Python — évite blocage WebChannel). */
    var _freeCatalogBeginHandler = null;
    var _freeCatalogBeginSignalBound = false;

    function _toast(level, msg) {
        if (typeof Components !== 'undefined' && Components.showToast) {
            Components.showToast(level, msg);
        }
    }

    function _bindFreeCatalogBeginResult() {
        if (_freeCatalogBeginSignalBound) return;
        _freeCatalogBeginSignalBound = true;
        Bridge.on('free_catalog_begin_result', function (jsonStr) {
            var h = _freeCatalogBeginHandler;
            _freeCatalogBeginHandler = null;
            if (!h) return;
            h(jsonStr);
        });
    }

    var TRIPLE_RANK_IDS = {
        triple_monstre: 1, triplemonstre: 1, triple_monster: 1, triplemonster: 1,
        triple: 1, tm: 1, unlimited: 1, role_unlimited: 1, vip: 1, premium: 1
    };
    var MONSTRE_RANK_IDS = {
        monstre: 1, monster: 1, plan_monstre: 1, role_monstre: 1,
        double_monstre: 1, deux_monstres: 1, pass_monstre: 1
    };
    var PASS24H_RANK_IDS = {
        '24hpass': 1, '24h_pass': 1, pass_24h: 1, pass24h: 1, hpass24: 1,
        day_pass_24h: 1, pass_24hpass: 1
    };

    function _normalizeRank(rank) {
        var s = String(rank == null || rank === '' ? 'free' : rank).trim().toLowerCase();
        return s.replace(/\s+/g, '_');
    }

    function _launcherRankBucket(rank) {
        var r = _normalizeRank(rank);
        if (r === 'free') return 'free';
        if (TRIPLE_RANK_IDS[r]) return 'triple';
        if (PASS24H_RANK_IDS[r]) return 'pass24h';
        if (MONSTRE_RANK_IDS[r]) return 'monstre';
        if (r) return 'monstre';
        return 'free';
    }

    function _isTripleMonstreRank(rank) {
        return _launcherRankBucket(rank) === 'triple';
    }

    function _isMonstreRank(rank) {
        return _launcherRankBucket(rank) === 'monstre';
    }

    function _isPaidInstallRank(rank) {
        return _normalizeRank(rank) !== 'free';
    }

    /** Aligné avec web_bridge._LAUNCHER_FREE_CATALOG_IDS et le bot (free-claim). */
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
            app_id : '1943950',
            name   : 'Escape the Backrooms',
            url    : 'https://store.steampowered.com/app/1943950/Escape_the_Backrooms/',
        },
        {
            app_id : '1144200',
            name   : 'Ready or Not',
            url    : 'https://store.steampowered.com/app/1144200/Ready_or_Not/',
        },
        {
            app_id : '2968420',
            name   : 'PowerWash Simulator 2',
            url    : 'https://store.steampowered.com/app/2968420/PowerWash_Simulator_2/',
        },
        {
            app_id : '1321680',
            name   : 'Hello Neighbor 2',
            url    : 'https://store.steampowered.com/app/1321680/Hello_Neighbor_2/',
        },
        {
            app_id : '655500',
            name   : 'MX Bikes',
            url    : 'https://store.steampowered.com/app/655500/MX_Bikes/',
        },
        {
            app_id : '526870',
            name   : 'Satisfactory',
            url    : 'https://store.steampowered.com/app/526870/Satisfactory/',
        },
    ];

    /** Aperçu non gratuit : exemples accessibles avec abonnement (+ lien Steam). */
    var SUBSCRIPTION_SHOWCASE = [
        {
            app_id : '2483190',
            name   : 'Forza Horizon 6',
            url    : 'https://store.steampowered.com/app/2483190/Forza_Horizon_6/',
            header_url :
                'https://gaming-cdn.com/images/products/21624/orig/forza-horizon-6-premium-upgrade-acces-en-avant-premiere-pc-xbox-series-x-s-microsoft-store-cover.jpg?v=1778688480',
        },
        {
            app_id : '221100',
            name   : 'DayZ',
            url    : 'https://store.steampowered.com/app/221100/DayZ/',
        },
        {
            app_id : '1962700',
            name   : 'Subnautica 2',
            url    : 'https://store.steampowered.com/app/1962700/Subnautica_2/',
        },
        {
            app_id : '3240220',
            name   : 'Grand Theft Auto V Enhanced',
            url    : 'https://store.steampowered.com/app/3240220/Grand_Theft_Auto_V_Enhanced/',
        },
    ];

    function _steamHeader(appId) {
        return 'https://cdn.cloudflare.steamstatic.com/steam/apps/' + appId + '/header.jpg';
    }

    function _escHtml(s) {
        if (typeof Components !== 'undefined' && Components.escapeHtml) {
            return Components.escapeHtml(s);
        }
        if (!s) return '';
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(s));
        return div.innerHTML;
    }

    function _escAttr(s) {
        if (s == null || s === '') return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;');
    }

    function _hideFreeCatalogWaitModal() {
        if (typeof Components !== 'undefined' && Components.hideModal) {
            Components.hideModal('free-catalog-steam-wait-modal');
        }
    }

    function _showFreeCatalogWaitModal(gameName) {
        var waitGame = document.getElementById('free-catalog-wait-game');
        if (waitGame) waitGame.textContent = gameName || '—';
        var sub = document.getElementById('free-catalog-wait-sub');
        if (sub) {
            sub.innerHTML =
                'Merci de <strong>patienter quelques instants</strong> : le jeu va être téléchargé puis enregistré sur <strong>Steam</strong>.';
        }
        var spinLabel = document.querySelector('#free-catalog-steam-wait-modal .free-catalog-wait-spinner span');
        if (spinLabel) spinLabel.textContent = 'Préparation…';
        if (typeof Components !== 'undefined' && Components.showModal) {
            Components.showModal('free-catalog-steam-wait-modal');
        }
    }

    function _bindFreeCatalogInstallTaskListener() {
        if (_freeCatalogTaskListenerBound) return;
        _freeCatalogTaskListenerBound = true;
        Bridge.on('task_finished', function(jsonStr) {
            var d;
            try { d = JSON.parse(jsonStr); } catch (e) { return; }
            if (d.task !== 'download_fastest') return;
            if (!_freeCatalogInstallPending) return;
            if (String(d.app_id || '') !== String(_freeCatalogInstallPending.appId)) return;
            var gameName = _freeCatalogInstallPending.gameName;
            _freeCatalogInstallPending = null;
            _hideFreeCatalogWaitModal();
            var wrap = document.getElementById('free-catalog-install-result-modal');
            var titleEl = document.getElementById('free-catalog-result-title');
            var bodyEl = document.getElementById('free-catalog-result-body');
            if (wrap) {
                wrap.classList.remove('free-catalog-result--ok', 'free-catalog-result--fail');
                wrap.classList.add(d.success ? 'free-catalog-result--ok' : 'free-catalog-result--fail');
            }
            if (d.success) {
                if (titleEl) titleEl.textContent = 'C’est dans Steam';
                if (bodyEl) {
                    bodyEl.innerHTML =
                        '<p><strong>' + _escHtml(gameName) + '</strong> a bien été ajouté à ta bibliothèque <strong>Steam</strong>.</p>' +
                        '<p class="text-muted free-catalog-result-hint">Tu peux ouvrir le client Steam pour vérifier.</p>';
                }
                var okApp = String(d.app_id || '');
                if (okApp) {
                    Bridge.onReady(function(py) {
                        if (py.record_free_claim) {
                            py.record_free_claim(okApp, function(jsonStr) {
                                var r = {};
                                try { r = JSON.parse(jsonStr); } catch (e) { r = {}; }
                                if (r.ok) {
                                    _freeClaimed = okApp;
                                    _renderFreeCatalog();
                                } else {
                                    var detail = (r.error && String(r.error).trim()) || '';
                                    _toast('error',
                                        detail
                                            ? ('Enregistrement du choix sur le compte : ' + detail)
                                            : 'Steam semble à jour mais l’enregistrement du choix sur le compte a échoué — contacte le support.'
                                    );
                                }
                                Bridge.call('sync_launcher_profile');
                            });
                        } else {
                            _freeClaimed = okApp;
                            _renderFreeCatalog();
                            Bridge.call('sync_launcher_profile');
                        }
                    });
                }
            } else {
                if (titleEl) titleEl.textContent = 'Problème rencontré';
                var err = d.message ? String(d.message) : 'Erreur inconnue';
                if (bodyEl) {
                    bodyEl.innerHTML =
                        '<p>Le jeu <strong>n’a pas pu être correctement mis sur Steam</strong> (téléchargement ou étape Steam).</p>' +
                        '<p class="text-muted free-catalog-result-err">' + _escHtml(err) + '</p>' +
                        '<p class="text-muted free-catalog-result-hint">Ton <strong>choix catalogue n’est pas définitif</strong> tant que l’installation ne réussit pas : tu peux en sélectionner un autre après fermeture de cette fenêtre.</p>';
                }
                var failAppId = String(d.app_id || '');
                if (failAppId) {
                    Bridge.onReady(function(py) {
                        if (py.cancel_free_catalog_install) {
                            py.cancel_free_catalog_install(failAppId, function(jsonStr) {
                                var r = {};
                                try { r = JSON.parse(jsonStr); } catch (e2) { r = {}; }
                                if (r.ok) {
                                    _freeClaimed = null;
                                    _renderFreeCatalog();
                                }
                                Bridge.call('sync_launcher_profile');
                                if (r.ok && (r.cleared === 'pending' || r.reverted)) {
                                    _toast('info', 'Tu peux sélectionner un autre jeu du catalogue.');
                                }
                            });
                        } else if (py.revert_free_claim) {
                            py.revert_free_claim(failAppId, function(jsonStr) {
                                var r = {};
                                try { r = JSON.parse(jsonStr); } catch (e2) { r = {}; }
                                if (r.ok && r.reverted) {
                                    _freeClaimed = null;
                                    _renderFreeCatalog();
                                }
                                Bridge.call('sync_launcher_profile');
                            });
                        } else {
                            Bridge.call('sync_launcher_profile');
                        }
                    });
                } else {
                    Bridge.call('sync_launcher_profile');
                }
            }
            if (typeof Components !== 'undefined' && Components.showModal) {
                Components.showModal('free-catalog-install-result-modal');
            }
        });
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
                _monstreSlotsUsed = typeof d.monstre_slots_used === 'number' ? d.monstre_slots_used : null;
                _monstreSlotsMax = typeof d.monstre_slots_max === 'number' ? d.monstre_slots_max : null;
                if (loadEl) loadEl.classList.add('hidden');
                _renderStore();
            });
        });
    }

    var _profileSyncBound = false;

    function _bindLauncherProfileSync() {
        if (_profileSyncBound) return;
        _profileSyncBound = true;
        Bridge.on('launcher_profile_synced', function (jsonStr) {
            var d;
            try { d = JSON.parse(jsonStr); } catch (e) { return; }
            if (!d.ok) return;
            _userRank = d.rank || 'free';
            _freeClaimed = d.free_claimed != null && d.free_claimed !== '' ? d.free_claimed : null;
            if (typeof d.monstre_slots_used === 'number') {
                _monstreSlotsUsed = d.monstre_slots_used;
                _monstreSlotsMax = typeof d.monstre_slots_max === 'number' ? d.monstre_slots_max : null;
            } else {
                _monstreSlotsUsed = null;
                _monstreSlotsMax = null;
            }
            _renderStore();
        });
    }

    function _renderStore() {
        var freeSection = document.getElementById('store-free-section');
        var ttcSection  = document.getElementById('store-ttc-section');
        var subtitle    = document.getElementById('store-subtitle');

        if (ttcSection) ttcSection.classList.remove('hidden');

        var bucket = _launcherRankBucket(_userRank);

        if (bucket === 'free') {
            if (freeSection) freeSection.classList.remove('hidden');
            if (subtitle) {
                subtitle.textContent =
                    'Plan FREE — choisis un jeu du catalogue ou teste la recherche (installation : abonnes)';
            }
            _renderFreeCatalog();
            _bindFreePlanGuide();
            _bindSubscriptionShowcaseCta();
        } else {
            if (freeSection) freeSection.classList.add('hidden');
            if (subtitle) {
                if (bucket === 'triple') {
                    var triQ = '';
                    if (_monstreSlotsUsed != null) {
                        triQ = ' Quota jeux : ' + _monstreSlotsUsed + '/illimité.';
                    }
                    subtitle.textContent =
                        'Colle un lien Steam — TRIPLE MONSTRE : jeux illimites + sauvegardes cloud.' + triQ;
                } else if (bucket === 'pass24h') {
                    var cap24 = 8;
                    var q24 = '';
                    if (_monstreSlotsUsed != null && _monstreSlotsMax != null) {
                        q24 = ' Quota : ' + _monstreSlotsUsed + '/' + _monstreSlotsMax
                            + ' jeux distincts sur ce PC (reinstallation d\'un jeu deja en liste : OK).';
                    } else {
                        q24 = ' Jusqu\'a ' + cap24 + ' jeux distincts sur ce PC (reinstallation d\'un jeu deja en liste : OK).';
                    }
                    subtitle.textContent =
                        'Colle un lien Steam — 24H PASS : installation comme les autres paliers payants.' + q24
                        + ' Pas d\'Online FIX, pas de ROCKSTAR BYPASS ni sauvegardes cloud (reserves au Triple Monstre).';
                } else {
                    var capM = 10;
                    var quotaLine = '';
                    if (_monstreSlotsUsed != null && _monstreSlotsMax != null) {
                        quotaLine = ' Quota : ' + _monstreSlotsUsed + '/' + _monstreSlotsMax
                            + ' jeux distincts sur ce PC (reinstallation d\'un jeu deja en liste : OK).';
                    } else {
                        quotaLine = ' Jusqu\'a ' + capM + ' jeux distincts sur ce PC (reinstallation d\'un jeu deja en liste : OK).';
                    }
                    subtitle.textContent =
                        'Colle un lien Steam — plan MONSTRE : recherche et installation comme Triple.' + quotaLine
                        + ' Pas d\'Online FIX ni ROCKSTAR BYPASS (reserves au Triple Monstre). Sauvegardes cloud : reserve au Triple Monstre.';
                }
            }
        }
        _initTtcListeners();
        _bindFreeUpsellModal();
    }

    var _freePlanGuideBound = false;
    var _subscriptionShowcaseCtaBound = false;
    var _discordAvisUrl = 'https://discord.gg/c2pRJKjvgE';

    function _bindSubscriptionShowcaseCta() {
        if (_subscriptionShowcaseCtaBound) return;
        var cta = document.getElementById('subscription-showcase-cta-tarifs');
        if (!cta) return;
        _subscriptionShowcaseCtaBound = true;
        cta.addEventListener('click', function (e) {
            e.preventDefault();
            Bridge.call('open_url', 'https://slimedeals.fr/#tarifs');
        });
    }

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

        _renderSubscriptionShowcase();
    }

    function _renderSubscriptionShowcase() {
        var grid = document.getElementById('subscription-showcase-grid');
        if (!grid) return;
        grid.innerHTML = '';
        SUBSCRIPTION_SHOWCASE.forEach(function (game) {
            var card = document.createElement('article');
            card.className = 'subscription-showcase-card';
            var nm = _escHtml(game.name);
            var imgSrc = _escAttr(game.header_url || _steamHeader(game.app_id));
            card.innerHTML =
                '<div class="subscription-showcase-card-badge" aria-hidden="true">Abonnement</div>' +
                '<img src="' + imgSrc + '" alt="' + nm + '" loading="lazy" referrerpolicy="no-referrer">' +
                '<div class="subscription-showcase-card-body">' +
                    '<div class="subscription-showcase-card-name">' + nm + '</div>' +
                    '<p class="subscription-showcase-card-hint">Exemple — dispo via recherche Steam avec un plan payant.</p>' +
                    '<button type="button" class="btn subscription-showcase-card-btn">Fiche Steam</button>' +
                '</div>';
            var btn = card.querySelector('.subscription-showcase-card-btn');
            if (btn) {
                btn.addEventListener('click', function (e) {
                    e.stopPropagation();
                    Bridge.call('open_url', game.url);
                });
            }
            card.addEventListener('click', function () {
                Bridge.call('open_url', game.url);
            });
            grid.appendChild(card);
        });
    }

    function _claimFreeGame(appId, gameName) {
        if (!confirm('Confirmer la sélection de "' + gameName + '" ?\n'
            + 'Si le téléchargement ou l’installation échoue, tu pourras en choisir un autre.\n'
            + 'Une fois l’installation réussie, ce choix devient définitif.')) return;

        _bindFreeCatalogBeginResult();
        _bindFreeCatalogInstallTaskListener();

        var allBtns = document.querySelectorAll('.free-catalog-card-btn');
        allBtns.forEach(function(b) { b.disabled = true; b.textContent = 'Traitement…'; });

        _showFreeCatalogWaitModal(gameName);

        Bridge.onReady(function (py) {
            if (!py.begin_free_catalog_install) {
                _freeCatalogInstallPending = null;
                _hideFreeCatalogWaitModal();
                allBtns.forEach(function (b) { b.disabled = false; b.textContent = '⬇ Choisir ce jeu'; });
                _toast('error', 'Mise à jour du launcher requise pour le catalogue gratuit.');
                return;
            }
            _freeCatalogBeginHandler = function (jsonStr) {
                var result;
                try { result = JSON.parse(jsonStr); } catch (e) { result = { ok: false, error: 'Erreur interne' }; }

                if (result.ok) {
                    if (result.mode === 'committed') {
                        _freeClaimed = String(appId);
                    }
                    var sub = document.getElementById('free-catalog-wait-sub');
                    if (sub) {
                        sub.innerHTML =
                            'Téléchargement et enregistrement sur <strong>Steam</strong> en cours… Merci de <strong>patienter</strong> encore un instant.';
                    }
                    var spinLabel = document.querySelector('#free-catalog-steam-wait-modal .free-catalog-wait-spinner span');
                    if (spinLabel) spinLabel.textContent = 'En cours…';
                    _freeCatalogInstallPending = { appId: String(appId), gameName: gameName };
                    setTimeout(function () {
                        Bridge.call('download_game_with_source', String(appId), 'twentytwocloud', '0', '');
                    }, 0);
                    _renderFreeCatalog();
                } else if (result.error === 'pending_other_game') {
                    _freeCatalogInstallPending = null;
                    _hideFreeCatalogWaitModal();
                    allBtns.forEach(function (b) { b.disabled = false; b.textContent = '⬇ Choisir ce jeu'; });
                    var pendId = String(result.app_id || '');
                    if (pendId && confirm(
                        'Une préparation catalogue est enregistrée pour l\'App ' + pendId + '.\n\n' +
                        'Si cette installation ne tourne plus (fenêtre fermée, plantage, etc.), clique OK pour effacer cette étape et pouvoir choisir un autre jeu.'
                    )) {
                        Bridge.onReady(function (py) {
                            if (!py.cancel_free_catalog_install) {
                                _toast('error', 'Impossible d\'annuler : mets à jour le launcher.');
                                return;
                            }
                            py.cancel_free_catalog_install(pendId, function (jsonStr) {
                                var cr = {};
                                try { cr = JSON.parse(jsonStr || '{}'); } catch (e1) { cr = {}; }
                                if (cr.ok) {
                                    _toast('info', 'Préparation annulée — tu peux choisir un jeu à nouveau.');
                                    Bridge.call('sync_launcher_profile');
                                } else {
                                    _toast('error', cr.error || 'Impossible d\'annuler.');
                                }
                                _renderFreeCatalog();
                            });
                        });
                    } else if (pendId) {
                        _toast('warning',
                            'Installation encore réservée pour l\'App ' + pendId + '. Réessaie et accepte l\'annulation si tu veux changer de jeu.'
                        );
                    } else {
                        _toast('error', 'Conflit de préparation catalogue. Réessaie ou reconnecte-toi.');
                    }
                } else if (result.error === 'already_claimed') {
                    _freeCatalogInstallPending = null;
                    _hideFreeCatalogWaitModal();
                    allBtns.forEach(function (b) { b.disabled = false; b.textContent = '⬇ Choisir ce jeu'; });
                    _freeClaimed = result.app_id || appId;
                    _renderFreeCatalog();
                    if (String(result.app_id || '') !== String(appId)) {
                        _toast('warning',
                            'Tu as déjà utilisé ton jeu catalogue gratuit (App ' + result.app_id + ').'
                        );
                    }
                    Bridge.call('sync_launcher_profile');
                } else {
                    _freeCatalogInstallPending = null;
                    _hideFreeCatalogWaitModal();
                    allBtns.forEach(function (b) { b.disabled = false; b.textContent = '⬇ Choisir ce jeu'; });
                    _toast('error', 'Erreur : ' + (result.error || 'Impossible de valider.'));
                }
            };
            Bridge.call('begin_free_catalog_install', String(appId));
        });
    }

    // ── Recherche Steam (onglet Télécharger, plan premium) ───────────────────

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

        var dlcEl = document.getElementById('ttc-dlc-badge');
        if (dlcEl) {
            if (data.dlc_count != null && data.dlc_count !== '') {
                var n = parseInt(data.dlc_count, 10);
                if (!isNaN(n)) {
                    dlcEl.classList.remove('hidden');
                    if (n === 0) {
                        dlcEl.textContent = 'DLC : aucun listé';
                    } else if (n === 1) {
                        dlcEl.textContent = '1 DLC listé';
                    } else {
                        dlcEl.textContent = n + ' DLC listés';
                    }
                } else {
                    dlcEl.classList.add('hidden');
                }
            } else {
                dlcEl.classList.add('hidden');
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

    var _ttcListenersAttached = false;
    var _freeUpsellModalBound = false;

    function _showFreePlanUpsellModal() {
        if (typeof Components !== 'undefined' && Components.showModal) {
            Components.showModal('free-plan-upsell-modal');
        } else {
            alert('Un abonnement SlimeDeals est requis pour télécharger depuis cette recherche. Voir slimedeals.fr/#tarifs');
        }
    }

    function _bindFreeUpsellModal() {
        if (_freeUpsellModalBound) return;
        var modal = document.getElementById('free-plan-upsell-modal');
        var btnT  = document.getElementById('free-upsell-open-tarifs');
        var btnD  = document.getElementById('free-upsell-open-discord');
        if (!modal || !btnT || !btnD) return;
        _freeUpsellModalBound = true;
        btnT.addEventListener('click', function () {
            Bridge.call('open_url', 'https://slimedeals.fr/#tarifs');
        });
        btnD.addEventListener('click', function () {
            Bridge.onReady(function (py) {
                if (typeof py.discord_free_subscribe_url !== 'function') {
                    Bridge.call('open_url', 'https://discord.gg/c2pRJKjvgE');
                    return;
                }
                py.discord_free_subscribe_url(function (url) {
                    Bridge.call('open_url', url && url.indexOf('http') === 0 ? url : 'https://discord.gg/c2pRJKjvgE');
                });
            });
        });
    }

    function _initTtcListeners() {
        if (_ttcListenersAttached) return;
        _ttcListenersAttached = true;

        var searchBtn = document.getElementById('ttc-search-btn');
        var urlInput  = document.getElementById('ttc-url-input');
        var dlBtn     = document.getElementById('ttc-download-btn');
        var depotBtn  = document.getElementById('ttc-depot-btn');

        if (searchBtn) searchBtn.addEventListener('click', _doSearch);
        if (urlInput)  urlInput.addEventListener('keydown', function(e) { if (e.key === 'Enter') _doSearch(); });

        if (dlBtn) {
            dlBtn.addEventListener('click', function() {
                if (!_currentAppId) return;
                if (!_isPaidInstallRank(_userRank)) {
                    _showFreePlanUpsellModal();
                    return;
                }
                _resetProgress();
                _showProgress('Démarrage du téléchargement…', 5);
                Bridge.call('download_game_with_source', _currentAppId, 'twentytwocloud', '0', '');
            });
        }
        if (depotBtn) {
            depotBtn.addEventListener('click', function() {
                if (!_isPaidInstallRank(_userRank)) {
                    _showFreePlanUpsellModal();
                    return;
                }
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
        _bindFreeCatalogInstallTaskListener();
        _bindLauncherProfileSync();
    }

    function onPageEnter() {
        init();
        _bindFreeCatalogBeginResult();
        Bridge.call('sync_launcher_profile');
        _loadRankAndDisplay();
        // Focus input only if premium section ends up visible
        setTimeout(function() {
            var input = document.getElementById('ttc-url-input');
            var ttcSec = document.getElementById('store-ttc-section');
            if (input && ttcSec && !ttcSec.classList.contains('hidden')) input.focus();
        }, 200);
    }

    function onApiKeyAvailable(_key) { /* conservé pour compatibilité */ }

    return { init: init, onPageEnter: onPageEnter, onApiKeyAvailable: onApiKeyAvailable };
})();
