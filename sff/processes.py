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


from functools import partial

import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil


from sff.extras import Konami, replace_boot_image

from sff.prompts import prompt_confirm


logger = logging.getLogger(__name__)


def is_proc_running(process_name: str) -> bool:
    target = (process_name or "").lower()
    if not target:
        return False
    for proc in psutil.process_iter(["name"]):
        try:
            if target == (proc.info.get("name") or "").lower():
                return True
        except (psutil.Error, psutil.NoSuchProcess):
            pass
    return False


def _running_process_names_lower() -> set[str]:
    names: set[str] = set()
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                n = (proc.info.get("name") or "").lower()
                if n:
                    names.add(n)
            except (psutil.Error, psutil.NoSuchProcess):
                pass
    except Exception:
        pass
    return names


def _steam_related_running() -> bool:
    if sys.platform != "win32":
        return "steam.exe" in _running_process_names_lower()
    steam_names = {"steam.exe", "steamwebhelper.exe", "dllinjector.exe", "steamservice.exe"}
    return bool(_running_process_names_lower() & steam_names)


def _kill_steam_exe_windows_silent() -> None:
    """taskkill + psutil, sans print (usage en arriere-plan)."""
    for exe_name in ("steam.exe", "steamwebhelper.exe", "steamservice.exe", "DLLInjector.exe"):
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", exe_name],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            logger.debug("taskkill %s: %s", exe_name, e)
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                n = (proc.info.get("name") or "").lower()
                if n in ("steam.exe", "steamwebhelper.exe", "steamservice.exe", "dllinjector.exe"):
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception as e:
        logger.debug("psutil kill steam: %s", e)


def _kill_steam_exe_windows_elevated() -> None:
    """taskkill élevé — nécessaire si Steam a été lancé en admin via GreenLuma/DLLInjector."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        params = (
            "/F /T /IM steam.exe /IM steamwebhelper.exe "
            "/IM DLLInjector.exe /IM steamservice.exe"
        )
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "taskkill", params, None, 0
        )
    except Exception as e:
        logger.debug("elevated taskkill steam: %s", e)


def kill_steam_client_completely(*, try_elevated: bool = True, wait_seconds: float = 14.0) -> bool:
    """
    Termine steam.exe, steamwebhelper, DLLInjector et steamservice.
    Retourne True si plus aucun de ces processus n'est actif.
    """
    if sys.platform != "win32":
        if not is_proc_running("steam.exe"):
            return True
        _kill_steam_exe_windows_silent()
        deadline = time.time() + wait_seconds
        while time.time() < deadline and is_proc_running("steam.exe"):
            time.sleep(0.4)
        return not is_proc_running("steam.exe")

    if not _steam_related_running():
        return True

    _kill_steam_exe_windows_silent()
    deadline = time.time() + wait_seconds
    while time.time() < deadline and _steam_related_running():
        time.sleep(0.4)

    if _steam_related_running() and try_elevated:
        _kill_steam_exe_windows_elevated()
        deadline = time.time() + wait_seconds
        while time.time() < deadline and _steam_related_running():
            time.sleep(0.4)

    still = _steam_related_running()
    if still:
        logger.warning("Steam: processus encore actifs apres fermeture forcee")
    return not still


def force_close_steam_client(*, wait_seconds: float = 16.0, poll: float = 0.4) -> bool:
    """
    Termine le client Steam pour que la bibliotheque recharge ACF / Lua / cles
    sans redemarrage manuel par l'utilisateur.

    Retourne True si steam.exe (Windows) ou Steam (Linux) semblait actif au depart.
    """
    if sys.platform == "win32":
        if not _steam_related_running():
            return False
        kill_steam_client_completely(try_elevated=True, wait_seconds=wait_seconds)
        if _steam_related_running():
            logger.warning("Steam: processus encore actifs apres fermeture forcee")
        else:
            logger.info("Steam: client ferme pour appliquer le verrou d'abonnement")
        return True
    if sys.platform == "linux":
        try:
            from sff.linux.steam_process import kill_steam

            return bool(kill_steam(print_fn=lambda *_a, **_k: None))
        except Exception as e:
            logger.debug("linux kill_steam: %s", e)
            return False
    return False


def _resolve_applist_folder(steam_path: Path) -> Path | None:
    try:
        from sff.storage.settings import get_setting
        from sff.structs import Settings

        saved = get_setting(Settings.APPLIST_FOLDER)
        if saved:
            p = Path(str(saved))
            if p.is_dir():
                return p
    except Exception as e:
        logger.debug("resolve applist from settings: %s", e)
    default = steam_path / "AppList"
    return default if default.is_dir() else None


def launch_steam_client(steam_path: Path | str) -> bool:
    """Relance Steam (DLLInjector GreenLuma ou steam.exe)."""
    sp = Path(steam_path)
    if sys.platform == "linux":
        try:
            from sff.linux.steam_process import start_steam

            return start_steam() == "SUCCESS"
        except Exception as e:
            logger.warning("launch_steam_client linux: %s", e)
            return False

    if sys.platform != "win32":
        return False

    if not sp.exists():
        return False

    applist_folder = _resolve_applist_folder(sp)
    if not applist_folder:
        steam_exe = sp / "steam.exe"
        if steam_exe.is_file():
            try:
                subprocess.Popen(
                    [str(steam_exe)],
                    cwd=str(sp),
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                return True
            except Exception as e:
                logger.warning("launch steam.exe fallback: %s", e)
        return False

    steam_proc = SteamProcess(sp, applist_folder)
    injector = steam_proc.injector_dir / "DLLInjector.exe"
    if not injector.is_file():
        injector = sp / "steam.exe"
    if not injector.is_file():
        return False
    injector_path = str(injector.resolve())

    try:
        import ctypes

        already_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        if already_admin:
            subprocess.Popen([injector_path], cwd=str(sp))
            return True
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", injector_path, None, str(sp), 1
        )
        if ret > 32:
            return True
        subprocess.Popen([injector_path], cwd=str(sp))
        return True
    except Exception as e:
        logger.warning("launch_steam_client: %s", e)
        return False


def restart_steam_for_library_refresh(
    steam_path: Path | str | None,
    *,
    wait_seconds: float = 16.0,
) -> bool:
    """
    Ferme Steam s'il tournait, puis le relance pour recharger bibliothèque / verrou abonnement.
    Retourne True si Steam a été relancé.
    """
    if not steam_path:
        return False
    was_running = force_close_steam_client(wait_seconds=wait_seconds)
    if not was_running:
        return False
    time.sleep(1.0)
    ok = launch_steam_client(steam_path)
    if ok:
        logger.info("Steam relancé après mise à jour bibliothèque / abonnement")
    else:
        logger.warning(
            "Steam fermé pour appliquer le changement d'abonnement mais relance échouée"
        )
    return ok


class SteamProcess:

    def __init__(self, steam_path: Path, applist_folder: Path):

        self.steam_path = steam_path
        self.injector_dir = applist_folder.parent
        self.exe_name = "steam.exe"
        self.wait_time = 3

    def kill(self):
        """Termine steam.exe et steamwebhelper.exe (évite les zombies UI)."""
        print(" ", end="", flush=True)
        if sys.platform == "win32":
            _kill_steam_exe_windows_silent()
            time.sleep(0.5)
            if not is_proc_running(self.exe_name):
                return
        # Fallback ciblé steam.exe uniquement
        try:
            result = subprocess.run(
                ["taskkill", "/F", "/IM", self.exe_name],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.returncode in (0, 128):
                return
        except subprocess.TimeoutExpired:
            print("(timeout, trying psutil)...", end="", flush=True)
        except Exception as e:
            logger.debug(f"taskkill failed: {e}")
        try:
            killed = False
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if proc.info['name'].lower() == self.exe_name.lower():
                        proc.kill()
                        killed = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if killed:
                return
        except Exception as e:
            logger.debug(f"psutil failed: {e}")
        pass

    def resolve_injector_path(self):

        candidates = ["DLLInjector.exe", "steam.exe"]
        matches = [
            x for x in map(lambda x: (self.injector_dir / x), candidates) if x.exists()
        ]
        if len(matches) == 1:
            return str(matches[0].resolve())
        if len(matches) == 0:
            return None
        print(f"The following were found: {', '.join(x.name for x in matches)}")
        if prompt_confirm("Is your GreenLuma installation in Normal Mode right now?"):
            return str(matches[0].resolve())
        renamed_path = matches[0].parent / (matches[0].name + ".backup")
        matches[0].rename(renamed_path)
        print(
            "You must be in stealth mode then. "
            f"You shouldn't leave {candidates[0]} in that folder! I've renamed it "
            f"to {renamed_path.name} for you."
        )
        return str(matches[1].resolve())

    def prompt_launch_or_restart(self):

        watcher = Konami(on_success=partial(replace_boot_image, self.injector_dir))
        t = threading.Thread(target=watcher.listen, daemon=True)
        t.start()
        do_start = prompt_confirm("Would like me to restart/start Steam for you?")
        watcher.stop()
        if not do_start:
            return False
        if is_proc_running(self.exe_name):
            print("Killing Steam...", flush=True, end="")
            self.kill()
            wait_start = time.time()
            max_wait = 15  # 15 seconds max
            while is_proc_running(self.exe_name):
                if time.time() - wait_start > max_wait:
                    print("\nSteam is taking too long to close.")
                    if prompt_confirm("Force close Steam?"):
                        subprocess.run(
                            ["taskkill", "/F", "/IM", self.exe_name],
                            capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW
                        )
                        time.sleep(2)
                        if is_proc_running(self.exe_name):
                            print("Could not close Steam. Please close it manually.")
                        break
                    else:
                        print("Skipping Steam restart.")
                        return False
                time.sleep(0.5)
            if not is_proc_running(self.exe_name):
                print(" Done!")
        injector = self.resolve_injector_path()
        if injector is None:
            print("Could not find any matching executables. Launch it yourself.")
            return False
        print("Launching Steam...")
        try:
            import ctypes
            import sys
            already_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
            if already_admin:
                # Already elevated — ShellExecuteW("runas") would fail with Access Denied.
                # Launch the injector directly; it inherits the elevated token.
                subprocess.Popen([injector], cwd=str(self.steam_path))
                print("Steam launched successfully!")
                return True
            # Not admin — use ShellExecute with 'runas' verb to request elevation
            ret = ctypes.windll.shell32.ShellExecuteW(
                None,                    # hwnd
                "runas",                 # operation (run as admin)
                injector,                # file to execute
                None,                    # parameters
                str(self.steam_path),    # working directory
                1                        # SW_SHOWNORMAL (show window normally)
            )
            # ShellExecute returns a value > 32 on success
            if ret > 32:
                print("Steam launched successfully!")
                return True
            # ShellExecuteW failed — try launching without elevation as a last resort
            error_messages = {
                0: "Out of memory or resources",
                2: "File not found",
                3: "Path not found",
                5: "Access denied",
                8: "Out of memory",
                26: "Sharing violation",
                27: "File association incomplete or invalid",
                28: "DDE timeout",
                29: "DDE transaction failed",
                30: "DDE busy",
                31: "No file association",
                32: "DLL not found"
            }
            error_msg = error_messages.get(ret, f"Unknown error (code {ret})")
            print(f"ShellExecute failed ({error_msg}), trying without elevation...")
            try:
                subprocess.Popen([injector], cwd=str(self.steam_path))
                print("Steam launched (elevation skipped). GreenLuma injection may not work if admin rights are required.")
                return True
            except Exception:
                pass
            print(f"\nFailed to launch Steam: {error_msg}")
            print("Please launch Steam manually from your Start Menu or Desktop.")
            return False
        except Exception as e:
            print(f"\nError launching Steam: {e}")
            print("Please launch Steam manually from your Start Menu or Desktop.")
            return False
