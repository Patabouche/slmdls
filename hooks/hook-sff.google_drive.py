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

# PyInstaller hook — sous-modules souvent omis par l’analyse statique (googleapiclient, etc.)

from PyInstaller.utils.hooks import collect_submodules

_pkgs = (
    "google.auth",
    "google.oauth2",
    "google_auth_oauthlib",
    "google_auth_httplib2",
    "googleapiclient",
    "google.api_core",
    "httplib2",
    "uritemplate",
)

hiddenimports = []
for _p in _pkgs:
    try:
        hiddenimports.extend(collect_submodules(_p))
    except Exception:
        pass

hiddenimports = sorted(set(hiddenimports))
