# SlimeDeals - Steam game setup and manifest tool (SFF)
# Copyright (c) 2025-2026 Midrag (https://github.com/Midrags)
#
# This file is part of SlimeDeals.
#
# SlimeDeals is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SlimeDeals is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SlimeDeals.  If not, see <https://www.gnu.org/licenses/>.

"""Mise à jour au démarrage (exe Windows PyInstaller) + journalisation claire."""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger("sff")


def maybe_auto_update_frozen_windows() -> None:
    """
    Conservé pour compatibilité : délègue au flux unifié (log + auto + porte obligatoire).
    Préférer ``run_frozen_windows_startup_updates`` depuis Main_gui.
    """
    run_frozen_windows_startup_updates()


def run_frozen_windows_startup_updates() -> None:
    """
    Exe Windows uniquement : interroge GitHub (slmdls), écrit une ligne [Mise à jour] en INFO,
    tente une mise à jour silencieuse si nécessaire, puis dialogue bloquant si toujours obsolète.

    Désactiver : SLIMEDEALS_NO_AUTO_UPDATE=1
    """
    v = os.environ.get("SLIMEDEALS_NO_AUTO_UPDATE", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        logger.info("[Mise à jour] Vérifications désactivées (SLIMEDEALS_NO_AUTO_UPDATE).")
        return
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        from sff.github_release_apply import apply_windows_frozen_update
        from sff.mandatory_update_gui import MandatoryUpdateDialog
        from sff.updater import Updater

        is_newer, release = Updater.update_available()
        Updater.log_version_compare(release, is_newer, context="au lancement")

        if is_newer and release:
            logger.info("[Mise à jour] Tentative de mise à jour automatique avant l'interface…")
            if apply_windows_frozen_update(
                release,
                announce=lambda m: logger.info("%s", m),
            ):
                logger.info("[Mise à jour] Script d'installation lancé — fermeture du processus.")
                os._exit(0)

        while True:
            is_newer, release = Updater.update_available()
            Updater.log_version_compare(release, is_newer, context="porte obligatoire")
            if not is_newer or release is None:
                return
            MandatoryUpdateDialog(None, release).exec()
    except Exception:
        logger.exception("[Mise à jour] Erreur au démarrage — poursuite du lancement.")
