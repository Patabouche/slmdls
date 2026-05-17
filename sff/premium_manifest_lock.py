# SlimeDeals — verrouillage manifests / Lua pour passage plan payant → FREE
# Les fichiers sont déplacés vers ~/.slimedeals/Manifests_Backup/ (pas chiffré :
# la clé de déchiffrement est dans config.vdf ; l’objectif est d’empêcher Steam
# de relancer sans action manuelle, avec restauration auto au retour abonné.)

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any

# Dépendances ciblées : vdf (storage.vdf, utils.enter_path) — pas writer → http_utils → keyring.
from sff.launcher_ranks import launcher_rank_bucket, paid_install_slot_cap_for_bucket
from sff.lua.parse_lua import parse_lua_contents
from sff.steam_tools_compat import sync_manifest_to_config_depotcache
from sff.storage.vdf import VDFLoadAndDumper, get_steam_libs
from sff.utils import enter_path

logger = logging.getLogger(__name__)

_AUTH_FILE = Path.home() / ".slimedeals" / "auth.json"
_STATE_FILE = Path.home() / ".slimedeals" / "premium_manifest_state.json"
_REGISTRY_FILE = Path.home() / ".slimedeals" / "premium_install_registry.json"
_BACKUP_ROOT = Path.home() / ".slimedeals" / "Manifests_Backup"
# Aligné avec web_bridge._LAUNCHER_FREE_CATALOG_IDS
_LAUNCHER_FREE_CATALOG_IDS = frozenset({
    "2416450",
    "284160",
    "1943950",
    "1144200",
    "2968420",
    "1321680",
    "655500",
    "526870",
})


def _norm_rank(rank: Any) -> str:
    if rank is None:
        return "free"
    r = str(rank).strip().lower().replace(" ", "_")
    if not r or r in ("none", "null"):
        return "free"
    return r


def _load_json(path: Path, default: dict) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("premium lock: could not read %s: %s", path, e)
    return dict(default)


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _remove_depot_keys_from_config(steam_path: Path, depot_ids: list) -> int:
    """Même logique que ConfigVDFWriter.remove_decryption_keys (sans dépendance pathvalidate)."""
    vdf_file = steam_path / "config" / "config.vdf"
    if not vdf_file.is_file():
        logger.warning("premium lock: config.vdf introuvable: %s", vdf_file)
        return 0
    shutil.copyfile(vdf_file, steam_path / "config" / "config.vdf.backup")
    removed = 0
    with VDFLoadAndDumper(vdf_file) as vdf_data:
        depots = enter_path(
            vdf_data,
            "InstallConfigStore",
            "Software",
            "Valve",
            "Steam",
            "depots",
            mutate=True,
            ignore_case=True,
        )
        for depot_id in depot_ids:
            depot_id_str = str(depot_id)
            if depot_id_str in depots:
                del depots[depot_id_str]
                removed += 1
    return removed


def _add_depot_keys_from_parsed(steam_path: Path, parsed) -> None:
    """Même logique que ConfigVDFWriter.add_decryption_keys_to_config (sans pathvalidate)."""
    vdf_file = steam_path / "config" / "config.vdf"
    if not vdf_file.is_file():
        logger.warning("premium lock: config.vdf introuvable: %s", vdf_file)
        return
    shutil.copyfile(vdf_file, steam_path / "config" / "config.vdf.backup")
    with VDFLoadAndDumper(vdf_file) as vdf_data:
        for pair in parsed.depots:
            depot_id = pair.depot_id
            dec_key = pair.decryption_key
            if dec_key == "":
                continue
            depots = enter_path(
                vdf_data,
                "InstallConfigStore",
                "Software",
                "Valve",
                "Steam",
                "depots",
                mutate=True,
                ignore_case=True,
            )
            if depot_id not in depots:
                depots[depot_id] = {"DecryptionKey": dec_key}


def _steam_key(steam_path: Path) -> str:
    try:
        key_src = str(steam_path.resolve()).lower()
    except Exception:
        key_src = str(steam_path).lower()
    return hashlib.sha256(key_src.encode("utf-8", errors="replace")).hexdigest()[:24]


def paid_apps_dict_for_steam(steam_path: Path | str | None) -> dict[str, Any]:
    """Jeux enregistres via maybe_register_paid_install pour ce dossier Steam."""
    if not steam_path:
        return {}
    sp = Path(steam_path)
    if not sp.exists():
        return {}
    reg = _load_json(_REGISTRY_FILE, {})
    sk = _steam_key(sp)
    raw = (reg.get("per_steam") or {}).get(sk, {}).get("apps") or {}
    return raw if isinstance(raw, dict) else {}


def paid_distinct_game_count_for_steam(steam_path: Path | str | None) -> int:
    return len(paid_apps_dict_for_steam(steam_path))


def monstre_new_install_allowed(
    steam_path: Path | str | None, app_id: str
) -> tuple[bool, str]:
    """
    Quotas jeux distincts : Monstre (10), 24HPASS (8). Triple : illimite.
    Re-install / mise a jour d'un jeu deja enregistre : toujours autorise.
    """
    bucket = launcher_rank_bucket(_load_auth_rank())
    if bucket == "triple":
        return True, ""
    cap = paid_install_slot_cap_for_bucket(bucket)
    if cap is None:
        return True, ""
    aid = str(app_id).strip()
    if not aid.isdigit():
        return False, "Identifiant de jeu invalide."
    if not steam_path:
        return False, "Configure le dossier Steam dans les parametres avant d'installer."
    sp = Path(steam_path)
    if not sp.exists():
        return False, "Chemin Steam invalide (parametres)."
    apps = paid_apps_dict_for_steam(sp)
    if aid in apps:
        return True, ""
    if len(apps) >= cap:
        label = "Plan 24H PASS" if bucket == "pass24h" else "Plan Monstre"
        return False, (
            f"{label} : limite de {cap} jeux distincts via le launcher atteinte. "
            "Passe au Triple Monstre pour lever la limite, ou mets a jour un jeu deja enregistre."
        )
    return True, ""


def _load_auth_rank() -> str:
    data = _load_json(_AUTH_FILE, {})
    return _norm_rank(data.get("rank"))


def _free_claimed_app_id() -> str | None:
    data = _load_json(_AUTH_FILE, {})
    c = data.get("free_claimed")
    if c is None:
        return None
    s = str(c).strip()
    return s if s.isdigit() else None


def _all_depotcache_dirs(steam_path: Path) -> list[Path]:
    out: list[Path] = [
        steam_path / "depotcache",
        steam_path / "config" / "depotcache",
    ]
    try:
        for lib in get_steam_libs(steam_path):
            d = lib / "depotcache"
            if d not in out:
                out.append(d)
    except Exception as e:
        logger.debug("get_steam_libs for depotcache: %s", e)
    return out


def _library_roots(steam_path: Path) -> list[Path]:
    """Racines de bibliotheques Steam (dossier contenant steamapps/)."""
    seen: set[str] = set()
    out: list[Path] = []

    def _add(p: Path) -> None:
        if not p.exists():
            return
        try:
            key = str(p.resolve()).lower()
        except Exception:
            key = str(p).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)

    _add(steam_path)
    try:
        for lib in get_steam_libs(steam_path):
            _add(lib)
    except Exception as e:
        logger.debug("premium lock: get_steam_libs (library roots): %s", e)
    return out


def _find_appmanifest_acf(steam_path: Path, app_id: str) -> Path | None:
    name = f"appmanifest_{app_id}.acf"
    for root in _library_roots(steam_path):
        acf = root / "steamapps" / name
        if acf.is_file():
            return acf
    return None


def _quarantine_dir(steam_path: Path, app_id: str) -> Path:
    return _BACKUP_ROOT / _steam_key(steam_path) / str(app_id)


def _collect_manifest_basenames(
    manifest_paths: list[Path] | None,
    manifest_override: dict[str, str] | None,
) -> list[str]:
    names: list[str] = []
    if manifest_paths:
        for p in manifest_paths:
            try:
                n = Path(p).name
                if n.endswith(".manifest"):
                    names.append(n)
            except Exception:
                continue
    if manifest_override:
        for d, m in manifest_override.items():
            if d and m:
                names.append(f"{d}_{m}.manifest")
    # dédupliquer en gardant l’ordre
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _depot_ids_for_registry(parsed_lua) -> list[str]:
    out: list[str] = []
    try:
        for pair in getattr(parsed_lua, "depots", []) or []:
            k = getattr(pair, "decryption_key", "") or ""
            if k:
                out.append(str(pair.depot_id))
    except Exception:
        pass
    return out


def maybe_register_paid_install(
    steam_path: Path | str | None,
    parsed_lua,
    manifest_paths: list[Path] | None = None,
    manifest_override: dict[str, str] | None = None,
) -> None:
    """Enregistre une installation faite pendant un plan payant (≠ FREE seul)."""
    if _load_auth_rank() == "free":
        return
    aid = str(getattr(parsed_lua, "app_id", "") or "").strip()
    claimed = _free_claimed_app_id()
    if claimed and aid == claimed and aid in _LAUNCHER_FREE_CATALOG_IDS:
        return
    if not steam_path:
        return
    sp = Path(steam_path)
    if not sp.exists():
        return
    app_id = aid
    if not app_id.isdigit():
        return
    depot_ids = _depot_ids_for_registry(parsed_lua)
    manifest_names = _collect_manifest_basenames(manifest_paths, manifest_override)
    reg = _load_json(_REGISTRY_FILE, {})
    per = reg.setdefault("per_steam", {})
    sk = _steam_key(sp)
    bucket = per.setdefault(sk, {})
    apps = bucket.setdefault("apps", {})
    prev = apps.get(app_id, {})
    merged_depots = sorted(set(prev.get("depot_ids", []) + depot_ids))
    merged_mani = []
    seen_m: set[str] = set()
    for n in (prev.get("manifest_names", []) or []) + manifest_names:
        if n not in seen_m:
            seen_m.add(n)
            merged_mani.append(n)
    apps[app_id] = {"depot_ids": merged_depots, "manifest_names": merged_mani}
    _save_json(_REGISTRY_FILE, reg)
    logger.info(
        "premium lock: registered paid install app_id=%s depots=%s manifests=%s",
        app_id,
        len(merged_depots),
        len(merged_mani),
    )


def _move_file_quiet(src: Path, dest: Path) -> bool:
    try:
        if not src.is_file():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        shutil.move(str(src), str(dest))
        return True
    except OSError as e:
        logger.warning("premium lock: move %s -> %s failed: %s", src, dest, e)
        return False


def _copy_file_quiet(src: Path, dest: Path) -> bool:
    try:
        if not src.is_file():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))
        return True
    except OSError as e:
        logger.warning("premium lock: copy %s -> %s failed: %s", src, dest, e)
        return False


def _quarantine_one_app(steam_path: Path, app_id: str, entry: dict) -> None:
    qdir = _quarantine_dir(steam_path, app_id)
    qdir.mkdir(parents=True, exist_ok=True)
    lua_src = steam_path / "config" / "stplug-in" / f"{app_id}.lua"
    lua_dst = qdir / f"{app_id}.lua"
    _move_file_quiet(lua_src, lua_dst)
    mani_sub = qdir / "manifests"
    for name in entry.get("manifest_names", []) or []:
        placed = False
        for cache in _all_depotcache_dirs(steam_path):
            src = cache / name
            if src.is_file():
                dst = mani_sub / name
                if _move_file_quiet(src, dst):
                    placed = True
        if not placed and name:
            logger.debug("premium lock: manifest absent au quarantaine: %s", name)
    try:
        depot_ids = entry.get("depot_ids") or []
        if depot_ids:
            _remove_depot_keys_from_config(steam_path, depot_ids)
    except Exception as e:
        logger.warning("premium lock: remove_decryption_keys: %s", e)
    acf_src = _find_appmanifest_acf(steam_path, app_id)
    if acf_src is not None:
        acf_dst = qdir / acf_src.name
        if _move_file_quiet(acf_src, acf_dst):
            try:
                meta = {"steamapps_dir": str(acf_src.parent.resolve())}
                (qdir / "acf_meta.json").write_text(
                    json.dumps(meta, indent=0), encoding="utf-8"
                )
                logger.info(
                    "premium lock: ACF moved off library (hide Play in Steam) app_id=%s",
                    app_id,
                )
            except Exception as e:
                logger.warning("premium lock: acf_meta.json: %s", e)


def _restore_one_app(steam_path: Path, app_id: str) -> None:
    qdir = _quarantine_dir(steam_path, app_id)
    lua_bak = qdir / f"{app_id}.lua"
    lua_dest = steam_path / "config" / "stplug-in" / f"{app_id}.lua"
    if lua_bak.is_file():
        lua_dest.parent.mkdir(parents=True, exist_ok=True)
        _copy_file_quiet(lua_bak, lua_dest)
        try:
            text = lua_dest.read_text(encoding="utf-8", errors="replace")
            parsed = parse_lua_contents(text, lua_dest)
            if parsed:
                _add_depot_keys_from_parsed(steam_path, parsed)
        except Exception as e:
            logger.warning("premium lock: restore keys from lua: %s", e)
    mani_bak = qdir / "manifests"
    if mani_bak.is_dir():
        primary = steam_path / "depotcache"
        primary.mkdir(parents=True, exist_ok=True)
        for f in mani_bak.iterdir():
            if not f.is_file() or not f.name.endswith(".manifest"):
                continue
            dest = primary / f.name
            if _copy_file_quiet(f, dest):
                try:
                    sync_manifest_to_config_depotcache(steam_path, dest)
                except Exception as e:
                    logger.debug("sync_manifest_to_config_depotcache: %s", e)
    meta_path = qdir / "acf_meta.json"
    acf_bak = qdir / f"appmanifest_{app_id}.acf"
    if acf_bak.is_file():
        steamapps_dest: Path | None = None
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                steamapps_dest = Path(meta["steamapps_dir"])
            except Exception:
                steamapps_dest = None
        if steamapps_dest is None or not steamapps_dest.exists():
            steamapps_dest = steam_path / "steamapps"
        try:
            steamapps_dest.mkdir(parents=True, exist_ok=True)
            dest_acf = steamapps_dest / acf_bak.name
            if _copy_file_quiet(acf_bak, dest_acf):
                logger.debug("premium lock: ACF restaure vers %s", dest_acf)
        except Exception as e:
            logger.warning("premium lock: ACF restore failed: %s", e)


def _quarantine_all(steam_path: Path | None) -> int:
    if not steam_path or not steam_path.exists():
        logger.info("premium lock: quarantine skipped (no steam path)")
        return 0
    reg = _load_json(_REGISTRY_FILE, {})
    sk = _steam_key(steam_path)
    apps = (reg.get("per_steam") or {}).get(sk, {}).get("apps") or {}
    if not apps:
        logger.info("premium lock: quarantine - aucun jeu enregistre pour ce Steam")
        return 0
    skip_id = _free_claimed_app_id()
    for app_id, entry in list(apps.items()):
        sid = str(app_id)
        if skip_id and sid == skip_id and sid in _LAUNCHER_FREE_CATALOG_IDS:
            logger.info(
                "premium lock: jeu catalogue réclamé conservé (app_id=%s)", sid
            )
            continue
        _quarantine_one_app(steam_path, sid, entry if isinstance(entry, dict) else {})
    n = sum(
        1
        for k in apps
        if not (
            skip_id
            and str(k) == skip_id
            and str(k) in _LAUNCHER_FREE_CATALOG_IDS
        )
    )
    logger.info("premium lock: quarantaine appliquée (%d jeu(x) traité(s))", n)
    return n


def _restore_all(steam_path: Path | None) -> None:
    if not steam_path or not steam_path.exists():
        logger.info("premium lock: restore skipped (no steam path)")
        return
    reg = _load_json(_REGISTRY_FILE, {})
    sk = _steam_key(steam_path)
    apps = (reg.get("per_steam") or {}).get(sk, {}).get("apps") or {}
    qroot = _BACKUP_ROOT / sk
    if not qroot.is_dir():
        return
    for app_id in apps.keys():
        _restore_one_app(steam_path, str(app_id))
    # dossiers sous backup : restaurer tout ce qui a une sauvegarde même hors registry
    try:
        for sub in qroot.iterdir():
            if sub.is_dir() and sub.name.isdigit():
                _restore_one_app(steam_path, sub.name)
    except Exception as e:
        logger.debug("premium lock restore scan: %s", e)
    logger.info("premium lock: restauration terminée pour Steam courant")


def _close_steam_to_refresh_library() -> None:
    """
    Steam garde la bibliotheque en memoire : sans fermer le processus, Play peut
    rester disponible. Fermeture automatique = pas de redemarrage manuel par l'utilisateur.
    """
    try:
        from sff.processes import force_close_steam_client

        if force_close_steam_client():
            logger.info(
                "premium lock: Steam was closed so the subscription lock applies immediately"
            )
    except Exception as e:
        logger.warning("premium lock: could not close Steam: %s", e)


def apply_rank_transition(steam_path: Path | str | None, new_rank_raw: str) -> dict[str, Any]:
    """
    À appeler après mise à jour auth.json avec le rang serveur.
    Compare au dernier rang enregistré ; en cas de passage payant -> FREE, met les
    Lua / manifests / clés / ACF sous quarantaine ; FREE -> payant restaure.
    """
    new_norm = _norm_rank(new_rank_raw)
    state = _load_json(_STATE_FILE, {})
    old_norm = state.get("last_norm_rank")
    sp: Path | None = None
    if steam_path:
        try:
            sp = Path(steam_path)
        except Exception:
            sp = None

    out: dict[str, Any] = {"old": old_norm, "new": new_norm, "action": "noop"}

    if old_norm is None:
        state["last_norm_rank"] = new_norm
        _save_json(_STATE_FILE, state)
        out["action"] = "init"
        return out

    paid_old = _norm_rank(old_norm) != "free"
    paid_new = new_norm != "free"

    if paid_old and not paid_new:
        if not sp or not sp.exists():
            logger.warning(
                "premium lock: passage payant->FREE sans chemin Steam valide - "
                "quarantaine reportee (reessaiera au prochain verify / sync)."
            )
            out["action"] = "quarantine_deferred"
            return out
        nq = _quarantine_all(sp)
        state["quarantine_active"] = True
        out["action"] = "quarantine"
        out["apps_quarantined"] = nq
        if nq > 0:
            _close_steam_to_refresh_library()
    elif not paid_old and paid_new:
        if not sp or not sp.exists():
            logger.warning(
                "premium lock: restauration reportee - chemin Steam absent ou invalide."
            )
            out["action"] = "restore_deferred"
            return out
        _restore_all(sp)
        state["quarantine_active"] = False
        out["action"] = "restore"
        _close_steam_to_refresh_library()

    state["last_norm_rank"] = new_norm
    _save_json(_STATE_FILE, state)
    return out


def run_startup_check(steam_path: Path | str | None) -> dict[str, Any]:
    """
    À chaque ouverture du launcher (après auth) : si le compte est en quarantaine
    active (passage payant → FREE) mais des .lua réapparaissent dans stplug-in,
    les renvoie dans Manifests_Backup (copie manuelle / sync outil tiers).
    """
    state = _load_json(_STATE_FILE, {})
    if _norm_rank(state.get("last_norm_rank")) != "free":
        return {"action": "skip", "reason": "not_free_plan"}
    if not state.get("quarantine_active"):
        return {"action": "skip", "reason": "not_quarantined"}
    if not steam_path:
        return {"action": "skip", "reason": "no_steam"}
    sp = Path(steam_path)
    if not sp.exists():
        return {"action": "skip", "reason": "bad_steam"}
    reg = _load_json(_REGISTRY_FILE, {})
    sk = _steam_key(sp)
    apps = (reg.get("per_steam") or {}).get(sk, {}).get("apps") or {}
    fixed = 0
    skip_id = _free_claimed_app_id()
    for app_id, entry in apps.items():
        sid = str(app_id)
        if skip_id and sid == skip_id and sid in _LAUNCHER_FREE_CATALOG_IDS:
            continue
        lua_live = sp / "config" / "stplug-in" / f"{sid}.lua"
        if lua_live.is_file():
            _quarantine_one_app(sp, sid, entry if isinstance(entry, dict) else {})
            fixed += 1
    if fixed > 0:
        _close_steam_to_refresh_library()
    return {"action": "leak_repair", "count": fixed}
