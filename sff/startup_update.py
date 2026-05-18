# SlimeDeals - Steam game setup and manifest tool (SFF)
# Copyright (c) 2025-2026 Midrag (https://github.com/Midrags)
#
# Vérification de version au démarrage (journalisation uniquement — pas d’install auto).

from __future__ import annotations

import logging
import os

logger = logging.getLogger("sff")


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
            tag = (release.get("tag_name") or "?").strip()
            logger.info(
                "[Mise à jour] Nouvelle version détectée (%s) — "
                "téléchargement manuel sur https://slimedeals.fr/launcher (pas de MAJ auto).",
                tag,
            )
    except Exception:
        logger.exception("[Mise à jour] Erreur au démarrage — poursuite du lancement.")
