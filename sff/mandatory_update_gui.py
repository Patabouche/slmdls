# SlimeDeals - Steam game setup and manifest tool (SFF)
# Copyright (c) 2025-2026 Midrag (https://github.com/Midrags)
#
# Mise à jour obligatoire du launcher (pas de « Plus tard »).

from __future__ import annotations

import json
import logging
import os

from sff.strings import LAUNCHER_DOWNLOAD_PAGE_URL, VERSION
from sff.updater import Updater

log = logging.getLogger("sff")

MANDATORY_UPDATE_POLL_INTERVAL_MS = 5 * 60 * 1000
MANDATORY_UPDATE_FIRST_POLL_MS = 0

LAUNCHER_UPDATE_BLOCK_MSG = (
    "Mise à jour du launcher obligatoire. Télécharge la dernière version sur slimedeals.fr."
)


def update_disabled_by_env() -> bool:
    v = os.environ.get("SLIMEDEALS_NO_AUTO_UPDATE", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def launcher_update_blocks_usage(window) -> bool:
    return bool(window and getattr(window, "_launcher_update_required", False))


def set_launcher_update_required(window, required: bool, release: dict | None = None) -> None:
    window._launcher_update_required = bool(required)
    if required and release:
        window._pending_launcher_update_release = release
    elif not required:
        window._pending_launcher_update_release = None
    _inject_launcher_update_block_state(window, required)


def check_outdated_vs_github() -> tuple[bool, dict | None]:
    """Retourne (True, release) si la release GitHub est strictement plus récente que VERSION."""
    if update_disabled_by_env():
        return False, None
    try:
        is_newer, release = Updater.update_available()
        if not release:
            return False, None
        return bool(is_newer), release
    except Exception:
        log.exception("check_outdated_vs_github")
        return False, None


def _remote_version_label(release: dict) -> str:
    tag = (release.get("tag_name") or "").strip()
    return tag.lstrip("vV") or "?"


def _inject_launcher_update_block_state(window, blocked: bool) -> None:
    web = getattr(window, "_web_view", None)
    if web is None or web.page() is None:
        return
    flag = "true" if blocked else "false"
    js = (
        f"try {{ window.__SLIMEDEALS_LAUNCHER_UPDATE_REQUIRED__ = {flag}; "
        "if (!" + flag + " && document.body) { "
        "document.body.classList.remove('sd-launcher-update-blocked'); } "
        "} catch (e) { console.warn(e); }"
    )
    web.page().runJavaScript(js)


def _inject_launcher_update_modal(window, release: dict) -> bool:
    """Affiche la modale WebUI bloquante ; False si la page n’est pas prête."""
    web = getattr(window, "_web_view", None)
    if web is None or web.page() is None:
        return False
    remote = _remote_version_label(release)
    payload = json.dumps(
        {
            "current": VERSION,
            "remote": remote,
            "url": LAUNCHER_DOWNLOAD_PAGE_URL,
            "mandatory": True,
        },
        ensure_ascii=False,
    )
    js = (
        "(function(){"
        "try {"
        f"var opts = {payload};"
        "window.__SLIMEDEALS_LAUNCHER_UPDATE_REQUIRED__ = true;"
        "if (window.SlimeDealsLauncherUpdate && window.SlimeDealsLauncherUpdate.show) {"
        "window.SlimeDealsLauncherUpdate.show(opts); return;"
        "}"
        "var m = document.getElementById('launcher-update-modal');"
        "if (!m) {"
        "m = document.createElement('div');"
        "m.id = 'launcher-update-modal';"
        "m.className = 'modal launcher-update-mandatory';"
        "m.setAttribute('role','alertdialog');"
        "m.innerHTML = '<div class=\"modal-overlay\" data-no-close=\"1\"></div>"
        "<div class=\"modal-content\" style=\"max-width:420px;margin:10vh auto;padding:24px;"
        "background:#151520;border:1px solid rgba(124,92,191,.35);border-radius:16px;"
        "text-align:center;color:#e8e8f0;font-family:Segoe UI,system-ui,sans-serif;\">"
        "<h2 style=\"margin:0 0 12px;font-size:18px;\">Mise à jour obligatoire</h2>"
        "<p style=\"margin:0 0 10px;font-size:14px;\">Télécharge la version <strong id=\"lu-remote\"></strong> "
        "pour continuer (actuelle : <strong id=\"lu-current\"></strong>).</p>"
        "<p style=\"margin:0 0 12px;font-size:12px;line-height:1.55;text-align:left;padding:10px 12px;"
        "border-radius:10px;background:rgba(251,146,60,.12);border:1px solid rgba(251,146,60,.35);color:#fde68a;\">"
        "<strong style=\"color:#fdba74;\">Important — avant l'installation :</strong> désactive "
        "<strong>Windows Defender</strong> (protection en temps réel). Le launcher installe des jeux et "
        "applique le correctif Steam pour les titres marqués « Acheter » — Defender peut bloquer "
        "ou supprimer ces fichiers (faux positifs).</p>"
        "<button type=\"button\" id=\"lu-dl-btn\" style=\"margin-top:14px;padding:10px 18px;"
        "border:none;border-radius:10px;background:#7c5cbf;color:#fff;font-weight:700;cursor:pointer;\">"
        "Télécharger sur slimedeals.fr</button></div>';"
        "document.body.appendChild(m);"
        "document.getElementById('lu-dl-btn').onclick = function(){"
        "if (window.qt && window.qt.webChannelTransport) {"
        "/* bridge via QWebChannel si dispo */"
        "}"
        "window.open(opts.url || 'https://slimedeals.fr/launcher','_blank');"
        "};"
        "}"
        "var c = document.getElementById('launcher-update-current') || document.getElementById('lu-current');"
        "var r = document.getElementById('launcher-update-remote') || document.getElementById('lu-remote');"
        "if (c) c.textContent = opts.current || '—';"
        "if (r) r.textContent = opts.remote || '—';"
        "m.classList.remove('hidden');"
        "document.body.classList.add('sd-launcher-update-blocked','sd-modal-open');"
        "var card = document.getElementById('auth-card');"
        "if (card) card.style.pointerEvents = 'none';"
        "} catch (e) { console.warn(e); }"
        "})();"
    )
    web.page().runJavaScript(js)
    return True


def notify_launcher_update_available(window, release: dict) -> None:
    """
    Bloque l'utilisation du launcher tant qu'une version plus récente existe sur GitHub.
    Modale non fermable — seul le téléchargement sur slimedeals.fr est proposé.
    """
    if not release:
        return
    set_launcher_update_required(window, True, release)

    if not _inject_launcher_update_modal(window, release):
        log.info(
            "[Mise à jour] v%s obligatoire — notification différée (UI web pas encore prête).",
            _remote_version_label(release),
        )
        return

    log.info(
        "[Mise à jour] Blocage actif : %s → %s (%s)",
        VERSION,
        _remote_version_label(release),
        LAUNCHER_DOWNLOAD_PAGE_URL,
    )


def clear_launcher_update_required(window) -> None:
    if not getattr(window, "_launcher_update_required", False):
        return
    set_launcher_update_required(window, False)
    web = getattr(window, "_web_view", None)
    if web is None or web.page() is None:
        return
    js = (
        "try { window.__SLIMEDEALS_LAUNCHER_UPDATE_REQUIRED__ = false; "
        "document.body.classList.remove('sd-launcher-update-blocked'); "
        "var m = document.getElementById('launcher-update-modal'); "
        "if (m) m.classList.add('hidden'); "
        "} catch (e) { console.warn(e); }"
    )
    web.page().runJavaScript(js)
    log.info("[Mise à jour] Launcher à jour — blocage levé (%s).", VERSION)


def apply_startup_outdated_state(window) -> None:
    """Applique le résultat de la vérification GitHub faite avant l'affichage de la fenêtre."""
    if update_disabled_by_env():
        return
    try:
        from sff.startup_update import pop_startup_outdated_release

        is_newer, release = pop_startup_outdated_release()
    except Exception:
        return
    if is_newer and release:
        notify_launcher_update_available(window, release)


def flush_pending_launcher_update_notice(window) -> None:
    """À appeler après chargement de l’UI (auth ou index.html)."""
    if getattr(window, "_launcher_update_required", False):
        release = getattr(window, "_pending_launcher_update_release", None)
        if release:
            notify_launcher_update_available(window, release)
        return
    release = getattr(window, "_pending_launcher_update_release", None)
    if release:
        notify_launcher_update_available(window, release)


def run_mandatory_version_gate_if_outdated(window) -> None:
    """Compare à GitHub et active le blocage si une version plus récente existe."""
    if update_disabled_by_env():
        return
    is_newer, release = Updater.update_available()
    Updater.log_version_compare(release, is_newer, context="périodique (5 min)")
    if is_newer and release:
        notify_launcher_update_available(window, release)
        return
    clear_launcher_update_required(window)


def run_mandatory_version_gate(parent) -> None:
    run_mandatory_version_gate_if_outdated(parent)
