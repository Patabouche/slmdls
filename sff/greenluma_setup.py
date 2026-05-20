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

"""
Auto GreenLuma Setup — extracts a GL archive (ZIP/RAR/7z) and patches DLLInjector.ini.

Method A: GreenLuma folder placed next to the SlimeDeals launcher (.exe).
Method B: GreenLuma files placed inside Steam's installation folder.
"""

import logging
import shutil
import zipfile
from pathlib import Path

log = logging.getLogger("sff")


def _gl(msg: str) -> None:
    """Journal launcher — préfixe [GreenLuma]."""
    log.info("[GreenLuma] %s", msg)

_UNRAR_CANDIDATES = [
    r"C:\Program Files\WinRAR\UnRAR.exe",
    r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
    r"C:\Program Files\WinRAR\WinRAR.exe",
    r"C:\Program Files (x86)\WinRAR\WinRAR.exe",
    "unrar",
    "unrar.exe",
]

_7ZIP_CANDIDATES = [
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
    "7z",
    "7z.exe",
]

_GL_DLL_PATTERNS = [
    "GreenLuma_2024_x64.dll",
    "GreenLuma_2025_x64.dll",
    "GreenLuma_2024_x86.dll",
    "GreenLuma_2025_x86.dll",
]

_DLL_INI_SECTION = "DllInjector"


def _find_unrar() -> str:
    """Return path to UnRAR/WinRAR executable, or empty string."""
    for candidate in _UNRAR_CANDIDATES:
        p = Path(candidate)
        if p.exists():
            return str(p)
        found = shutil.which(candidate)
        if found:
            return found
    return ""


def _find_7zip() -> str:
    """Return path to 7-Zip executable, or empty string."""
    for candidate in _7ZIP_CANDIDATES:
        p = Path(candidate)
        if p.exists():
            return str(p)
        found = shutil.which(candidate)
        if found:
            return found
    return ""


def _extract_zip(archive_path: str, dest_dir: str) -> None:
    with zipfile.ZipFile(archive_path, "r") as z:
        z.extractall(dest_dir)


def _extract_rar(archive_path: str, dest_dir: str) -> None:
    import subprocess
    import sys
    flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}

    # 1. Try Python rarfile module (uses WinRAR/UnRAR as backend)
    unrar = _find_unrar()
    try:
        import rarfile
        if unrar:
            rarfile.UNRAR_TOOL = unrar
        with rarfile.RarFile(archive_path) as r:
            r.extractall(dest_dir)
        return
    except Exception:
        pass

    # 2. Try WinRAR/UnRAR subprocess directly
    if unrar:
        subprocess.run(
            [unrar, "x", "-y", archive_path, dest_dir + "\\"],
            capture_output=True, timeout=120, **flags,
        )
        return

    # 3. Try 7-Zip subprocess
    seven_z = _find_7zip()
    if seven_z:
        subprocess.run(
            [seven_z, "x", archive_path, f"-o{dest_dir}", "-y"],
            capture_output=True, timeout=120, **flags,
        )
        return

    # 4. Try Windows built-in tar.exe (Win10/11 with libarchive)
    if sys.platform == "win32":
        tar = shutil.which("tar")
        if tar:
            result = subprocess.run(
                [tar, "-xf", archive_path, "-C", dest_dir],
                capture_output=True, timeout=120,
            )
            if result.returncode == 0:
                return

    raise RuntimeError(
        "Cannot extract RAR: install WinRAR or 7-Zip to extract .rar archives."
    )


def _extract_7z(archive_path: str, dest_dir: str) -> None:
    try:
        import py7zr
        with py7zr.SevenZipFile(archive_path, mode="r") as z:
            z.extractall(path=dest_dir)
        return
    except ImportError:
        pass
    # Fallback: system 7z.exe
    seven_z = shutil.which("7z") or shutil.which("7z.exe")
    if seven_z:
        import subprocess
        import sys
        flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
        subprocess.run(
            [seven_z, "x", archive_path, f"-o{dest_dir}", "-y"],
            capture_output=True, timeout=120, **flags,
        )
        return
    raise RuntimeError("Cannot extract 7z: py7zr not installed and 7z.exe not found.")


def extract_archive(archive_path: str, dest_dir: str) -> None:
    """Extract archive to dest_dir. Supports ZIP, RAR, 7z."""
    ext = Path(archive_path).suffix.lower()
    if ext == ".zip":
        _extract_zip(archive_path, dest_dir)
    elif ext == ".rar":
        _extract_rar(archive_path, dest_dir)
    elif ext == ".7z":
        _extract_7z(archive_path, dest_dir)
    else:
        # Try ZIP first, then RAR, then 7z
        for fn in (_extract_zip, _extract_rar, _extract_7z):
            try:
                fn(archive_path, dest_dir)
                return
            except Exception:
                continue
        raise RuntimeError(f"Unsupported or unextractable archive: {archive_path}")


def find_dll_in_dir(dir_path: str) -> str:
    """Find the GreenLuma DLL in a directory tree. Returns full path or empty string."""
    root = Path(dir_path)
    for pattern in _GL_DLL_PATTERNS:
        matches = list(root.rglob(pattern))
        if matches:
            return str(matches[0])
    # Fallback: look for any *GreenLuma*.dll
    matches = list(root.rglob("*GreenLuma*.dll"))
    if matches:
        return str(matches[0])
    return ""


def find_ini_in_dir(dir_path: str) -> str:
    """Find DLLInjector.ini in a directory tree. Returns full path or empty string."""
    root = Path(dir_path)
    matches = list(root.rglob("DLLInjector.ini"))
    if matches:
        return str(matches[0])
    return ""


def patch_dll_injector_ini(ini_path: str, steam_exe: str, dll_path: str) -> None:
    """Patch DLLInjector.ini — équivalent GreenLumaSettings option 2 (chemins complets)."""
    p = Path(ini_path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        text = ""

    steam_exe = str(Path(steam_exe).resolve())
    dll_path = str(Path(dll_path).resolve())

    if not text:
        text = (
            f"[{_DLL_INI_SECTION}]\r\n"
            "AllowMultipleInstancesOfDLLInjector = 0\r\n"
            "UseFullPathsFromIni = 1\r\n"
            f"Exe = {steam_exe}\r\n"
            "CommandLine = -inhibitbootstrap\r\n"
            f"Dll = {dll_path}\r\n"
            "WaitForProcessTermination = 1\r\n"
            "CreateFiles = 1\r\n"
            "FileToCreate_1 = NoQuestion.bin\r\n"
        )
        p.write_text(text, encoding="utf-8")
        return

    lines = text.splitlines(keepends=True)
    result = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=")[0].strip() if "=" in stripped else stripped
        if key == "UseFullPathsFromIni":
            indent = line[: len(line) - len(line.lstrip())]
            result.append(f"{indent}UseFullPathsFromIni = 1\r\n")
        elif key == "Exe":
            indent = line[: len(line) - len(line.lstrip())]
            result.append(f"{indent}Exe = {steam_exe}\r\n")
        elif key == "Dll":
            indent = line[: len(line) - len(line.lstrip())]
            result.append(f"{indent}Dll = {dll_path}\r\n")
        elif key == "CreateFiles":
            indent = line[: len(line) - len(line.lstrip())]
            result.append(f"{indent}CreateFiles = 1\r\n")
        elif key == "FileToCreate_1":
            indent = line[: len(line) - len(line.lstrip())]
            result.append(f"{indent}FileToCreate_1 = NoQuestion.bin\r\n")
        else:
            result.append(line)
    p.write_text("".join(result), encoding="utf-8")


def apply_greenluma_settings_option2(steam_dir: str | Path) -> tuple[bool, str]:
    """
    Applique la config GreenLumaSettings option 2 (chemins exe/dll complets).
    Équivalent à lancer GreenLumaSettings_2025.exe → 2 → steam.exe → dll.
    """
    root = Path(steam_dir)
    steam_exe = root / "steam.exe"
    if not steam_exe.is_file():
        return False, f"steam.exe introuvable : {steam_exe}"

    dll = _installed_gl_dll_path(root)
    if not dll:
        return False, f"DLL GreenLuma introuvable dans {root}"

    ini_hits = list(root.glob("DLLInjector.ini")) + list(root.rglob("DLLInjector.ini"))
    if not ini_hits:
        return False, f"DLLInjector.ini introuvable dans {root}"

    ini_path = ini_hits[0]
    try:
        patch_dll_injector_ini(str(ini_path), str(steam_exe), dll)
    except Exception as exc:
        return False, f"Échec patch DLLInjector.ini : {exc}"

    _gl(
        f"GreenLumaSettings (option 2) appliqué — "
        f"Exe={steam_exe} | Dll={dll} | INI={ini_path}"
    )
    return True, str(ini_path)


def _read_dll_injector_ini(ini_path: Path) -> dict[str, str]:
    vals: dict[str, str] = {}
    try:
        text = ini_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return vals
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        vals[key.strip()] = val.strip().strip('"')
    return vals


def verify_greenluma_configuration(steam_dir: str | Path) -> dict:
    """Vérifie l'état GreenLuma + DLLInjector.ini et journalise un résumé lisible."""
    root = Path(steam_dir)
    steam_exe = root / "steam.exe"
    dll = _installed_gl_dll_path(root)
    applist = root / "AppList"
    installed = is_greenluma_installed_in_steam(root)

    _gl("——— Résumé GreenLuma ———")
    _gl(f"Installé dans Steam : {'oui' if installed else 'non'}")
    _gl(f"steam.exe : {steam_exe if steam_exe.is_file() else 'introuvable'}")
    _gl(f"DLL GreenLuma : {dll or 'introuvable'}")
    _gl(f"AppList : {applist} ({'existe' if applist.is_dir() else 'absent'})")

    ini_hits = list(root.glob("DLLInjector.ini")) + list(root.rglob("DLLInjector.ini"))
    if not ini_hits:
        _gl("DLLInjector.ini : introuvable")
        return {"ok": False, "installed": installed}

    ini_path = ini_hits[0]
    vals = _read_dll_injector_ini(ini_path)
    use_full = vals.get("UseFullPathsFromIni", "")
    ini_exe = vals.get("Exe", "")
    ini_dll = vals.get("Dll", "")

    expected_exe = str(steam_exe.resolve()) if steam_exe.is_file() else ""
    expected_dll = str(Path(dll).resolve()) if dll else ""

    def _norm(p: str) -> str:
        return str(Path(p).resolve()).lower() if p else ""

    exe_ok = _norm(ini_exe) == _norm(expected_exe) and bool(expected_exe)
    dll_ok = _norm(ini_dll) == _norm(expected_dll) and bool(expected_dll)
    full_ok = use_full in ("1", "true", "True")

    _gl(f"DLLInjector.ini : {ini_path}")
    _gl(f"  UseFullPathsFromIni = {use_full or '?'} {'OK' if full_ok else 'KO'}")
    _gl(f"  Exe = {ini_exe or '?'} {'OK' if exe_ok else 'KO'}")
    _gl(f"  Dll = {ini_dll or '?'} {'OK' if dll_ok else 'KO'}")

    all_ok = installed and exe_ok and dll_ok and full_ok
    _gl(f"Configuration globale : {'OK' if all_ok else 'KO — vérifie les chemins ci-dessus'}")
    _gl("———————————————————————")

    return {
        "ok": all_ok,
        "installed": installed,
        "ini_path": str(ini_path),
        "use_full_paths_ok": full_ok,
        "exe_ok": exe_ok,
        "dll_ok": dll_ok,
    }


def is_greenluma_installed_in_steam(steam_path: str | Path) -> bool:
    """True si la DLL GreenLuma est déjà présente dans le dossier Steam."""
    root = Path(steam_path)
    if not root.is_dir():
        return False
    for pattern in _GL_DLL_PATTERNS:
        if (root / pattern).is_file():
            return True
    found = find_dll_in_dir(str(root))
    return bool(found)


def _installed_gl_dll_path(steam_path: str | Path) -> str | None:
    root = Path(steam_path)
    for pattern in _GL_DLL_PATTERNS:
        p = root / pattern
        if p.is_file():
            return str(p)
    return find_dll_in_dir(str(root)) or None


def find_bundled_greenluma_archive() -> str | None:
    """Localise greenlumafix.rar livré avec le launcher (exe ou bundle dev)."""
    from sff.utils import root_folder

    names = ("greenlumafix.rar", "GreenLumaFix.rar", "greenluma.rar")
    bases: list[Path] = []
    for outside in (True, False):
        try:
            base = Path(root_folder(outside_internal=outside))
            if base not in bases:
                bases.append(base)
        except Exception:
            pass
    for base in bases:
        for name in names:
            for candidate in (base / name, base / "GreenLuma" / name):
                if candidate.is_file():
                    return str(candidate.resolve())
    return None


def ensure_greenluma_installed(steam_path: str | Path) -> dict:
    """
    Installe GreenLuma dans Steam (méthode B) si absent.
    Utilise greenlumafix.rar à côté du launcher.
    """
    import sys

    steam = Path(steam_path)
    _gl(f"Vérification installation auto — dossier Steam : {steam}")

    if sys.platform != "win32":
        _gl("Installation auto ignorée (hors Windows).")
        return {
            "ok": True,
            "message": "GreenLuma auto-setup ignoré (hors Windows).",
            "applist_path": "",
            "skipped": True,
        }

    steam_exe = steam / "steam.exe"
    applist = steam / "AppList"

    if is_greenluma_installed_in_steam(steam):
        dll = _installed_gl_dll_path(steam)
        applist.mkdir(parents=True, exist_ok=True)
        _gl(f"Déjà installé — DLL : {dll or '?'} | AppList : {applist}")
        ok_cfg, msg_cfg = apply_greenluma_settings_option2(steam)
        if not ok_cfg:
            _gl(f"GreenLumaSettings (option 2) : {msg_cfg}")
        verify_greenluma_configuration(steam)
        return {
            "ok": True,
            "message": "GreenLuma déjà installé.",
            "applist_path": str(applist),
            "skipped": True,
        }

    _gl("GreenLuma absent — recherche de l'archive greenlumafix.rar…")
    archive = find_bundled_greenluma_archive()
    if not archive:
        _gl("Échec : greenlumafix.rar introuvable à côté du launcher.")
        return {
            "ok": False,
            "message": "Archive greenlumafix.rar introuvable à côté du launcher.",
            "applist_path": "",
            "skipped": False,
        }

    size_mb = Path(archive).stat().st_size / (1024 * 1024)
    _gl(f"Archive trouvée : {archive} ({size_mb:.2f} Mo) — installation dans Steam…")

    result = auto_gl_setup(
        method="B",
        archive_path=archive,
        steam_exe_path=str(steam_exe if steam_exe.is_file() else steam / "steam.exe"),
    )
    result["skipped"] = False

    if result.get("ok"):
        ok_cfg, msg_cfg = apply_greenluma_settings_option2(steam)
        if not ok_cfg:
            log.warning("[GreenLuma] GreenLumaSettings (option 2) : %s", msg_cfg)
        verify_greenluma_configuration(steam)
        _gl(
            f"Installation terminée — AppList : {result.get('applist_path') or applist} "
            f"| {result.get('message', '')}"
        )
    else:
        log.warning("[GreenLuma] Installation échouée : %s", result.get("message", "erreur inconnue"))

    return result


def auto_gl_setup(method: str, archive_path: str, steam_exe_path: str) -> dict:
    """
    Extract and configure GreenLuma.

    method='A': install next to the SlimeDeals launcher in a GreenLuma/ subfolder.
    method='B': install directly into Steam's installation directory.

    Returns {'ok': bool, 'message': str, 'applist_path': str}.
    """
    from sff.utils import root_folder

    archive_path = str(Path(archive_path).resolve())
    if not Path(archive_path).exists():
        _gl(f"Archive introuvable : {archive_path}")
        return {"ok": False, "message": f"Archive not found: {archive_path}", "applist_path": ""}

    steam_exe = Path(steam_exe_path)
    if not steam_exe.exists():
        _gl(f"steam.exe introuvable à {steam_exe_path} — poursuite quand même")

    # Determine destination directory
    if method == "B":
        dest_dir = steam_exe.parent if steam_exe.exists() else Path(r"C:\Program Files (x86)\Steam")
        _gl(f"Méthode B — cible : {dest_dir}")
    else:
        # Method A: GreenLuma subfolder next to the launcher .exe
        app_dir = root_folder()
        dest_dir = Path(app_dir) / "GreenLuma"
        _gl(f"Méthode A — cible : {dest_dir}")

    dest_dir.mkdir(parents=True, exist_ok=True)

    # Extract archive into a temp folder, then copy into dest_dir
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="slimedeals_gl_"))
    try:
        _gl(f"Extraction {Path(archive_path).name} → dossier temporaire…")
        extract_archive(archive_path, str(tmp))

        # Find DLL and INI
        dll_path = find_dll_in_dir(str(tmp))
        ini_path = find_ini_in_dir(str(tmp))

        if not dll_path:
            _gl("Échec : DLL GreenLuma absente de l'archive.")
            return {"ok": False, "message": "GreenLuma DLL not found in archive.", "applist_path": ""}
        _gl(f"DLL trouvée : {Path(dll_path).name}")
        if not ini_path:
            _gl("DLLInjector.ini absent — création d'un fichier minimal")
        else:
            _gl(f"INI trouvé : {Path(ini_path).name}")

        # Copy all extracted files into dest_dir
        copied = 0
        for item in Path(tmp).rglob("*"):
            if item.is_file():
                rel = item.relative_to(tmp)
                target = dest_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                copied += 1
        _gl(f"{copied} fichier(s) copié(s) vers {dest_dir}")

        # Resolve final paths
        final_dll = str(dest_dir / Path(dll_path).relative_to(tmp))
        final_ini_path = str(dest_dir / Path(ini_path).relative_to(tmp)) if ini_path else str(dest_dir / "DLLInjector.ini")

        # GreenLumaSettings option 2 — chemins exe/dll complets dans DLLInjector.ini
        apply_greenluma_settings_option2(dest_dir)

        # AppList folder — must be next to DLLInjector.exe (GL reads it relative to itself)
        dllinjector_hits = list(dest_dir.rglob("DLLInjector.exe"))
        if dllinjector_hits:
            applist_dir = dllinjector_hits[0].parent / "AppList"
        else:
            applist_dir = dest_dir / "AppList"
        applist_dir.mkdir(parents=True, exist_ok=True)
        _gl(f"Dossier AppList prêt : {applist_dir}")

        return {
            "ok": True,
            "message": f"GreenLuma installed to {dest_dir}. Edit AppList and run DLLInjector.exe.",
            "applist_path": str(applist_dir),
        }
    except Exception as exc:
        log.exception("[GreenLuma] Setup failed: %s", exc)
        return {"ok": False, "message": f"Setup failed: {exc}", "applist_path": ""}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
