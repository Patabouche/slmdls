# SlimeDeals — réparation interface Steam (blocage « chargement des données du compte »)
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_BACKUP_ROOT = Path.home() / ".slimedeals" / "steam_ui_repair_backup"


def _active_steam_user_id(steam_path: Path) -> str | None:
    loginusers = steam_path / "config" / "loginusers.vdf"
    if not loginusers.is_file():
        return None
    try:
        from sff.storage.vdf import vdf_load

        data = vdf_load(loginusers)
        users = data.get("users") or {}
        if not isinstance(users, dict):
            return None
        for sid, entry in users.items():
            if not isinstance(entry, dict):
                continue
            if str(entry.get("MostRecent", "")).strip() == "1":
                return str(sid)
        if len(users) == 1:
            return str(next(iter(users.keys())))
    except Exception as e:
        logger.debug("active_steam_user_id: %s", e)
    return None


def _backup_rename(path: Path, backup_dir: Path) -> bool:
    if not path.is_file():
        return False
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        dest = backup_dir / path.name
        if dest.exists():
            dest.unlink()
        shutil.copy2(path, dest)
        path.rename(path.with_suffix(path.suffix + ".sd_bak"))
        return True
    except OSError as e:
        logger.warning("steam_ui_repair backup %s: %s", path, e)
        return False


def repair_steam_ui(
    steam_path: Path | str | None,
    *,
    rank_raw: str | None = None,
) -> tuple[bool, str]:
    """
    Répare l'interface Steam bloquée sans toucher aux jeux installés ni
    restaurer les jeux verrouillés (quarantaine abonnement).
    """
    if sys.platform != "win32":
        return False, "Réparation UI Steam disponible uniquement sur Windows."

    if not steam_path:
        return False, "Chemin Steam non configuré."

    sp = Path(steam_path)
    if not (sp / "steam.exe").is_file():
        return False, "steam.exe introuvable dans le dossier Steam configuré."

    from sff.processes import kill_steam_client_completely

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = _BACKUP_ROOT / stamp
    steps: list[str] = []

    if not kill_steam_client_completely(try_elevated=True, wait_seconds=16.0):
        return (
            False,
            "Impossible de fermer Steam. Ferme Steam, steamwebhelper et DLLInjector "
            "dans le Gestionnaire des tâches, puis réessaie.",
        )
    steps.append("Steam fermé")
    time.sleep(1.0)

    local_steam = Path.home() / "AppData" / "Local" / "Steam"
    if local_steam.is_dir():
        try:
            shutil.rmtree(local_steam, ignore_errors=True)
            steps.append("Cache interface vidé")
        except OSError as e:
            logger.warning("steam_ui_repair local cache: %s", e)

    appcache = sp / "appcache"
    if appcache.is_dir():
        try:
            shutil.rmtree(appcache, ignore_errors=True)
            steps.append("Cache Steam nettoyé")
        except OSError as e:
            logger.debug("steam_ui_repair appcache: %s", e)

    user_id = _active_steam_user_id(sp)
    if user_id:
        user_cfg = sp / "userdata" / user_id / "config"
        localconfig = user_cfg / "localconfig.vdf"
        sharedconfig = user_cfg / "7" / "remote" / "sharedconfig.vdf"
        if _backup_rename(localconfig, backup_dir):
            steps.append("Profil UI réinitialisé")
        if _backup_rename(sharedconfig, backup_dir):
            steps.append("Config cloud locale réinitialisée")

    try:
        from sff.launcher_ranks import launcher_rank_bucket
        from sff.premium_manifest_lock import run_startup_check

        bucket = launcher_rank_bucket(rank_raw)
        chk = run_startup_check(sp)
        if bucket == "free":
            steps.append("Verrou abonnement Free conservé (aucun jeu payant restauré)")
        elif bucket != "triple":
            steps.append("Jeux Pépites toujours soumis à ton abonnement actuel")
        if chk.get("action") not in (None, "skip", "noop"):
            logger.info("steam_ui_repair startup_check: %s", chk)
    except Exception as e:
        logger.debug("steam_ui_repair rank check: %s", e)

    steam_exe = sp / "steam.exe"
    try:
        subprocess.Popen([str(steam_exe)], cwd=str(sp))
        steps.append("Steam relancé (mode normal)")
    except OSError as e:
        return False, f"Steam réparé mais relance impossible : {e}"

    backup_note = f"Sauvegarde : {backup_dir}" if backup_dir.is_dir() else ""
    detail = " · ".join(steps)
    msg = (
        "Réparation terminée. Reconnecte-toi si Steam le demande. "
        f"{detail}."
    )
    if backup_note:
        msg += f" {backup_note}."
    msg += (
        " Si l'interface reste bloquée, vérifie le zoom Windows (100 %) "
        "dans Paramètres → Affichage."
    )
    return True, msg
