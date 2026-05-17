# SlimeDeals — vérification session launcher (API compte) sans dépendance PyQt.
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_API_BASE = os.getenv("SLIMEDEALS_API", "https://slimedeals.fr").rstrip("/")
_AUTH_FILE = Path.home() / ".slimedeals" / "auth.json"

_CACHE: dict[str, Any] = {"t": 0.0, "result": None}
_VERIFY_TTL_SEC = 90.0


def invalidate_launcher_verify_cache() -> None:
    """À appeler après login / logout / sync profil pour forcer une nouvelle vérif."""
    _CACHE["t"] = 0.0
    _CACHE["result"] = None


def fetch_launcher_banner() -> dict:
    """GET /api/launcher/banner — public. Retourne {text, rev} ou {text:'', rev:-1} en erreur."""
    req = urllib.request.Request(
        f"{_API_BASE}/api/launcher/banner",
        headers={
            "Accept": "application/json",
            "User-Agent": "SlimeDealsLauncher/1.0 (banner-poll)",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            code = resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")
            if code != 200:
                return {"text": "", "rev": -1}
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                return {"text": "", "rev": -1}
            if not isinstance(data, dict):
                return {"text": "", "rev": -1}
            return {
                "text": str(data.get("text") or ""),
                "rev": int(data.get("rev") or 0),
            }
    except urllib.error.HTTPError:
        return {"text": "", "rev": -1}
    except Exception:
        return {"text": "", "rev": -1}


def _hwid() -> str:
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


def _load_auth() -> dict:
    try:
        return json.loads(_AUTH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _api_post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
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
        return {"ok": False, "error": err_msg, "http_status": e.code}
    except Exception as exc:
        logger.debug("launcher_session api post: %s", type(exc).__name__)
        return {"ok": False, "error": "Serveur injoignable"}


def apply_verify_to_local_auth(verify_out: dict) -> None:
    """Met à jour auth.json avec le rang serveur (empêche un rank local falsifié)."""
    if not verify_out.get("ok"):
        return
    try:
        data = _load_auth()
        tok = (data.get("token") or "").strip()
        if not tok:
            return
        data["rank"] = verify_out.get("rank", data.get("rank", "free"))
        if "free_claimed" in verify_out:
            fc = verify_out.get("free_claimed")
            pend = str(data.get("free_catalog_pending_install") or "").strip()
            if fc is not None and str(fc).strip() != "":
                data["free_claimed"] = str(fc).strip()
            elif not pend:
                # Ne pas effacer free_claimed local pendant une install « pending » :
                # verify peut renvoyer null jusqu'à record_free_claim.
                data["free_claimed"] = None
        if "rank_expires_at" in verify_out:
            data["rank_expires_at"] = verify_out.get("rank_expires_at")
        _AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        _AUTH_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("apply_verify_to_local_auth: %s", e)


def verify_launcher_session(force_refresh: bool = False) -> dict:
    """
    POST /api/launcher/verify — token + HWID. Résultat mis en cache (TTL court).
    """
    now = time.time()
    if (
        not force_refresh
        and _CACHE["result"] is not None
        and (now - float(_CACHE["t"])) < _VERIFY_TTL_SEC
    ):
        return _CACHE["result"]

    auth = _load_auth()
    token = (auth.get("token") or "").strip()
    if not token:
        out: dict = {"ok": False, "error": "non_connecte"}
        _CACHE["t"] = now
        _CACHE["result"] = out
        return out

    out = _api_post("/api/launcher/verify", {"token": token, "hwid": _hwid()})
    _CACHE["t"] = now
    _CACHE["result"] = out
    return out


def fetch_launcher_notifications() -> dict:
    """POST /api/launcher/notifications — même auth que verify (token + HWID local)."""
    auth = _load_auth()
    token = (auth.get("token") or "").strip()
    if not token:
        return {"ok": False, "error": "non_connecte", "items": [], "unread": 0}
    return _api_post("/api/launcher/notifications", {"token": token, "hwid": _hwid()})


def mark_launcher_notifications_read(ids: list[int]) -> dict:
    """POST /api/launcher/notifications/read."""
    auth = _load_auth()
    token = (auth.get("token") or "").strip()
    if not token:
        return {"ok": False, "error": "non_connecte"}
    return _api_post(
        "/api/launcher/notifications/read",
        {"token": token, "hwid": _hwid(), "ids": ids},
    )
