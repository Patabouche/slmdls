/**
 * SlimeDeals — QWebChannel Python↔JS Bridge
 * Connects to the Python WebBridge QObject via QWebChannel.
 * All slot calls are async in Qt6 — use callbacks or signals.
 */

window.Bridge = (function() {
    'use strict';

    let _py = null;
    let _ready = false;
    const _readyCallbacks = [];
    const _signalListeners = {};

    function init() {
        if (typeof QWebChannel === 'undefined') {
            console.error('[Bridge] QWebChannel not available — running outside QtWebEngine?');
            _simulateBridge();
            return;
        }
        new QWebChannel(qt.webChannelTransport, function(channel) {
            _py = channel.objects.bridge;
            if (!_py) {
                console.error('[Bridge] No "bridge" object registered in QWebChannel');
                return;
            }
            _ready = true;
            _connectSignals();
            _applyAppVersionToUI();
            _readyCallbacks.forEach(function(cb) { cb(_py); });
            _readyCallbacks.length = 0;
            console.log('[Bridge] Connected to Python backend');
        });
    }

    function _applyAppVersionToUI() {
        function apply(ver) {
            if (!ver) return;
            ver = String(ver).trim();
            if (!ver) return;
            var el = document.getElementById('sidebar-app-version');
            if (el) el.textContent = /^v/i.test(ver) ? ver : ('v' + ver);
            var about = document.getElementById('about-app-version');
            if (about) about.textContent = ' — version ' + ver;
            try {
                document.title = 'SlimeDeals ' + ver;
            } catch (e2) {}
        }
        var pinned = typeof window.__SLIMEDEALS_APP_VERSION__ === 'string'
            ? window.__SLIMEDEALS_APP_VERSION__.trim()
            : '';
        if (pinned) {
            apply(pinned);
            return;
        }
        if (!_py || typeof _py.get_app_version !== 'function') return;
        try {
            _py.get_app_version(function(ver) {
                apply(ver);
            });
        } catch (e) {
            console.warn('[Bridge] get_app_version:', e);
        }
    }

    function _connectSignals() {
        var signalNames = [
            'search_results',
            'depot_history_results',
            'download_progress',
            'task_finished',
            'log_message',
            'ttc_game_info',
            'auth_done',
            'launcher_profile_synced',
            'free_catalog_begin_result'
        ];
        signalNames.forEach(function(name) {
            if (_py[name] && typeof _py[name].connect === 'function') {
                _py[name].connect(function(data) {
                    _emit(name, data);
                });
            }
        });
    }

    function onReady(callback) {
        if (_ready && _py) {
            callback(_py);
        } else {
            _readyCallbacks.push(callback);
        }
    }

    function isReady() {
        return _ready && _py !== null;
    }

    // Signal listener system
    function on(signalName, callback) {
        if (!_signalListeners[signalName]) {
            _signalListeners[signalName] = [];
        }
        _signalListeners[signalName].push(callback);
    }

    function off(signalName, callback) {
        if (!_signalListeners[signalName]) return;
        var idx = _signalListeners[signalName].indexOf(callback);
        if (idx !== -1) _signalListeners[signalName].splice(idx, 1);
    }

    function _emit(signalName, data) {
        var listeners = _signalListeners[signalName];
        if (!listeners) return;
        listeners.forEach(function(cb) {
            try { cb(data); } catch(e) { console.error('[Bridge] Signal handler error:', signalName, e); }
        });
    }

    // Call a bridge method (async slot — no return value, results via signals)
    function call(method /*, ...args */) {
        if (!_py) {
            console.warn('[Bridge] Not connected, queuing call:', method);
            onReady(function() { call.apply(null, arguments); });
            return;
        }
        var args = Array.prototype.slice.call(arguments, 1);
        if (typeof _py[method] === 'function') {
            _py[method].apply(_py, args);
        } else {
            console.error('[Bridge] Unknown method:', method);
        }
    }

    // Call a sync bridge method (with callback — because Qt6 QWebChannel is always async)
    function callSync(method, callback) {
        if (!_py) {
            onReady(function() { callSync(method, callback); });
            return;
        }
        if (typeof _py[method] === 'function') {
            _py[method](callback);
        } else {
            console.error('[Bridge] Unknown method:', method);
        }
    }

    // Call with args + trailing callback (for sync slots with parameters)
    function callWithCallback(method /*, arg1, arg2, ..., callback */) {
        if (!_py) {
            onReady(function() { callWithCallback.apply(null, arguments); });
            return;
        }
        var args = Array.prototype.slice.call(arguments, 1);
        if (typeof _py[method] === 'function') {
            _py[method].apply(_py, args);
        } else {
            console.error('[Bridge] Unknown method:', method);
        }
    }

    // Simulation mode for development outside QtWebEngine
    function _simulateBridge() {
        console.warn('[Bridge] Running in SIMULATION mode — no Python backend');
        _py = {
            search_games: function() {},
            fetch_depot_history: function() {},
            download_game_fastest: function() {},
            download_game_version: function() {},
            run_game_action: function() {},
            get_platform: function(cb) { if (cb) cb('win32'); },
            connect_store: function() {},
            get_stored_api_key: function(cb) { if (cb) cb(''); },
            list_profiles: function(cb) { if (cb) cb('[]'); },
            switch_profile: function() {},
            save_profile: function() {},
            delete_profile: function() {},
            rename_profile: function() {},
            set_setting: function() {},
            get_setting: function(key, cb) { if (cb) cb(''); },
            get_steam_libraries: function(cb) { if (cb) cb('[]'); },
            get_fixed_games_catalog: function(cb) {
                if (cb) {
                    cb(JSON.stringify([
                        {
                            id: 'pragmata',
                            name: 'Pragmata',
                            app_id: '3124140',
                            size_label: '34,9 Go',
                            tags: ['Jeu complet', 'Correctifs intégrés']
                        },
                        {
                            id: 'subnautica2',
                            name: 'Subnautica 2',
                            app_id: '1962700',
                            size_label: '13,1 Go',
                            tags: ['Jeu complet', 'Correctifs intégrés']
                        }
                    ]));
                }
            },
            check_fixed_game_install: function(gameId, path, cb) {
                if (cb) {
                    cb(JSON.stringify({
                        ok: true,
                        install_path: path + '\\steamapps\\common',
                        free_install_human: '100 Go',
                        free_temp_human: '50 Go',
                        required_human: '38 Go',
                        message: 'Simulation'
                    }));
                }
            },
            install_fixed_game: function() {},
            get_fixed_games_installed: function(cb) {
                if (cb) cb(JSON.stringify({ installed_ids: [] }));
            },
            set_active_library: function() {},
            open_file_dialog: function(cb) { if (cb) cb(''); },
            open_log_window: function() {},
            restart_steam: function() {},
            repair_steam_ui: function() {},
            refresh_library: function(cb) { if (cb) cb('[]'); },
            get_installed_games: function(cb) { if (cb) cb('[]'); },
            scan_cloud_games: function() {},
            backup_cloud_save: function() {},
            restore_cloud_save: function() {},
            generate_gbe_token: function() {},
            extract_vdf_keys: function(cb) { if (cb) cb('[]'); },
            open_workshop: function() {},
            fix_game: function() {},
            revert_game: function() {},
            get_fix_game_list: function(cb) { if (cb) cb('[]'); },
            get_applist_games: function(cb) { if (cb) cb('[]'); },
            browse_game_folder: function(cb) { if (cb) cb(''); },
            launch_game_as_admin: function(folder, cb) {
                if (cb) {
                    cb(JSON.stringify({
                        ok: false,
                        message: 'Mode simulation : lance depuis le launcher Windows pour un vrai test.'
                    }));
                }
            },
            open_url: function() {},
            launch_slimedeals_bprg: function() {},
            gdrive_status: function(cb) {
                if (cb) cb(JSON.stringify({
                    available: true,
                    connected: false,
                    email: '',
                    deps_installed: true,
                    credentials_configured: true
                }));
            },
            cloud_saves_self_test: function(steamPath, steam32, cb) {
                if (cb) {
                    cb(JSON.stringify({
                        ok: !!(steamPath && steam32),
                        steam_path_set: !!steamPath,
                        steam_install_ok: !!steamPath,
                        steam_exe_found: !!steamPath,
                        userdata_id_set: !!steam32,
                        account_id: steam32 || '',
                        userdata_folder_ok: false,
                        gdrive_oauth_available: true,
                        gdrive_deps_installed: true,
                        gdrive_credentials_configured: true,
                        gdrive_connected: false,
                        gdrive_backup_root_ok: false,
                        messages: [
                            'Mode simulation : pas de vérification réelle. Lance l’app avec le launcher pour tester.'
                        ]
                    }));
                }
            },
            gdrive_disconnect: function() {},
            get_user_rank: function(cb) { if (cb) cb(JSON.stringify({rank:'free',free_claimed:null,username:'',rank_expires_at:null,monstre_slots_used:null,monstre_slots_max:null,cloud_saves_enabled:false})); },
            sync_launcher_profile: function() {},
            record_free_claim: function(app_id, cb) { if (cb) cb(JSON.stringify({ok:false,error:'simulation'})); },
            revert_free_claim: function(app_id, cb) { if (cb) cb(JSON.stringify({ok:true,reverted:true})); },
            begin_free_catalog_install: function(app_id, cb) { if (cb) cb(JSON.stringify({ok:true,mode:'pending'})); },
            cancel_free_catalog_install: function(app_id, cb) { if (cb) cb(JSON.stringify({ok:true,cleared:'pending'})); },
            notify_gen_activity: function() {},
            get_app_version: function(cb) { if (cb) cb('dev'); },
            discord_avis_url: function(cb) { if (cb) cb('https://discord.gg/c2pRJKjvgE'); },
            discord_free_subscribe_url: function(cb) { if (cb) cb('https://discord.gg/c2pRJKjvgE'); },
        };
        _ready = true;
        _applyAppVersionToUI();
        _readyCallbacks.forEach(function(cb) { cb(_py); });
        _readyCallbacks.length = 0;
    }

    return {
        init: init,
        onReady: onReady,
        isReady: isReady,
        on: on,
        off: off,
        call: call,
        callSync: callSync,
        callWithCallback: callWithCallback,
        getPy: function() { return _py; }
    };
})();

// Initialize the bridge immediately
Bridge.init();
