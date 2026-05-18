# SlimeDeals - Steam game setup and manifest tool (SFF)
# Copyright (c) 2025-2026 Midrag (https://github.com/Midrags)
#
# Notification de mise à jour du launcher (lien slimedeals.fr — pas d’install automatique).

from __future__ import annotations

import json
import logging
import os

from sff.strings import LAUNCHER_DOWNLOAD_PAGE_URL, VERSION
from sff.updater import Updater

log = logging.getLogger("sff")

MANDATORY_UPDATE_POLL_INTERVAL_MS = 5 * 60 * 1000
MANDATORY_UPDATE_FIRST_POLL_MS = 10_000


def update_disabled_by_env() -> bool:
    v = os.environ.get("SLIMEDEALS_NO_AUTO_UPDATE", "").strip().lower()
    return v in ("1", "true", "yes", "on")


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


def _inject_launcher_update_modal(window, release: dict) -> bool:
    """Affiche la modale WebUI ; False si la page n’est pas prête."""
    web = getattr(window, "_web_view", None)
    if web is None or web.page() is None:
        return False
    remote = _remote_version_label(release)
    payload = json.dumps(
        {
            "current": VERSION,
            "remote": remote,
            "url": LAUNCHER_DOWNLOAD_PAGE_URL,
        },
        ensure_ascii=False,
    )
    js = (
        "try { if (window.SlimeDealsLauncherUpdate && "
        "window.SlimeDealsLauncherUpdate.show) { "
        f"window.SlimeDealsLauncherUpdate.show({payload}); "
        "} } catch (e) { console.warn(e); }"
    )
    web.page().runJavaScript(js)
    return True


def notify_launcher_update_available(window, release: dict) -> None:
    """
    Affiche une fois par session et par tag GitHub la modale « nouvelle mise à jour »
    avec lien vers slimedeals.fr/launcher.
    """
    tag = (release.get("tag_name") or "").strip()
    if not tag:
        return
    shown = getattr(window, "_launcher_update_notice_tag", None)
    if shown == tag:
        return

    if not _inject_launcher_update_modal(window, release):
        window._pending_launcher_update_release = release
        log.info(
            "[Mise à jour] v%s disponible — notification différée (UI web pas encore prête).",
            _remote_version_label(release),
        )
        return

    window._launcher_update_notice_tag = tag
    window._pending_launcher_update_release = None
    log.info(
        "[Mise à jour] Notification affichée : %s → %s (%s)",
        VERSION,
        _remote_version_label(release),
        LAUNCHER_DOWNLOAD_PAGE_URL,
    )


def flush_pending_launcher_update_notice(window) -> None:
    """À appeler après chargement de l’UI principale (index.html)."""
    release = getattr(window, "_pending_launcher_update_release", None)
    if not release:
        return
    notify_launcher_update_available(window, release)


def run_mandatory_version_gate_if_outdated(window) -> None:
    """Timer : compare à GitHub et affiche la modale si une version plus récente existe."""
    if update_disabled_by_env():
        return
    is_newer, release = Updater.update_available()
    Updater.log_version_compare(release, is_newer, context="périodique (5 min)")
    if not is_newer or release is None:
        return
    notify_launcher_update_available(window, release)


# Compatibilité (plus de porte bloquante ni d’install auto)
def run_mandatory_version_gate(parent) -> None:
    run_mandatory_version_gate_if_outdated(parent)
