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

"""Mise à jour obligatoire (exe Windows PyInstaller) — compare à GitHub Releases (slmdls)."""

from __future__ import annotations

import logging
import os
import sys

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from sff.strings import RELEASE_PAGE_URL, VERSION
from sff.updater import Updater

log = logging.getLogger("sff")

# Vérification pendant que le launcher est ouvert (ms)
MANDATORY_UPDATE_POLL_INTERVAL_MS = 5 * 60 * 1000
MANDATORY_UPDATE_FIRST_POLL_MS = 10_000


def is_frozen_windows() -> bool:
    return sys.platform == "win32" and getattr(sys, "frozen", False)


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


def _apply_update_from_release(release: dict) -> bool:
    from sff.github_release_apply import apply_windows_frozen_update

    return apply_windows_frozen_update(release, announce=lambda m: log.info("%s", m))


class MandatoryUpdateDialog(QDialog):
    """Sans bouton Fermer : mise à jour ou quitter l'application."""

    def __init__(self, parent, release: dict):
        super().__init__(parent)
        self._release = release
        tag = (release.get("tag_name") or "?").strip()
        self.setWindowTitle("Mise à jour obligatoire")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.CustomizeWindowHint
        )
        lay = QVBoxLayout(self)
        lay.addWidget(
            QLabel(
                f"<p><b>Une nouvelle version est disponible ({tag}).</b></p>"
                f"<p>Ta version actuelle : <b>{VERSION}</b></p>"
                "<p>Tu dois mettre à jour pour continuer à utiliser SlimeDeals.</p>"
            )
        )
        box = QDialogButtonBox()
        self._btn_upd = box.addButton(
            "Mettre à jour maintenant", QDialogButtonBox.ButtonRole.ActionRole
        )
        self._btn_open = box.addButton(
            "Ouvrir la page des téléchargements", QDialogButtonBox.ButtonRole.ActionRole
        )
        self._btn_quit = box.addButton("Quitter", QDialogButtonBox.ButtonRole.ActionRole)
        lay.addWidget(box)
        self._btn_upd.clicked.connect(self._on_update)
        self._btn_open.clicked.connect(self._open_releases)
        self._btn_quit.clicked.connect(self._on_quit)

    def _open_releases(self) -> None:
        QDesktopServices.openUrl(QUrl(RELEASE_PAGE_URL))

    def _on_quit(self) -> None:
        sys.exit(0)

    def _on_update(self) -> None:
        if _apply_update_from_release(self._release):
            os._exit(0)
        QMessageBox.critical(
            self,
            "Échec de la mise à jour",
            "La mise à jour automatique a échoué (réseau, antivirus, ou fichier manquant sur GitHub).\n\n"
            "Utilise « Ouvrir la page des téléchargements », récupère le zip Windows indiqué sur la release, "
            "puis remplace ton dossier d'installation.",
        )


def run_mandatory_version_gate(parent) -> None:
    """
    Tant que l'exe est en retard sur GitHub : affiche le dialogue (bloquant).
    Retourne seulement si la version est à jour ou si la vérification est désactivée / indisponible.
    """
    if not is_frozen_windows():
        return
    while True:
        outdated, release = check_outdated_vs_github()
        if not outdated or release is None:
            return
        MandatoryUpdateDialog(parent, release).exec()


def run_mandatory_version_gate_if_outdated(parent) -> None:
    """Timer : revérifie GitHub toutes les 5 min (premier passage ~10 s après l'ouverture)."""
    if sys.platform != "win32":
        return
    if update_disabled_by_env():
        return
    from sff.updater import Updater

    frozen = getattr(sys, "frozen", False)
    is_newer, release = Updater.update_available()
    ctx = (
        "périodique (5 min)"
        if frozen
        else "périodique (5 min, Python — log seulement, pas d'install exe)"
    )
    Updater.log_version_compare(release, is_newer, context=ctx)
    if not frozen:
        return
    if not is_newer or release is None:
        return
    MandatoryUpdateDialog(parent, release).exec()
