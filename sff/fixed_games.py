# SlimeDeals — Jeux fixed (téléchargement BuzzHeavier + extraction Steam)



from __future__ import annotations



import json

import logging

import os

import re

import shutil

import tempfile

import time

import zipfile

from datetime import datetime

from pathlib import Path

from typing import Callable



import httpx

from sff.buzzheavier_download import download_buzzheavier, parse_buzzheavier_url, UiLogCb

from sff.hv_fix import _extract_to_game_folder

from sff.utils import root_folder



log = logging.getLogger("sff")



ProgressCb = Callable[[int, int, str], None]





def _fixed_log(ui_log: UiLogCb | None, msg: str) -> None:

    if ui_log:

        try:

            ui_log(msg)

        except Exception:

            pass

    log.info("[fixed] %s", msg)



# Termes à ne jamais afficher dans l’UI (messages utilisateur)

_UI_BLOCKLIST_RE = re.compile(

    r"\b(buzzheavier|steamrip|steam\s*rip|repack|fafda\.to)\b",

    re.IGNORECASE,

)





def sanitize_user_message(msg: str) -> str:

    """Retire les mentions de sources / hébergeurs dans les textes affichés."""

    if not msg:

        return ""

    text = _UI_BLOCKLIST_RE.sub("", str(msg))

    text = re.sub(r"\s{2,}", " ", text)

    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()



_CATALOG_PATH = Path(__file__).resolve().parent / "data" / "fixed_games.json"
_CATALOG_REMOTE_URL = os.getenv("SLIMEDEALS_API", "https://slimedeals.fr") + "/api/fixed-games/catalog"
_CATALOG_REV_URL = os.getenv("SLIMEDEALS_API", "https://slimedeals.fr") + "/api/fixed-games/rev"
_CATALOG_CACHE_TTL = 15  # secondes — rafraîchissement quasi live depuis l’admin
_catalog_cache: list[dict] | None = None
_catalog_cache_ts: float = 0.0
_catalog_cache_rev: int = 0





def _catalog_path_writable() -> Path:
    """Catalogue embarqué ou copie utilisateur."""
    base = root_folder(outside_internal=True) / "fixed_games"
    user_copy = base / "catalog.json"
    if user_copy.is_file():
        return user_copy
    return _CATALOG_PATH


def _catalog_user_copy_path() -> Path:
    return root_folder(outside_internal=True) / "fixed_games" / "catalog.json"


def _load_local_catalog() -> list[dict]:
    path = _catalog_path_writable()
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, list):
            return [g for g in data if isinstance(g, dict) and g.get("id")]
    except Exception:
        log.exception("load_fixed_games_catalog (local) %s", path)
    return []


def _fetch_remote_catalog_rev() -> int | None:
    try:
        resp = httpx.get(_CATALOG_REV_URL, timeout=3.0, follow_redirects=True)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if isinstance(data, dict):
            rev = data.get("rev")
            if rev is not None:
                return int(rev)
    except Exception:
        pass
    return None


def _fetch_remote_catalog() -> list[dict] | None:
    try:
        resp = httpx.get(_CATALOG_REMOTE_URL, timeout=5.0, follow_redirects=True)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, list):
            return None
        remote = [g for g in data if isinstance(g, dict) and g.get("id")]
        if not remote:
            return None
        rev_hdr = resp.headers.get("X-Catalog-Rev") or resp.headers.get("x-catalog-rev")
        if rev_hdr:
            try:
                global _catalog_cache_rev
                _catalog_cache_rev = int(rev_hdr)
            except (TypeError, ValueError):
                pass
        return remote
    except Exception:
        return None


def invalidate_fixed_games_catalog_cache() -> None:
    global _catalog_cache, _catalog_cache_ts, _catalog_cache_rev
    _catalog_cache = None
    _catalog_cache_ts = 0.0
    _catalog_cache_rev = 0


def load_fixed_games_catalog_fast() -> list[dict]:
    """Cache mémoire ou fichier local — jamais de réseau (safe pour le thread UI Qt)."""
    global _catalog_cache, _catalog_cache_ts
    if _catalog_cache is not None:
        return _catalog_cache
    result = _load_local_catalog()
    if result:
        _catalog_cache = result
        _catalog_cache_ts = time.monotonic()
    return result


def load_fixed_games_catalog(*, force: bool = False) -> list[dict]:
    global _catalog_cache, _catalog_cache_ts, _catalog_cache_rev
    now = time.monotonic()

    if not force and _catalog_cache is not None and (now - _catalog_cache_ts) < _CATALOG_CACHE_TTL:
        return _catalog_cache

    remote_rev = _fetch_remote_catalog_rev()
    if (
        not force
        and _catalog_cache is not None
        and remote_rev is not None
        and remote_rev == _catalog_cache_rev
        and (now - _catalog_cache_ts) < 60
    ):
        _catalog_cache_ts = now
        return _catalog_cache

    remote = _fetch_remote_catalog()
    if remote:
        _catalog_cache = remote
        _catalog_cache_ts = now
        if remote_rev is not None:
            _catalog_cache_rev = remote_rev
        try:
            copy = _catalog_user_copy_path()
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_text(
                json.dumps(remote, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
        return remote

    if not force and _catalog_cache is not None:
        _catalog_cache_ts = now
        return _catalog_cache

    result = _load_local_catalog()
    _catalog_cache = result
    _catalog_cache_ts = now
    return result


def get_fixed_game(game_id: str) -> dict | None:

    gid = (game_id or "").strip().lower()

    for g in load_fixed_games_catalog_fast():

        if str(g.get("id", "")).strip().lower() == gid:

            return g

    return None





def parse_size_to_bytes(size_label: str | None) -> int | None:

    """Convertit « 34.9 GB », « 34,9 Go », etc. en octets."""

    if not size_label:

        return None

    s = str(size_label).strip().lower().replace(",", ".")

    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(tb|to|gb|go|mb|mo|kb|ko|b)?", s)

    if not m:

        return None

    val = float(m.group(1))

    unit = (m.group(2) or "b").lower()

    mult = {

        "tb": 1024**4,

        "to": 1024**4,

        "gb": 1024**3,

        "go": 1024**3,

        "mb": 1024**2,

        "mo": 1024**2,

        "kb": 1024,

        "ko": 1024,

        "b": 1,

    }.get(unit, 1)

    return int(val * mult)





def required_bytes_for_game(entry: dict | None) -> int:

    if not entry:

        return 40 * 1024**3

    raw = entry.get("size_bytes")

    if raw is not None:

        try:

            n = int(raw)

            if n > 0:

                return n

        except (TypeError, ValueError):

            pass

    parsed = parse_size_to_bytes(entry.get("size_label"))

    return parsed if parsed and parsed > 0 else 40 * 1024**3





def _trim_decimal(value: str) -> str:
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value


def format_bytes(n: int) -> str:
    n = max(0, int(n))
    gb, mb, kb = 1024**3, 1024**2, 1024
    if n >= gb:
        v = n / gb
        if v >= 100:
            return f"{v:.0f} Go"
        if v >= 10:
            return f"{_trim_decimal(f'{v:.1f}')} Go"
        return f"{_trim_decimal(f'{v:.2f}')} Go"
    if n >= mb:
        v = n / mb
        if v >= 100:
            return f"{v:.0f} Mo"
        return f"{_trim_decimal(f'{v:.1f}')} Mo"
    if n >= kb:
        return f"{n / kb:.0f} Ko"
    return f"{n} o"


def format_progress_bytes(done: int, total: int) -> str:
    """Affiche une progression lisible, ex. « 0,26 Go / 13,1 Go »."""
    done = max(0, int(done))
    total = max(0, int(total))
    if total <= 0:
        return format_bytes(done)

    gb, mb = 1024**3, 1024**2

    def _fmt_gb(v: int) -> str:
        x = v / gb
        if x >= 10:
            return f"{_trim_decimal(f'{x:.1f}')} Go"
        if x >= 1:
            return f"{_trim_decimal(f'{x:.1f}')} Go"
        return f"{_trim_decimal(f'{x:.2f}')} Go"

    def _fmt_mb(v: int) -> str:
        x = v / mb
        if x >= 100:
            return f"{x:.0f} Mo"
        return f"{_trim_decimal(f'{x:.1f}')} Mo"

    if total >= gb:
        return f"{_fmt_gb(done)} / {_fmt_gb(total)}"
    if total >= mb:
        return f"{_fmt_mb(done)} / {_fmt_mb(total)}"
    return f"{format_bytes(done)} / {format_bytes(total)}"





def resolve_install_directory(target: str | Path) -> Path:

    """

    Chemin d'installation final.

    Accepte une bibliothèque Steam (racine) ou un dossier déjà ciblé (ex. steamapps/common).

    """

    p = Path(target).resolve()

    if (p / "steamapps" / "common").is_dir() or (p / "steamapps").is_dir():

        return _steam_common_dir(p)

    if p.name.lower() == "common" and p.parent.name.lower() == "steamapps":

        return p

    return p





def _partial_download_info_for_entry(entry: dict | None) -> dict:
    """Partiel BuzzHeavier pour une entrée catalogue (sans recharger le catalogue)."""
    if not entry:
        return {"partial_bytes": 0, "partial_pct": 0, "partial_human": ""}

    url = (entry.get("url") or "").strip()

    if not url:

        return {"partial_bytes": 0, "partial_pct": 0, "partial_human": ""}

    try:

        from sff.buzzheavier_download import parse_buzzheavier_url

        file_id = parse_buzzheavier_url(url)

        if not file_id:

            return {"partial_bytes": 0, "partial_pct": 0, "partial_human": ""}

        dl_dir = root_folder(outside_internal=True) / "fixed_downloads" / file_id.strip().lower()

        if not dl_dir.is_dir():

            return {"partial_bytes": 0, "partial_pct": 0, "partial_human": ""}

        partial_file = next((p for p in sorted(dl_dir.glob(f"{file_id}.*")) if p.is_file()), None)

        if not partial_file:

            return {"partial_bytes": 0, "partial_pct": 0, "partial_human": ""}

        partial_bytes = partial_file.stat().st_size

        if partial_bytes < 1024 * 1024:

            return {"partial_bytes": 0, "partial_pct": 0, "partial_human": ""}

        total = required_bytes_for_game(entry)

        pct = int(partial_bytes * 100 / total) if total > 0 else 0

        pct = min(pct, 99)

        return {

            "partial_bytes": partial_bytes,

            "partial_pct": pct,

            "partial_human": format_bytes(partial_bytes),

        }

    except Exception:

        return {"partial_bytes": 0, "partial_pct": 0, "partial_human": ""}


def _partial_download_info(game_id: str) -> dict:
    """Retourne les infos du téléchargement partiel existant pour un jeu (taille, %)."""
    return _partial_download_info_for_entry(get_fixed_game(game_id))


def get_all_partials_from_catalog(catalog: list[dict]) -> dict:
    """Partiels pour un catalogue déjà chargé (évite N× lookup)."""
    result: dict = {}
    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        gid = (entry.get("id") or "").strip()
        if not gid:
            continue
        info = _partial_download_info_for_entry(entry)
        if info.get("partial_bytes", 0) > 0:
            result[gid] = info
    return result


def get_all_partials() -> dict:
    """Retourne les infos de téléchargement partiel pour tous les jeux du catalogue."""
    try:
        return get_all_partials_from_catalog(load_fixed_games_catalog_fast())
    except Exception:
        return {}


def get_installed_fixed_catalog_ids_from_catalog(catalog: list[dict]) -> list[str]:
    """IDs catalogue des Pépites installées, à partir d’un catalogue déjà en mémoire."""
    app_to_catalog: dict[str, str] = {}
    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        cid = (entry.get("id") or "").strip()
        aid = str(entry.get("app_id") or "").strip()
        if cid and aid.isdigit():
            app_to_catalog[aid] = cid
    installed: list[str] = []
    seen: set[str] = set()
    for sg in get_sideloaded_games():
        aid = str(sg.get("app_id") or "").strip()
        cid = app_to_catalog.get(aid)
        if cid and cid not in seen:
            seen.add(cid)
            installed.append(cid)
    return installed


def _steam_header_image_url(app_id: str) -> str:
    aid = str(app_id or "").strip()
    if not aid.isdigit():
        return ""
    return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{aid}/header.jpg"


def _fetch_steam_header_urls_batch(app_ids: list[int]) -> dict[int, str]:
    """URLs d’assets Steam officielles (IStoreBrowseService) — Pragmata et jeux récents."""
    if not app_ids:
        return {}
    import json as _json
    import urllib.parse as _urlparse
    import urllib.request as _req

    result: dict[int, str] = {}
    try:
        payload = {
            "ids": [{"appid": aid} for aid in app_ids],
            "context": {"language": "english", "country_code": "US"},
            "data_request": {"include_assets": True},
        }
        url = (
            "https://api.steampowered.com/IStoreBrowseService/GetItems/v1?input_json="
            + _urlparse.quote(_json.dumps(payload, separators=(",", ":")))
        )
        request = _req.Request(url, headers={"User-Agent": "SlimeDeals/5.4.0"})
        with _req.urlopen(request, timeout=8) as resp:
            data = _json.loads(resp.read())
        for item in data.get("response", {}).get("store_items", []):
            appid = item.get("appid")
            header = (item.get("assets") or {}).get("header", "")
            if appid and header:
                result[int(appid)] = (
                    f"https://shared.steamstatic.com/store_item_assets/steam/apps/"
                    f"{appid}/{header}"
                )
        log.info("[Jeux VIP] GetItems OK — %s/%s jaquettes", len(result), len(app_ids))
    except Exception as exc:
        log.warning("[Jeux VIP] Steam GetItems batch échoué : %s", exc)
    return result


def _fetch_steam_store_header_image(app_id: int) -> str:
    """Fallback store.steampowered.com/api/appdetails (header_image)."""
    try:
        import json as _json
        import urllib.request as _req

        url = (
            f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english"
        )
        request = _req.Request(url, headers={"User-Agent": "SlimeDeals/5.4.0"})
        with _req.urlopen(request, timeout=10) as resp:
            data = _json.loads(resp.read())
        block = data.get(str(app_id), {})
        if block.get("success") and isinstance(block.get("data"), dict):
            hdr = (block["data"].get("header_image") or "").strip()
            if hdr.startswith("http"):
                return hdr.split("?")[0]
    except Exception as exc:
        log.debug("[Jeux VIP] appdetails %s : %s", app_id, exc)
    return ""


def enrich_catalog_header_images(catalog: list[dict]) -> list[dict]:
    """header_image via API Steam (prioritaire) puis CDN générique."""
    app_ids: list[int] = []
    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        aid = str(entry.get("app_id") or "").strip()
        if aid.isdigit():
            app_ids.append(int(aid))
    steam_urls = _fetch_steam_header_urls_batch(app_ids)

    out: list[dict] = []
    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        row = dict(entry)
        aid = str(row.get("app_id") or "").strip()
        aid_int = int(aid) if aid.isdigit() else 0
        eid = (row.get("id") or "?").strip()
        if aid_int and aid_int in steam_urls:
            row["header_image"] = steam_urls[aid_int]
        elif aid_int:
            store_hdr = _fetch_steam_store_header_image(aid_int)
            if store_hdr:
                row["header_image"] = store_hdr
                log.info("[Jeux VIP] %s appdetails → %s", eid, store_hdr[:72])
            elif not (row.get("header_image") or row.get("image_url")):
                url = _steam_header_image_url(aid)
                if url:
                    row["header_image"] = url
        elif not (row.get("header_image") or row.get("image_url")):
            url = _steam_header_image_url(aid)
            if url:
                row["header_image"] = url
        out.append(row)
    return out


def collect_gamefixes_page_state(*, fetch_remote: bool = False) -> dict:
    """Tout le travail I/O Jeux VIP — à exécuter hors du thread UI Qt."""
    catalog = load_fixed_games_catalog_fast()
    if fetch_remote:
        try:
            remote = load_fixed_games_catalog(force=True)
            if remote:
                catalog = remote
        except Exception:
            log.debug("collect_gamefixes_page_state remote", exc_info=True)
    catalog = enrich_catalog_header_images(catalog)
    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        eid = entry.get("id", "?")
        aid = entry.get("app_id", "")
        hdr = bool(entry.get("header_image") or entry.get("image_url"))
        hdr_url = (entry.get("header_image") or entry.get("image_url") or "")[:80]
        log.info(
            "[Jeux VIP] catalogue %s app_id=%s image=%s",
            eid,
            aid,
            hdr_url or "(aucune)",
        )
    return {
        "catalog": catalog,
        "installed_ids": get_installed_fixed_catalog_ids_from_catalog(catalog),
        "partials": get_all_partials_from_catalog(catalog),
    }





def check_install_requirements(game_id: str, install_dir: str | Path) -> dict:

    """Vérifie l'espace disque (dossier cible + temp pour le .rar téléchargé)."""

    entry = get_fixed_game(game_id)

    required = required_bytes_for_game(entry)

    margin = int(required * 0.08) + 2 * 1024**3

    need = required + margin



    install_path = resolve_install_directory(install_dir)

    temp_root = Path(tempfile.gettempdir()).resolve()



    partial = _partial_download_info(game_id)



    out = {

        "ok": False,

        "game_id": game_id,

        "game_name": (entry.get("name") if entry else None) or game_id,

        "size_label": (entry.get("size_label") if entry else None) or format_bytes(required),

        "required_bytes": required,

        "required_with_margin_bytes": need,

        "install_path": str(install_path),

        "temp_path": str(temp_root),

        "free_install_bytes": 0,

        "free_temp_bytes": 0,

        "install_ok": False,

        "temp_ok": False,

        "message": "",

        "partial_bytes": partial["partial_bytes"],

        "partial_pct": partial["partial_pct"],

        "partial_human": partial["partial_human"],

    }



    try:

        install_path.mkdir(parents=True, exist_ok=True)

    except OSError as e:

        out["message"] = f"Impossible d'utiliser ce dossier : {e}"

        return out



    try:

        free_install = shutil.disk_usage(str(install_path)).free

        free_temp = shutil.disk_usage(str(temp_root)).free

    except OSError as e:

        out["message"] = f"Impossible de lire l'espace disque : {e}"

        return out



    out["free_install_bytes"] = free_install

    out["free_temp_bytes"] = free_temp

    out["install_ok"] = free_install >= need

    out["temp_ok"] = free_temp >= need

    out["ok"] = out["install_ok"] and out["temp_ok"]



    if out["ok"]:

        out["message"] = "Espace disque suffisant."

    elif not out["install_ok"] and not out["temp_ok"]:

        out["message"] = (

            f"Espace insuffisant sur le disque d'installation ({format_bytes(free_install)} libre) "

            f"et sur le disque temporaire ({format_bytes(free_temp)} libre). "

            f"Environ {format_bytes(need)} requis sur chaque disque."

        )

    elif not out["install_ok"]:

        out["message"] = (

            f"Espace insuffisant sur le disque d'installation : {format_bytes(free_install)} libre, "

            f"{format_bytes(need)} recommandés."

        )

    else:

        out["message"] = (

            f"Espace insuffisant sur le disque temporaire (téléchargement) : {format_bytes(free_temp)} libre, "

            f"{format_bytes(need)} recommandés."

        )

    return out





def _persistent_download_dir(file_id: str) -> Path:

    """Dossier persistant pour reprendre un gros téléchargement après coupure."""

    p = root_folder(outside_internal=True) / "fixed_downloads" / (file_id or "unknown").strip().lower()

    p.mkdir(parents=True, exist_ok=True)

    return p





def _steam_common_dir(library_path: str | Path) -> Path:

    lib = Path(library_path).resolve()

    if (lib / "steamapps" / "common").is_dir():

        return lib / "steamapps" / "common"

    if lib.name.lower() == "common" and lib.parent.name.lower() == "steamapps":

        return lib

    return lib / "steamapps" / "common"





# ── Registre local des jeux sideloaded ──────────────────────────────────────



def _sideloaded_registry_path() -> Path:

    return root_folder(outside_internal=True) / "sideloaded_games.json"





def get_sideloaded_games() -> list[dict]:

    """Retourne la liste des jeux Pépites installés (registre local JSON)."""

    p = _sideloaded_registry_path()

    if not p.exists():

        return []

    try:

        data = json.loads(p.read_text(encoding="utf-8"))

        return data if isinstance(data, list) else []

    except Exception:

        return []





def _register_sideloaded_game(app_id: str | int, name: str, game_folder: Path) -> None:

    """Enregistre ou met à jour un jeu Pépites dans le registre local."""

    registry = get_sideloaded_games()

    path_str = str(game_folder)

    app_id_int = int(app_id) if str(app_id).isdigit() else 0

    for entry in registry:

        if entry.get("path") == path_str or (app_id_int and entry.get("app_id") == app_id_int):

            entry.update({"app_id": app_id_int, "name": name, "path": path_str, "source": "fixed"})

            break

    else:

        registry.append({

            "app_id": app_id_int,

            "name": name,

            "path": path_str,

            "source": "fixed",

            "install_date": datetime.now().isoformat(timespec="seconds"),

        })

    try:

        _sideloaded_registry_path().write_text(

            json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"

        )

    except Exception as e:

        log.warning(f"_register_sideloaded_game: {e}")


def get_installed_fixed_catalog_ids() -> list[str]:
    """IDs catalogue (ex. subnautica2) des Pépites déjà installées (registre sideloaded)."""
    return get_installed_fixed_catalog_ids_from_catalog(load_fixed_games_catalog_fast())


_FIXED_GAMES_BACKUP_ROOT = Path.home() / ".slimedeals" / "FixedGames_Backup"
_FIXED_GAMES_BACKUP_INDEX = _FIXED_GAMES_BACKUP_ROOT / "index.json"


def _sideload_path_key(path: str | Path) -> str:
    try:
        return str(Path(path).resolve()).lower()
    except OSError:
        return str(path or "").strip().lower()


def is_registered_sideloaded_path(folder: str | Path) -> bool:
    """True si le dossier correspond à un jeu Pépite enregistré localement."""
    target = _sideload_path_key(folder)
    if not target:
        return False
    for sg in get_sideloaded_games():
        sg_path = (sg.get("path") or "").strip()
        if sg_path and _sideload_path_key(sg_path) == target:
            return True
    return False


def quarantine_sideloaded_fixed_games() -> int:
    """
    Retire les jeux Pépites du disque actif (backup + registre vide).
    Appelé quand l'abonnement Triple Monstre n'est plus actif.
    """
    registry = get_sideloaded_games()
    if not registry:
        return 0

    _FIXED_GAMES_BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stored: dict = {}
    if _FIXED_GAMES_BACKUP_INDEX.is_file():
        try:
            raw = json.loads(_FIXED_GAMES_BACKUP_INDEX.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                stored = raw
        except Exception:
            stored = {}

    count = 0
    for entry in registry:
        path_str = (entry.get("path") or "").strip()
        if not path_str:
            continue
        src = Path(path_str)
        app_id = str(entry.get("app_id") or "").strip()
        slug = app_id or re.sub(r"[^a-z0-9]+", "", (entry.get("name") or "game").lower()) or "game"
        dest = _FIXED_GAMES_BACKUP_ROOT / slug
        if src.is_dir():
            try:
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.move(str(src), str(dest))
            except OSError:
                try:
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                    shutil.rmtree(src, ignore_errors=True)
                except OSError as e:
                    log.warning("quarantine_sideloaded_fixed_games move %s: %s", src, e)
                    dest = src
        stored[slug] = {
            **entry,
            "backup_path": str(dest),
            "original_path": path_str,
        }
        count += 1

    try:
        _FIXED_GAMES_BACKUP_INDEX.write_text(
            json.dumps(stored, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _sideloaded_registry_path().write_text("[]", encoding="utf-8")
    except Exception as e:
        log.warning("quarantine_sideloaded_fixed_games index: %s", e)
    return count


def restore_sideloaded_fixed_games() -> int:
    """Restaure les jeux Pépites depuis le backup (retour Triple Monstre)."""
    if not _FIXED_GAMES_BACKUP_INDEX.is_file():
        return 0
    try:
        stored = json.loads(_FIXED_GAMES_BACKUP_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(stored, dict) or not stored:
        return 0

    registry: list[dict] = []
    count = 0
    for slug, entry in stored.items():
        if not isinstance(entry, dict):
            continue
        backup_path = Path(str(entry.get("backup_path") or ""))
        original_path = Path(str(entry.get("original_path") or backup_path))
        if backup_path.is_dir():
            try:
                original_path.parent.mkdir(parents=True, exist_ok=True)
                if original_path.exists():
                    shutil.rmtree(original_path, ignore_errors=True)
                if backup_path.resolve() != original_path.resolve():
                    shutil.move(str(backup_path), str(original_path))
            except OSError as e:
                log.warning("restore_sideloaded_fixed_games %s: %s", backup_path, e)
                continue
        registry.append({
            "app_id": entry.get("app_id") or 0,
            "name": entry.get("name") or slug,
            "path": str(original_path),
            "source": "fixed",
        })
        count += 1

    if registry:
        try:
            _sideloaded_registry_path().write_text(
                json.dumps(registry, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("restore_sideloaded_fixed_games registry: %s", e)
    try:
        _FIXED_GAMES_BACKUP_INDEX.unlink(missing_ok=True)
    except OSError:
        pass
    return count


def enforce_sideloaded_rank_policy(rank: str | None) -> int:
    """Quarantaine auto si le rang ne permet plus les Pépites (Triple Monstre)."""
    from sff.launcher_ranks import triple_exclusive_tools_allowed_for_rank

    if triple_exclusive_tools_allowed_for_rank(rank):
        return 0
    if not get_sideloaded_games():
        return 0
    return quarantine_sideloaded_fixed_games()




def _detect_game_folder(

    common: Path, before_names: set[str], folder_hint: str | None

) -> Path | None:

    """Détecte le dossier du jeu créé dans common/ après extraction."""

    # 1. Cherche d'abord par folder_hint

    if folder_hint:

        hint_path = common / folder_hint

        if hint_path.is_dir():

            return hint_path

    # 2. Compare snapshot avant/après

    try:

        after_names = {d.name for d in common.iterdir() if d.is_dir()}

        new_names = after_names - before_names

        if len(new_names) == 1:

            return common / next(iter(new_names))

        if new_names:

            # Plusieurs nouveaux dossiers : prend le plus grand

            candidates = [common / n for n in new_names]

            return max(candidates, key=lambda p: sum(

                f.stat().st_size for f in p.rglob("*") if f.is_file()

            ), default=None)

    except Exception as e:

        log.debug(f"_detect_game_folder: {e}")

    return None





def install_fixed_game_from_url(

    buzz_url: str,

    install_dir: str | Path,

    game_name: str = "Jeu",

    on_progress: ProgressCb | None = None,

    ui_log: UiLogCb | None = None,

    expected_bytes: int = 0,

    folder_hint: str | None = None,

) -> tuple[bool, str, Path | None]:

    """Télécharge depuis BuzzHeavier et extrait dans install_dir."""

    _fixed_log(ui_log, f"URL catalogue : {buzz_url!r}")

    file_id = parse_buzzheavier_url(buzz_url)

    if not file_id:

        _fixed_log(ui_log, "parse URL → file_id invalide (hôte ou chemin incorrect)")

        return False, "Lien de téléchargement invalide.", None



    _fixed_log(ui_log, f"Identifiant distant : {file_id!r}")



    common = resolve_install_directory(install_dir)

    try:

        common.mkdir(parents=True, exist_ok=True)

    except OSError as e:

        _fixed_log(ui_log, f"mkdir installation : {e!r}")

        return False, f"Impossible de créer le dossier d'installation : {e}", None



    _fixed_log(ui_log, f"Dossier d’installation résolu : {common}")



    # Snapshot avant extraction pour détecter le dossier du jeu créé

    try:

        before_names: set[str] = {d.name for d in common.iterdir() if d.is_dir()}

    except Exception:

        before_names = set()



    def _prog(done: int, total: int, msg: str) -> None:

        if on_progress:

            on_progress(done, total, msg)



    dl_dir = _persistent_download_dir(file_id)

    _fixed_log(ui_log, f"Dossier téléchargement (reprise) : {dl_dir}")

    archive = download_buzzheavier(

        file_id,

        dl_dir,

        on_progress=_prog,

        ui_log=ui_log,

        expected_bytes=expected_bytes,

        catalog_url=buzz_url,

    )

    if archive is None or not archive.is_file():
        _fixed_log(ui_log, "Archive absente après téléchargement")
        return (
            False,
            "Téléchargement BuzzHeavier échoué (lien inaccessible ou bloqué par Cloudflare). "
            "Réessaie dans quelques minutes.",
            None,
        )



    from sff.buzzheavier_download import validate_downloaded_archive



    ok_arc, arc_err = validate_downloaded_archive(archive, expected_bytes)

    if not ok_arc:

        _fixed_log(ui_log, f"Validation archive : {arc_err}")

        return False, arc_err, None



    _fixed_log(

        ui_log,

        f"Archive OK : {archive} ({archive.stat().st_size:,} octets)",

    )

    _prog(0, 0, "Extraction des fichiers du jeu…")

    ext = archive.suffix.lower()

    _fixed_log(ui_log, f"Extraction type={ext!r} → {common}")

    try:

        if ext == ".zip":

            _fixed_log(ui_log, "Méthode : zipfile (stdlib)")

            with zipfile.ZipFile(archive, "r") as zf:

                names = zf.namelist()

                _fixed_log(ui_log, f"ZIP : {len(names)} entrée(s)")

                zf.extractall(common)

            ok = True

        else:

            _fixed_log(ui_log, "Méthode : 7-Zip / WinRAR (hv_fix)")

            ok = _extract_to_game_folder(archive, common, game_name)

    except Exception as e:

        log.exception("install_fixed_game extract")

        _fixed_log(ui_log, f"Exception extraction : {type(e).__name__}: {e}")

        return False, f"Extraction échouée : {e}", None



    if not ok:

        _fixed_log(ui_log, "Extraction renvoyée False (outil manquant ou archive corrompue)")

        return False, "Extraction échouée (7-Zip / WinRAR requis pour .rar/.7z).", None



    _fixed_log(ui_log, f"Extraction terminée dans {common}")



    try:

        if archive.is_file():

            archive.unlink()

            _fixed_log(ui_log, "Archive supprimée après extraction (libération d’espace).")

    except OSError:

        pass



    # Détection du dossier du jeu (avant/après extraction + folder_hint)

    game_folder = _detect_game_folder(common, before_names, folder_hint)

    return True, f"{game_name} installé dans :\n{common}", game_folder





def install_fixed_game_by_id(

    game_id: str,

    install_dir: str | Path,

    on_progress: ProgressCb | None = None,

    ui_log: UiLogCb | None = None,

) -> tuple[bool, str]:

    entry = get_fixed_game(game_id)

    if not entry:

        _fixed_log(ui_log, f"Catalogue : jeu {game_id!r} introuvable")

        return False, "Jeu introuvable dans le catalogue."

    url = (entry.get("url") or "").strip()

    name = (entry.get("name") or game_id).strip()

    app_id = entry.get("app_id")

    _fixed_log(

        ui_log,

        f"Catalogue : id={game_id!r} nom={name!r} app_id={app_id!r} "

        f"taille={entry.get('size_label')!r}",

    )

    if not url:

        _fixed_log(ui_log, "Pas d’URL de téléchargement dans l’entrée catalogue")

        return False, "Ce jeu n'a pas de lien de téléchargement configuré."



    check = check_install_requirements(game_id, install_dir)

    _fixed_log(

        ui_log,

        f"Vérif espace : ok={check.get('ok')} install={check.get('free_install_bytes'):,} o "

        f"temp={check.get('free_temp_bytes'):,} o requis≈{check.get('required_with_margin_bytes'):,} o "

        f"chemin={check.get('install_path')!r}",

    )

    if not check.get("ok"):

        _fixed_log(ui_log, f"Refus espace disque : {check.get('message')}")

        return False, check.get("message") or "Espace disque insuffisant."



    expected = required_bytes_for_game(entry)

    folder_hint = (entry.get("folder_hint") or "").strip() or None

    ok, message, game_folder = install_fixed_game_from_url(

        url,

        install_dir,

        name,

        on_progress=on_progress,

        ui_log=ui_log,

        expected_bytes=expected,

        folder_hint=folder_hint,

    )

    message = sanitize_user_message(message)

    if ok:

        common = resolve_install_directory(install_dir)

        message = f"{name} a été installé avec succès.\nEmplacement : {common}"

        # Enregistrement dans le registre local (bibliothèque)

        _fixed_log(ui_log, f"Enregistrement dans le registre sideloaded : dossier={game_folder}")

        if game_folder and game_folder.is_dir():

            _register_sideloaded_game(app_id or 0, name, game_folder)

        else:

            # Fallback : utilise common comme dossier racine du jeu

            _register_sideloaded_game(app_id or 0, name, common)

    return ok, message

