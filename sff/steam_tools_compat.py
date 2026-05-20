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

"""Install LUAs and manifests into Steam's config directories.

- LUAs: Steam\\config\\stplug-in\\{app_id}.lua
- Manifests: Steam\\depotcache (primary) and Steam\\config\\depotcache (alternate)
- Decryption keys: already in config.vdf via ConfigVDFWriter
"""


import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

STPLUGIN_DIR = "stplug-in"
CONFIG_DEPOTCACHE_SUBDIR = ("config", "depotcache")


def install_lua_to_steam(steam_path, app_id, lua_source_path):
    if not lua_source_path.exists():
        logger.debug("LUA source not found: %s", lua_source_path)
        return False
    dest_dir = steam_path / "config" / STPLUGIN_DIR
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / f"{app_id}.lua"
        shutil.copy2(lua_source_path, dest_file)
        logger.info("Installed LUA to Steam config: %s", dest_file)
        return True
    except OSError as e:
        logger.warning("Could not install LUA to Steam config: %s", e)
        return False


def sync_manifest_to_config_depotcache(steam_path, manifest_path):
    if not manifest_path.exists():
        return False
    try:
        config_depot = steam_path.joinpath(*CONFIG_DEPOTCACHE_SUBDIR)
        config_depot.mkdir(parents=True, exist_ok=True)
        dest = config_depot / manifest_path.name
        if dest != manifest_path:
            shutil.copy2(manifest_path, dest)
            logger.debug("Synced manifest to config/depotcache: %s", dest.name)
        return True
    except OSError as e:
        logger.debug("Could not sync manifest to config/depotcache: %s", e)
        return False


def remove_lua_from_steam(steam_path, app_id: str | int):
    dest_dir = steam_path / "config" / STPLUGIN_DIR
    dest_file = dest_dir / f"{app_id}.lua"
    try:
        if dest_file.exists():
            dest_file.unlink()
            logger.info("Removed LUA from Steam config: %s", dest_file)
        return True
    except OSError as e:
        logger.warning("Could not remove LUA from Steam config: %s", e)
        return False


def remove_acf_and_manifests(steam_path, app_id: str | int, mounted_depots: dict, acf_path=None):
    deleted = 0
    for depot_id, manifest_id in mounted_depots.items():
        filename = f"{depot_id}_{manifest_id}.manifest"
        for cache_dir in [
            steam_path / "depotcache",
            steam_path / "config" / "depotcache",
        ]:
            f = cache_dir / filename
            try:
                if f.exists():
                    f.unlink()
                    logger.info("Deleted manifest: %s", f)
                    deleted += 1
            except OSError as e:
                logger.warning("Could not delete manifest %s: %s", f, e)
    if acf_path is not None:
        try:
            if acf_path.exists():
                acf_path.unlink()
                logger.info("Deleted ACF: %s", acf_path)
                deleted += 1
        except OSError as e:
            logger.warning("Could not delete ACF %s: %s", acf_path, e)
    return deleted


def full_remove_game_from_steam(
    steam_path: Path | str,
    app_id: str | int,
    game_folder: Path | str | None = None,
) -> dict[str, int | bool]:
    """
    Retire un jeu de Steam côté disque : stplug-in, ACF, manifests, dossiers
    partiels, registre launcher et backup ~/.slimedeals/Manifests_Backup.
    """
    import shutil

    from sff.storage.acf import ACFParser
    from sff.storage.vdf import get_steam_libs

    sp = Path(steam_path)
    aid = str(app_id)
    stats: dict[str, int | bool] = {
        "lua_removed": False,
        "acf_removed": 0,
        "manifests_removed": 0,
        "folder_removed": False,
        "registry_purged": False,
    }

    remove_lua_from_steam(sp, aid)

    libs: list[Path] = []
    try:
        libs = list(get_steam_libs(sp))
    except Exception as e:
        logger.debug("full_remove_game_from_steam get_steam_libs: %s", e)
    if not libs:
        libs = [sp]

    mounted_all: dict = {}
    acf_paths: list[Path] = []
    for lib in libs:
        acf = lib / "steamapps" / f"appmanifest_{aid}.acf"
        if acf.is_file():
            acf_paths.append(acf)
            try:
                mounted_all.update(ACFParser(acf).get_mounted_depots())
            except Exception as e:
                logger.debug("full_remove_game_from_steam parse %s: %s", acf, e)

    stats["lua_removed"] = True

    for acf in acf_paths:
        stats["manifests_removed"] = int(stats["manifests_removed"]) + remove_acf_and_manifests(
            sp, aid, mounted_all, acf_path=acf
        )
        stats["acf_removed"] = int(stats["acf_removed"]) + 1

    if mounted_all:
        try:
            from sff.lua.writer import ConfigVDFWriter

            ConfigVDFWriter(sp).remove_decryption_keys(list(mounted_all.keys()))
        except Exception as e:
            logger.debug("full_remove_game_from_steam remove keys: %s", e)

    for lib in libs:
        steamapps = lib / "steamapps"
        for partial in (
            steamapps / "downloading" / aid,
            steamapps / "temp" / aid,
            steamapps / "shadercache" / aid,
        ):
            if partial.exists():
                try:
                    shutil.rmtree(partial, ignore_errors=True)
                except Exception as e:
                    logger.debug("full_remove_game_from_steam rmtree %s: %s", partial, e)

    try:
        from sff.premium_manifest_lock import purge_app_from_launcher_registry

        purge_app_from_launcher_registry(sp, aid)
        stats["registry_purged"] = True
    except Exception as e:
        logger.warning("full_remove_game_from_steam registry purge: %s", e)

    if game_folder:
        folder = Path(game_folder)
        if folder.is_dir():
            try:
                shutil.rmtree(folder, ignore_errors=False)
                stats["folder_removed"] = True
            except Exception as e:
                logger.warning("full_remove_game_from_steam folder %s: %s", folder, e)

    return stats
