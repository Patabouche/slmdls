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

"""Mise à jour automatique au démarrage (exe Windows gelé par PyInstaller)."""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger("sff")


def maybe_auto_update_frozen_windows() -> None:
    """
    Compare la version locale à la dernière release GitHub (slmdls) ; si plus récente,
    télécharge le zip, lance le script de mise à jour et quitte (redémarrage de l'exe).

    Désactiver : variable d'environnement SLIMEDEALS_NO_AUTO_UPDATE=1 (ou true / yes).
    """
    v = os.environ.get("SLIMEDEALS_NO_AUTO_UPDATE", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        from sff.strings import VERSION
        from sff.updater import Updater
        from sff.github_release_apply import apply_windows_frozen_update

        is_newer, release = Updater.update_available()
        if not is_newer or not release:
            return
        tag = (release.get("tag_name") or "").strip()
        logger.info("Mise à jour auto : release %s > version locale %s", tag, VERSION)
        if apply_windows_frozen_update(release, announce=lambda m: logger.info("%s", m)):
            logger.info("Mise à jour : installation lancée ; fermeture du processus.")
            os._exit(0)
    except Exception:
        logger.exception("Mise à jour automatique au démarrage échouée — lancement normal.")
