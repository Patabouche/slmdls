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

"""Clé API ManifestHub (optionnelle) — uniquement depuis les réglages, sans invite CLI."""

import logging
import time

logger = logging.getLogger(__name__)


def _key_usable() -> bool:
    """True si une clé est enregistrée et, si une date d’expiration est connue, qu’elle n’est pas dépassée."""
    from sff.storage.settings import get_setting
    from sff.structs import Settings

    key = (get_setting(Settings.MANIFESTHUB_API_KEY) or "").strip()
    if not key:
        return False
    expiry_str = get_setting(Settings.MANIFESTHUB_KEY_EXPIRY)
    if not expiry_str:
        return True
    try:
        return time.time() < float(expiry_str)
    except (ValueError, TypeError):
        return True


def get_manifesthub_api_key():
    """
    Renvoie la clé ManifestHub si configurée et utilisable, sinon None.

    Pas de navigateur ni de saisie interactive : les flux catalogue / CDN
    (ex. twentytwocloud) n’en dépendent pas ; pour ManifestHub uniquement,
    renseigner la clé dans les paramètres du launcher.
    """
    from sff.storage.settings import get_setting
    from sff.structs import Settings

    if not _key_usable():
        logger.debug("ManifestHub: pas de clé API valide — ignoré (voir Paramètres si besoin)")
        return None
    return (get_setting(Settings.MANIFESTHUB_API_KEY) or "").strip()


def save_manifesthub_key_with_expiry(key: str) -> None:
    """Enregistre une clé et sa date d’expiration (+24 h), ex. après saisie dans l’UI."""
    from sff.storage.settings import set_setting
    from sff.structs import Settings

    k = (key or "").strip()
    if not k:
        return
    set_setting(Settings.MANIFESTHUB_API_KEY, k)
    set_setting(Settings.MANIFESTHUB_KEY_EXPIRY, str(time.time() + 86_400))
