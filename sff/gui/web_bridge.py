# SteaMidra - Steam game setup and manifest tool (SFF)
# Copyright (c) 2025-2026 Midrag (https://github.com/Midrags)
#
# This file is part of SteaMidra.
#
# SteaMidra is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SteaMidra is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SteaMidra.  If not, see <https://www.gnu.org/licenses/>.

"""
QWebChannel bridge — exposes Python backend functions to the web UI.

All I/O methods dispatch to QThread workers and emit results via pyqtSignal.
Only trivial getters use synchronous result= slots.
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Callable, Optional

from sff.log_redact import redact_sensitive_log_text

from sff.launcher_ranks import (
    MONSTRE_MAX_DISTINCT_INSTALLS,
    PASS24H_MAX_DISTINCT_INSTALLS,
    cloud_saves_launcher_allowed_for_rank,
    launcher_rank_bucket as _launcher_rank_bucket,
    norm_launcher_rank as _norm_saved_launcher_rank,
    triple_exclusive_tools_allowed_for_rank,
)
from sff.utils import launcher_manifests_dir, launcher_saved_lua_dir

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QFileDialog

logger = logging.getLogger(__name__)

# ── Launcher auth helpers ────────────────────────────────────────────────────
_API_BASE   = os.getenv("SLIMEDEALS_API", "https://slimedeals.fr")
_AUTH_FILE  = Path.home() / ".slimedeals" / "auth.json"
# Deep-link salon #avis (https://discord.com/channels/<guild>/<channel>). Sinon → invite.
_SLIMEDEALS_DISCORD_GUILD_ID = os.getenv("SLIMEDEALS_DISCORD_GUILD_ID", "").strip()
_DISCORD_AVIS_CHANNEL_ID = "1502728174356660274"
# Salon « abonnement gratuit » (deep-link si SLIMEDEALS_DISCORD_GUILD_ID défini)
_DISCORD_FREE_SUB_CHANNEL_ID = "1501929971764166677"


def _log_download_source(source: str) -> str:
    """Libellé neutre pour les journaux (pas de nom de fournisseur tiers)."""
    s = (source or "").strip().lower()
    if s == "twentytwocloud":
        return "catalogue"
    return s or "auto"


def _get_hwid() -> str:
    """Return a stable hardware fingerprint for this machine (SHA-256, 32 hex chars)."""
    try:
        _run_kw: dict = dict(
            capture_output=True,
            text=True,
            timeout=8,
            stdin=subprocess.DEVNULL,
        )
        if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            _run_kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        raw = subprocess.run(
            ["wmic", "csproduct", "get", "uuid"],
            **_run_kw,
        )
        lines = [l.strip() for l in raw.stdout.strip().splitlines() if l.strip() and l.strip() != "UUID"]
        uuid = lines[0] if lines else "unknown"
    except Exception:
        uuid = "unknown"
    return hashlib.sha256(uuid.encode()).hexdigest()[:32]


def _api_post(path: str, payload: dict) -> dict:
    data  = json.dumps(payload).encode()
    req   = urllib.request.Request(
        f"{_API_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {}
        err_msg = body.get("error", f"Erreur HTTP {e.code}")
        out: dict = {"ok": False, "error": err_msg, "http_status": e.code}
        if "app_id" in body:
            out["app_id"] = body["app_id"]
        return out
    except Exception as exc:
        logger.debug("api_post: %s", redact_sensitive_log_text(str(exc)))
        return {"ok": False, "error": "Serveur injoignable"}


def _notify_launcher_gen_activity(
    app_id: str,
    ui_log: Optional[Callable[[str], None]] = None,
    steam_path: Optional[Path] = None,
) -> None:
    """Notifie Discord (salon activité) après une installation — FREE, Monstre ou Triple Monstre uniquement."""

    def _u(msg: str) -> None:
        if ui_log:
            try:
                ui_log(msg)
            except Exception:
                pass
        logger.debug("[Discord activité] %s", msg)

    aid = str(app_id).strip()
    if not aid.isdigit():
        _u("Notification d’activité ignorée : identifiant de jeu invalide.")
        return
    saved = _load_auth()
    token = (saved.get("token") or "").strip()
    if not token:
        _u("Notification d’activité ignorée : connecte-toi dans le launcher pour activer les annonces.")
        return
    _u("Envoi de la notification d’activité sur Discord…")
    payload: dict = {"token": token, "hwid": _get_hwid(), "app_id": aid}
    if steam_path is not None:
        try:
            from sff.premium_manifest_lock import paid_distinct_game_count_for_steam

            payload["paid_slots_used"] = int(paid_distinct_game_count_for_steam(steam_path))
        except Exception:
            logger.debug("notify-gen: paid_slots_used indisponible", exc_info=True)
    out = _api_post(
        "/api/launcher/notify-gen",
        payload,
    )
    if not out.get("ok") or not out.get("sent"):
        http_st = out.get("http_status")
        err = out.get("error") or out.get("reason") or ""
        if http_st == 404 or "404" in str(err):
            _u(
                "La notification d’activité sur Discord n’a pas pu être envoyée "
                "(service temporairement indisponible). Réessaie plus tard."
            )
        else:
            _u("La notification d’activité sur Discord n’a pas pu être envoyée (erreur réseau ou serveur).")
    else:
        _u("Notification d’activité sur Discord envoyée.")


_PENDING_INSTALL_UNCHANGED = object()


def _save_auth(
    token: str,
    username: str,
    rank: str = "free",
    free_claimed=None,
    rank_expires_at=None,
    *,
    free_catalog_pending_install=_PENDING_INSTALL_UNCHANGED,
) -> None:
    """Persiste auth.json. ``free_catalog_pending_install`` autorise le téléchargement catalogue
    avant enregistrement serveur (une seule fois, après installation réussie)."""
    _AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    prev = _load_auth()
    payload = {
        "token": token,
        "username": username,
        "rank": rank,
        "free_claimed": free_claimed,
        "rank_expires_at": rank_expires_at,
    }
    committed = free_claimed is not None and str(free_claimed).strip() != ""
    if committed:
        pass
    elif free_catalog_pending_install is _PENDING_INSTALL_UNCHANGED:
        pinst = prev.get("free_catalog_pending_install")
        if pinst:
            payload["free_catalog_pending_install"] = pinst
        pat = prev.get("free_catalog_pending_at")
        if pat is not None:
            try:
                payload["free_catalog_pending_at"] = int(pat)
            except (TypeError, ValueError):
                pass
    elif free_catalog_pending_install is None:
        pass
    else:
        payload["free_catalog_pending_install"] = str(free_catalog_pending_install).strip()
        payload["free_catalog_pending_at"] = int(time.time())
    _AUTH_FILE.write_text(json.dumps(payload), encoding="utf-8")
    try:
        from sff.launcher_session import invalidate_launcher_verify_cache

        invalidate_launcher_verify_cache()
    except Exception:
        pass


def _load_auth() -> dict:
    try:
        return json.loads(_AUTH_FILE.read_text())
    except Exception:
        return {}


def _clear_auth() -> None:
    try:
        _AUTH_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        from sff.launcher_session import invalidate_launcher_verify_cache

        invalidate_launcher_verify_cache()
    except Exception:
        pass


# Jeux catalogue plan FREE (doit rester aligné avec le bot / store.js)
_LAUNCHER_FREE_CATALOG_IDS = frozenset({
    "2416450",
    "284160",
    "1943950",
    "1144200",
    "2968420",
    "1321680",
    "655500",
    "526870",
})

# Préparation catalogue FREE : auto-déblocage si abandonnée (crash, ancien état sans date).
_FREE_CATALOG_PENDING_STALE_SEC = 24 * 3600


def _free_catalog_pending_is_stale(saved: dict) -> bool:
    """True si une préparation « en cours » est trop vieille ou sans horodatage (fichier legacy)."""
    pend = str(saved.get("free_catalog_pending_install") or "").strip()
    if not pend:
        return False
    at = saved.get("free_catalog_pending_at")
    try:
        t0 = int(at)
    except (TypeError, ValueError):
        t0 = 0
    if t0 <= 0:
        return True
    return (int(time.time()) - t0) > _FREE_CATALOG_PENDING_STALE_SEC


def _clear_free_catalog_pending_fields(saved: dict) -> None:
    """Retire pending + horodatage sans toucher au reste de l'auth."""
    _save_auth(
        str(saved.get("token") or ""),
        str(saved.get("username") or ""),
        str(saved.get("rank") or "free"),
        saved.get("free_claimed"),
        saved.get("rank_expires_at"),
        free_catalog_pending_install=None,
    )


def _sync_expire_free_catalog_pending_if_stale(saved: dict | None = None) -> dict:
    """Purge pending périmé et retourne auth.json à jour."""
    if saved is None:
        saved = _load_auth()
    if _free_catalog_pending_is_stale(saved):
        _clear_free_catalog_pending_fields(saved)
        return _load_auth()
    return saved


_CLOUD_SAVES_DENIED_MSG = (
    "Les sauvegardes cloud Google Drive sont reservees au plan Triple Monstre "
    "(pas au plan Monstre ni au plan FREE). Voir slimedeals.fr/#tarifs."
)


def _cloud_saves_feature_allowed() -> bool:
    """Sauvegardes cloud : Triple Monstre uniquement."""
    saved = _load_auth()
    return cloud_saves_launcher_allowed_for_rank(saved.get("rank"))


def _launcher_free_catalog_download_allowed(app_id: str) -> tuple[bool, str]:
    """Compte FREE : un jeu du catalogue gratuit après choix — réclamation serveur OU session locale (pending)."""
    saved = _sync_expire_free_catalog_pending_if_stale()
    if _norm_saved_launcher_rank(saved.get("rank")) != "free":
        return True, ""
    aid = str(app_id).strip()
    if aid not in _LAUNCHER_FREE_CATALOG_IDS:
        return False, (
            "Plan FREE : seuls les jeux du catalogue gratuit (onglet « Télécharger ») sont autorisés. "
            "Passe a un abonnement Monstre ou Triple Monstre pour installer n'importe quel jeu Steam."
        )
    claimed = saved.get("free_claimed")
    pending = saved.get("free_catalog_pending_install")
    c = str(claimed).strip() if claimed is not None else ""
    p = str(pending).strip() if pending is not None else ""
    if c and c != aid:
        return False, (
            f"Plan FREE : tu as déjà réclamé ton jeu catalogue gratuit (App {c}). "
            "Un seul titre : passe à un abonnement Monstre ou Triple Monstre pour d'autres jeux."
        )
    if c == aid:
        return True, ""
    if p == aid:
        return True, ""
    return False, (
        "Plan FREE : sur la carte du jeu dans « Télécharger », clique d'abord sur "
        "« Choisir ce jeu » pour lancer la préparation, puis l'installation."
    )


def _begin_free_catalog_install_impl(app_id: str) -> str:
    """Logique catalogue FREE (appelée depuis un worker — pas sur le thread UI)."""
    saved = _sync_expire_free_catalog_pending_if_stale()
    token = (saved.get("token") or "").strip()
    if not token:
        return json.dumps({"ok": False, "error": "Non connecté"})
    aid = str(app_id).strip()
    if aid not in _LAUNCHER_FREE_CATALOG_IDS:
        return json.dumps({"ok": False, "error": "Jeu hors catalogue Free"})
    from sff.launcher_session import apply_verify_to_local_auth, verify_launcher_session

    vr = verify_launcher_session(force_refresh=True)
    apply_verify_to_local_auth(vr)
    saved = _load_auth()
    if not vr.get("ok"):
        return json.dumps({"ok": False, "error": (vr.get("error") or "Session invalide")})
    rank = vr.get("rank", saved.get("rank", "free"))
    if _norm_saved_launcher_rank(rank) != "free":
        return json.dumps(
            {
                "ok": False,
                "error": "Le catalogue gratuit est réservé aux comptes plan FREE.",
            }
        )
    srv_claim = vr.get("free_claimed")
    local_claim = str(saved.get("free_claimed") or "").strip()
    if local_claim and local_claim != aid:
        return json.dumps(
            {"ok": False, "error": "already_claimed", "app_id": local_claim}
        )
    if srv_claim is not None and str(srv_claim).strip() != "":
        sc = str(srv_claim).strip()
        if sc != aid:
            return json.dumps(
                {"ok": False, "error": "already_claimed", "app_id": sc}
            )
        _save_auth(
            token,
            saved.get("username", ""),
            rank,
            sc,
            vr.get("rank_expires_at"),
            free_catalog_pending_install=None,
        )
        return json.dumps({"ok": True, "mode": "committed"})
    pend = str(saved.get("free_catalog_pending_install") or "").strip()
    if pend and pend != aid:
        return json.dumps(
            {
                "ok": False,
                "error": "pending_other_game",
                "app_id": pend,
            }
        )
    _save_auth(
        token,
        saved.get("username", ""),
        rank,
        None,
        vr.get("rank_expires_at"),
        free_catalog_pending_install=aid,
    )
    return json.dumps({"ok": True, "mode": "pending"})


def launcher_fetch_billing_portal() -> dict:
    """Demande une URL de portail Stripe pour le compte connecté (abonnement payant lié)."""
    saved = _load_auth()
    token = (saved.get("token") or "").strip()
    if not token:
        return {"ok": False, "error": "Non connecté"}
    return _api_post(
        "/api/launcher/billing-portal",
        {"token": token, "hwid": _get_hwid()},
    )


def launcher_verify_saved_token() -> dict:
    """Called at startup. Returns {ok, username} if saved token still valid."""
    saved = _load_auth()
    if not saved.get("token"):
        return {"ok": False}
    hwid = _get_hwid()
    return _api_post("/api/launcher/verify", {"token": saved["token"], "hwid": hwid})


class _Worker(QObject):
    """Generic thread worker for async bridge operations."""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as e:
            safe = redact_sensitive_log_text(str(e))
            logger.warning("Worker error (%s): %s", type(e).__name__, safe)
            self.error.emit(safe)
            self.finished.emit(None)


class WebBridge(QObject):
    """QObject subclass registered via QWebChannel.
    JS accesses this as ``channel.objects.bridge``.
    """

    # --- Signals (Python → JS) ---
    search_results = pyqtSignal(str)
    depot_history_results = pyqtSignal(str)
    download_progress = pyqtSignal(str)
    task_finished = pyqtSignal(str)
    log_message = pyqtSignal(str)
    ttc_game_info   = pyqtSignal(str)
    auth_done       = pyqtSignal(str)   # emitted with username after successful login
    launcher_profile_synced = pyqtSignal(str)  # JSON {ok, rank?, free_claimed?, username?} après /verify
    # Résultat de begin_free_catalog_install (worker — évite blocage WebChannel sur /verify)
    free_catalog_begin_result = pyqtSignal(str)
    # Notification Discord d’activité : traitement sur le thread UI uniquement
    request_notify_gen = pyqtSignal(str)

    def __init__(self, ui, steam_path, parent=None):
        super().__init__(parent)
        self._ui = ui
        self._steam_path = Path(steam_path) if steam_path else None
        self._active_library = None
        self._api_key = None
        self._store_client = None
        self._workers = []  # prevent GC of running workers
        self.request_notify_gen.connect(self._deliver_notify_gen, Qt.ConnectionType.QueuedConnection)
        if ui is not None and hasattr(ui, "post_install_notify"):
            def _post_install_hook(aid: str, br=self) -> None:
                br._log_ui(
                    f"Fin d’installation (Lua / DepotDownloader) — demande notification Discord app_id={aid}"
                )
                br.request_notify_gen.emit(str(aid))

            ui.post_install_notify = _post_install_hook

    def _log_ui(self, msg: str) -> None:
        """Affiche une ligne dans l'onglet Journaux (signal log_message → app.js)."""
        try:
            safe = redact_sensitive_log_text(msg)
        except Exception:
            safe = msg
        try:
            ts = time.strftime("%H:%M:%S")
            self.log_message.emit(f"[{ts}] [Téléchargement] {safe}")
        except Exception:
            logger.info("[Téléchargement] %s", safe)

    @pyqtSlot(str)
    def _deliver_notify_gen(self, app_id: str) -> None:
        self._log_ui("Préparation de la notification d’activité sur Discord…")
        _notify_launcher_gen_activity(app_id, ui_log=self._log_ui, steam_path=self._steam_path)

    @pyqtSlot(str)
    def notify_gen_activity(self, app_id: str) -> None:
        """Slot public (QWebChannel) — même effet que l’auto-notify après install."""
        self._log_ui(f"Notification d’activité (appel manuel) pour le jeu {app_id!r}")
        self.request_notify_gen.emit(str(app_id).strip())

    @pyqtSlot(result=str)
    def get_app_version(self) -> str:
        """Version du launcher (sff.strings.VERSION) pour l’UI web."""
        from sff.strings import VERSION as _v

        return _v

    # ── helpers ──────────────────────────────────────────────────

    def _run_async(self, func, *args, on_done=None, on_error=None, **kwargs):
        """Spawn a QThread worker for the given function."""
        # Forward stdout/stderr from the background thread to the parent window's
        # StreamEmitter so that print() output appears in the Modern UI log panel.
        # Classic UI's _start_worker does this too; we mirror that behaviour here.
        parent = self.parent()
        stream = getattr(parent, '_stream_emitter', None) if parent else None
        if stream is not None:
            _orig_func = func
            def func(*_a, **_kw):   # noqa: E731
                import sys as _sys
                _old_out, _old_err = _sys.stdout, _sys.stderr
                _sys.stdout = stream
                _sys.stderr = stream
                try:
                    return _orig_func(*_a, **_kw)
                finally:
                    _sys.stdout = _old_out
                    _sys.stderr = _old_err
        thread = QThread()
        worker = _Worker(func, *args, **kwargs)
        worker.moveToThread(thread)

        def _cleanup(result):
            thread.quit()
            thread.wait()
            if worker in self._workers:
                self._workers.remove(worker)
            if on_done:
                on_done(result)

        def _on_error(msg):
            thread.quit()
            thread.wait()
            if worker in self._workers:
                self._workers.remove(worker)
            try:
                safe_msg = redact_sensitive_log_text(str(msg))
            except Exception:
                safe_msg = str(msg)
            try:
                ts = time.strftime("%H:%M:%S")
                self.log_message.emit(f"[{ts}] [Worker] Erreur : {safe_msg}")
            except Exception:
                logger.warning("[Worker] Erreur : %s", safe_msg)
            if on_error:
                on_error(safe_msg)
            else:
                self.task_finished.emit(json.dumps({
                    "task": "unknown", "success": False, "message": safe_msg
                }))

        worker.finished.connect(_cleanup)
        worker.error.connect(_on_error)
        thread.started.connect(worker.run)
        self._workers.append(worker)
        thread.start()

    def _emit_task_result(self, task_name, success, message="", **extra):
        data = {"task": task_name, "success": success, "message": message}
        data.update(extra)
        self.task_finished.emit(json.dumps(data))

    def _get_store_client(self):
        if self._store_client is None and self._api_key:
            from sff.store_browser import StoreApiClient
            self._store_client = StoreApiClient(self._api_key)
        return self._store_client

    # ── Auth slots ───────────────────────────────────────────────

    @pyqtSlot()
    def auth_check_saved(self) -> None:
        """Called by auth.html on load — checks saved token in background.
        Emits auth_done(token) if valid, or auth_done('') to show login form."""
        def _check():
            return launcher_verify_saved_token()

        def _done(result):
            if result and result.get("ok"):
                # Send the saved token back to JS so it can pass it to auth_success
                saved = _load_auth()
                self.auth_done.emit(saved.get("token", ""))
            else:
                _clear_auth()
                self.auth_done.emit("")  # empty → show login form

        self._run_async(_check, on_done=_done)

    @pyqtSlot(str, str, result=str)
    def auth_login(self, username: str, password: str) -> str:
        """Called from auth.html — performs login and returns JSON with token."""
        hwid   = _get_hwid()
        result = _api_post("/api/launcher/login", {
            "username": username.strip().lower(),
            "password": password,
            "hwid": hwid,
        })
        if result.get("ok"):
            _save_auth(
                result["token"],
                result["username"],
                result.get("rank", "free"),
                result.get("free_claimed"),
                result.get("rank_expires_at"),
                free_catalog_pending_install=None,
            )
        return json.dumps(result)

    @pyqtSlot(str, str, result=str)
    def auth_register(self, username: str, password: str) -> str:
        """Called from auth.html — creates account and returns JSON with token."""
        hwid   = _get_hwid()
        result = _api_post("/api/launcher/register", {
            "username": username.strip().lower(),
            "password": password,
            "hwid": hwid,
        })
        if result.get("ok"):
            _save_auth(
                result["token"],
                result["username"],
                result.get("rank", "free"),
                result.get("free_claimed"),
                result.get("rank_expires_at"),
                free_catalog_pending_install=None,
            )
        return json.dumps(result)

    @pyqtSlot(str)
    def auth_success(self, token: str) -> None:
        """Called from auth.html with the session token.
        Python re-verifies the token + HWID with the server — no bypass possible.
        If valid, loads the main UI. If invalid, stays on auth page silently."""
        if not token or len(token) < 16:
            logger.warning("[Auth] auth_success called with empty/short token — ignored")
            return

        def _verify():
            hwid   = _get_hwid()
            saved  = _load_auth()
            # Token passed by JS must match what Python saved
            if saved.get("token") != token:
                return None
            return _api_post("/api/launcher/verify", {"token": token, "hwid": hwid})

        def _done(result):
            if result and result.get("ok"):
                # Persist fresh rank / free_claimed from server
                saved = _load_auth()
                _save_auth(
                    saved.get("token", token),
                    result.get("username", ""),
                    result.get("rank", "free"),
                    result.get("free_claimed"),
                    result.get("rank_expires_at"),
                )
                try:
                    from sff.premium_manifest_lock import apply_rank_transition

                    apply_rank_transition(
                        self._steam_path,
                        result.get("rank", "free"),
                    )
                except Exception as _e:
                    logger.warning("premium_manifest_lock (auth_success): %s", _e)
                try:
                    from sff.premium_manifest_lock import run_startup_check

                    run_startup_check(self._steam_path)
                except Exception:
                    pass
                parent = self.parent()
                if parent and hasattr(parent, "_on_auth_success"):
                    parent._on_auth_success(
                        result.get("username", ""),
                        result.get("rank", "free"),
                    )
            else:
                logger.warning("[Auth] Server rejected token during auth_success — staying on login page")
                # Wipe invalid token so next launch shows login form
                _clear_auth()

        self._run_async(_verify, on_done=_done)

    @pyqtSlot(result=str)
    def get_user_rank(self) -> str:
        """Returns JSON {rank, free_claimed, username, monstre_slots_*, cloud_saves_enabled} from local auth."""
        saved = _load_auth()
        rank = saved.get("rank", "free")
        bucket = _launcher_rank_bucket(rank)
        out = {
            "rank": rank,
            "free_claimed": saved.get("free_claimed"),
            "username": saved.get("username", ""),
            "rank_expires_at": saved.get("rank_expires_at"),
            "cloud_saves_enabled": cloud_saves_launcher_allowed_for_rank(rank),
        }
        if bucket in ("monstre", "pass24h", "triple") and self._steam_path:
            from sff.premium_manifest_lock import paid_distinct_game_count_for_steam

            out["monstre_slots_used"] = paid_distinct_game_count_for_steam(self._steam_path)
            if bucket == "triple":
                out["monstre_slots_max"] = None
            elif bucket == "pass24h":
                out["monstre_slots_max"] = PASS24H_MAX_DISTINCT_INSTALLS
            else:
                out["monstre_slots_max"] = MONSTRE_MAX_DISTINCT_INSTALLS
        else:
            out["monstre_slots_used"] = None
            out["monstre_slots_max"] = None
        return json.dumps(out)

    @pyqtSlot()
    def sync_launcher_profile(self) -> None:
        """Re-vérifie la session sur le serveur (rang, free_claimed) sans recharger toute la webview.
        Met à jour auth.json, la barre utilisateur Qt et émet ``launcher_profile_synced`` pour le JS."""
        def _do():
            try:
                from sff.launcher_session import invalidate_launcher_verify_cache

                invalidate_launcher_verify_cache()
                saved = _load_auth()
                token = saved.get("token", "")
                if not token:
                    return None
                hwid = _get_hwid()
                return _api_post("/api/launcher/verify", {"token": token, "hwid": hwid})
            except Exception as e:
                logger.warning(
                    "[Auth] sync_launcher_profile: %s",
                    redact_sensitive_log_text(str(e)),
                )
                return None

        def _done(result):
            if not result or not result.get("ok"):
                err = (result or {}).get("error") if isinstance(result, dict) else None
                self.launcher_profile_synced.emit(
                    json.dumps({"ok": False, "error": err or "verify_failed"})
                )
                return
            saved = _load_auth()
            tok = saved.get("token", "")
            uname = result.get("username", "") or saved.get("username", "")
            rank = result.get("rank", "free")
            claimed = result.get("free_claimed")
            _save_auth(tok, uname, rank, claimed, result.get("rank_expires_at"))
            try:
                from sff.premium_manifest_lock import apply_rank_transition

                apply_rank_transition(self._steam_path, rank)
            except Exception as _e:
                logger.warning("premium_manifest_lock (sync): %s", _e)
            try:
                from sff.premium_manifest_lock import run_startup_check

                run_startup_check(self._steam_path)
            except Exception:
                pass
            try:
                from sff.premium_manifest_lock import paid_distinct_game_count_for_steam

                b = _launcher_rank_bucket(rank)
                if b in ("monstre", "pass24h", "triple") and self._steam_path:
                    ms_used = paid_distinct_game_count_for_steam(self._steam_path)
                    if b == "triple":
                        ms_max = None
                    elif b == "pass24h":
                        ms_max = PASS24H_MAX_DISTINCT_INSTALLS
                    else:
                        ms_max = MONSTRE_MAX_DISTINCT_INSTALLS
                else:
                    ms_used = ms_max = None
            except Exception:
                ms_used = ms_max = None
            self.launcher_profile_synced.emit(
                json.dumps(
                    {
                        "ok": True,
                        "rank": rank,
                        "free_claimed": claimed,
                        "username": uname,
                        "rank_expires_at": result.get("rank_expires_at"),
                        "cloud_saves_enabled": cloud_saves_launcher_allowed_for_rank(rank),
                        "monstre_slots_used": ms_used,
                        "monstre_slots_max": ms_max,
                    }
                )
            )
            parent = self.parent()
            if parent and getattr(parent, "_authenticated", False):
                if hasattr(parent, "_apply_rank_from_server"):
                    parent._apply_rank_from_server(uname, rank)

        self._run_async(_do, on_done=_done)

    @pyqtSlot(str, result=str)
    def record_free_claim(self, app_id: str) -> str:
        """Records a free-plan game claim on the server.
        Returns JSON {ok, app_id} or {ok:false, error}."""
        saved = _load_auth()
        token = saved.get("token", "")
        if not token:
            return json.dumps({"ok": False, "error": "Non connecté"})

        def _norm_catalog_aid(raw: object) -> str:
            if raw is None:
                return ""
            s = str(raw).strip()
            if not s:
                return ""
            try:
                n = int(float(s))
                if n > 0:
                    return str(n)
            except (TypeError, ValueError):
                pass
            return s

        aid = _norm_catalog_aid(app_id)
        if not aid:
            return json.dumps({"ok": False, "error": "App ID invalide"})
        hwid = _get_hwid()
        result = _api_post(
            "/api/launcher/free-claim",
            {"token": token, "hwid": hwid, "app_id": aid},
        )
        err = str(result.get("error") or "").strip()
        committed = bool(result.get("ok")) or (
            err == "already_claimed" and _norm_catalog_aid(result.get("app_id")) == aid
        )
        if not committed:
            # Réponse réseau perdue alors que le POST a réussi, ou course côté serveur :
            # re-sync via /verify avant d'afficher un échec.
            try:
                from sff.launcher_session import apply_verify_to_local_auth, verify_launcher_session

                vr = verify_launcher_session(force_refresh=True)
                apply_verify_to_local_auth(vr)
                srv = str(vr.get("free_claimed") or "").strip()
                if vr.get("ok") and srv == aid:
                    committed = True
                    result = {"ok": True, "app_id": aid, "note": "synced_from_verify"}
            except Exception:
                logger.debug("record_free_claim verify fallback", exc_info=True)
        if committed:
            fresh = _load_auth()
            _save_auth(
                token,
                fresh.get("username", "") or saved.get("username", ""),
                fresh.get("rank", "free"),
                aid,
                fresh.get("rank_expires_at"),
                free_catalog_pending_install=None,
            )
            if result.get("ok"):
                return json.dumps(result)
            return json.dumps({"ok": True, "app_id": aid, "note": "already_claimed_same_app"})
        if aid in _LAUNCHER_FREE_CATALOG_IDS and "non autorisé" in err.lower():
            logger.warning(
                "free-claim refusé pour l'app catalogue %s (%s) : l'API distante n'autorise pas cet ID — "
                "vérifier que le bot en production expose la même liste que _LAUNCHER_FREE_CATALOG_IDS.",
                aid,
                err,
            )
        return json.dumps(result)

    @pyqtSlot(str)
    def begin_free_catalog_install(self, app_id: str) -> None:
        """Prépare l'installation catalogue FREE (réseau sur worker → signal free_catalog_begin_result)."""
        aid = str(app_id).strip()

        def _do():
            return _begin_free_catalog_install_impl(aid)

        def _done(res):
            if res is None:
                res = json.dumps({"ok": False, "error": "Échec interne"})
            self.free_catalog_begin_result.emit(str(res))

        def _err(_msg):
            self.free_catalog_begin_result.emit(
                json.dumps(
                    {
                        "ok": False,
                        "error": "Erreur réseau ou serveur (vérifie ta connexion).",
                    }
                )
            )

        self._run_async(_do, on_done=_done, on_error=_err)

    @pyqtSlot(str, result=str)
    def cancel_free_catalog_install(self, app_id: str) -> str:
        """Échec installation : supprime le pending local, ou tente free-claim-revert si ancienne logique."""
        saved = _load_auth()
        token = (saved.get("token") or "").strip()
        if not token:
            return json.dumps({"ok": False, "error": "Non connecté"})
        aid = str(app_id).strip()
        rank = saved.get("rank", "free")
        pending = saved.get("free_catalog_pending_install")
        if pending is not None and str(pending).strip() == aid:
            _save_auth(
                token,
                saved.get("username", ""),
                rank,
                saved.get("free_claimed"),
                saved.get("rank_expires_at"),
                free_catalog_pending_install=None,
            )
            return json.dumps({"ok": True, "cleared": "pending"})
        if str(saved.get("free_claimed") or "").strip() == aid:
            return self.revert_free_claim(aid)
        _save_auth(
            token,
            saved.get("username", ""),
            rank,
            saved.get("free_claimed"),
            saved.get("rank_expires_at"),
            free_catalog_pending_install=None,
        )
        return json.dumps({"ok": True, "cleared": "noop"})

    @pyqtSlot(str, result=str)
    def revert_free_claim(self, app_id: str) -> str:
        """Après échec du téléchargement catalogue FREE : retire la réclamation serveur + locale.
        Retourne JSON {ok, reverted?, error?}."""
        saved = _load_auth()
        token = saved.get("token", "")
        if not token:
            return json.dumps({"ok": False, "error": "Non connecté"})
        hwid = _get_hwid()
        result = _api_post(
            "/api/launcher/free-claim-revert",
            {
                "token": token,
                "hwid": hwid,
                "app_id": str(app_id).strip(),
            },
        )
        if result.get("ok") and result.get("reverted"):
            _save_auth(
                token,
                saved.get("username", ""),
                saved.get("rank", "free"),
                None,
                saved.get("rank_expires_at"),
                free_catalog_pending_install=None,
            )
        return json.dumps(result)

    @pyqtSlot(result=str)
    def discord_avis_url(self) -> str:
        """URL vers le salon #avis (deep-link si SLIMEDEALS_DISCORD_GUILD_ID est défini)."""
        if _SLIMEDEALS_DISCORD_GUILD_ID.isdigit():
            return (
                f"https://discord.com/channels/{_SLIMEDEALS_DISCORD_GUILD_ID}/"
                f"{_DISCORD_AVIS_CHANNEL_ID}"
            )
        return "https://discord.gg/c2pRJKjvgE"

    @pyqtSlot(result=str)
    def discord_free_subscribe_url(self) -> str:
        """URL salon Discord pour un abonnement gratuit (procédure communautaire)."""
        if _SLIMEDEALS_DISCORD_GUILD_ID.isdigit():
            return (
                f"https://discord.com/channels/{_SLIMEDEALS_DISCORD_GUILD_ID}/"
                f"{_DISCORD_FREE_SUB_CHANNEL_ID}"
            )
        return "https://discord.gg/c2pRJKjvgE"

    # ── ASYNC slots — dispatch to QThread ────────────────────────

    @pyqtSlot(str)
    def lookup_ttc_game(self, app_id):
        """Récupère les infos jeu pour l’onglet Télécharger (métadonnées catalogue).
        Émet ttc_game_info avec un JSON contenant name, header_image, available, dlc_count."""
        def _do():
            from sff.launcher_session import apply_verify_to_local_auth, verify_launcher_session
            from sff.lua.endpoints import steam_store_dlc_count, ttc_get_game_info

            auth = _load_auth()
            if (auth.get("token") or "").strip():
                vr = verify_launcher_session(force_refresh=True)
                apply_verify_to_local_auth(vr)
                if not vr.get("ok"):
                    return {
                        "app_id": app_id,
                        "available": False,
                        "name": f"App {app_id}",
                        "header_image": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg",
                        "dlc_count": None,
                    }
            dlc_n = steam_store_dlc_count(str(app_id))
            info = ttc_get_game_info(str(app_id))
            if info is None:
                return {
                    "app_id": app_id,
                    "available": False,
                    "name": f"App {app_id}",
                    "header_image": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg",
                    "dlc_count": dlc_n,
                }
            data = info.get("data", info)
            common = data.get("common", {}) if isinstance(data, dict) else {}
            name = (common.get("name") or data.get("name") or
                    info.get("name") or f"App {app_id}")
            return {
                "app_id": app_id,
                "available": True,
                "name": name,
                "header_image": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg",
                "dlc_count": dlc_n,
            }

        def _on_done(result):
            self.ttc_game_info.emit(json.dumps(result))

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str, int, int, str)
    def search_games(self, query, offset, per_page, sort_by='updated'):
        """Search the Hubcap store. Falls back to Steam catalog on failure. Emits search_results signal."""
        def _do():
            _hubcap_error = False
            client = self._get_store_client()
            if client:
                try:
                    if query:
                        # Fetch large batch via /library?search= for client-side pagination
                        all_games = client.get_library(limit=200, offset=0, search=query).games
                        q_words = query.lower().split()
                        # Name keyword + word filter (all query words must appear in name)
                        filtered = []
                        for g in all_games:
                            name_lc = g.name.lower()
                            if any(kw in name_lc for kw in _NONGAME_NAME_KW):
                                continue
                            if q_words and not all(w in name_lc for w in q_words):
                                continue
                            filtered.append(g)
                        # Fetch images + types for ALL filtered items before pagination
                        all_ids = [g.app_id for g in filtered]
                        image_urls, type_map = _fetch_steam_image_urls(all_ids)
                        # Type filter — must happen before total so pagination is accurate
                        final = [g for g in filtered if type_map.get(g.app_id) not in _NON_GAME_TYPES]
                        total = len(final)
                        page_games = final[offset: offset + per_page]
                        games = [{
                            "app_id": g.app_id,
                            "name": g.name,
                            "last_updated": g.last_updated,
                            "status": g.status,
                            "size": g.size,
                            "image_url": image_urls.get(g.app_id),
                        } for g in page_games]
                        return {"games": games, "total": total, "fallback": False}
                    else:
                        # Browse: /library endpoint with server-side pagination
                        result = client.get_library(limit=per_page, offset=offset, sort_by=sort_by or 'updated')
                        app_ids = [g.app_id for g in result.games]
                        image_urls, type_map = _fetch_steam_image_urls(app_ids)
                        games = []
                        for g in result.games:
                            if type_map.get(g.app_id) in _NON_GAME_TYPES:
                                continue
                            name_lc = g.name.lower()
                            if any(kw in name_lc for kw in _NONGAME_NAME_KW):
                                continue
                            games.append({
                                "app_id": g.app_id,
                                "name": g.name,
                                "last_updated": g.last_updated,
                                "status": g.status,
                                "size": g.size,
                                "image_url": image_urls.get(g.app_id),
                            })
                        return {"games": games, "total": result.total, "fallback": False}
                except Exception as e:
                    logger.warning("Hubcap search failed, falling back to Steam catalog: %s", e)
                    _hubcap_error = True
            result = _search_steam_catalog(query, offset, per_page)
            if _hubcap_error:
                result['hubcap_error'] = True
            return result

        def _on_done(data):
            if data:
                self.search_results.emit(json.dumps(data))
            else:
                self.search_results.emit(json.dumps({"games": [], "total": 0, "fallback": True}))

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str, bool)
    def fetch_depot_history(self, app_id, force_refresh):
        """Fetch depot/manifest history for a game. Emits depot_history_results."""
        def _progress(msg):
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": msg, "progress": -1
            }))

        def _do():
            from sff.manifest.depot_history import get_depots_for_app, group_by_version, get_build_ids
            depots = get_depots_for_app(app_id, force_refresh=force_refresh, progress_cb=_progress)
            build_ids = get_build_ids(app_id)
            groups = group_by_version(depots, build_ids=build_ids)
            result = []
            for group in groups:
                result.append({
                    "label": group.label,
                    "date": group.date,
                    "branch": group.branch,
                    "source": group.source,
                    "build_id": group.build_id,
                    "entries": [
                        {"depot_id": str(d), "manifest_id": str(m)}
                        for d, m in group.entries
                    ],
                })
            return result

        def _on_done(data):
            self.depot_history_results.emit(json.dumps(data or []))

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str)
    def download_game_fastest(self, app_id):
        """Platform-aware fastest download (auto-selects source).
        Windows: prompt-free 11-step pipeline mirroring process_lua_full().
        Linux: auto-selects latest manifests, wraps process_from_store().
        Emits download_progress + task_finished signals."""
        self._log_ui(f"[Slot] download_game_fastest({app_id!r}) — lancement thread worker…")

        def _do():
            self._log_ui(f"download_game_fastest : démarrage worker app_id={app_id!r}")
            from sff.launcher_session import apply_verify_to_local_auth, verify_launcher_session

            vr = verify_launcher_session(force_refresh=True)
            apply_verify_to_local_auth(vr)
            if not vr.get("ok"):
                err = (vr.get("error") or "Session invalide").strip()
                self._log_ui(f"Refus (verification compte) : {err}")
                self._emit_task_result(
                    "download_fastest",
                    False,
                    "Connexion ou PC non autorise pour ce compte. Reconnecte-toi ou contacte le support.",
                    app_id=str(app_id),
                )
                return False
            allow, deny_msg = _launcher_free_catalog_download_allowed(str(app_id))
            if not allow:
                self._log_ui(f"Refus (plan FREE / catalogue) : {deny_msg}")
                self._emit_task_result(
                    "download_fastest",
                    False,
                    deny_msg,
                    app_id=str(app_id),
                )
                return False
            from sff.premium_manifest_lock import monstre_new_install_allowed

            m_ok, m_deny = monstre_new_install_allowed(self._steam_path, str(app_id))
            if not m_ok:
                self._log_ui(f"Refus (plan Monstre / quota jeux) : {m_deny}")
                self._emit_task_result(
                    "download_fastest",
                    False,
                    m_deny,
                    app_id=str(app_id),
                )
                return False
            self._log_ui("Contrôle catalogue / plan : OK — lancement pipeline (Starting → 0 %)")
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Starting", "progress": 0
            }))

            if sys.platform == "win32":
                self._log_ui("Windows : pipeline _run_windows_fastest (source auto)")
                return self._run_windows_fastest(app_id)
            self._log_ui("Linux : _run_linux_fastest (manifests → process_from_store)")
            return self._run_linux_fastest(app_id)

        def _on_done(result):
            success = (result is True) or (result == True)
            self._log_ui(
                f"download_game_fastest terminé : success={success!r} result={result!r} app_id={app_id}"
            )
            self._emit_task_result(
                "download_fastest",
                success,
                (
                    f"Installation terminée (App {app_id})"
                    if success
                    else f"Échec de l'installation (App {app_id})"
                ),
                app_id=app_id,
            )
            if success and sys.platform == "win32":
                self._log_ui(f"File d’attente : notification d’activité Discord pour le jeu {app_id}")
                self.request_notify_gen.emit(str(app_id))

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str, str, str, str)
    def download_game_with_source(self, app_id, source, request_update='0', local_lua_path=''):
        """Téléchargement rapide : catalogue SlimeDeals (Ryuu secure_download) ou fichier Lua local.

        ``local_lua_path`` : obligatoire si ``source == 'local'`` (Windows : pipeline rapide ;
        Linux/macOS : ``process_lua_full``). Émet download_progress + task_finished.
        """
        self._log_ui(
            f"[Slot] download_game_with_source(app_id={app_id!r}, source={_log_download_source(source)!r}, "
            f"request_update={request_update!r}) — lancement thread worker…"
        )

        def _do():
            self._log_ui(
                f"download_game_with_source : worker démarré app_id={app_id!r} source={_log_download_source(source)!r} "
                f"request_update={request_update!r}"
            )
            from sff.launcher_session import apply_verify_to_local_auth, verify_launcher_session

            vr = verify_launcher_session(force_refresh=True)
            apply_verify_to_local_auth(vr)
            if not vr.get("ok"):
                err = (vr.get("error") or "Session invalide").strip()
                self._log_ui(f"Refus (verification compte) : {err}")
                self._emit_task_result(
                    "download_fastest",
                    False,
                    "Connexion ou PC non autorise pour ce compte. Reconnecte-toi ou contacte le support.",
                    app_id=str(app_id),
                )
                return False
            allow, deny_msg = _launcher_free_catalog_download_allowed(str(app_id))
            if not allow:
                self._log_ui(f"Refus (plan FREE / catalogue) : {deny_msg}")
                self._emit_task_result(
                    "download_fastest",
                    False,
                    deny_msg,
                    app_id=str(app_id),
                )
                return False
            from sff.premium_manifest_lock import monstre_new_install_allowed

            m_ok, m_deny = monstre_new_install_allowed(self._steam_path, str(app_id))
            if not m_ok:
                self._log_ui(f"Refus (plan Monstre / quota jeux) : {m_deny}")
                self._emit_task_result(
                    "download_fastest",
                    False,
                    m_deny,
                    app_id=str(app_id),
                )
                return False
            self._log_ui("Contrôle catalogue / plan : OK — lancement pipeline (Starting → 0 %)")
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Starting", "progress": 0
            }))
            src_key = str(source or "").strip().lower()
            if sys.platform == "win32":
                self._log_ui(
                    f"Windows : _run_windows_fastest (request_update={(request_update == '1')!r})"
                )
                return self._run_windows_fastest(
                    app_id,
                    source=source,
                    request_update=(request_update == '1'),
                    local_lua_path=str(local_lua_path or ""),
                )
            if src_key == "local":
                lp = str(local_lua_path or "").strip()
                if not lp:
                    self._log_ui("Échec : fichier local non sélectionné.")
                    return False
                from sff.structs import MainReturnCode

                self._log_ui(f"Linux/macOS : traitement Lua local {lp!r} (process_lua_full)")
                rc = self._ui.process_lua_full(file=lp)
                return rc == MainReturnCode.LOOP
            self._log_ui("Linux : _run_linux_fastest")
            return self._run_linux_fastest(app_id)

        def _on_done(result):
            success = (result is True) or (result == True)
            self._log_ui(
                f"download_game_with_source terminé : success={success!r} result={result!r} app_id={app_id}"
            )
            self._emit_task_result(
                "download_fastest",
                success,
                (
                    f"Installation terminée (App {app_id})"
                    if success
                    else f"Échec de l'installation (App {app_id})"
                ),
                app_id=app_id,
            )
            if success and sys.platform == "win32":
                self._log_ui(f"File d’attente : notification d’activité Discord pour le jeu {app_id}")
                self.request_notify_gen.emit(str(app_id))

        self._run_async(_do, on_done=_on_done)

    def _run_windows_fastest(self, app_id, source='', request_update=False, local_lua_path=''):
        """Prompt-free 11-step pipeline for Windows."""
        try:
            from sff.lua.choices import download_lua_direct
            from sff.lua.manager import parse_lua_contents
            from sff.lua.writer import ACFWriter, ConfigVDFWriter
            from sff.steam_tools_compat import install_lua_to_steam
            from sff.storage.vdf import ensure_library_has_app
            from sff.registry_access import set_stats_and_achievements
            from sff.structs import LuaEndpoint

            steam_path = self._steam_path
            lib_path = Path(self._active_library) if self._active_library else steam_path
            src_key = str(source or "").strip().lower()
            self._log_ui(
                f"_run_windows_fastest : steam_path={steam_path} lib_path={lib_path} "
                f"source={_log_download_source(source)!r} request_update={request_update}"
            )

            # Step 1: download lua
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Downloading Lua", "progress": 10
            }))
            lua_path = None
            local_path_raw = str(local_lua_path or "").strip()
            if src_key == "local":
                if not local_path_raw:
                    self._log_ui("Échec : source locale sans chemin de fichier.")
                    return False
                lp = Path(local_path_raw)
                if not lp.is_file():
                    self._log_ui(f"Échec : fichier Lua local introuvable : {local_path_raw!r}")
                    return False
                if lp.suffix.lower() == ".zip":
                    from sff.zip import read_lua_from_zip

                    _dc = (steam_path / "depotcache") if steam_path else None
                    lua_text = read_lua_from_zip(lp, decode=True, depotcache=_dc)
                    if not lua_text:
                        self._log_ui("Échec : aucun .lua lisible dans l’archive ZIP.")
                        return False
                    _out_dir = steam_path / "config" if steam_path else Path(".")
                    _out_dir.mkdir(parents=True, exist_ok=True)
                    lua_path = _out_dir / f"{app_id}_local.lua"
                    lua_path.write_text(lua_text, encoding="utf-8")
                else:
                    lua_path = lp
            else:
                # Catalogue SlimeDeals uniquement (pas de clés Hubcap / OurEveryday / Ryuu).
                selected_source = LuaEndpoint.TWENTYTWOCLOUD
                self._log_ui(
                    f"Téléchargement Lua ({getattr(selected_source, 'value', str(selected_source))})…"
                )
                lua_path = download_lua_direct(
                    dest=steam_path / "config",
                    app_id=app_id,
                    source=selected_source,
                    steam_path=steam_path,
                    request_update=request_update,
                )
            if not lua_path:
                self._log_ui(
                    "Échec : download_lua_direct n’a renvoyé aucun chemin (réseau, source, ou jeu indisponible)."
                )
                return False

            self._log_ui(f"Lua obtenu : {lua_path}")
            saved_lua = launcher_saved_lua_dir()
            saved_lua.mkdir(parents=True, exist_ok=True)
            backup_target = saved_lua / f"{app_id}.lua"
            try:
                if lua_path != backup_target:
                    shutil.copyfile(lua_path, backup_target)
            except Exception:
                pass

            # Step 2: parse lua
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Parsing Lua", "progress": 20
            }))
            lua_contents = lua_path.read_text(encoding="utf-8", errors="replace")
            parsed = parse_lua_contents(lua_contents, lua_path)
            if not parsed:
                self._log_ui("Échec : parse_lua_contents → None (fichier Lua invalide ou incomplet).")
                return False

            # Step 3: set stats and achievements (Windows only)
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Setting up achievements", "progress": 30
            }))
            try:
                set_stats_and_achievements(app_id)
            except Exception as e:
                logger.warning("set_stats_and_achievements failed: %s", e)

            # Step 4: add to AppList
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Adding to AppList", "progress": 40
            }))
            if hasattr(self._ui, 'app_list_man') and self._ui.app_list_man:
                try:
                    self._ui.app_list_man.add_ids(parsed)
                except Exception as e:
                    logger.warning("add_ids failed: %s", e)

            # Step 5: write decryption keys
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Writing decryption keys", "progress": 50
            }))
            config_writer = ConfigVDFWriter(steam_path)
            try:
                config_writer.add_decryption_keys_to_config(parsed)
            except Exception as e:
                logger.warning("add_decryption_keys failed: %s", e)

            # Step 6: backup & install lua to Steam plugin dir
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Installing Lua to Steam", "progress": 60
            }))
            try:
                install_lua_to_steam(steam_path, app_id, lua_path)
            except Exception as e:
                logger.warning("install_lua_to_steam failed: %s", e)

            # Step 7: write ACF + patch workshop ACF
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Writing ACF files", "progress": 70
            }))
            acf_writer = ACFWriter(lib_path)
            try:
                acf_writer.write_acf(parsed)
            except Exception as e:
                logger.warning("write_acf failed: %s", e)
            try:
                if hasattr(acf_writer, 'patch_workshop_acf'):
                    acf_writer.patch_workshop_acf(parsed)
            except Exception as e:
                logger.warning("patch_workshop_acf failed: %s", e)

            # Step 8: register in libraryfolders.vdf
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Registering in library", "progress": 80
            }))
            try:
                ensure_library_has_app(steam_path, lib_path, app_id)
            except Exception as e:
                logger.warning("ensure_library_has_app failed: %s", e)

            # Step 9: download manifests
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Downloading manifests", "progress": 85
            }))
            _manifest_paths = []
            try:
                from sff.manifest.downloader import ManifestDownloader
                from sff.steam_client import create_provider_for_current_thread
                from sff.storage.settings import get_setting as _get_setting
                from sff.structs import Settings as _Settings
                _provider = create_provider_for_current_thread()
                _dl = ManifestDownloader(_provider, steam_path)
                _use_parallel = _get_setting(_Settings.USE_PARALLEL_DOWNLOADS)
                if _use_parallel:
                    _manifest_paths = _dl.download_manifests_parallel(parsed, auto_manifest=True) or []
                else:
                    _manifest_paths = _dl.download_manifests(parsed, auto_manifest=True) or []
            except Exception as e:
                logger.warning("download_manifests failed: %s", e)

            # Step 10: track in download manager
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Updating download tracker", "progress": 95
            }))
            if hasattr(self._ui, 'download_manager') and self._ui.download_manager:
                try:
                    dl_id = self._ui.download_manager.track_external(
                        app_id=app_id,
                        game_name=parsed.name if hasattr(parsed, 'name') else f"App {app_id}",
                    )
                    self._ui.download_manager.complete_external(dl_id, success=True)
                except Exception as e:
                    logger.warning("download tracking failed: %s", e)

            # Step 11: done
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Complete", "progress": 100
            }))
            self._log_ui("Pipeline Windows : succès (100 %) — manifests / bibliothèque mis à jour.")
            try:
                from sff.premium_manifest_lock import maybe_register_paid_install

                maybe_register_paid_install(steam_path, parsed, manifest_paths=_manifest_paths)
            except Exception as _e:
                logger.warning("premium_manifest_lock (register): %s", _e)
            return True

        except Exception as e:
            logger.exception("Windows fastest download failed: %s", e)
            self._log_ui(f"Exception pipeline Windows : {e!r}")
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": f"Error: {e}", "progress": 0
            }))
            return False

    def _run_linux_fastest(self, app_id):
        """Auto-selects latest manifests, wraps process_from_store()."""
        try:
            from sff.manifest.depot_history import get_depots_for_app

            self._log_ui(f"_run_linux_fastest : récupération dépôts pour app_id={app_id}")
            # Auto-select latest manifest for each depot
            depots = get_depots_for_app(app_id)
            manifest_override = {}
            for depot_id, entries in depots.items():
                if entries:
                    manifest_override[str(depot_id)] = str(entries[0].manifest_id)

            if not manifest_override:
                self._log_ui(
                    "Linux : aucun manifest automatique — get_depots_for_app vide ou sans entrées."
                )
                return False

            self._log_ui(f"Linux : lancement process_from_store ({len(manifest_override)} dépôt(s))…")
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Downloading via DepotDownloader", "progress": 30
            }))

            self._ui.process_from_store(
                app_id=app_id,
                manifest_override=manifest_override,
                use_hubcap=False,
            )

            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Complete", "progress": 100
            }))
            self._log_ui("Linux : process_from_store terminé (100 %).")
            return True

        except Exception as e:
            logger.exception("Linux fastest download failed: %s", e)
            self._log_ui(f"Exception _run_linux_fastest : {e!r}")
            return False

    @pyqtSlot(str, str)
    def download_game_version(self, app_id, manifest_override_json):
        """Download specific version via process_from_store().
        Emits download_progress + task_finished signals."""
        self._log_ui(f"[Slot] download_game_version app_id={app_id!r} — lancement worker…")

        def _do():
            self._log_ui("download_game_version : worker démarré")
            try:
                manifest_override = json.loads(manifest_override_json)
            except (json.JSONDecodeError, TypeError) as ex:
                self._log_ui(f"JSON manifestes invalide : {ex}")
                return False

            if not manifest_override:
                self._log_ui("Manifestes vides après parse — abandon.")
                return False

            self._log_ui(f"Téléchargement version spécifique ({len(manifest_override)} dépôt(s))…")
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Starting version download", "progress": 10
            }))

            if self._active_library:
                # Pre-set library to avoid prompt
                pass  # gui_prompts.py will handle if needed

            self._ui.process_from_store(
                app_id=app_id,
                manifest_override=manifest_override,
                use_hubcap=False,
            )

            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Complete", "progress": 100
            }))
            self._log_ui("download_game_version : process_from_store terminé → True")
            return True

        def _on_done(result):
            success = (result is True) or (result == True)
            self._log_ui(
                f"download_game_version terminé : success={success!r} result={result!r} app_id={app_id}"
            )
            self._emit_task_result(
                "download_version",
                success,
                f"Version download {'completed' if success else 'failed'} for App {app_id}",
                app_id=app_id,
            )

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str, str)
    def run_game_action(self, app_id, action):
        """Routes to backend action (crack, dlc_check, etc.).
        Game-specific actions need an ACFInfo; non-game actions call ui methods directly.
        Emits task_finished signal."""
        # SteamAutoCrack must run on the main thread — it uses _start_worker internally.
        # Calling it from _run_async (background thread) causes immediate 'completed'
        # and a freeze/deadlock on the second click.
        if action == "steam_auto":
            from sff.steamauto import get_steamauto_cli_path
            if get_steamauto_cli_path() is None:
                self._emit_task_result("steam_auto", False, "SteamAutoCrack CLI not found")
                return
            acf = self._resolve_acf(app_id)
            if acf is None:
                self._emit_task_result("steam_auto", False, "No game found for the selected App ID")
                return
            parent = self.parent()
            if parent and hasattr(parent, '_run_steam_auto_with_acf'):
                parent._run_steam_auto_with_acf(acf)
            return

        def _do():
            from sff.structs import MainMenu

            if action == "download_games":
                self._log_ui(
                    f"run_game_action(download_games) app_id={app_id!r} — pipeline Lua interactif…"
                )

            # Non-game-specific actions — call ui methods directly
            non_game_actions = {
                "download_games": lambda: self._ui.process_lua_full(),
                "download_manifests": lambda: self._ui.process_lua_minimal(),
                "recent_lua": lambda: self._ui.recent_files_menu(),
                "update_manifests": lambda: self._ui.update_all_manifests(),
                "applist_menu": lambda: self._ui.applist_menu(),
                "offline_fix": lambda: self._ui.offline_fix_menu(),
                "remove_game": lambda: self._ui.remove_game_menu(),
                "context_menu": lambda: self._ui.manage_context_menu(),
                "check_updates": lambda: self._ui.check_updates(self._ui.os_type),
                "scan_library": lambda: self._ui.scan_library_menu(),
                "analytics": lambda: self._ui.analytics_dashboard_menu(),
            }

            if action in non_game_actions:
                try:
                    non_game_actions[action]()
                    return None
                except Exception as e:
                    return str(e)

            # Mute toggle — special handling, not a MainMenu choice
            if action == "mute_toggle":
                try:
                    parent = self.parent()
                    if parent and hasattr(parent, '_toggle_mute'):
                        parent._toggle_mute()
                    elif self._ui and hasattr(self._ui, 'midi_player') and self._ui.midi_player:
                        self._ui.midi_player.set_muted(not self._ui.midi_player._muted)
                    return None
                except Exception as e:
                    return str(e)

            # Game-specific actions — need an ACFInfo from app_id
            game_action_map = {
                "crack": MainMenu.CRACK_GAME,
                "steamstub": MainMenu.REMOVE_DRM,
                "dlc_check": MainMenu.DLC_CHECK,
                "workshop": MainMenu.DL_WORKSHOP_ITEM,
                "multiplayer": MainMenu.MULTIPLAYER_FIX,
                "community_fixes": MainMenu.CRACK_FIX,
                "hv_fix": MainMenu.HV_FIX,
                "achievements": MainMenu.DL_USER_GAME_STATS,
                "dlc_unlockers": MainMenu.MANAGE_DLC_UNLOCKERS,
                "check_mod_updates": MainMenu.CHECK_MOD_UPDATES,
            }

            menu_choice = game_action_map.get(action)
            if menu_choice is None:
                return f"Unknown action: {action}"

            # Build ACFInfo from app_id
            acf = self._resolve_acf(app_id)
            if acf is None:
                return f"No game found for App ID: {app_id}"

            if action == "multiplayer":
                saved = _load_auth()
                if not triple_exclusive_tools_allowed_for_rank(saved.get("rank")):
                    self._emit_task_result(
                        "multiplayer",
                        False,
                        "L'option ONLINE FIX est reservee au plan Triple Monstre. Offres : slimedeals.fr/#tarifs — salon #avis sur Discord.",
                        free_plan_denied=True,
                    )
                    return "__noop__"

            try:
                ret = self._ui.run_game_action_with_selection(menu_choice, acf)
                if (
                    action == "multiplayer"
                    and isinstance(ret, tuple)
                    and len(ret) == 2
                    and isinstance(ret[0], str)
                    and ret[0] in ("ok", "fail", "cancelled")
                ):
                    return ret
                return None
            except Exception as e:
                return str(e)

        def _on_done(result):
            if result == "__noop__":
                return
            if (
                isinstance(result, tuple)
                and len(result) == 2
                and isinstance(result[0], str)
                and result[0] in ("ok", "fail", "cancelled")
                and action == "multiplayer"
            ):
                status, gname = result
                g = (gname or "").strip() or "ce jeu"
                if status == "ok":
                    self._emit_task_result(
                        action,
                        True,
                        f"Mod online ajouté sur « {g} ».",
                        game_name=g,
                    )
                elif status == "cancelled":
                    self._emit_task_result(
                        action,
                        False,
                        f"Opération multijoueur annulée. (Jeu : « {g} »)",
                        game_name=g,
                        cancelled=True,
                    )
                else:
                    self._emit_task_result(
                        action,
                        False,
                        f"Mode online introuvable pour « {g} ».",
                        game_name=g,
                    )
                return
            if result:
                self._emit_task_result(action, False, str(result))
            else:
                self._emit_task_result(action, True, f"Action '{action}' completed")

        self._run_async(_do, on_done=_on_done)

    def _resolve_acf(self, app_id):
        """Find ACFInfo for a given app_id by scanning Steam libraries."""
        if not app_id:
            return None
        try:
            from sff.game_specific import ACFInfo
            from sff.storage.vdf import get_steam_libs, vdf_load
            libs = get_steam_libs(self._steam_path) if self._steam_path else []
            for lib in libs:
                steamapps = lib / "steamapps"
                if not steamapps.exists():
                    continue
                acf_path = steamapps / f"appmanifest_{app_id}.acf"
                if acf_path.exists():
                    data = vdf_load(acf_path)
                    state = data.get("AppState", {})
                    installdir = state.get("installdir", "")
                    game_path = steamapps / "common" / installdir
                    return ACFInfo(str(app_id), game_path)
        except Exception as e:
            logger.warning("_resolve_acf failed: %s", e)
        return None

    @pyqtSlot(str)
    def fix_game(self, config_json):
        """Apply emulator fix to a game. Emits task_finished."""
        def _do():
            try:
                config = json.loads(config_json)
                from sff.fix_game.service import FixGameService
                raw_id = config.get("app_id", "")
                app_id = int(raw_id) if str(raw_id).strip().isdigit() else 0
                svc = FixGameService()
                success = svc.fix_game(
                    app_id=app_id,
                    game_dir=config.get("game_path", ""),
                    emu_mode=config.get("emu_mode", "regular"),
                    skip_steamstub=not config.get("unpack_steamstub", True),
                    steamless_experimental=config.get("use_experimental_steamless", True),
                    skip_goldberg_update=not config.get("goldberg_update", False),
                    create_launch_bat=config.get("create_launch_bat", False),
                    player_name=config.get("username") or "Player",
                    steam_id=config.get("steam_id") or "76561198001737783",
                    avatar_path=config.get("avatar_path") or None,
                    simple_settings=config.get("simple_settings", False),
                    gse_auth_mode=config.get("gse_auth_mode", "anonymous"),
                    gse_username=config.get("gse_username", ""),
                    gse_password=config.get("gse_password", ""),
                )
                return success
            except Exception as e:
                logger.exception("fix_game failed: %s", e)
                return str(e)

        def _on_done(result):
            if result is True:
                self._emit_task_result("fix_game", True, "Game fix applied successfully")
            else:
                self._emit_task_result("fix_game", False, str(result) if result else "Fix failed")

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str)
    def revert_game(self, game_path):
        """Revert emulator changes."""
        def _do():
            try:
                from sff.gui.fix_game_tab import FixGameService
                FixGameService.revert(game_path)
                return True
            except Exception as e:
                return str(e)

        def _on_done(result):
            if result is True:
                self._emit_task_result("revert_game", True, "Changes reverted")
            else:
                self._emit_task_result("revert_game", False, str(result))

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str)
    def generate_gbe_token(self, config_json):
        """Generate GBE token files."""
        def _do():
            config = json.loads(config_json)
            api_key = config.get("api_key", "").strip()
            app_id_str = str(config.get("app_id", "")).strip()
            output_dir = config.get("output_dir", "").strip()
            if not api_key:
                return (False, "No Steam Web API key provided.")
            if not app_id_str.isdigit():
                return (False, "App ID must be a number.")
            if not output_dir:
                return (False, "No output directory provided.")
            from sff.tools.gbe_token_generator import GBETokenGenerator
            log_lines = []
            def _log(msg):
                log_lines.append(msg)
                self.log_message.emit(msg)
            gen = GBETokenGenerator(steam_web_api_key=api_key)
            success = gen.generate(int(app_id_str), output_dir, log_func=_log)
            if success:
                try:
                    from sff.storage.settings import set_setting
                    from sff.structs import Settings
                    set_setting(Settings.STEAM_WEB_API_KEY, api_key)
                except Exception:
                    pass
            return (success, "\n".join(log_lines))

        def _on_done(result):
            if isinstance(result, tuple):
                ok, log_text = result
                msg = "GBE config generated successfully" if ok else log_text.split("\n")[-1]
                self._emit_task_result("generate_gbe_token", ok, msg, log=log_text)
            else:
                self._emit_task_result("generate_gbe_token", False, "Generation failed")

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str, str)
    def scan_cloud_games(self, steam_path, steam32_id):
        """Scan userdata for cloud saves."""
        if not _cloud_saves_feature_allowed():
            self._emit_task_result(
                "scan_cloud_games",
                False,
                _CLOUD_SAVES_DENIED_MSG,
                games=[],
                scan_hint="",
            )
            return

        def _do():
            from sff.cloud_saves import CloudSaves, normalize_steam_userdata_folder_id, scan_hint_for_empty_userdata
            sid = normalize_steam_userdata_folder_id(str(steam32_id or "").strip())
            pairs = CloudSaves.list_steam_games(steam_path, sid)
            games = []
            for app_id, game_name in pairs:
                base = Path(steam_path) / "userdata" / sid / str(app_id)
                remote_dir = base / "remote"
                local_dir = base / "local"
                size = 0
                try:
                    if remote_dir.exists():
                        size = sum(f.stat().st_size for f in remote_dir.rglob("*") if f.is_file())
                    elif local_dir.exists():
                        size = sum(f.stat().st_size for f in local_dir.rglob("*") if f.is_file())
                except Exception:
                    pass
                games.append({
                    "app_id": str(app_id),
                    "name": game_name,
                    "size": _format_size(size),
                })
            hint = ""
            if not games:
                hint = scan_hint_for_empty_userdata(str(steam_path).strip(), sid)
            return (games, hint)

        def _on_done(result):
            games, hint = [], ""
            if isinstance(result, tuple) and len(result) == 2:
                games, hint = result[0] or [], (result[1] or "")
            self._emit_task_result("scan_cloud_games", True, "", games=games, scan_hint=hint)

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str)
    def backup_cloud_save(self, config_json):
        """Backup cloud saves for a game."""
        if not _cloud_saves_feature_allowed():
            self._emit_task_result("backup_cloud_save", False, _CLOUD_SAVES_DENIED_MSG, log="")
            return

        def _do():
            config = json.loads(config_json)
            app_id = str(config.get("app_id", "")).strip()
            dest_path = config.get("dest_path", "").strip()
            steam_path = config.get("steam_path", "").strip()
            steam32_id = str(config.get("steam32_id", "")).strip()
            game_name = config.get("game_name", f"App {app_id}").strip() or f"App {app_id}"
            if not app_id or not dest_path or not steam_path or not steam32_id:
                return (False, "", "Missing required parameters for backup")
            from sff.cloud_saves import CloudSaves
            log_lines = []
            result = CloudSaves().backup_steam_save(
                steam_path, steam32_id, int(app_id), game_name, dest_path,
                log_func=log_lines.append,
            )
            log_text = "\n".join(log_lines)
            if result:
                return (True, log_text, f"Saves backed up for {game_name}")
            return (False, log_text, "Backup failed — check log")

        def _on_done(result):
            if isinstance(result, tuple):
                ok, log_text, msg = result
                self._emit_task_result("backup_cloud_save", ok, msg, log=log_text)
            else:
                self._emit_task_result("backup_cloud_save", False, "Backup failed")

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str)
    def restore_cloud_save(self, config_json):
        """Restore cloud saves from backup."""
        if not _cloud_saves_feature_allowed():
            self._emit_task_result("restore_cloud_save", False, _CLOUD_SAVES_DENIED_MSG, log="")
            return

        def _do():
            config = json.loads(config_json)
            backup_path = config.get("backup_path", "").strip()
            app_id = str(config.get("app_id", "")).strip()
            steam_path = config.get("steam_path", "").strip()
            steam32_id = str(config.get("steam32_id", "")).strip()
            if not backup_path or not app_id or not steam_path or not steam32_id:
                return (False, "", "Missing required parameters for restore")
            from sff.cloud_saves import CloudSaves
            log_lines = []
            ok = CloudSaves().restore_steam_save(
                backup_path, steam_path, steam32_id, int(app_id),
                log_func=log_lines.append,
            )
            log_text = "\n".join(log_lines)
            if ok:
                return (True, log_text, "Saves restored successfully")
            return (False, log_text, "Restore failed — check log")

        def _on_done(result):
            if isinstance(result, tuple):
                ok, log_text, msg = result
                self._emit_task_result("restore_cloud_save", ok, msg, log=log_text)
            else:
                self._emit_task_result("restore_cloud_save", False, "Restore failed")

        self._run_async(_do, on_done=_on_done)

    # ── Bundled tool resolution ───────────────────────────────────

    @staticmethod
    def _get_bundled_tool_path(tool: str) -> Path | None:
        """Return path to a bundled executable in third_party/<tool>/<tool>.exe.
        Checks sys._MEIPASS first (frozen EXE), then project root (dev mode).
        Returns None if not found.
        """
        from sff.utils import root_folder
        ext = ".exe" if sys.platform == "win32" else ""
        rel = Path("third_party") / tool / f"{tool}{ext}"
        if getattr(sys, "frozen", False):
            meipass = Path(getattr(sys, "_MEIPASS", ""))
            p = meipass / rel
            if p.exists():
                return p
        try:
            p = root_folder() / rel
            if p.exists():
                return p
        except Exception:
            pass
        return None

    @pyqtSlot(str, result=str)
    def get_bundled_tool_path(self, tool_name: str) -> str:
        """Return the absolute path to a bundled tool executable, or empty string."""
        p = self._get_bundled_tool_path(tool_name)
        return str(p) if p else ""

    @pyqtSlot(str)
    def rclone_backup_save(self, config_json):
        """Upload a game's Steam userdata saves to an rclone remote."""
        if not _cloud_saves_feature_allowed():
            self._emit_task_result("rclone_backup_save", False, _CLOUD_SAVES_DENIED_MSG, log="")
            return

        def _do():
            import subprocess
            import tempfile
            config = json.loads(config_json)
            app_id = str(config.get("app_id", "")).strip()
            rclone_exe = config.get("rclone_exe", "").strip()
            remote_dest = config.get("remote_dest", "").strip()
            steam_path = config.get("steam_path", "").strip()
            steam32_id = str(config.get("steam32_id", "")).strip()
            game_name = config.get("game_name", f"App {app_id}").strip() or f"App {app_id}"
            if not rclone_exe:
                bundled = WebBridge._get_bundled_tool_path("rclone")
                if bundled:
                    rclone_exe = str(bundled)
            if not app_id or not rclone_exe or not remote_dest or not steam_path or not steam32_id:
                return (False, "", "Missing rclone configuration")
            if not Path(rclone_exe).exists():
                return (False, "", f"rclone executable not found: {rclone_exe}")
            from sff.cloud_saves import CloudSaves
            log_lines = []
            tmp = Path(tempfile.mkdtemp(prefix="slimedeals_rclone_"))
            try:
                result = CloudSaves().backup_steam_save(
                    steam_path, steam32_id, int(app_id), game_name, str(tmp),
                    log_func=log_lines.append,
                )
                if not result:
                    return (False, "\n".join(log_lines), "Local backup step failed")
                local_dir = Path(result)
                remote_path = remote_dest.rstrip("/") + "/" + local_dir.name
                _no_win = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
                proc = subprocess.run(
                    [
                        rclone_exe, "copy", str(local_dir), remote_path,
                        "--update",
                        "--transfers", "10", "--checkers", "20",
                        "--create-empty-src-dirs",
                        "--fast-list",
                    ],
                    capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300, **_no_win,
                )
                log_lines.append(proc.stdout)
                if proc.returncode == 0:
                    return (True, "\n".join(log_lines), f"Uploaded to {remote_path}")
                log_lines.append(proc.stderr)
                return (False, "\n".join(log_lines), f"rclone failed (exit {proc.returncode})")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        def _on_done(result):
            if isinstance(result, tuple):
                ok, log_text, msg = result
                self._emit_task_result("rclone_backup_save", ok, msg, log=log_text)
            else:
                self._emit_task_result("rclone_backup_save", False, "Upload failed")

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str)
    def rclone_list_remotes(self, rclone_exe_json):
        """Run rclone listremotes --long and return JSON list of configured remote names."""
        def _do():
            import subprocess
            try:
                rclone_exe = json.loads(rclone_exe_json).get("rclone_exe", "").strip()
            except Exception:
                rclone_exe = ""
            if not rclone_exe:
                bundled = WebBridge._get_bundled_tool_path("rclone")
                rclone_exe = str(bundled) if bundled else ""
            if not rclone_exe or not Path(rclone_exe).exists():
                return json.dumps({"ok": False, "error": "rclone executable not found"})
            _no_win = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
            try:
                proc = subprocess.run(
                    [rclone_exe, "listremotes", "--long"],
                    capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=15, **_no_win,
                )
                if proc.returncode != 0:
                    return json.dumps({"ok": False, "error": proc.stderr.strip()[:300]})
                remotes = []
                for line in proc.stdout.splitlines():
                    line = line.strip()
                    if line:
                        name = line.split()[0]
                        remotes.append(name)
                return json.dumps({"ok": True, "remotes": remotes})
            except Exception as e:
                return json.dumps({"ok": False, "error": str(e)})

        def _on_done(result):
            try:
                parsed = json.loads(result or "{}")
            except Exception:
                parsed = {}
            if parsed.get("ok"):
                self._emit_task_result("rclone_list_remotes", True, "", remotes=parsed.get("remotes", []))
            else:
                self._emit_task_result("rclone_list_remotes", False, "", error=parsed.get("error", "Failed to list remotes"))

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str)
    def rclone_test_remote(self, config_json):
        """Test an rclone remote by running lsd with a short timeout. Returns JSON ok/error."""
        def _do():
            import subprocess
            config = json.loads(config_json)
            rclone_exe = config.get("rclone_exe", "").strip()
            remote = config.get("remote", "").strip()
            if not rclone_exe:
                bundled = WebBridge._get_bundled_tool_path("rclone")
                rclone_exe = str(bundled) if bundled else ""
            if not rclone_exe or not Path(rclone_exe).exists():
                return json.dumps({"ok": False, "error": "rclone executable not found"})
            if not remote:
                return json.dumps({"ok": False, "error": "No remote specified"})
            # Test only the remote root — the backup subfolder may not exist yet
            remote_root = remote.split(":")[0] + ":" if ":" in remote else remote + ":"
            _no_win = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
            try:
                proc = subprocess.run(
                    [rclone_exe, "lsd", remote_root, "--max-depth", "1", "--timeout", "15s"],
                    capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=20, **_no_win,
                )
                if proc.returncode == 0:
                    return json.dumps({"ok": True})
                return json.dumps({"ok": False, "error": proc.stderr.strip()[:300]})
            except subprocess.TimeoutExpired:
                return json.dumps({"ok": False, "error": "Timed out after 20s"})
            except Exception as e:
                return json.dumps({"ok": False, "error": str(e)})

        def _on_done(result):
            try:
                parsed = json.loads(result or "{}")
            except Exception:
                parsed = {}
            if parsed.get("ok"):
                self._emit_task_result("rclone_test_remote", True, "")
            else:
                self._emit_task_result("rclone_test_remote", False, "", error=parsed.get("error", "Remote test failed")[:300])

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str)
    def rclone_open_config(self, rclone_exe_json):
        """Open rclone config in a new terminal window so the user can add or edit remotes."""
        import sys
        import subprocess
        try:
            rclone_exe = json.loads(rclone_exe_json).get("rclone_exe", "").strip()
        except Exception:
            rclone_exe = ""
        if not rclone_exe:
            bundled = WebBridge._get_bundled_tool_path("rclone")
            rclone_exe = str(bundled) if bundled else ""
        if not rclone_exe or not Path(rclone_exe).exists():
            self._emit_task_result("rclone_open_config", False, "", error="rclone executable not found")
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(
                    ["cmd", "/k", rclone_exe, "config"],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                cmd = [rclone_exe, "config"]
                launched = False
                for term, args in [
                    ("x-terminal-emulator", ["-e"]),
                    ("gnome-terminal", ["--"]),
                    ("xterm", ["-e"]),
                    ("konsole", ["-e"]),
                    ("xfce4-terminal", ["-e"]),
                ]:
                    try:
                        subprocess.Popen([term] + args + cmd)
                        launched = True
                        break
                    except FileNotFoundError:
                        continue
                if not launched:
                    self._emit_task_result("rclone_open_config", False, "", error="No terminal emulator found. Open a terminal and run: rclone config")
                    return
            self._emit_task_result("rclone_open_config", True, "")
        except Exception as e:
            self._emit_task_result("rclone_open_config", False, "", error=str(e))

    @pyqtSlot(str)
    def open_workshop(self, app_id):
        """Open the workshop browser for a game."""
        try:
            from sff.gui.workshop_browser import open_workshop_browser
            open_workshop_browser(app_id, self.parent())
        except Exception as e:
            logger.exception("open_workshop failed: %s", e)

    @pyqtSlot(str)
    def download_workshop_item(self, params_json):
        """Download a workshop item using 4-method cascade (SteamWebAPI, GGNetwork, SteamCMD).
        params_json: {"app_id": "...", "item_url": "..."} or {"app_id": "...", "item_id": "..."}
        Emits task_finished with task='workshop_download'."""
        def _do():
            try:
                params = json.loads(params_json)
                app_id = str(params.get("app_id", "0"))
                item_url = params.get("item_url") or params.get("item_id") or ""
                from sff.manifest.workshop_dl import (
                    download_workshop_item as _dl,
                    parse_workshop_item_id,
                )
                from sff.storage.settings import get_setting
                from sff.structs import Settings
                item_id = parse_workshop_item_id(item_url)
                if not item_id:
                    return {"success": False, "error": f"Could not parse item ID from: {item_url}"}
                out_dir = Path.cwd() / "downloaded_files" / "workshop" / item_id
                user = get_setting(Settings.STEAM_USER) or "anonymous"
                pwd = get_setting(Settings.STEAM_PASS) or ""
                result = _dl(item_id, app_id, out_dir, steam_username=user, steam_password=pwd)
                return result
            except Exception as e:
                return {"success": False, "error": str(e)}

        def _on_done(result):
            result = result or {}
            self._emit_task_result(
                "workshop_download",
                bool(result.get("success")),
                result.get("method") or result.get("error") or "",
                path=result.get("path") or "",
            )

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str)
    def check_game_update(self, app_id):
        """Compare installed ACF buildid against Steam CM public buildid.
        If Steam CM is newer: download updated manifests and patch the ACF.
        Emits task_finished with task='update_check'."""
        def _do():
            try:
                from pathlib import Path as _Path
                from sff.storage.vdf import get_steam_libs, vdf_load
                from sff.lua.writer import ACFWriter
                from sff.manifest.downloader import ManifestDownloader
                from sff.lua.manager import LuaManager, LuaChoice
                from sff.steam_client import create_provider_for_current_thread
                from sff.storage.settings import get_setting
                from sff.structs import OSType, Settings
                from sff.steam_tools_compat import install_lua_to_steam

                steam_libs = get_steam_libs(self._steam_path) if self._steam_path else []
                acf_path = None
                lib_path = None
                for lib in steam_libs:
                    candidate = lib / "steamapps" / f"appmanifest_{app_id}.acf"
                    if candidate.exists():
                        acf_path = candidate
                        lib_path = lib
                        break

                if acf_path is None:
                    return {"found": False, "error": f"ACF not found for App ID {app_id}"}

                acf_data = vdf_load(acf_path)
                state = acf_data.get("AppState", {})
                installed_buildid = str(state.get("buildid", "0")).strip()

                provider = create_provider_for_current_thread()
                app_data = provider.get_single_app_info(int(app_id))
                cm_buildid = str(
                    app_data.get("depots", {})
                    .get("branches", {})
                    .get("public", {})
                    .get("buildid", "0")
                ).strip()

                if not cm_buildid or cm_buildid == "0":
                    return {"found": True, "error": "Could not retrieve buildid from Steam CM"}

                if installed_buildid == cm_buildid:
                    return {
                        "found": True,
                        "up_to_date": True,
                        "installed_buildid": installed_buildid,
                        "cm_buildid": cm_buildid,
                    }

                os_type = OSType.WINDOWS if sys.platform == "win32" else OSType.LINUX
                lua_manager = LuaManager(os_type)
                saved_lua_path = launcher_saved_lua_dir() / f"{app_id}.lua"
                if not saved_lua_path.exists():
                    return {
                        "found": True,
                        "up_to_date": False,
                        "installed_buildid": installed_buildid,
                        "cm_buildid": cm_buildid,
                        "error": f"No saved .lua for App ID {app_id} — run Download Games first",
                    }

                parsed_lua = lua_manager.fetch_lua(LuaChoice.ADD_LUA, saved_lua_path)
                if parsed_lua is None:
                    return {
                        "found": True,
                        "up_to_date": False,
                        "error": "Failed to parse saved .lua file",
                    }

                install_lua_to_steam(self._steam_path, str(parsed_lua.app_id), saved_lua_path)

                downloader = ManifestDownloader(provider, self._steam_path)
                use_parallel = get_setting(Settings.USE_PARALLEL_DOWNLOADS)
                if use_parallel:
                    manifest_paths = downloader.download_manifests_parallel(parsed_lua, auto_manifest=True)
                else:
                    manifest_paths = downloader.download_manifests(parsed_lua, auto_manifest=True)

                new_manifest_map = {}
                for mp in (manifest_paths or []):
                    stem = _Path(mp).stem
                    parts = stem.split("_")
                    if len(parts) == 2 and all(p.isdigit() for p in parts):
                        new_manifest_map[parts[0]] = parts[1]

                if new_manifest_map:
                    acf_writer = ACFWriter(lib_path)
                    acf_writer.patch_acf_depot_manifests(acf_path, new_manifest_map)
                    acf_writer._patch_acf_error_state(acf_path)

                return {
                    "found": True,
                    "up_to_date": False,
                    "updated": True,
                    "installed_buildid": installed_buildid,
                    "cm_buildid": cm_buildid,
                    "manifests_updated": len(new_manifest_map),
                }

            except Exception as e:
                logger.exception("check_game_update failed: %s", e)
                return {"found": True, "error": str(e)}

        def _on_done(result):
            result = result or {}
            success = bool(result.get("up_to_date") or result.get("updated"))
            msg = ""
            if result.get("up_to_date"):
                msg = f"Already up to date (build {result.get('installed_buildid', '')})"
            elif result.get("updated"):
                msg = f"Updated to build {result.get('cm_buildid', '')}"
            elif result.get("error"):
                msg = result["error"]
            self._emit_task_result("update_check", success, msg, **{
                k: v for k, v in result.items() if k not in ("error",)
            })

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str)
    def lure_fix_acf(self, app_id):
        """Patch the game's ACF with the latest Steam CM manifest IDs and buildid.
        No files are downloaded — pure ACF update to suppress Steam's update prompt.
        Emits task_finished with task='lure_fix'."""
        def _do():
            try:
                from pathlib import Path as _Path
                from sff.storage.vdf import get_steam_libs, vdf_load, vdf_dump
                from sff.lua.writer import ACFWriter
                from sff.steam_client import create_provider_for_current_thread

                steam_libs = get_steam_libs(self._steam_path) if self._steam_path else []
                acf_path = None
                lib_path = None
                for lib in steam_libs:
                    candidate = lib / "steamapps" / f"appmanifest_{app_id}.acf"
                    if candidate.exists():
                        acf_path = candidate
                        lib_path = lib
                        break

                if acf_path is None:
                    return {"success": False, "error": f"ACF not found for App ID {app_id}"}

                provider = create_provider_for_current_thread()
                app_data = provider.get_single_app_info(int(app_id))
                depots_data = app_data.get("depots", {})

                cm_buildid = str(
                    depots_data.get("branches", {})
                    .get("public", {})
                    .get("buildid", "0")
                ).strip()

                if not cm_buildid or cm_buildid == "0":
                    return {"success": False, "error": "Could not retrieve buildid from Steam CM"}

                acf_data = vdf_load(acf_path)
                state = acf_data.get("AppState", {})
                installed = state.get("InstalledDepots", {})

                new_manifest_map = {}
                for depot_id in list(installed.keys()):
                    mani_pub = (
                        depots_data.get(str(depot_id), {})
                        .get("manifests", {})
                        .get("public", {})
                    )
                    if isinstance(mani_pub, dict):
                        gid = mani_pub.get("gid")
                    else:
                        gid = mani_pub
                    if gid:
                        new_manifest_map[depot_id] = str(gid)

                if new_manifest_map:
                    acf_writer = ACFWriter(lib_path)
                    acf_writer.patch_acf_depot_manifests(acf_path, new_manifest_map)

                acf_data = vdf_load(acf_path)
                state = acf_data.get("AppState", {})
                state["buildid"] = cm_buildid
                state["StateFlags"] = "4"
                state["TargetBuildID"] = "0"
                state["DownloadType"] = "0"
                state["UpdateResult"] = "0"
                state["ScheduledAutoUpdate"] = "0"
                state["BytesToDownload"] = "0"
                state["BytesDownloaded"] = "0"
                state["BytesToStage"] = "0"
                state["BytesStaged"] = "0"
                acf_data["AppState"] = state
                vdf_dump(acf_path, acf_data)

                return {
                    "success": True,
                    "cm_buildid": cm_buildid,
                    "depots_patched": len(new_manifest_map),
                }

            except Exception as e:
                logger.exception("lure_fix_acf failed: %s", e)
                return {"success": False, "error": str(e)}

        def _on_done(result):
            result = result or {}
            if result.get("success"):
                msg = (
                    f"ACF patched to build {result.get('cm_buildid', '')} "
                    f"({result.get('depots_patched', 0)} depot(s)). Restart Steam."
                )
            else:
                msg = result.get("error", "Lure fix failed")
            self._emit_task_result("lure_fix", bool(result.get("success")), msg, **{
                k: v for k, v in result.items() if k != "error"
            })

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot()
    def restart_steam(self):
        """Restart or launch Steam."""
        def _do():
            if sys.platform == "win32":
                import time
                import subprocess
                from sff.processes import SteamProcess, is_proc_running

                if not self._steam_path:
                    return (False, "Steam path not set")

                applist_folder = None
                if hasattr(self._ui, 'app_list_man') and self._ui.app_list_man:
                    applist_folder = self._ui.app_list_man.applist_folder
                if not applist_folder:
                    return (False, "AppList folder not found")

                steam_proc = SteamProcess(self._steam_path, applist_folder)

                # Kill Steam if running
                if is_proc_running(steam_proc.exe_name):
                    print("Killing Steam...", end="", flush=True)
                    steam_proc.kill()
                    max_wait = 10
                    waited = 0
                    while is_proc_running(steam_proc.exe_name) and waited < max_wait:
                        time.sleep(0.5)
                        waited += 0.5
                    if is_proc_running(steam_proc.exe_name):
                        return (False, "Steam did not close in time — try again")
                    print(" Done!")

                # Find injector: prefer DLLInjector.exe, fallback to steam.exe
                injector = steam_proc.injector_dir / "DLLInjector.exe"
                if not injector.exists():
                    injector = self._steam_path / "steam.exe"
                if not injector.exists():
                    return (False, "DLLInjector.exe and steam.exe not found")

                print(f"Launching {injector.name}...")
                try:
                    import ctypes as _ctypes
                    already_admin = bool(_ctypes.windll.shell32.IsUserAnAdmin())
                    if already_admin:
                        subprocess.Popen([str(injector)], cwd=str(self._steam_path))
                        return (True, "Steam launched successfully")
                    # Not admin — request UAC elevation via ShellExecuteW runas
                    ret = _ctypes.windll.shell32.ShellExecuteW(
                        None, "runas", str(injector), None, str(self._steam_path), 1)
                    if ret > 32:
                        return (True, "Steam launched successfully")
                    # Elevation declined/failed — try without elevation as fallback
                    subprocess.Popen([str(injector)], cwd=str(self._steam_path))
                    return (True, "Steam launched (elevation skipped)")
                except Exception as e:
                    return (False, f"Failed to launch: {e}")

            else:
                from sff.linux.steam_process import kill_steam, start_steam
                kill_steam()
                result = start_steam()
                if result == "SUCCESS":
                    return (True, "Steam restarted")
                return (False, f"Steam start failed: {result}")

        def _on_done(result):
            if isinstance(result, tuple):
                success, msg = result
            else:
                success, msg = bool(result), "Steam restarted" if result else "Failed to restart Steam"
            self._emit_task_result("restart_steam", success, msg)

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot()
    def open_log_window(self):
        """Opens the existing GlobalLogWindow as a standalone native window."""
        parent = self.parent()
        if hasattr(parent, '_log_window'):
            parent._log_window.show()
            parent._log_window.raise_()
            parent._log_window.activateWindow()

    @pyqtSlot(str)
    def copy_to_clipboard(self, text):
        """Copy text to system clipboard via Qt (works in QWebEngine)."""
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)

    @pyqtSlot(result=str)
    def browse_game_folder(self):
        """Open a native folder-picker dialog and return the selected path (or '')."""
        from PyQt6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self.parent(), "Select game folder")
        return path or ""

    @pyqtSlot(str, str, str)
    def run_game_action_outside(self, game_path, app_id, action):
        """Run a game action against a folder outside the Steam library.
        Builds ACFInfo from the explicit path instead of scanning steamapps."""
        from pathlib import Path as _Path
        from sff.game_specific import ACFInfo

        p = _Path(game_path)
        if not p.is_dir():
            self._emit_task_result(action, False, f"Folder not found: {game_path}")
            return

        acf = ACFInfo(app_id or "0", p)

        if action == "steam_auto":
            from sff.steamauto import get_steamauto_cli_path
            if get_steamauto_cli_path() is None:
                self._emit_task_result("steam_auto", False, "SteamAutoCrack CLI not found")
                return
            parent = self.parent()
            if parent and hasattr(parent, '_run_steam_auto_with_acf'):
                parent._run_steam_auto_with_acf(acf)
            return

        def _do():
            from sff.structs import MainMenu
            game_action_map = {
                "crack": MainMenu.CRACK_GAME,
                "steamstub": MainMenu.REMOVE_DRM,
                "dlc_check": MainMenu.DLC_CHECK,
                "workshop": MainMenu.DL_WORKSHOP_ITEM,
                "multiplayer": MainMenu.MULTIPLAYER_FIX,
                "community_fixes": MainMenu.CRACK_FIX,
                "hv_fix": MainMenu.HV_FIX,
                "achievements": MainMenu.DL_USER_GAME_STATS,
                "dlc_unlockers": MainMenu.MANAGE_DLC_UNLOCKERS,
                "check_mod_updates": MainMenu.CHECK_MOD_UPDATES,
            }
            menu_choice = game_action_map.get(action)
            if menu_choice is None:
                return f"Unknown action: {action}"
            if action == "multiplayer":
                saved = _load_auth()
                if not triple_exclusive_tools_allowed_for_rank(saved.get("rank")):
                    self._emit_task_result(
                        "multiplayer",
                        False,
                        "L'option ONLINE FIX est reservee au plan Triple Monstre. Offres : slimedeals.fr/#tarifs — salon #avis sur Discord.",
                        free_plan_denied=True,
                    )
                    return "__noop__"
            try:
                ret = self._ui.run_game_action_with_selection(menu_choice, acf)
                if (
                    action == "multiplayer"
                    and isinstance(ret, tuple)
                    and len(ret) == 2
                    and isinstance(ret[0], str)
                    and ret[0] in ("ok", "fail", "cancelled")
                ):
                    return ret
                return None
            except Exception as e:
                return str(e)

        def _on_done(result):
            if result == "__noop__":
                return
            if (
                isinstance(result, tuple)
                and len(result) == 2
                and isinstance(result[0], str)
                and result[0] in ("ok", "fail", "cancelled")
                and action == "multiplayer"
            ):
                status, gname = result
                g = (gname or "").strip() or "ce jeu"
                if status == "ok":
                    self._emit_task_result(
                        action,
                        True,
                        f"Mod online ajouté sur « {g} ».",
                        game_name=g,
                    )
                elif status == "cancelled":
                    self._emit_task_result(
                        action,
                        False,
                        f"Opération multijoueur annulée. (Jeu : « {g} »)",
                        game_name=g,
                        cancelled=True,
                    )
                else:
                    self._emit_task_result(
                        action,
                        False,
                        f"Mode online introuvable pour « {g} ».",
                        game_name=g,
                    )
                return
            if result:
                self._emit_task_result(action, False, str(result))
            else:
                self._emit_task_result(action, True, f"Action '{action}' completed")

        self._run_async(_do, on_done=_on_done)

    # ── SYNC slots — fast, no I/O ────────────────────────────────

    @pyqtSlot(result=str)
    def get_applist_games(self):
        """Returns JSON list of {app_id, name} for installed Steam games with saved .lua files."""
        try:
            saved_lua = launcher_saved_lua_dir()
            saved_ids = {p.stem for p in saved_lua.glob("*.lua")} if saved_lua.exists() else set()
            installed = json.loads(self.get_installed_games())
            games = [
                {"app_id": str(g["app_id"]), "name": g["name"]}
                for g in installed
                if str(g["app_id"]) in saved_ids
            ]
            games.sort(key=lambda x: x["name"].lower())
            return json.dumps(games)
        except Exception as e:
            logger.warning("get_applist_games failed: %s", e)
            return json.dumps([])

    @pyqtSlot(result=str)
    def get_platform(self):
        """Returns 'win32' or 'linux'."""
        return sys.platform

    @pyqtSlot(str, result=str)
    def get_disk_usage(self, path):
        """Return disk usage JSON {total, used, free} for the given path."""
        import shutil
        import json as _json
        try:
            usage = shutil.disk_usage(path)
            return _json.dumps({"total": usage.total, "used": usage.used, "free": usage.free})
        except Exception:
            return _json.dumps({"error": True})

    @pyqtSlot(str)
    def auto_gl_setup_action(self, config_json):
        """Extract and configure GreenLuma from a ZIP or RAR archive.
        config_json: {method: 'A'|'B', archive_path: str, steam_exe: str}
        Emits task_finished with task='auto_gl_setup'."""
        def _do():
            import json as _json
            cfg = _json.loads(config_json)
            method = cfg.get("method", "A")
            archive_path = cfg.get("archive_path", "").strip()
            steam_exe = cfg.get("steam_exe", "").strip()
            if not archive_path:
                return (False, "No archive selected.", "")
            if not steam_exe:
                steam_exe = r"C:\Program Files (x86)\Steam\steam.exe"
            from sff.greenluma_setup import auto_gl_setup
            result = auto_gl_setup(method=method, archive_path=archive_path, steam_exe_path=steam_exe)
            return (result["ok"], result["message"], result.get("applist_path", ""))

        def _on_done(result):
            if isinstance(result, tuple) and len(result) >= 2:
                ok, msg = result[0], result[1]
                applist_path = result[2] if len(result) > 2 else ""
                if ok and applist_path:
                    try:
                        from sff.storage.settings import set_setting
                        from sff.structs import Settings
                        set_setting(Settings.APPLIST_FOLDER, applist_path)
                    except Exception:
                        pass
                import json as _json
                self.task_finished.emit(_json.dumps({
                    "task": "auto_gl_setup",
                    "success": bool(ok),
                    "message": msg,
                    "applist_path": applist_path,
                }))
            else:
                import json as _json
                self.task_finished.emit(_json.dumps({"task": "auto_gl_setup", "success": False, "message": "Setup failed"}))

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot()
    def launch_slimedeals_bprg(self):
        """Lance ROCKSTAR BYPASS (Windows) — SlimeDealsBPRG à côté de l'exe ou embarqué (_internal)."""
        from sff.utils import root_folder

        if sys.platform != "win32":
            self._emit_task_result(
                "slimedeals_bprg",
                False,
                "ROCKSTAR BYPASS n'est disponible que sous Windows.",
            )
            return

        saved = _load_auth()
        if not triple_exclusive_tools_allowed_for_rank(saved.get("rank")):
            self._emit_task_result(
                "slimedeals_bprg",
                False,
                "ROCKSTAR BYPASS est reserve au plan Triple Monstre. Voir slimedeals.fr/#tarifs",
            )
            return

        rel = Path("SlimeDealsBPRG") / "SlimeDealsBPRG.exe"
        candidates: list[Path] = []
        if getattr(sys, "frozen", False):
            # D'abord à côté du .exe (copie manuelle / zip) ; puis bundle PyInstaller (souvent _internal\…)
            candidates.append(Path(root_folder(outside_internal=True)) / rel)
            candidates.append(Path(root_folder(outside_internal=False)) / rel)
        else:
            candidates.append(Path(root_folder()) / rel)

        exe: Optional[Path] = None
        for p in candidates:
            rp = p.resolve()
            if rp.is_file():
                exe = rp
                break

        if exe is None:
            hint = candidates[0] if candidates else rel
            self._emit_task_result(
                "slimedeals_bprg",
                False,
                f"Introuvable : {hint}. Compilez / copiez SlimeDealsBPRG avant le build — voir SlimeDealsBPRG/README.txt.",
            )
            return

        cwd = exe.parent
        try:
            flags = 0
            if sys.platform == "win32":
                flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen(
                [str(exe)],
                cwd=str(cwd),
                close_fds=True,
                creationflags=flags,
            )
            self._emit_task_result("slimedeals_bprg", True, "ROCKSTAR BYPASS lancé.")
        except Exception as exc:
            logger.exception("launch_slimedeals_bprg")
            self._emit_task_result("slimedeals_bprg", False, str(exc))

    @pyqtSlot(str)
    def connect_store(self, api_key):
        """Validates and stores Hubcap API key."""
        from sff.store_browser import StoreApiClient
        self._api_key = api_key
        self._store_client = StoreApiClient(api_key)
        # Save to settings
        from sff.storage.settings import set_setting
        from sff.structs import Settings
        set_setting(Settings.HUBCAP_KEY, api_key)

    @pyqtSlot(result=str)
    def get_stored_api_key(self):
        """Returns saved API key from settings (may be empty)."""
        from sff.storage.settings import get_setting
        from sff.structs import Settings
        key = get_setting(Settings.HUBCAP_KEY)
        if key:
            self._api_key = key
        return key or ""

    @pyqtSlot(result=str)
    def list_profiles(self):
        """Returns JSON array of profile names."""
        from sff.app_injector.applist_profiles import list_profiles
        return json.dumps(list_profiles())

    @pyqtSlot(str)
    def switch_profile(self, name):
        """Switch to a named AppList profile."""
        def _do():
            from sff.app_injector.applist_profiles import switch_profile
            from sff.storage.settings import get_setting
            from sff.structs import Settings
            from pathlib import Path
            if hasattr(self._ui, 'app_list_man') and self._ui.app_list_man:
                folder = self._ui.app_list_man.applist_folder
            else:
                saved = get_setting(Settings.APPLIST_FOLDER)
                if not saved:
                    return False
                folder = Path(saved)
            success, count = switch_profile(name, folder)
            return success

        def _on_done(result):
            self._emit_task_result("switch_profile", bool(result), f"Switched to '{name}'")

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str)
    def save_profile(self, name):
        """Save current AppList as a profile."""
        from sff.app_injector.applist_profiles import save_profile
        if hasattr(self._ui, 'app_list_man') and self._ui.app_list_man:
            ids = [x.app_id for x in self._ui.app_list_man.get_local_ids(sort=True)]
            save_profile(name, ids)

    @pyqtSlot(str)
    def delete_profile(self, name):
        """Delete a profile."""
        from sff.app_injector.applist_profiles import delete_profile
        delete_profile(name)

    @pyqtSlot(str, str)
    def rename_profile(self, old_name, new_name):
        """Rename a profile."""
        from sff.app_injector.applist_profiles import rename_profile
        rename_profile(old_name, new_name)

    @pyqtSlot(str)
    def open_url(self, url):
        """Open a URL in the system default browser."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url))

    @pyqtSlot()
    def clear_applist(self):
        """Delete all numbered .txt files from the GreenLuma AppList folder."""
        def _do():
            if not hasattr(self._ui, 'app_list_man') or not self._ui.app_list_man:
                return -1
            folder = Path(self._ui.app_list_man.applist_folder)
            count = 0
            for f in folder.glob("*.txt"):
                if f.stem.isdigit():
                    f.unlink(missing_ok=True)
                    count += 1
            return count

        def _on_done(count):
            if count == -1:
                self.task_finished.emit(json.dumps({
                    "task": "applist_cleared", "success": False,
                    "message": "AppList manager not available", "count": 0,
                }))
            else:
                self.task_finished.emit(json.dumps({
                    "task": "applist_cleared", "success": True,
                    "message": f"Cleared {count} IDs from AppList", "count": count,
                }))

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot()
    def rebuild_applist_from_installed(self):
        """Clear AppList and repopulate with only currently installed Steam games."""
        def _do():
            if not hasattr(self._ui, 'app_list_man') or not self._ui.app_list_man:
                return {"success": False, "message": "AppList manager not available", "count": 0}
            folder = Path(self._ui.app_list_man.applist_folder)
            for f in folder.glob("*.txt"):
                if f.stem.isdigit():
                    f.unlink(missing_ok=True)
            games = json.loads(self.get_installed_games())
            app_ids = [g["app_id"] for g in games if g.get("app_id")]
            for i, app_id in enumerate(app_ids):
                (folder / f"{i}.txt").write_text(str(app_id), encoding="utf-8")
            return {"success": True, "count": len(app_ids)}

        def _on_done(result):
            self.task_finished.emit(json.dumps({
                "task": "applist_rebuilt",
                "success": result.get("success", False),
                "message": result.get("message", f"Rebuilt AppList with {result.get('count', 0)} installed games"),
                "count": result.get("count", 0),
            }))

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str, str)
    def set_setting(self, key, value):
        """Set a setting by key name, then apply it live (same as classic UI)."""
        from sff.storage.settings import set_setting as _set
        from sff.structs import Settings
        for s in Settings:
            if s.key_name == key or s.name.lower() == key.lower():
                # Convert string "True"/"False" to real bool for bool-typed settings
                if s.type == bool:
                    value = value in ('True', 'true', '1')
                _set(s, value)
                # Apply live so changes take effect immediately
                parent = self.parent()
                if parent and hasattr(parent, '_apply_setting_live'):
                    try:
                        parent._apply_setting_live(s)
                    except Exception as e:
                        logger.warning("_apply_setting_live(%s) failed: %s", key, e)
                return

    @pyqtSlot(str, result=str)
    def get_setting(self, key):
        """Get a setting by key name."""
        from sff.storage.settings import get_setting as _get
        from sff.structs import Settings
        for s in Settings:
            if s.key_name == key or s.name.lower() == key.lower():
                val = _get(s)
                return str(val) if val is not None else ""
        return ""

    @pyqtSlot(str, result=str)
    def get_webui_translations(self, lang):
        """Return the webui translation JSON for the given language."""
        from sff.utils import root_folder
        from pathlib import Path as _Path
        locales_dir = root_folder() / "sff" / "locales"
        if lang in ("Auto", "", None):
            lang = "en"
        path = locales_dir / f"webui_{lang}.json"
        if not path.exists():
            path = locales_dir / "webui_en.json"
        if not path.exists():
            return "{}"
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return "{}"

    @pyqtSlot(result=str)
    def get_steam_libraries(self):
        """Returns JSON array of Steam library paths."""
        from sff.storage.vdf import get_steam_libs
        if not self._steam_path:
            return "[]"
        try:
            libs = get_steam_libs(self._steam_path)
            return json.dumps([str(p) for p in libs])
        except Exception:
            return "[]"

    @pyqtSlot(str)
    def set_active_library(self, path):
        """Sets the library path for the next download."""
        self._active_library = path

    @pyqtSlot(result=str)
    def open_file_dialog(self):
        """Opens native QFileDialog, returns selected path."""
        parent = self.parent()
        path = QFileDialog.getExistingDirectory(parent, "Select Folder")
        return path or ""

    @pyqtSlot(result=str)
    def open_archive_dialog(self):
        """Opens a file picker for ZIP/RAR/7z archives. Returns selected file path."""
        path, _ = QFileDialog.getOpenFileName(
            self.parent(),
            "Select GreenLuma Archive",
            "",
            "Archives (*.zip *.rar *.7z);;All Files (*)",
        )
        return path or ""

    @pyqtSlot(result=str)
    def open_exe_file_dialog(self):
        """Opens a file picker for executables. Returns selected file path."""
        path, _ = QFileDialog.getOpenFileName(
            self.parent(),
            "Select Executable",
            "",
            "Executables (*.exe);;All Files (*)",
        )
        return path or ""

    @pyqtSlot(result=str)
    def browse_image_file(self):
        """Opens a native file picker filtered to PNG/JPG/JPEG images. Returns selected path or ''."""
        from PyQt6.QtWidgets import QFileDialog as _QFD
        path, _ = _QFD.getOpenFileName(
            self.parent(),
            "Select Avatar Image",
            "",
            "Image Files (*.png *.jpg *.jpeg)",
        )
        return path or ""

    @pyqtSlot(result=str)
    def open_lua_file_dialog(self):
        """Opens a file picker for Lua files. Returns selected file path."""
        path, _ = QFileDialog.getOpenFileName(
            self.parent(),
            "Select Lua File",
            "",
            "Lua Files (*.lua *.zip);;All Files (*)",
        )
        return path or ""

    @pyqtSlot(result=str)
    def open_manifest_folder_dialog(self):
        """Opens a folder picker for selecting a directory containing .manifest files."""
        path = QFileDialog.getExistingDirectory(
            self.parent(),
            "Select Manifest Folder",
            "",
        )
        return path or ""

    @pyqtSlot(result=str)
    def get_recent_lua_files(self):
        """Returns JSON array of recent Lua files [{name, path}, ...] from RecentFilesManager."""
        try:
            from sff.recent_files import get_recent_files_manager
            mgr = get_recent_files_manager()
            files = mgr.get_all()
            return json.dumps([{"name": p.name, "path": str(p)} for p in files])
        except Exception as e:
            logger.warning("get_recent_lua_files failed: %s", e)
            return "[]"

    @pyqtSlot(str, str, str, str)
    def download_game_ddmod(self, app_id, source, lua_path, manifest_folder=''):
        """Download a game using DepotDownloaderMod.
        source: 'twentytwocloud' / 'catalogue' (défaut réseau) ou 'local'
        lua_path: used when source == 'local'
        Emits download_progress + task_finished signals."""
        def _do():
            self.download_progress.emit(json.dumps({
                "app_id": app_id, "status": "Starting DDMod download", "progress": 0
            }))
            try:
                from pathlib import Path as _Path
                from sff.lua.endpoints import get_twentytwocloud
                from sff.lua.manager import parse_lua_contents
                from sff.depot_downloader import run_download

                steam_path = self._steam_path
                dest = _Path(self._active_library) if self._active_library else steam_path
                if dest is None:
                    return (False, "No Steam library selected. Please select a download location.")

                lua_dest = (steam_path / "config") if steam_path else _Path(".")
                _dc = (steam_path / "depotcache") if steam_path else None

                self.download_progress.emit(json.dumps({
                    "app_id": app_id, "status": "Fetching Lua file...", "progress": 5
                }))

                if source == "local":
                    lua_file = _Path(lua_path) if lua_path else None
                    if not lua_file or not lua_file.exists():
                        return (False, f"Lua file not found: {lua_path}")
                else:
                    lua_file = get_twentytwocloud(lua_dest, app_id, depotcache=_dc)

                if not lua_file or not lua_file.exists():
                    return (False, f"Failed to obtain Lua file from source '{source}'")

                self.download_progress.emit(json.dumps({
                    "app_id": app_id, "status": "Parsing Lua...", "progress": 15
                }))

                # ZIP: extract lua text and seed depotcache with any embedded manifests
                if lua_file.suffix.lower() == '.zip':
                    from sff.zip import read_lua_from_zip
                    _dc = (steam_path / "depotcache") if steam_path else None
                    lua_text = read_lua_from_zip(lua_file, decode=True, depotcache=_dc)
                    if not lua_text:
                        return (False, "Could not find .lua file inside ZIP archive")
                else:
                    lua_text = lua_file.read_text(encoding="utf-8", errors="replace")
                parsed = parse_lua_contents(lua_text, lua_file)
                if not parsed or not parsed.depots:
                    return (False, "Failed to parse Lua — no depot info found")

                self.download_progress.emit(json.dumps({
                    "app_id": app_id, "status": "Resolving manifests...", "progress": 25
                }))

                # Build game_data for run_download
                depots_dict = {}
                manifests_dict = {}
                for d in parsed.depots:
                    if d.decryption_key:
                        depots_dict[str(d.depot_id)] = {"key": d.decryption_key}

                _depot_ids_set = set(depots_dict.keys())

                # Step 1: scan staging manifests (ZIP Morrenus / ~/.slimedeals/work/manifests)
                _staging = launcher_manifests_dir()
                if _staging.exists():
                    for _mf in _staging.glob("*.manifest"):
                        _parts = _mf.stem.split("_", 1)
                        if len(_parts) == 2 and _parts[0] in _depot_ids_set:
                            if _parts[0] not in manifests_dict:
                                manifests_dict[_parts[0]] = _parts[1]

                # Step 2: scan user-provided manifest folder
                if manifest_folder:
                    import shutil as _shutil
                    _mf_path = _Path(manifest_folder)
                    if _mf_path.exists():
                        _staging.mkdir(parents=True, exist_ok=True)
                        for _mf in _mf_path.glob("*.manifest"):
                            _parts = _mf.stem.split("_", 1)
                            if len(_parts) == 2 and _parts[0] in _depot_ids_set:
                                manifests_dict[_parts[0]] = _parts[1]
                                _shutil.copy2(_mf, _staging / _mf.name)

                # Step 3: try Steam App Info for manifest IDs + game_name/installdir/buildid (non-fatal)
                game_name = ""
                installdir = ""
                buildid = "0"
                if steam_path and depots_dict:
                    try:
                        from sff.steam_client import create_provider_for_current_thread
                        from sff.manifest.downloader import ManifestDownloader
                        _provider = create_provider_for_current_thread()
                        _md = ManifestDownloader(provider=_provider, steam_path=steam_path)
                        _manifest_map = _md.get_manifest_ids(parsed, auto=True)
                        for _depot_id, _manifest_id in _manifest_map.items():
                            if _manifest_id and str(_depot_id) not in manifests_dict:
                                manifests_dict[str(_depot_id)] = str(_manifest_id)
                        # Also pull game_name, installdir, buildid from App Info
                        _eff_id = int(parsed.app_id or app_id)
                        _app_info = _provider.get_single_app_info(_eff_id)
                        if _app_info:
                            game_name = _app_info.get("common", {}).get("name", "")
                            installdir = _app_info.get("config", {}).get("installdir", "")
                            try:
                                buildid = str(
                                    _app_info.get("depots", {})
                                    .get("branches", {})
                                    .get("public", {})
                                    .get("buildid", "0")
                                )
                            except Exception:
                                buildid = "0"
                    except Exception as _me:
                        logger.debug("Manifest auto-resolve (Steam provider) failed: %s", _me)

                # Fallback: parse game name from first short Lua comment line
                if not game_name:
                    import re as _re2
                    for _cl in lua_text.splitlines():
                        _cl = _cl.strip()
                        if _cl.startswith("--"):
                            _cand = _re2.sub(r'^--\s*', '', _cl).strip()
                            if _cand and ':' not in _cand and "'" not in _cand and 'http' not in _cand and 2 < len(_cand) < 60 and not _cand[0].isdigit():
                                game_name = _cand
                                break
                if not installdir:
                    installdir = game_name or f"App_{parsed.app_id or app_id}"

                # Step 4: download manifest files from ManifestHub + GitHub for known IDs
                if manifests_dict and steam_path:
                    try:
                        from sff.manifest.downloader import ManifestDownloader
                        _md2 = ManifestDownloader(provider=None, steam_path=steam_path, use_hubcap=False)
                        _staging.mkdir(parents=True, exist_ok=True)
                        _dc2 = steam_path / "depotcache"
                        _dc2.mkdir(parents=True, exist_ok=True)
                        _eff_app_id = str(parsed.app_id or app_id)
                        for _depot_id, _manifest_id in list(manifests_dict.items()):
                            _dest_mf = _staging / f"{_depot_id}_{_manifest_id}.manifest"
                            if _dest_mf.exists():
                                continue
                            print(f"Fetching manifest for depot {_depot_id} ({_manifest_id})...")
                            _data = _md2._try_manifesthub_combined(_depot_id, _manifest_id, _eff_app_id)
                            if _data:
                                _dest_mf.write_bytes(_data)
                                (_dc2 / _dest_mf.name).write_bytes(_data)
                            else:
                                logger.debug("ManifestHub/GitHub: no manifest for depot %s", _depot_id)
                    except Exception as _fe:
                        logger.debug("ManifestHub/GitHub manifest fetch failed (non-fatal): %s", _fe)

                game_data = {
                    "appid": parsed.app_id or app_id,
                    "game_name": game_name,
                    "depots": depots_dict,
                    "manifests": manifests_dict,
                    "installdir": installdir,
                    "buildid": buildid,
                }

                selected_depots = list(depots_dict.keys())
                if not selected_depots:
                    return (False, "No depots with decryption keys found in Lua")

                self.download_progress.emit(json.dumps({
                    "app_id": app_id, "status": "Running DepotDownloaderMod...", "progress": 35
                }))

                def _print_fn(msg):
                    import re as _re
                    clean = _re.sub(r'\x1b\[[0-9;]*m', '', msg)
                    print(clean)

                ok, _size = run_download(game_data, selected_depots, dest, steam_path, print_fn=_print_fn)

                # Write ACF so Steam recognises the install
                try:
                    from sff.linux.acf_writer import create_acf
                    create_acf(
                        game_data=game_data,
                        dest_path=dest,
                        selected_depots=selected_depots,
                        size_on_disk=_size,
                        print_fn=_print_fn,
                    )
                except Exception as _ae:
                    logger.warning("ACF write failed (non-fatal): %s", _ae)

                # Add to recent files
                try:
                    from sff.recent_files import get_recent_files_manager
                    get_recent_files_manager().add(lua_file)
                except Exception:
                    pass

                return (ok, "Download complete" if ok else "DepotDownloaderMod reported failure")

            except Exception as e:
                logger.exception("download_game_ddmod failed: %s", e)
                return (False, str(e))

        def _on_done(result):
            if isinstance(result, tuple):
                ok, msg = result
            else:
                ok, msg = False, "Download failed"
            self._emit_task_result("download_ddmod", ok, msg, app_id=app_id)
            if ok:
                self._log_ui(f"DDMod terminé — notification d’activité Discord pour le jeu {app_id}")
                self.request_notify_gen.emit(str(app_id))
            else:
                self._log_ui(f"DDMod échec : {msg} (app_id={app_id})")

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(result=str)
    def get_avatar_base64(self):
        """Read the global GBE avatar from GSE Saves/settings/ and return a base64 data URL.
        Returns empty string if no avatar is set."""
        import base64
        from sff.fix_game.config_generator import _get_gbe_saves_root
        settings_dir = _get_gbe_saves_root() / "settings"
        for ext in (".png", ".jpg", ".jpeg"):
            avatar_file = settings_dir / f"account_avatar{ext}"
            if avatar_file.exists():
                try:
                    data = avatar_file.read_bytes()
                    b64 = base64.b64encode(data).decode("ascii")
                    mime = "image/png" if ext == ".png" else "image/jpeg"
                    return f"data:{mime};base64,{b64}"
                except Exception:
                    pass
        return ""

    @pyqtSlot(str, result=str)
    def set_global_avatar(self, source_path):
        """Copy source_path to GSE Saves/settings/account_avatar.{ext}.
        Removes any existing avatar files with other extensions first.
        Returns 'ok' on success or an error message."""
        import shutil
        from sff.fix_game.config_generator import _get_gbe_saves_root
        src = Path(source_path)
        if not src.exists():
            return f"File not found: {source_path}"
        ext = src.suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg"):
            return f"Unsupported format '{ext}' — use .png, .jpg, or .jpeg"
        settings_dir = _get_gbe_saves_root() / "settings"
        settings_dir.mkdir(parents=True, exist_ok=True)
        for old_ext in (".png", ".jpg", ".jpeg"):
            old = settings_dir / f"account_avatar{old_ext}"
            if old.exists() and old_ext != ext:
                try:
                    old.unlink()
                except Exception:
                    pass
        dst = settings_dir / f"account_avatar{ext}"
        try:
            shutil.copy2(src, dst)
            return "ok"
        except Exception as e:
            return str(e)

    @pyqtSlot(result=str)
    def get_installed_games(self):
        """Returns JSON array of installed games from ALL Steam library folders."""
        try:
            if not self._steam_path:
                return "[]"
            from sff.storage.vdf import get_steam_libs
            import os
            libs = list(get_steam_libs(self._steam_path))
            # Also scan common Windows drive paths
            if os.name == 'nt':
                from string import ascii_uppercase
                for drive_letter in ascii_uppercase:
                    drive = Path(f"{drive_letter}:/")
                    if not drive.exists():
                        continue
                    for subdir in ("SteamLibrary", "Steam", "Program Files (x86)/Steam",
                                   "Program Files/Steam", "Games/Steam"):
                        candidate = drive / subdir
                        steamapps = candidate / "steamapps"
                        if steamapps.exists() and candidate not in libs:
                            libs.append(candidate)
            games = []
            seen = set()
            for lib in libs:
                steamapps = lib / "steamapps"
                if not steamapps.exists():
                    continue
                for acf in steamapps.glob("appmanifest_*.acf"):
                    try:
                        text = acf.read_text(encoding="utf-8", errors="replace")
                        app_id = ""
                        name = ""
                        installdir = ""
                        for line in text.splitlines():
                            line = line.strip()
                            if '"appid"' in line:
                                app_id = line.split('"')[-2] if '"' in line else ""
                            elif '"name"' in line and not name:
                                name = line.split('"')[-2] if '"' in line else ""
                            elif '"installdir"' in line:
                                installdir = line.split('"')[-2] if '"' in line else ""
                        if not app_id or app_id in seen:
                            continue
                        # Skip if game folder doesn't exist
                        if installdir:
                            game_path = steamapps / "common" / installdir
                            if not game_path.exists():
                                continue
                        seen.add(app_id)
                        games.append({
                            "app_id": int(app_id) if app_id.isdigit() else 0,
                            "name": name or f"App {app_id}",
                            "installed": True,
                            "path": str(steamapps / "common" / installdir) if installdir else "",
                        })
                    except Exception:
                        continue
            games.sort(key=lambda g: g.get("name", "").lower())
            return json.dumps(games)
        except Exception:
            return "[]"

    @pyqtSlot(result=str)
    def get_fix_game_list(self):
        """Returns JSON list of games available for fixing."""
        return self.get_installed_games()

    @pyqtSlot(str, result=str)
    def extract_vdf_keys(self, vdf_path):
        """Extract depot keys from config.vdf."""
        try:
            from sff.storage.vdf import extract_depot_keys
            keys = extract_depot_keys(vdf_path or None)
            return json.dumps(keys or [])
        except Exception:
            return "[]"

    @pyqtSlot()
    def toggle_music(self):
        """Toggle background music on/off."""
        parent = self.parent()
        if parent and hasattr(parent, '_toggle_mute'):
            parent._toggle_mute()

    @pyqtSlot(result=str)
    def get_gse_identity(self):
        """Returns JSON {name, steam_id} from the GSE Saves global config, or empty object."""
        import configparser
        import os
        try:
            appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
            user_ini = Path(appdata) / "GSE Saves" / "settings" / "configs.user.ini"
            if not user_ini.exists():
                return json.dumps({})
            cfg = configparser.ConfigParser()
            cfg.read(str(user_ini), encoding="utf-8")
            return json.dumps({
                "name": cfg.get("user::general", "account_name", fallback="").strip(),
                "steam_id": cfg.get("user::general", "account_steamid", fallback="").strip(),
            })
        except Exception:
            return json.dumps({})

    @pyqtSlot(result=str)
    def get_all_settings(self):
        """Returns JSON object with all current settings for the Settings page."""
        from sff.storage.settings import load_all_settings
        from sff.structs import Settings
        saved = load_all_settings()
        result = {}
        for s in Settings:
            raw = saved.get(s.key_name)
            if raw is None:
                result[s.key_name] = ""
            elif s.hidden:
                result[s.key_name] = "[ENCRYPTED]" if raw else ""
            elif s.value.type == dict:
                result[s.key_name] = ""
            else:
                result[s.key_name] = str(raw)
        try:
            from sff.online_fix import online_fix_has_embedded_credentials

            result["online_fix_embedded"] = online_fix_has_embedded_credentials()
        except Exception:
            result["online_fix_embedded"] = False
        return json.dumps(result)

    @pyqtSlot(result=str)
    def get_game_list(self):
        """Returns JSON list of games from all Steam libraries (name + app_id + path).
        Same scan as get_installed_games but always includes path."""
        return self.get_installed_games()

    @pyqtSlot(str)
    def fetch_library_images(self, app_ids_json):
        """Async: fetch canonical image URLs for library games via Steam API.
        Emits task_finished with task='library_images' and images={appid: url}.
        """
        try:
            app_ids = [int(x) for x in json.loads(app_ids_json or '[]') if x]
        except Exception:
            app_ids = []

        def _do():
            image_urls, _ = _fetch_steam_image_urls(app_ids)
            return image_urls

        def _on_done(result):
            self.task_finished.emit(json.dumps({
                "task": "library_images",
                "success": True,
                "images": {str(k): v for k, v in result.items()},
            }))

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot()
    def load_library(self):
        """Async: scan installed games + fetch Steam API image URLs in one pass.
        Emits task_finished with task='library_loaded' and games=[{...}].
        Mirrors search_games so image_url is ready before card rendering.
        """
        def _do():
            games = json.loads(self.get_installed_games())
            if not games:
                return []
            app_ids = [g["app_id"] for g in games if g.get("app_id")]
            image_urls, _ = _fetch_steam_image_urls(app_ids)
            for g in games:
                g["image_url"] = image_urls.get(g["app_id"])
            return games

        def _on_done(games):
            self.task_finished.emit(json.dumps({
                "task": "library_loaded",
                "success": True,
                "games": games or [],
            }))

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str, result=str)
    def launch_game_as_admin(self, game_folder: str) -> str:
        """Lance l'exécutable principal détecté dans le dossier d'installation.

        Windows : ``ShellExecuteW`` avec verbe ``runas`` (UAC). Linux : ``Popen`` sans élévation.
        Le chemin doit être celui du dossier ``steamapps/common/<installdir>`` (comme dans la bibliothèque).
        """
        def _fail(msg: str) -> str:
            return json.dumps({"ok": False, "message": msg})

        folder = (game_folder or "").strip()
        if not folder:
            return _fail("Dossier du jeu inconnu.")
        try:
            game_r = Path(folder).resolve()
        except OSError:
            return _fail("Chemin du jeu invalide.")
        if not game_r.is_dir():
            return _fail("Le dossier d'installation du jeu est introuvable.")

        try:
            from sff.fix_game.goldberg_applier import GoldbergApplier
        except Exception as exc:
            logger.warning("launch_game_as_admin: GoldbergApplier — %s", exc)
            return _fail("Module de détection d'exécutable indisponible.")

        if sys.platform == "win32":
            main_exe = GoldbergApplier.find_main_exe(str(game_r))
            if not main_exe:
                return _fail("Aucun .exe utilisable trouvé dans le dossier du jeu.")
            exe_p = Path(main_exe)
            if not exe_p.is_file():
                return _fail("Fichier exécutable introuvable.")
            workdir = str(exe_p.parent)
            try:
                import ctypes

                ret = ctypes.windll.shell32.ShellExecuteW(
                    None,
                    "runas",
                    str(exe_p),
                    None,
                    workdir,
                    1,
                )
                if ret <= 32:
                    return _fail(
                        "Élévation refusée ou échec du lancement (UAC). "
                        f"Code Windows : {int(ret)}."
                    )
                return json.dumps(
                    {
                        "ok": True,
                        "exe": str(exe_p),
                        "message": "Lancement avec droits administrateur demandé.",
                    }
                )
            except Exception as e:
                logger.exception("launch_game_as_admin Windows")
                return _fail(str(e))

        if sys.platform == "linux":
            main_bin = GoldbergApplier.find_main_binary_linux(str(game_r))
            if not main_bin:
                return _fail("Aucun binaire Linux trouvé dans le dossier du jeu.")
            bpath = Path(main_bin)
            if not bpath.is_file():
                return _fail("Binaire introuvable.")
            try:
                subprocess.Popen([str(bpath)], cwd=str(bpath.parent))
            except Exception as e:
                return _fail(str(e))
            return json.dumps(
                {"ok": True, "exe": str(bpath), "message": "Jeu lancé (Linux, sans élévation)."}
            )

        return _fail("Plateforme non supportée pour ce lancement.")

    @pyqtSlot(str, str, str)
    def delete_game(self, app_id, game_path, mode):
        """Remove a game from the AppList and optionally delete its files.
        mode='applist' removes from AppList folder + all profiles only.
        mode='full' also deletes the ACF manifest and the game folder from disk.
        """
        def _do():
            import shutil
            app_id_int = int(app_id) if str(app_id).isdigit() else None
            if app_id_int is None:
                return (False, "Invalid App ID")

            removed_from_applist = False

            # --- Remove from AppList folder ---
            if hasattr(self._ui, 'app_list_man') and self._ui.app_list_man:
                folder = Path(self._ui.app_list_man.applist_folder)
                for f in list(folder.glob("*.txt")):
                    if not f.stem.isdigit():
                        continue
                    try:
                        if f.read_text(encoding="utf-8").strip() == str(app_id_int):
                            f.unlink()
                            removed_from_applist = True
                            break
                    except OSError:
                        pass
                if removed_from_applist:
                    remaining = sorted(
                        [f for f in folder.glob("*.txt") if f.stem.isdigit()],
                        key=lambda f: int(f.stem),
                    )
                    for i, f in enumerate(remaining):
                        target = folder / f"{i}.txt"
                        if f != target:
                            f.rename(target)

            # --- Remove from all saved profiles ---
            try:
                from sff.app_injector.applist_profiles import list_profiles, load_profile, save_profile
                for profile_name in list_profiles():
                    ids = load_profile(profile_name)
                    if ids and app_id_int in ids:
                        save_profile(profile_name, [i for i in ids if i != app_id_int])
            except Exception as e:
                logger.warning("delete_game: profile update failed: %s", e)

            if mode != "full":
                return (True, "Removed from AppList")

            # --- Delete game files (mode='full') ---
            files_deleted = False

            # Delete the ACF manifest
            if self._steam_path:
                try:
                    from sff.storage.vdf import get_steam_libs
                    for lib in get_steam_libs(self._steam_path):
                        acf = lib / "steamapps" / f"appmanifest_{app_id_int}.acf"
                        if acf.exists():
                            acf.unlink()
                            files_deleted = True
                            break
                except Exception as e:
                    logger.warning("delete_game: ACF removal failed: %s", e)

            # Delete the game folder
            if game_path:
                p = Path(game_path)
                if p.exists() and p.is_dir():
                    try:
                        shutil.rmtree(p, ignore_errors=False)
                        files_deleted = True
                    except Exception as e:
                        logger.warning("delete_game: folder removal failed: %s", e)

            if files_deleted:
                return (True, "Game removed from AppList and deleted from disk")
            return (True, "Removed from AppList (game folder not found or already gone)")

        def _on_done(result):
            if isinstance(result, tuple):
                ok, msg = result
                self._emit_task_result("delete_game", ok, msg, app_id=app_id)
            else:
                self._emit_task_result("delete_game", False, "Delete failed", app_id=app_id)

        self._run_async(_do, on_done=_on_done)

    # ── Google Drive auth ─────────────────────────────────────────

    @pyqtSlot()
    def gdrive_authorize(self):
        """Start the Google Drive OAuth flow in a background thread."""
        if not _cloud_saves_feature_allowed():
            self._emit_task_result("gdrive_authorize", False, _CLOUD_SAVES_DENIED_MSG)
            return

        def _do():
            from sff.google_drive import (
                authorize,
                oauth_credentials_configured,
                oauth_deps_installed,
            )

            if not oauth_deps_installed():
                return (
                    False,
                    "Google Drive indisponible : les bibliothèques OAuth Google ne sont pas "
                    "correctement incluses dans cette application (build PyInstaller incomplète). "
                    "Réinstalle la build officielle ou signale le problème.",
                )
            if not oauth_credentials_configured():
                return (
                    False,
                    "Identifiants OAuth Google non configurés : place « gdrive_oauth_client.json » "
                    "à la racine SFF ou dans sff/ avant le build PyInstaller, ou lance "
                    "« python write_gdrive_gc_secrets.py », ou définis "
                    "SLIMEDEALS_GDRIVE_CLIENT_ID / SLIMEDEALS_GDRIVE_CLIENT_SECRET "
                    "(fichier possible aussi sous %APPDATA%\\SlimeDeals).",
                )
            log_lines = []
            ok = authorize(log_func=log_lines.append)
            return (ok, "\n".join(log_lines))

        def _on_done(result):
            if isinstance(result, tuple):
                ok, msg = result
                if ok:
                    from sff.google_drive import get_service, get_user_email
                    svc = get_service()
                    email = get_user_email(svc) if svc else ""
                    self._emit_task_result("gdrive_authorize", True, msg, email=email)
                else:
                    self._emit_task_result("gdrive_authorize", False, msg)
            else:
                self._emit_task_result("gdrive_authorize", False, "Authorization failed")

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot()
    def gdrive_disconnect(self):
        """Supprime le jeton OAuth Google Drive enregistré localement."""
        from sff.google_drive import clear_saved_token

        try:
            clear_saved_token()
            self._emit_task_result("gdrive_disconnect", True, "Google Drive déconnecté.")
        except Exception as e:
            self._emit_task_result("gdrive_disconnect", False, str(e))

    @pyqtSlot(result=str)
    def gdrive_status(self):
        """Return GDrive connection status as JSON (synchronous)."""
        from sff.google_drive import (
            get_service,
            get_user_email,
            is_authenticated,
            is_available,
            oauth_credentials_configured,
            oauth_deps_installed,
        )

        if not is_available():
            return json.dumps(
                {
                    "available": False,
                    "connected": False,
                    "email": "",
                    "deps_installed": oauth_deps_installed(),
                    "credentials_configured": oauth_credentials_configured(),
                }
            )
        if not is_authenticated():
            return json.dumps({"available": True, "connected": False, "email": ""})
        svc = get_service()
        email = get_user_email(svc) if svc else ""
        return json.dumps({"available": True, "connected": bool(svc), "email": email})

    @pyqtSlot(str, str, result=str)
    def cloud_saves_self_test(self, steam_path: str, steam32_id: str) -> str:
        """Vérifie chemin Steam, dossier userdata et accès Google Drive — retour JSON pour le WebUI."""
        import sys
        from pathlib import Path

        from sff.cloud_saves import normalize_steam_userdata_folder_id

        steam_path = (steam_path or "").strip()
        steam32_raw = str(steam32_id or "").strip()
        msgs: list[str] = []
        out = {
            "ok": False,
            "steam_path_set": bool(steam_path),
            "steam_install_ok": False,
            "steam_exe_found": False,
            "userdata_id_set": bool(steam32_raw),
            "account_id": "",
            "userdata_folder_ok": False,
            "gdrive_oauth_available": False,
            "gdrive_deps_installed": True,
            "gdrive_credentials_configured": False,
            "gdrive_connected": False,
            "gdrive_backup_root_ok": False,
            "messages": msgs,
        }

        if not _cloud_saves_feature_allowed():
            msgs.append(_CLOUD_SAVES_DENIED_MSG)
            return json.dumps(out, ensure_ascii=False)

        if not steam_path:
            msgs.append("Chemin Steam vide — remplis le champ ou utilise Parcourir.")
            return json.dumps(out, ensure_ascii=False)

        root = Path(steam_path)
        if not root.exists():
            msgs.append("Ce dossier Steam n’existe pas sur le disque (chemin incorrect ?).")
            return json.dumps(out, ensure_ascii=False)
        if not root.is_dir():
            msgs.append("Le chemin Steam n’est pas un dossier.")
            return json.dumps(out, ensure_ascii=False)

        out["steam_install_ok"] = True
        if sys.platform == "win32":
            out["steam_exe_found"] = (root / "steam.exe").is_file()
            if not out["steam_exe_found"]:
                msgs.append("steam.exe introuvable ici — indique le dossier qui contient steam.exe.")
        else:
            out["steam_exe_found"] = (root / "steam.sh").is_file() or (root / "steam").is_file()
            if not out["steam_exe_found"]:
                msgs.append("steam / steam.sh introuvable dans ce dossier (installation Steam Linux).")

        sid = ""
        if steam32_raw:
            sid = normalize_steam_userdata_folder_id(steam32_raw)
            out["account_id"] = sid
            ud = root / "userdata" / sid
            out["userdata_folder_ok"] = ud.is_dir()
            if not out["userdata_folder_ok"]:
                msgs.append(
                    f"Dossier userdata introuvable : …/userdata/{sid}/ "
                    "(vérifie le numéro du dossier sous Steam/userdata/)."
                )
        else:
            msgs.append("ID userdata vide — le numéro du dossier sous Steam/userdata/.")

        try:
            from sff.google_drive import (
                get_backup_root,
                get_service,
                is_authenticated,
                is_available,
                oauth_credentials_configured,
                oauth_deps_installed,
            )

            out["gdrive_deps_installed"] = bool(oauth_deps_installed())
            out["gdrive_credentials_configured"] = bool(oauth_credentials_configured())
            out["gdrive_oauth_available"] = bool(is_available())
            if not out["gdrive_deps_installed"]:
                msgs.append(
                    "Bibliothèques Google (OAuth) absentes de cette build — problème d’empaquetage, "
                    "pas de configuration utilisateur."
                )
            elif not out["gdrive_credentials_configured"]:
                msgs.append("OAuth Google non configuré (client JSON / variables d’environnement).")
            elif not is_authenticated():
                msgs.append("Google Drive non connecté — clique sur « Se connecter à Google Drive ».")
            else:
                out["gdrive_connected"] = True
                svc = get_service()
                if not svc:
                    msgs.append("Impossible d’obtenir le service Google Drive.")
                else:
                    br = get_backup_root(svc)
                    if br:
                        out["gdrive_backup_root_ok"] = True
                    else:
                        msgs.append("Impossible d’accéder au dossier racine des sauvegardes sur Drive.")
        except Exception as exc:
            msgs.append(f"Erreur Google Drive : {exc}")

        out["ok"] = bool(
            out["steam_install_ok"]
            and out["steam_exe_found"]
            and out["userdata_id_set"]
            and out["userdata_folder_ok"]
            and out["gdrive_oauth_available"]
            and out["gdrive_connected"]
            and out["gdrive_backup_root_ok"]
        )
        if out["ok"]:
            msgs.insert(0, "Tout est OK — tu peux scanner les jeux ou lancer une sauvegarde.")
        return json.dumps(out, ensure_ascii=False)

    # ── All Save Locations ────────────────────────────────────────

    @pyqtSlot(str)
    def scan_all_save_locations(self, config_json):
        """Scan all emu save locations + Steam userdata. Emits task_finished with results list."""
        if not _cloud_saves_feature_allowed():
            self._emit_task_result(
                "scan_all_save_locations",
                False,
                _CLOUD_SAVES_DENIED_MSG,
                entries=[],
            )
            return

        def _do():
            config = json.loads(config_json)
            steam_path = config.get("steam_path", "").strip()
            steam32_id = str(config.get("steam32_id", "")).strip()
            from sff.cloud_saves import scan_all_save_locations as _scan
            entries = _scan(
                steam_path=steam_path or None,
                steam32_id=steam32_id or None,
            )
            return entries

        def _on_done(entries):
            if entries is None:
                entries = []
            self._emit_task_result("scan_all_save_locations", True, f"Found {len(entries)} save folder(s)", entries=entries)

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str)
    def backup_all_save_locations(self, config_json):
        """Backup all (or selected) save location entries using the configured provider."""
        if not _cloud_saves_feature_allowed():
            self._emit_task_result(
                "backup_all_save_locations",
                False,
                _CLOUD_SAVES_DENIED_MSG,
                log=_CLOUD_SAVES_DENIED_MSG,
            )
            return

        def _do():
            config = json.loads(config_json)
            entries = config.get("entries", [])
            provider = config.get("provider", "local").lower()
            dest_path = config.get("dest_path", "").strip()
            rclone_exe = config.get("rclone_exe", "").strip()
            remote_dest = config.get("remote_dest", "").strip()

            if not entries:
                return (False, "No entries to back up.", [])

            from sff.cloud_saves import (
                backup_save_location_local,
                backup_save_location_rclone,
                backup_save_location_gdrive,
            )

            log_lines = []
            succeeded = 0
            failed = 0
            total = len(entries)
            done = 0

            def _emit_backup_progress(label, s, f):
                self.download_progress.emit(json.dumps({
                    "task": "backup_progress",
                    "done": done, "total": total,
                    "percent": int(done / total * 100) if total > 0 else 0,
                    "current_label": label,
                    "succeeded": s, "failed": f,
                }))

            _emit_backup_progress("Starting...", 0, 0)

            if provider in ("local", "gdrive_sync"):
                if not dest_path:
                    return (False, "Destination folder not set.", [])
                for entry in entries:
                    result = backup_save_location_local(entry, dest_path, log_func=log_lines.append)
                    if result:
                        succeeded += 1
                    else:
                        failed += 1
                    done += 1
                    _emit_backup_progress(entry.get("label", ""), succeeded, failed)

            elif provider == "rclone":
                import threading
                import subprocess
                from concurrent.futures import ThreadPoolExecutor, as_completed
                if not rclone_exe:
                    bundled = WebBridge._get_bundled_tool_path("rclone")
                    rclone_exe = str(bundled) if bundled else ""
                if not rclone_exe or not remote_dest:
                    return (False, "rclone exe or remote destination not set.", [])
                lock = threading.Lock()
                _rclone_exe = rclone_exe
                _remote_dest = remote_dest

                import sys as _sys
                _no_window = {"creationflags": 0x08000000} if _sys.platform == "win32" else {}
                unique_locations = list({e["location"] for e in entries})
                for _loc in unique_locations:
                    subprocess.run(
                        [_rclone_exe, "mkdir",
                         _remote_dest.rstrip("/") + f"/SlimeDealsAllSaves/{_loc}"],
                        capture_output=True, stdin=subprocess.DEVNULL, timeout=30, **_no_window,
                    )

                def _backup_one_rclone(entry):
                    thread_log = []
                    ok = backup_save_location_rclone(
                        entry, _rclone_exe, _remote_dest, log_func=thread_log.append
                    )
                    with lock:
                        log_lines.extend(thread_log)
                    return ok

                with ThreadPoolExecutor(max_workers=10) as ex:
                    futures = {ex.submit(_backup_one_rclone, e): e for e in entries}
                    for fut in as_completed(futures):
                        e = futures[fut]
                        try:
                            ok = fut.result()
                        except Exception as exc:
                            ok = False
                            with lock:
                                log_lines.append(f"[FAIL] {e.get('label', '?')}: {exc}")
                        with lock:
                            if ok:
                                succeeded += 1
                            else:
                                failed += 1
                        done += 1
                        _emit_backup_progress(e.get("label", ""), succeeded, failed)

                subprocess.run(
                    [_rclone_exe, "dedupe", "--dedupe-mode", "newest",
                     _remote_dest.rstrip("/") + "/SlimeDealsAllSaves"],
                    capture_output=True, stdin=subprocess.DEVNULL, timeout=180, **_no_window,
                )

            elif provider == "gdrive_api":
                import threading
                from concurrent.futures import ThreadPoolExecutor, as_completed
                from sff.google_drive import (
                    get_service, get_backup_root, is_authenticated, get_or_create_folder,
                )
                if not is_authenticated():
                    return (False, "Google Drive not connected. Use Connect button first.", [])
                svc = get_service()
                if not svc:
                    return (False, "Could not connect to Google Drive.", [])
                root_id = get_backup_root(svc)
                if not root_id:
                    return (False, "Could not create backup root on Google Drive.", [])
                from pathlib import Path as _Path
                valid_entries = []
                for e in entries:
                    if _Path(e["source_path"]).exists():
                        valid_entries.append(e)
                    else:
                        failed += 1
                        log_lines.append(
                            f"[SKIP] Source not found: {e.get('label', '?')} ({e.get('source_path', '?')})"
                        )

                folder_cache = {}
                for loc in {e["location"] for e in valid_entries}:
                    loc_id = get_or_create_folder(svc, loc, root_id)
                    if loc_id:
                        folder_cache[(loc, root_id)] = loc_id
                lock = threading.Lock()

                def _backup_one_gdrive(entry):
                    thread_log = []
                    thread_svc = get_service()
                    if not thread_svc:
                        with lock:
                            log_lines.append(
                                f"[FAIL] {entry.get('label', '?')}: could not connect to Drive"
                            )
                        return False
                    thread_cache = dict(folder_cache)
                    ok = backup_save_location_gdrive(
                        entry, thread_svc, root_id,
                        log_func=thread_log.append,
                        folder_cache=thread_cache,
                    )
                    with lock:
                        log_lines.extend(thread_log)
                    return ok

                with ThreadPoolExecutor(max_workers=10) as ex:
                    futures = {ex.submit(_backup_one_gdrive, e): e for e in valid_entries}
                    for fut in as_completed(futures):
                        e = futures[fut]
                        try:
                            ok = fut.result()
                        except Exception as exc:
                            ok = False
                            with lock:
                                log_lines.append(f"[FAIL] {e.get('label', '?')}: {exc}")
                        with lock:
                            if ok:
                                succeeded += 1
                            else:
                                failed += 1
                        done += 1
                        _emit_backup_progress(e.get("label", ""), succeeded, failed)
            else:
                return (False, f"Provider '{provider}' not supported for all-saves backup.", [])

            ok = failed == 0
            msg = f"Backup complete: {succeeded} succeeded, {failed} failed"
            return (ok, msg, log_lines, provider, dest_path, rclone_exe, remote_dest)

        def _on_done(result):
            if isinstance(result, tuple) and len(result) >= 3:
                ok, msg, log_lines = result[0], result[1], result[2]
                self._emit_task_result("backup_all_save_locations", ok, msg, log="\n".join(log_lines))
                if ok and len(result) == 7:
                    _prov, _dest, _rclone_exe, _remote_dest = result[3], result[4], result[5], result[6]
                    import json as _json
                    from sff.storage.settings import set_setting as _set
                    from sff.structs import Settings as _S
                    if _prov in ('local', 'gdrive_sync'):
                        _cfg = {'provider': 'local', 'dest_path': _dest}
                    elif _prov == 'rclone':
                        _cfg = {'provider': 'rclone', 'rclone_exe': _rclone_exe, 'remote_dest': _remote_dest}
                    elif _prov == 'gdrive_api':
                        _cfg = {'provider': 'gdrive_api'}
                    else:
                        _cfg = None
                    if _cfg:
                        _set(_S.LAST_BACKUP_PROVIDER_CONFIG, _json.dumps(_cfg))
            else:
                self._emit_task_result("backup_all_save_locations", False, "Backup failed")

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str)
    def scan_backup_root(self, config_json):
        """Scan a backup root (local or GDrive) and return location/game tree."""
        try:
            _cfg = json.loads(config_json)
            _prov = str(_cfg.get("provider", "local")).lower()
        except Exception:
            _prov = "local"
        if _prov == "gdrive_api" and not _cloud_saves_feature_allowed():
            self._emit_task_result("scan_backup_root", False, _CLOUD_SAVES_DENIED_MSG, locations={})
            return

        def _do():
            config = json.loads(config_json)
            provider = config.get("provider", "local").lower()
            backup_root = config.get("backup_root", "").strip()

            if provider == "gdrive_api":
                from sff.google_drive import get_service, list_backup_locations, is_authenticated
                if not is_authenticated():
                    return (False, "Google Drive not connected.", {})
                svc = get_service()
                if not svc:
                    return (False, "Could not connect to Google Drive.", {})
                locations = list_backup_locations(svc)
                return (True, "", locations)
            elif provider == "rclone":
                rclone_exe = config.get("rclone_exe", "").strip()
                remote_dest = config.get("remote_dest", "").strip()
                if not rclone_exe:
                    bundled = WebBridge._get_bundled_tool_path("rclone")
                    rclone_exe = str(bundled) if bundled else ""
                if not rclone_exe or not remote_dest:
                    return (False, "rclone exe or remote destination not set.", {})
                from sff.cloud_saves import scan_backup_root_rclone
                locations = scan_backup_root_rclone(rclone_exe, remote_dest)
                return (True, "", locations)
            else:
                if not backup_root:
                    return (False, "Backup root folder not set.", {})
                from sff.cloud_saves import scan_backup_root_local
                locations = scan_backup_root_local(backup_root)
                return (True, "", locations)

        def _on_done(result):
            if isinstance(result, tuple):
                ok, msg, locations = result
                self._emit_task_result("scan_backup_root", ok, msg, locations=locations)
            else:
                self._emit_task_result("scan_backup_root", False, "Scan failed", locations={})

        self._run_async(_do, on_done=_on_done)

    @pyqtSlot(str)
    def restore_save_location(self, game_entry_json):
        """Restore a single game's saves from backup to its original source_path."""
        if not _cloud_saves_feature_allowed():
            self._emit_task_result(
                "restore_save_location",
                False,
                _CLOUD_SAVES_DENIED_MSG,
                log=_CLOUD_SAVES_DENIED_MSG,
            )
            return

        def _do():
            game_entry = json.loads(game_entry_json)
            log_lines = []
            from sff.cloud_saves import restore_save_entry
            ok = restore_save_entry(game_entry, log_func=log_lines.append)
            msg = "Restore complete" if ok else "Restore failed — check log"
            return (ok, msg, log_lines)

        def _on_done(result):
            if isinstance(result, tuple):
                ok, msg, log_lines = result
                self._emit_task_result("restore_save_location", ok, msg, log="\n".join(log_lines))
            else:
                self._emit_task_result("restore_save_location", False, "Restore failed")

        self._run_async(_do, on_done=_on_done)


def _fetch_steam_image_urls(app_ids):
    """Batch-fetch canonical image URLs via Steam IStoreBrowseService/GetItems/v1.

    Returns (images, types) where:
      images: dict mapping appid (int) -> canonical URL string
      types:  dict mapping appid (int) -> Steam app type int
                (1=game, 2=dlc, 3=demo, 13=music, etc.)
    On any network or parse error returns ({}, {}) so callers fall back gracefully.
    """
    if not app_ids:
        return {}, {}
    import json as _json
    import urllib.request as _req
    import urllib.parse as _urlparse
    result = {}
    types = {}
    try:
        payload = {
            "ids": [{"appid": aid} for aid in app_ids],
            "context": {"language": "english", "country_code": "US"},
            "data_request": {"include_assets": True},
        }
        url = (
            "https://api.steampowered.com/IStoreBrowseService/GetItems/v1?input_json="
            + _urlparse.quote(_json.dumps(payload, separators=(",", ":")))
        )
        request = _req.Request(url, headers={"User-Agent": "SlimeDeals/5.4.0"})
        with _req.urlopen(request, timeout=5) as resp:
            data = _json.loads(resp.read())
        for item in data.get("response", {}).get("store_items", []):
            appid = item.get("appid")
            header = (item.get("assets") or {}).get("header", "")
            if appid and header:
                result[appid] = (
                    f"https://shared.steamstatic.com/store_item_assets/steam/apps/{appid}/{header}"
                )
            if appid:
                types[appid] = int(item.get("type") or 1)
    except Exception as e:
        logger.debug("Steam image batch fetch failed: %s", e)
    return result, types


_STEAM_APPLIST_CACHE = None
_STEAM_APPLIST_CACHE_TIME = 0.0

_NONGAME_NAME_KW = ("soundtrack", "art book", "artbook", " ost", "music pack", "digital artbook")

_NON_GAME_TYPES = frozenset({2, 4, 6, 7, 9, 10, 11, 12, 13, 14})


def _load_steam_applist():
    """Download and cache the full Steam app list (ISteamApps/GetAppList/v2). Refreshes every 24h."""
    global _STEAM_APPLIST_CACHE, _STEAM_APPLIST_CACHE_TIME
    import time
    import urllib.request as _req
    import json as _json
    now = time.time()
    if _STEAM_APPLIST_CACHE is not None and (now - _STEAM_APPLIST_CACHE_TIME) < 86400:
        return _STEAM_APPLIST_CACHE
    try:
        url = "https://api.steampowered.com/ISteamApps/GetAppList/v2/?format=json"
        req = _req.Request(url, headers={"User-Agent": "SlimeDeals/5.4.0"})
        with _req.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read())
        apps = data.get("applist", {}).get("apps", [])
        if apps:
            _STEAM_APPLIST_CACHE = apps
            _STEAM_APPLIST_CACHE_TIME = now
            logger.debug("Steam applist loaded: %d apps", len(apps))
            return apps
    except Exception as e:
        logger.debug("Steam applist fetch failed: %s", e)
    return _STEAM_APPLIST_CACHE or []


def _search_steam_catalog(query, offset, per_page):
    """Fallback store search using full Steam public app list when Hubcap is unavailable."""
    apps = _load_steam_applist()
    if not apps:
        return {"games": [], "total": 0, "fallback": True}
    if query:
        q = query.lower()
        apps = [a for a in apps if q in a.get("name", "").lower()]
    total = len(apps)
    page_apps = apps[offset: offset + per_page]
    app_ids = [a["appid"] for a in page_apps if a.get("appid")]
    image_urls, type_map = _fetch_steam_image_urls(app_ids)
    games = []
    for a in page_apps:
        appid = a.get("appid", 0)
        if type_map.get(appid) in _NON_GAME_TYPES:
            continue
        name_lc = a.get("name", f"App {appid}").lower()
        if any(kw in name_lc for kw in _NONGAME_NAME_KW):
            continue
        games.append({
            "app_id": appid,
            "name": a.get("name", f"App {appid}"),
            "last_updated": "",
            "status": "",
            "size": 0,
            "image_url": image_urls.get(appid),
        })
    return {"games": games, "total": total, "fallback": True}


def _format_size(size_bytes):
    """Format bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
