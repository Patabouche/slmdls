# SlimeDeals - Steam game setup and manifest tool (SFF)
# Copyright (c) 2025-2026 Midrag (https://github.com/Midrags)
#
# Vérification de version au démarrage (journalisation uniquement — pas d’install auto).

from __future__ import annotations

import logging
import os

logger = logging.getLogger("sff")

_startup_outdated: bool = False
_startup_release: dict | None = None


def pop_startup_outdated_release() -> tuple[bool, dict | None]:
    """État détecté au lancement (avant affichage de la fenêtre principale)."""
    global _startup_outdated, _startup_release
    outdated, release = _startup_outdated, _startup_release
    _startup_outdated = False
    _startup_release = None
    return outdated, release


def maybe_auto_update_frozen_windows() -> None:
    """Compatibilité : délègue à ``run_frozen_windows_startup_updates``."""
    run_frozen_windows_startup_updates()


def run_frozen_windows_startup_updates() -> None:
    """
    Au lancement : interroge GitHub (slmdls), journalise la comparaison de version.
    La notification utilisateur est gérée par la fenêtre principale (modale WebUI).

    Désactiver : SLIMEDEALS_NO_AUTO_UPDATE=1
    """
    v = os.environ.get("SLIMEDEALS_NO_AUTO_UPDATE", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        logger.info("[Mise à jour] Vérifications désactivées (SLIMEDEALS_NO_AUTO_UPDATE).")
        return
    try:
        from sff.updater import Updater

        is_newer, release = Updater.update_available()
        Updater.log_version_compare(release, is_newer, context="au lancement")
        if is_newer and release:
            global _startup_outdated, _startup_release
            _startup_outdated = True
            _startup_release = release
            tag = (release.get("tag_name") or "?").strip()
            logger.info(
                "[Mise à jour] Nouvelle version détectée (%s) — "
                "mise à jour obligatoire sur https://slimedeals.fr/launcher.",
                tag,
            )
    except Exception:
        logger.exception("[Mise à jour] Erreur au démarrage — poursuite du lancement.")
