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

"""Applique une mise à jour depuis une release GitHub (.zip) — exe PyInstaller Windows."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from sff.http_utils import download_to_path
from sff.structs import OSType
from sff.utils import root_folder

log = logging.getLogger(__name__)


def find_release_zip_asset(release: dict, os_type: OSType) -> tuple[str | None, str | None]:
    """Retourne (browser_download_url, nom fichier) pour un zip Windows/Linux."""
    assets = release.get("assets") or []
    for asset in assets:
        name = asset.get("name") or ""
        url = asset.get("browser_download_url")
        if not url:
            continue
        name_lower = name.lower()
        if os_type == OSType.WINDOWS and "windows" in name_lower and name_lower.endswith(".zip"):
            return url, name
        if os_type == OSType.LINUX and "linux" in name_lower and name_lower.endswith(".zip"):
            return url, name
    for asset in assets:
        name = asset.get("name") or ""
        url = asset.get("browser_download_url")
        if url and name.lower().endswith(".zip"):
            return url, name
    return None, None


def apply_windows_frozen_update(release: dict, *, announce=print) -> bool:
    """
    Télécharge le zip de la release, extrait, lance tmp_updater.bat (robocopy + redémarrage exe).
    Ne termine pas le processus : l'appelant doit appeler os._exit(0) si True.
    """
    download_url, asset_name = find_release_zip_asset(release, OSType.WINDOWS)
    if not download_url or not asset_name:
        log.warning("Release sans zip Windows utilisable : %s", release.get("tag_name"))
        return False
    app_dir = root_folder(outside_internal=True)
    update_zip = app_dir / "update.zip"
    tmp_update = app_dir / "tmp_update"
    announce(f"Downloading {asset_name}...")
    if not download_to_path(download_url, update_zip):
        announce("Download failed.")
        return False
    announce("Extracting update...")
    if tmp_update.exists():
        shutil.rmtree(tmp_update, ignore_errors=True)
    tmp_update.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(update_zip) as zf:
        zf.extractall(tmp_update)
    entries = list(tmp_update.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        inner = entries[0]
        for p in inner.iterdir():
            shutil.move(str(p), str(tmp_update / p.name))
        inner.rmdir()
    exe_name = Path(sys.executable).name
    convert = subprocess.list2cmdline
    internal_dir = str(app_dir / "_internal")
    updater_bat = app_dir / "tmp_updater.bat"
    updater_bat.write_text(
        "@echo off\n"
        "timeout /t 3 /nobreak >nul\n"
        f"taskkill /F /PID {os.getpid()} >nul 2>&1\n"
        "rmdir /s /q " + convert([internal_dir]) + " >nul 2>&1\n"
        "robocopy " + convert([str(tmp_update), str(app_dir)]) + " /E /IS /IT >nul 2>&1\n"
        "if %errorlevel% GEQ 8 (\n"
        "  echo Robocopy error! Update may be incomplete. Check your SlimeDeals folder.\n"
        "  pause\n"
        "  goto :end\n"
        ")\n"
        "rmdir /s /q " + convert([str(tmp_update)]) + " >nul 2>&1\n"
        "del /q " + convert([str(update_zip)]) + " >nul 2>&1\n"
        "start \"\" " + convert([str(app_dir / exe_name)]) + "\n"
        ":end\n"
        "(goto) 2>nul & del \"%~f0\"\n",
        encoding="utf-8",
    )
    _BREAKAWAY = 0x01000000
    subprocess.Popen(
        ["cmd", "/c", str(updater_bat)],
        creationflags=subprocess.DETACHED_PROCESS | _BREAKAWAY,
        cwd=str(app_dir),
    )
    announce("Update started. SlimeDeals will restart automatically.")
    return True
