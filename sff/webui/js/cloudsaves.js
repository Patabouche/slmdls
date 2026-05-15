/**

 * SteaMidra — Sauvegardes cloud (Google Drive uniquement sur cette page).

 */



window.CloudSaves = (function() {

    'use strict';



    var _initialized = false;

    var _allSavesEntries = [];

    var _restoreLocationsData = {};



    function _gdriveProviderConfig() {

        return JSON.stringify({ provider: 'gdrive_api' });

    }



    function _persistSteamPathFromField(showToast) {

        var input = document.getElementById('cloud-steam-path');

        var v = input ? input.value.trim() : '';

        if (!v) return;

        Bridge.call('set_setting', 'steam_path', v);

        if (showToast) Components.showToast('success', 'Chemin Steam enregistré');

    }



    function _persistSteam32FromField(showToast) {

        var input = document.getElementById('cloud-steam32');

        var v = input ? input.value.trim() : '';

        if (!v) {

            if (showToast) Components.showToast('warning', 'Entre d’abord le numéro du dossier userdata');

            return;

        }

        Bridge.call('set_setting', 'steam32_id', v);

        if (showToast) Components.showToast('success', 'ID userdata enregistré');

    }



    function init() {

        if (_initialized) return;

        _initialized = true;



        var steamBrowse = document.getElementById('cloud-steam-browse');

        var saveIdBtn = document.getElementById('cloud-save-id');

        var scanBtn = document.getElementById('cloud-scan');

        var backupBtn = document.getElementById('cloud-backup-btn');

        var importBrowse = document.getElementById('cloud-import-browse');

        var importBtn = document.getElementById('cloud-import-btn');



        var autoInterval = document.getElementById('cloud-auto-interval');

        var autoEnable = document.getElementById('cloud-auto-enable-btn');

        var autoDisable = document.getElementById('cloud-auto-disable-btn');



        if (autoEnable) {

            autoEnable.addEventListener('click', function() {

                var min = autoInterval ? parseInt(autoInterval.value, 10) : 0;

                if (isNaN(min) || min < 1) {

                    Components.showToast('warning', 'Mets au moins 1 minute entre chaque envoi automatique');

                    return;

                }

                var steamPathEl = document.getElementById('cloud-steam-path');

                var steam32El = document.getElementById('cloud-steam32');

                var sp = steamPathEl ? steamPathEl.value.trim() : '';

                var s32 = steam32El ? steam32El.value.trim() : '';

                if (!sp || !s32) {

                    Components.showToast('warning', 'Renseigne d’abord le dossier Steam et l’ID userdata (étape 3) — l’auto a besoin des deux pour trouver les fichiers.');

                    return;

                }

                Bridge.call('set_setting', 'steam_path', sp);

                Bridge.call('set_setting', 'steam32_id', s32);

                Bridge.call('set_setting', 'save_watcher_interval', String(min));

                Bridge.call('set_setting', 'last_backup_provider_config', _gdriveProviderConfig());

                Components.showToast('success', 'Sauvegarde auto sur Google Drive activée (' + min + ' min)');

            });

        }

        if (autoDisable) {

            autoDisable.addEventListener('click', function() {

                Bridge.call('set_setting', 'save_watcher_interval', '0');

                if (autoInterval) autoInterval.value = '0';

                Components.showToast('info', 'Sauvegarde automatique désactivée');

            });

        }



        if (autoInterval) {

            autoInterval.addEventListener('change', function() {

                var v = String(this.value == null ? '' : this.value).trim();

                Bridge.call('set_setting', 'save_watcher_interval', v === '' ? '0' : v);

            });

        }



        // Google Drive connect / disconnect

        var gdriveConnectBtn = document.getElementById('gdrive-connect-btn');

        var gdriveDisconnectBtn = document.getElementById('gdrive-disconnect-btn');

        if (gdriveConnectBtn) {

            gdriveConnectBtn.addEventListener('click', function() {

                gdriveConnectBtn.disabled = true;

                gdriveConnectBtn.textContent = 'Connexion…';

                Bridge.call('gdrive_authorize');

            });

        }

        if (gdriveDisconnectBtn) {

            gdriveDisconnectBtn.addEventListener('click', function() {

                Bridge.call('gdrive_disconnect');

            });

        }



        if (steamBrowse) {

            steamBrowse.addEventListener('click', function() {

                Bridge.callSync('open_file_dialog', function(path) {

                    if (path) {

                        var input = document.getElementById('cloud-steam-path');

                        if (input) input.value = path;

                        _persistSteamPathFromField(true);

                    }

                });

            });

        }



        var steamPathInput = document.getElementById('cloud-steam-path');

        if (steamPathInput) {

            steamPathInput.addEventListener('blur', function() {

                _persistSteamPathFromField(false);

            });

            steamPathInput.addEventListener('change', function() {

                _persistSteamPathFromField(false);

            });

        }



        var steam32Input = document.getElementById('cloud-steam32');

        if (steam32Input) {

            steam32Input.addEventListener('blur', function() {

                _persistSteam32FromField(false);

            });

            steam32Input.addEventListener('change', function() {

                _persistSteam32FromField(false);

            });

        }



        if (saveIdBtn) {

            saveIdBtn.addEventListener('click', function() {

                _persistSteam32FromField(true);

            });

        }



        var selfTestBtn = document.getElementById('cloud-self-test-btn');

        if (selfTestBtn) {

            selfTestBtn.addEventListener('click', _runCloudSelfTest);

        }



        if (scanBtn) {

            scanBtn.addEventListener('click', _scanGames);

        }



        if (backupBtn) {

            backupBtn.addEventListener('click', function() {

                _persistSteamPathFromField(false);

                _persistSteam32FromField(false);

                var steamPath = document.getElementById('cloud-steam-path');

                var steam32 = document.getElementById('cloud-steam32');

                var sp = steamPath ? steamPath.value.trim() : '';

                var s32 = steam32 ? steam32.value.trim() : '';



                var tbody = document.getElementById('cloud-games-tbody');

                var selectedRow = tbody ? tbody.querySelector('tr.selected') : null;

                if (!selectedRow) {

                    Components.showToast('warning', 'Scanne les jeux puis clique une ligne du tableau pour choisir le jeu');

                    return;

                }

                var appId = selectedRow.dataset.appid;

                var gameName = selectedRow.cells[1] ? selectedRow.cells[1].textContent : '';



                if (!sp || !s32) {

                    Components.showToast('warning', 'Renseigne le dossier Steam et l’ID userdata');

                    return;

                }



                var entry = {

                    location: 'Steam Userdata',

                    folder_name: String(appId),

                    app_id: parseInt(appId, 10),

                    game_name: gameName || ('App ' + appId),

                    label: appId + (gameName ? ' - ' + gameName : ''),

                    source_path: sp + '/userdata/' + s32 + '/' + appId,

                    file_count: 0

                };

                Bridge.call('backup_all_save_locations', JSON.stringify({

                    entries: [entry],

                    provider: 'gdrive_api'

                }));

                Components.showToast('info', 'Envoi vers Google Drive…');

            });

        }



        if (importBrowse) {

            importBrowse.addEventListener('click', function() {

                Bridge.callSync('open_file_dialog', function(path) {

                    if (path) {

                        var input = document.getElementById('cloud-import-path');

                        if (input) input.value = path;

                    }

                });

            });

        }



        if (importBtn) {

            importBtn.addEventListener('click', function() {

                _persistSteamPathFromField(false);

                _persistSteam32FromField(false);

                var tbody = document.getElementById('cloud-games-tbody');

                var selectedRow = tbody ? tbody.querySelector('tr.selected') : null;

                if (!selectedRow) {

                    Components.showToast('warning', 'Choisis d’abord un jeu dans le tableau (après scan)');

                    return;

                }

                var appId = selectedRow.dataset.appid;

                var input = document.getElementById('cloud-import-path');

                var importPath = input ? input.value.trim() : '';

                if (!importPath) {

                    Components.showToast('warning', 'Choisis le dossier de la sauvegarde à restaurer');

                    return;

                }

                var steamPath = document.getElementById('cloud-steam-path');

                var steam32 = document.getElementById('cloud-steam32');

                var sp = steamPath ? steamPath.value.trim() : '';

                var s32 = steam32 ? steam32.value.trim() : '';

                if (!sp || !s32) {

                    Components.showToast('warning', 'Renseigne le dossier Steam et l’ID userdata');

                    return;

                }

                if (confirm('Restaurer cette sauvegarde dans Steam ? Une copie de sécurité sera créée si possible.')) {

                    Bridge.call('restore_cloud_save', JSON.stringify({

                        backup_path: importPath, app_id: appId,

                        steam_path: sp, steam32_id: s32

                    }));

                    Components.showToast('info', 'Restauration…');

                }

            });

        }



        var allSavesScanBtn = document.getElementById('all-saves-scan-btn');

        if (allSavesScanBtn) {

            allSavesScanBtn.addEventListener('click', _scanAllSaveLocations);

        }



        var allSavesBackupBtn = document.getElementById('all-saves-backup-btn');

        if (allSavesBackupBtn) {

            allSavesBackupBtn.addEventListener('click', _backupAllSaves);

        }



        var selectAll = document.getElementById('all-saves-select-all');

        if (selectAll) {

            selectAll.addEventListener('change', function() {

                document.querySelectorAll('.all-saves-row-check').forEach(function(cb) {

                    cb.checked = selectAll.checked;

                });

            });

        }



        var restoreBackupBrowse = document.getElementById('restore-backup-browse');

        if (restoreBackupBrowse) {

            restoreBackupBrowse.addEventListener('click', function() {

                Bridge.callSync('open_file_dialog', function(path) {

                    if (path) {

                        var inp = document.getElementById('restore-backup-root');

                        if (inp) inp.value = path;

                    }

                });

            });

        }



        var restoreScanBtn = document.getElementById('restore-scan-btn');

        if (restoreScanBtn) {

            restoreScanBtn.addEventListener('click', _scanBackupRoot);

        }



        var restoreLocSel = document.getElementById('restore-location-select');

        if (restoreLocSel) {

            restoreLocSel.addEventListener('change', function() {

                _renderRestoreGames(this.value);

            });

        }



        var restoreSelectedBtn = document.getElementById('restore-selected-btn');

        if (restoreSelectedBtn) {

            restoreSelectedBtn.addEventListener('click', _doRestoreSelected);

        }



        Bridge.on('download_progress', function(json) {

            try {

                var d = JSON.parse(json);

                if (d.task !== 'backup_progress') return;

                var progressEl = document.getElementById('all-saves-progress');

                var progressFill = document.getElementById('all-saves-progress-fill');

                var progressLabel = document.getElementById('all-saves-progress-label');

                var progressCount = document.getElementById('all-saves-progress-count');

                var progressOk = document.getElementById('all-saves-progress-ok');

                var progressFail = document.getElementById('all-saves-progress-fail');

                if (!progressEl) return;

                progressEl.classList.remove('hidden');

                if (progressFill) progressFill.style.width = (d.percent || 0) + '%';

                if (progressLabel) progressLabel.textContent = d.current_label || 'Sauvegarde…';

                if (progressCount) progressCount.textContent = (d.done || 0) + ' / ' + (d.total || 0);

                if (progressOk) progressOk.textContent = '\u2713 ' + (d.succeeded || 0) + ' OK';

                if (progressFail) progressFail.textContent = '\u2717 ' + (d.failed || 0) + ' échec(s)';

            } catch(e) {}

        });



        Bridge.on('task_finished', function(json) {

            try {

                var data = JSON.parse(json);



                if (data.task === 'gdrive_authorize') {

                    var btn = document.getElementById('gdrive-connect-btn');

                    if (btn) {

                        btn.disabled = false;

                        btn.textContent = 'Se connecter à Google Drive';

                    }

                    if (data.success) {

                        _setGdriveStatus(true, data.email || '');

                        Components.showToast('success', 'Google Drive connecté');

                    } else {

                        Components.showToast('error', data.message || 'Connexion échouée');

                    }

                }



                if (data.task === 'gdrive_disconnect') {

                    if (data.success) {

                        _checkGdriveStatus();

                        Components.showToast('info', data.message || 'Google Drive déconnecté');

                    } else {

                        Components.showToast('error', data.message || 'Déconnexion échouée');

                    }

                }



                if (data.task === 'scan_cloud_games') {

                    if (data.success && Array.isArray(data.games)) {

                        _renderGames(data.games, data.scan_hint || '');

                    } else if (!data.success && data.message) {

                        Components.showToast('warning', data.message);

                    }

                }



                if (data.task === 'scan_all_save_locations') {

                    if (data.success) {

                        _allSavesEntries = data.entries || [];

                        _renderAllSavesResults(_allSavesEntries);

                    } else {

                        Components.showToast('warning', data.message || 'Scan impossible');

                    }

                }



                if (data.task === 'backup_all_save_locations') {

                    var logEl = document.getElementById('all-saves-log-content');

                    var logDiv = document.getElementById('all-saves-log');

                    if (logEl && data.log) { logEl.textContent = data.log; }

                    if (logDiv) logDiv.classList.remove('hidden');

                    var progressEl = document.getElementById('all-saves-progress');

                    if (progressEl) {

                        if (data.success) {

                            var fill = document.getElementById('all-saves-progress-fill');

                            if (fill) fill.style.width = '100%';

                            var lbl = document.getElementById('all-saves-progress-label');

                            if (lbl) lbl.textContent = 'Terminé';

                        }

                        setTimeout(function() { progressEl.classList.add('hidden'); }, 3000);

                    }

                    if (data.success) {

                        Components.showToast('success', data.message || 'Sauvegarde terminée');

                    } else {

                        Components.showToast('error', data.message || 'Sauvegarde échouée');

                    }

                }



                if (data.task === 'scan_backup_root') {

                    if (data.success && data.locations) {

                        _restoreLocationsData = data.locations;

                        _renderRestoreLocations(data.locations);

                    } else {

                        Components.showToast('error', data.message || 'Scan échoué');

                    }

                }



                if (data.task === 'restore_save_location') {

                    var logEl2 = document.getElementById('all-saves-log-content');

                    var logDiv2 = document.getElementById('all-saves-log');

                    if (logEl2 && data.log) { logEl2.textContent = data.log; }

                    if (logDiv2) logDiv2.classList.remove('hidden');

                    if (data.success) {

                        Components.showToast('success', 'Restauration terminée');

                    } else {

                        Components.showToast('error', data.message || 'Restauration échouée');

                    }

                }



                var cloudTasks = ['backup_cloud_save', 'restore_cloud_save', 'rclone_backup_save'];

                if (cloudTasks.indexOf(data.task) !== -1) {

                    var logContent = document.getElementById('cloud-log-content');

                    var logOutput = document.getElementById('cloud-log');

                    if (logContent && data.log) {

                        logContent.textContent = data.log;

                        if (logOutput) logOutput.classList.remove('hidden');

                    }

                    if (data.success) {

                        Components.showToast('success', data.message || 'Terminé');

                    } else {

                        Components.showToast('error', data.message || 'Opération échouée');

                    }

                }

            } catch(e) {}

        });

    }



    function onPageEnter() {

        init();

        Bridge.callWithCallback('get_setting', 'steam_path', function(val) {

            var s = val ? String(val).trim() : '';

            if (s) {

                var input = document.getElementById('cloud-steam-path');

                if (input) input.value = s;

            }

        });

        Bridge.callWithCallback('get_setting', 'steam32_id', function(val) {

            var s = val ? String(val).trim() : '';

            if (s) {

                var input = document.getElementById('cloud-steam32');

                if (input) input.value = s;

            }

        });

        Bridge.callWithCallback('get_setting', 'save_watcher_interval', function(val) {

            var inp = document.getElementById('cloud-auto-interval');

            if (inp && (val !== undefined && val !== null && val !== '')) {

                inp.value = String(val);

            }

        });

        Bridge.call('set_setting', 'cloud_provider', 'gdrive');

        _checkGdriveStatus();

    }



    function _runCloudSelfTest() {

        _persistSteamPathFromField(false);

        _persistSteam32FromField(false);

        var steamPath = document.getElementById('cloud-steam-path');

        var steam32 = document.getElementById('cloud-steam32');

        var sp = steamPath ? steamPath.value.trim() : '';

        var s32 = steam32 ? steam32.value.trim() : '';

        if (!sp || !s32) {

            Components.showToast('warning', 'Renseigne d’abord le dossier Steam et l’ID userdata');

            return;

        }

        var btn = document.getElementById('cloud-self-test-btn');

        var oldLabel = btn ? btn.textContent : '';

        if (btn) {

            btn.disabled = true;

            btn.textContent = 'Test…';

        }

        Bridge.callWithCallback('cloud_saves_self_test', sp, s32, function(jsonRaw) {

            if (btn) {

                btn.disabled = false;

                btn.textContent = oldLabel || 'Tester la configuration';

            }

            try {

                var r = JSON.parse(jsonRaw || '{}');

                var lines = [];

                lines.push('— Résultat du test —');

                lines.push('Dossier Steam au bon endroit : ' + (r.steam_install_ok ? 'oui' : 'non'));

                lines.push('Binaire Steam présent : ' + (r.steam_exe_found ? 'oui' : 'non'));

                lines.push('ID userdata renseigné : ' + (r.userdata_id_set ? 'oui' : 'non'));

                if (r.account_id) {

                    lines.push('Dossier userdata utilisé (après normalisation) : ' + r.account_id);

                }

                lines.push('Dossier …/userdata/… existe : ' + (r.userdata_folder_ok ? 'oui' : 'non'));

                lines.push('OAuth Google configuré : ' + (r.gdrive_oauth_available ? 'oui' : 'non'));

                lines.push('Google Drive connecté : ' + (r.gdrive_connected ? 'oui' : 'non'));

                lines.push('Racine des sauvegardes sur Drive : ' + (r.gdrive_backup_root_ok ? 'OK' : 'non'));

                lines.push('');

                (r.messages || []).forEach(function(m) { lines.push('- ' + m); });

                var logContent = document.getElementById('cloud-log-content');

                var logOutput = document.getElementById('cloud-log');

                if (logContent) logContent.textContent = lines.join('\n');

                if (logOutput) {

                    logOutput.classList.remove('hidden');

                    logOutput.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

                }

                if (r.ok) {

                    Components.showToast('success', 'Test réussi — tout est prêt.');

                } else {

                    Components.showToast('warning', 'Problème détecté — lis le log « Log » sous la page.');

                }

            } catch (e) {

                Components.showToast('error', 'Réponse de test illisible');

            }

        });

    }



    function _scanGames() {

        _persistSteamPathFromField(false);

        _persistSteam32FromField(false);

        var steamPath = document.getElementById('cloud-steam-path');

        var steam32 = document.getElementById('cloud-steam32');

        var sp = steamPath ? steamPath.value.trim() : '';

        var s32 = steam32 ? steam32.value.trim() : '';



        if (!sp || !s32) {

            Components.showToast('warning', 'Renseigne le dossier Steam et l’ID userdata');

            return;

        }



        Components.showToast('info', 'Scan des jeux…');

        Bridge.call('scan_cloud_games', sp, s32);

    }



    function _renderGames(games, scanHint) {

        var tableDiv = document.getElementById('cloud-games');

        var tbody = document.getElementById('cloud-games-tbody');

        var hintEl = document.getElementById('cloud-scan-hint');

        if (hintEl) {

            if ((!games || games.length === 0) && scanHint) {

                hintEl.textContent = scanHint;

                hintEl.classList.remove('hidden');

            } else {

                hintEl.textContent = '';

                hintEl.classList.add('hidden');

            }

        }

        if (!tbody) return;



        tbody.innerHTML = '';

        (games || []).forEach(function(game) {

            var tr = document.createElement('tr');

            tr.dataset.appid = game.app_id;

            tr.style.cursor = 'pointer';

            tr.innerHTML =

                '<td>' + game.app_id + '</td>' +

                '<td>' + Components.escapeHtml(game.name || 'Inconnu') + '</td>' +

                '<td>' + (game.size || 'N/A') + '</td>';

            tr.addEventListener('click', function() {

                tbody.querySelectorAll('tr.selected').forEach(function(r) { r.classList.remove('selected'); r.style.background = ''; });

                this.classList.add('selected');

                this.style.background = 'var(--btn-bg)';

            });

            tbody.appendChild(tr);

        });



        if (tableDiv) {

            if (games && games.length > 0) {

                tableDiv.classList.remove('hidden');

            } else {

                tableDiv.classList.add('hidden');

            }

        }

        if (games && games.length > 0) {

            Components.showToast('success', games.length + ' jeu(x) trouvé(s)');

        } else {

            Components.showToast('warning', 'Aucun jeu — lis le message sous « Scanner les jeux »');

        }

    }



    function _checkGdriveStatus() {

        Bridge.callSync('gdrive_status', function(result) {

            try {

                if (!result) return;

                var status = JSON.parse(result);

                if (status.available === false) {

                    _setGdriveUnavailable();

                    return;

                }

                _setGdriveStatus(!!status.connected, status.email || '');

            } catch (e) {}

        });

    }



    function _setGdriveUnavailable() {

        var statusText = document.getElementById('gdrive-status-text');

        var connectBtn = document.getElementById('gdrive-connect-btn');

        var disconnectBtn = document.getElementById('gdrive-disconnect-btn');

        if (statusText) {

            statusText.textContent =

                'OAuth non configuré — ajoute gdrive_oauth_client.json dans le dossier SlimeDeals ou les variables STEAMIDRA_GDRIVE_CLIENT_*';

        }

        if (connectBtn) {

            connectBtn.style.display = '';

            connectBtn.disabled = true;

            connectBtn.textContent = 'Configurer OAuth';

        }

        if (disconnectBtn) disconnectBtn.style.display = 'none';

    }



    function _setGdriveStatus(connected, email) {

        var statusText = document.getElementById('gdrive-status-text');

        var connectBtn = document.getElementById('gdrive-connect-btn');

        var disconnectBtn = document.getElementById('gdrive-disconnect-btn');

        if (connected) {

            if (statusText) statusText.textContent = 'Connecté' + (email ? ' : ' + email : '');

            if (connectBtn) connectBtn.style.display = 'none';

            if (disconnectBtn) disconnectBtn.style.display = '';

        } else {

            if (statusText) statusText.textContent = 'Non connecté';

            if (connectBtn) {

                connectBtn.style.display = '';

                connectBtn.disabled = false;

                connectBtn.textContent = 'Se connecter à Google Drive';

            }

            if (disconnectBtn) disconnectBtn.style.display = 'none';

        }

    }



    function _scanAllSaveLocations() {

        _persistSteamPathFromField(false);

        _persistSteam32FromField(false);

        var steamPath = document.getElementById('cloud-steam-path');

        var steam32 = document.getElementById('cloud-steam32');

        var sp = steamPath ? steamPath.value.trim() : '';

        var s32 = steam32 ? steam32.value.trim() : '';

        Components.showToast('info', 'Scan de tous les emplacements…');

        Bridge.call('scan_all_save_locations', JSON.stringify({ steam_path: sp, steam32_id: s32 }));

    }



    function _renderAllSavesResults(entries) {

        var tbody = document.getElementById('all-saves-tbody');

        var resultsDiv = document.getElementById('all-saves-results');

        var backupBtn = document.getElementById('all-saves-backup-btn');

        if (!tbody) return;

        tbody.innerHTML = '';

        entries.forEach(function(entry, idx) {

            var tr = document.createElement('tr');

            tr.innerHTML =

                '<td><input type="checkbox" class="all-saves-row-check" data-idx="' + idx + '" checked></td>' +

                '<td>' + Components.escapeHtml(entry.location) + '</td>' +

                '<td>' + Components.escapeHtml(entry.label) + '</td>' +

                '<td>' + (entry.file_count || 0) + '</td>';

            tbody.appendChild(tr);

        });

        if (resultsDiv) resultsDiv.classList.remove('hidden');

        if (backupBtn) backupBtn.style.display = '';

        Components.showToast('success', entries.length + ' dossier(s) trouvé(s)');

    }



    function _backupAllSaves() {

        var checked = document.querySelectorAll('.all-saves-row-check:checked');

        var selectedEntries = [];

        checked.forEach(function(cb) {

            var idx = parseInt(cb.dataset.idx, 10);

            if (!isNaN(idx) && _allSavesEntries[idx]) {

                selectedEntries.push(_allSavesEntries[idx]);

            }

        });

        if (!selectedEntries.length) {

            Components.showToast('warning', 'Coche au moins un dossier dans le tableau');

            return;

        }

        var progressEl = document.getElementById('all-saves-progress');

        var progressFill = document.getElementById('all-saves-progress-fill');

        var progressLabel = document.getElementById('all-saves-progress-label');

        var progressCount = document.getElementById('all-saves-progress-count');

        var progressOk = document.getElementById('all-saves-progress-ok');

        var progressFail = document.getElementById('all-saves-progress-fail');

        if (progressEl) {

            progressEl.classList.remove('hidden');

            if (progressFill) progressFill.style.width = '0%';

            if (progressLabel) progressLabel.textContent = 'Démarrage…';

            if (progressCount) progressCount.textContent = '0 / ' + selectedEntries.length;

            if (progressOk) progressOk.textContent = '\u2713 0 OK';

            if (progressFail) progressFail.textContent = '\u2717 0 échec(s)';

        }

        Bridge.call('backup_all_save_locations', JSON.stringify({

            entries: selectedEntries,

            provider: 'gdrive_api'

        }));

        Components.showToast('info', 'Envoi de ' + selectedEntries.length + ' dossier(s) vers Google Drive…');

    }



    function _scanBackupRoot() {

        Components.showToast('info', 'Lecture des sauvegardes sur Google Drive…');

        Bridge.call('scan_backup_root', JSON.stringify({ provider: 'gdrive_api', backup_root: '' }));

    }



    function _renderRestoreLocations(locations) {

        var sel = document.getElementById('restore-location-select');

        var resultsDiv = document.getElementById('restore-results');

        if (!sel) return;

        sel.innerHTML = '<option value="">Choisir un emplacement…</option>';

        var keys = Object.keys(locations);

        keys.forEach(function(loc) {

            var opt = document.createElement('option');

            opt.value = loc;

            opt.textContent = loc + ' (' + (locations[loc].games || []).length + ' jeu(x))';

            sel.appendChild(opt);

        });

        if (resultsDiv) resultsDiv.classList.remove('hidden');

        var restoreFolderRow = document.getElementById('restore-folder-input-row');

        var restoreSourceRow = document.getElementById('restore-source-row');

        if (restoreFolderRow) restoreFolderRow.style.display = 'none';

        var restoreLabel = document.getElementById('restore-source-label');

        if (restoreLabel) restoreLabel.textContent = 'Source : Google Drive (déjà connecté)';

        if (restoreSourceRow) restoreSourceRow.style.display = '';

        Components.showToast('success', keys.length + ' emplacement(s) sur Drive');

    }



    function _renderRestoreGames(locationName) {

        var gamesSel = document.getElementById('restore-game-select');

        var gamesList = document.getElementById('restore-games-list');

        if (!gamesSel || !locationName) return;

        var loc = _restoreLocationsData[locationName];

        gamesSel.innerHTML = '<option value="">Choisir un jeu…</option>';

        if (loc && loc.games) {

            loc.games.forEach(function(game, idx) {

                var opt = document.createElement('option');

                opt.value = idx;

                opt.textContent = game.game_name || game.folder_name;

                if (game.app_id) opt.textContent = game.app_id + ' — ' + opt.textContent;

                if (game.backed_up_at) opt.textContent += '  [' + game.backed_up_at.split('T')[0] + ']';

                gamesSel.appendChild(opt);

            });

        }

        if (gamesList) gamesList.classList.remove('hidden');

    }



    function _doRestoreSelected() {

        var locSel = document.getElementById('restore-location-select');

        var gameSel = document.getElementById('restore-game-select');

        var locName = locSel ? locSel.value : '';

        var gameIdx = gameSel ? parseInt(gameSel.value, 10) : -1;

        if (!locName || isNaN(gameIdx) || gameIdx < 0) {

            Components.showToast('warning', 'Choisis un emplacement puis un jeu');

            return;

        }

        var loc = _restoreLocationsData[locName];

        if (!loc || !loc.games || !loc.games[gameIdx]) {

            Components.showToast('warning', 'Jeu introuvable');

            return;

        }

        var entry = loc.games[gameIdx];

        if (!entry.source_path) {

            Components.showToast('warning', 'Chemin de destination manquant dans les métadonnées');

            return;

        }

        if (!confirm('Restaurer « ' + (entry.game_name || entry.folder_name) + ' » vers :\n' + entry.source_path + ' ?')) {

            return;

        }

        Bridge.call('restore_save_location', JSON.stringify(Object.assign({}, entry)));

        Components.showToast('info', 'Restauration…');

    }



    return {

        init: init,

        onPageEnter: onPageEnter

    };

})();


