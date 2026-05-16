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

import asyncio
import re
import httpx
import json

from sff.http_utils import get_request
from sff.strings import GITHUB_RELEASE_OWNER, GITHUB_RELEASE_REPO, VERSION


def _parse_version(tag):
    # Strip leading 'v' if present (e.g. v4.5.0)
    s = tag.strip().lstrip("vV")
    parts = re.split(r"[.\-]", s)
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            break
    return tuple(out)


def is_newer_version(remote_tag, current):
    r = _parse_version(remote_tag)
    c = _parse_version(current)
    # Pad with zeros so (4, 5) compares equal to (4, 5, 0)
    n = max(len(r), len(c))
    r = r + (0,) * (n - len(r))
    c = c + (0,) * (n - len(c))
    return r > c


class Updater:

    _LATEST_URL = (
        f"https://api.github.com/repos/{GITHUB_RELEASE_OWNER}/{GITHUB_RELEASE_REPO}/releases/latest"
    )
    _RELEASES_URL = (
        f"https://api.github.com/repos/{GITHUB_RELEASE_OWNER}/{GITHUB_RELEASE_REPO}/releases"
    )
    _HEADERS = {"Accept": "application/vnd.github.v3+json", "User-Agent": "SlimeDeals-Updater"}

    @staticmethod
    def get_latest_stable():
        resp = asyncio.run(
            get_request(
                Updater._LATEST_URL,
                "json",
                headers=Updater._HEADERS,
            )
        )
        if resp is not None:
            return resp
        # Fallback: /releases/latest can 404 if latest is draft; fetch list and take first non-draft
        list_resp = asyncio.run(
            get_request(
                Updater._RELEASES_URL,
                "json",
                headers=Updater._HEADERS,
            )
        )
        if not isinstance(list_resp, list):
            return None
        for release in list_resp:
            if release.get("draft") is True or release.get("prerelease") is True:
                continue
            return release
        return None

    @staticmethod
    def get_latest_prerelease():
        url = Updater._RELEASES_URL
        while True:
            resp = httpx.get(url, headers=Updater._HEADERS)
            releases = json.loads(resp.text)
            for release in releases:
                tag = release.get("tag_name")
                if tag and is_newer_version(tag, VERSION) and release.get("prerelease") is True:
                    return release
            if "next" in resp.links:
                url = resp.links["next"]["url"]
            else:
                break
        return None

    @staticmethod
    def log_version_compare(
        release: dict | None,
        is_outdated: bool,
        *,
        context: str = "vérification",
    ) -> None:
        """Log INFO lisible pour debug.log / traçabilité des mises à jour."""
        import logging

        log = logging.getLogger("sff")
        if not release:
            log.info(
                "[Mise à jour] (%s) Impossible de lire la dernière release "
                "— réseau indisponible, API ou aucune release publiée.",
                context,
            )
            return
        tag = (release.get("tag_name") or "").strip()
        name = (release.get("name") or "").strip()
        if is_outdated:
            log.info(
                "[Mise à jour] (%s) Mise à jour disponible : %s (%s) > version locale %s.",
                context,
                tag,
                name or "—",
                VERSION,
            )
        else:
            log.info(
                "[Mise à jour] (%s) À jour — version locale %s | dernière release distante %s (%s).",
                context,
                VERSION,
                tag,
                name or "—",
            )

    @staticmethod
    def update_available():
        release = Updater.get_latest_stable()
        if not release:
            return False, None
        remote_tag = release.get("tag_name") or ""
        if not is_newer_version(remote_tag, VERSION):
            return False, release
        return True, release
