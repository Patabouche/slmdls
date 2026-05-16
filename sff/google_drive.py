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

import io
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _legacy_steamidra_config_dir() -> Path:
    """Ancien dossier config OAuth (%APPDATA%/SteaMidra, etc.) — compatibilité jetons existants."""
    if sys.platform == "win32":
        ap = (os.environ.get("APPDATA") or "").strip()
        if ap:
            return Path(ap) / "SteaMidra"
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "SteaMidra"
    return Path.home() / ".config" / "SteaMidra"


def _slimedeals_gdrive_config_dir() -> Path:
    """Dossier de configuration persistant (jeton OAuth, fichier client JSON) — marque SlimeDeals."""
    if sys.platform == "win32":
        ap = (os.environ.get("APPDATA") or "").strip()
        if ap:
            return Path(ap) / "SlimeDeals"
    xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "SlimeDeals"
    return Path.home() / ".config" / "SlimeDeals"


def _gdrive_oauth_client_json_paths() -> tuple[Path, Path]:
    return (
        _slimedeals_gdrive_config_dir() / "gdrive_oauth_client.json",
        _legacy_steamidra_config_dir() / "gdrive_oauth_client.json",
    )


def _resolved_gdrive_token_path() -> Path:
    primary = _slimedeals_gdrive_config_dir() / "gdrive_token.json"
    legacy = _legacy_steamidra_config_dir() / "gdrive_token.json"
    if primary.exists():
        return primary
    if legacy.exists():
        return legacy
    return primary


def _gdrive_token_path_write() -> Path:
    """Fichier jeton pour nouvelles écritures (toujours sous SlimeDeals)."""
    return _slimedeals_gdrive_config_dir() / "gdrive_token.json"


def _sff_install_root() -> Path:
    """Racine où PyInstaller extrait les ``datas`` (fichiers à la racine du bundle).

    En dev : parent du package ``sff`` (dossier ``launcher/SFF``).
    En exe PyInstaller : ``sys._MEIPASS`` (fiable ; ``parent.parent`` depuis ``sff/`` peut diverger selon versions).
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return Path(__file__).resolve().parent.parent


def _frozen_exe_parent() -> Optional[Path]:
    """Répertoire contenant l'exécutable (portable / install) — utile si le JSON n'est pas dans _MEIPASS."""
    if not getattr(sys, "frozen", False):
        return None
    appimage = (os.environ.get("APPIMAGE") or "").strip()
    if appimage:
        return Path(appimage).resolve().parent
    return Path(sys.executable).resolve().parent


def _cid_secret_from_parsed_json(raw: object) -> Tuple[str, str]:
    """Extrait client_id / client_secret depuis le dict racine ou la clé ``installed``."""
    if not isinstance(raw, dict):
        return "", ""
    ins = raw.get("installed") if isinstance(raw.get("installed"), dict) else raw
    if not isinstance(ins, dict):
        return "", ""
    cid = (ins.get("client_id") or ins.get("clientId") or "").strip()
    csec = (ins.get("client_secret") or ins.get("clientSecret") or "").strip()
    return cid, csec


def _try_load_oauth_json_file(path: Path) -> Tuple[str, str]:
    if not path.is_file():
        return "", ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _cid_secret_from_parsed_json(raw)
    except Exception as e:
        logger.warning("Lecture OAuth JSON %s impossible: %s", path, e)
        return "", ""


def _load_client_id_secret() -> Tuple[str, str]:
    """Identifiants OAuth type « application de bureau » (non versionnés dans le dépôt).

    Ordre :

    1. Module ``sff._gc`` (get_ci / get_cs), en pratique via ``sff._gc_secrets`` si généré par
       ``write_gdrive_gc_secrets.py`` (identifiants encodés base64, non versionné).
    2. Variables d'environnement ``SLIMEDEALS_GDRIVE_CLIENT_*`` / ``STEAMIDRA_GDRIVE_CLIENT_*`` (compat.) / ``GOOGLE_OAUTH_*``.
    3. ``%APPDATA%/SlimeDeals/gdrive_oauth_client.json`` puis ancien ``.../SteaMidra/...`` si présent.
    4. ``sff/gdrive_oauth_client.json`` à côté de ce module (PyInstaller : fichier dans les datas ``sff/``).
    5. Racine bundle : ``gdrive_oauth_client.json``, puis ``client_secret*.json``
       (dev : ``launcher/SFF`` ; exe PyInstaller : fichiers à la racine ``_MEIPASS``).
    6. **À côté de l'exe** (build figé) : mêmes noms de fichiers — pratique pour un zip portable sans
       embarquer le secret dans l'exe.

    Formats acceptés : JSON minimal ou clé ``installed`` comme celui fourni par Google.
    """
    cid, csec = "", ""
    try:
        from sff._gc import get_ci, get_cs

        cid = (get_ci() or "").strip()
        csec = (get_cs() or "").strip()
    except ImportError:
        pass
    except Exception as e:
        logger.debug("sff._gc credentials: %s", e)
    if not cid or not csec:
        cid = (
            os.environ.get("SLIMEDEALS_GDRIVE_CLIENT_ID", "")
            or os.environ.get("STEAMIDRA_GDRIVE_CLIENT_ID", "")
            or os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
        ).strip()
        csec = (
            os.environ.get("SLIMEDEALS_GDRIVE_CLIENT_SECRET", "")
            or os.environ.get("STEAMIDRA_GDRIVE_CLIENT_SECRET", "")
            or os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
        ).strip()
    if not cid or not csec:
        for oauth_path in _gdrive_oauth_client_json_paths():
            cid, csec = _try_load_oauth_json_file(oauth_path)
            if cid and csec:
                break
    # JSON livré à côté de google_drive.py (ex. ``sff/gdrive_oauth_client.json`` embarqué via PyInstaller datas -> ``sff/``)
    if not cid or not csec:
        cid, csec = _try_load_oauth_json_file(
            Path(__file__).resolve().parent / "gdrive_oauth_client.json"
        )
    if not cid or not csec:
        root = _sff_install_root()
        cid, csec = _try_load_oauth_json_file(root / "gdrive_oauth_client.json")
    if not cid or not csec:
        root = _sff_install_root()
        for p in sorted(root.glob("client_secret*.json")):
            cid, csec = _try_load_oauth_json_file(p)
            if cid and csec:
                logger.info("OAuth Google Drive : identifiants chargés depuis %s", p.name)
                break
    if not cid or not csec:
        portable = _frozen_exe_parent()
        if portable is not None:
            cid, csec = _try_load_oauth_json_file(portable / "gdrive_oauth_client.json")
            if not cid or not csec:
                for p in sorted(portable.glob("client_secret*.json")):
                    cid, csec = _try_load_oauth_json_file(p)
                    if cid and csec:
                        logger.info(
                            "OAuth Google Drive : identifiants depuis %s (dossier de l'exécutable)",
                            p.name,
                        )
                        break
    return cid, csec


def _client_config():
    cid, csec = _load_client_id_secret()
    if not cid or not csec:
        return None
    return {
        "installed": {
            "client_id": cid,
            "client_secret": csec,
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
            "redirect_uris": ["http://localhost"],
        }
    }


def clear_saved_token() -> None:
    """Supprime le jeton OAuth local (déconnexion Google Drive)."""
    for p in (
        _gdrive_token_path_write(),
        _legacy_steamidra_config_dir() / "gdrive_token.json",
    ):
        try:
            if p.exists():
                p.unlink()
        except OSError as e:
            logger.warning("clear_saved_token: %s", e)


def oauth_deps_installed() -> bool:
    """True si les paquets Google (auth, oauthlib, API client) sont importables."""
    try:
        import google.auth  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
        import googleapiclient  # noqa: F401
        return True
    except ImportError:
        return False


def oauth_credentials_configured() -> bool:
    """True si client_id / client_secret sont résolus (fichiers, env ou module embarqué)."""
    return _client_config() is not None


def is_available():
    """Drive OAuth utilisable : dépendances Python OK **et** identifiants OAuth présents."""
    return oauth_deps_installed() and oauth_credentials_configured()


def is_authenticated():
    tok = _resolved_gdrive_token_path()
    if not tok.exists():
        return False
    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(str(tok), _SCOPES)
        return creds is not None and creds.refresh_token is not None
    except Exception:
        return False


def get_user_email(service):
    try:
        info = service.about().get(fields="user").execute()
        return info.get("user", {}).get("emailAddress", "")
    except Exception:
        return ""


def authorize(log_func=None):
    if is_authenticated():
        if log_func:
            log_func("[OK] Google Drive already connected.")
        return True
    cfg = _client_config()
    if cfg is None:
        if log_func:
            log_func(
                "[!] Client OAuth Google Drive introuvable. Installe les paquets "
                "google-auth, google-auth-oauthlib, google-api-python-client, puis "
                f"crée le fichier « {_gdrive_oauth_client_json_paths()[0]} » (client_id + client_secret) "
                "ou définis SLIMEDEALS_GDRIVE_CLIENT_ID / SLIMEDEALS_GDRIVE_CLIENT_SECRET "
                "(ou STEAMIDRA_* pour compatibilité)."
            )
        return False
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_config(cfg, _SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True, prompt="consent")
        tw = _gdrive_token_path_write()
        tw.parent.mkdir(parents=True, exist_ok=True)
        tw.write_text(creds.to_json(), encoding="utf-8")
        if log_func:
            log_func("[OK] Google Drive connected.")
        return True
    except Exception as e:
        if log_func:
            log_func(f"[FAIL] Google Drive auth failed: {e}")
        return False


def get_service():
    cfg = _client_config()
    if cfg is None:
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        tok = _resolved_gdrive_token_path()
        if not tok.exists():
            return None

        creds = Credentials.from_authorized_user_file(str(tok), _SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                tw = _gdrive_token_path_write()
                tw.parent.mkdir(parents=True, exist_ok=True)
                tw.write_text(creds.to_json(), encoding="utf-8")
            else:
                return None

        return build("drive", "v3", credentials=creds)
    except Exception as e:
        logger.warning("GDrive get_service failed: %s", e)
        return None


def find_folder(service, name, parent_id="root"):
    escaped = name.replace("'", "\\'")
    q = f"name='{escaped}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    try:
        res = service.files().list(q=q, fields="files(id,name)", pageSize=10).execute()
        files = res.get("files", [])
        return files[0]["id"] if files else None
    except Exception as e:
        logger.warning("GDrive find_folder '%s': %s", name, e)
        return None


def get_or_create_folder(service, name, parent_id="root"):
    fid = find_folder(service, name, parent_id)
    if fid:
        return fid
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    import time
    for attempt in range(4):
        try:
            f = service.files().create(body=meta, fields="id").execute()
            return f["id"]
        except Exception as e:
            try:
                from googleapiclient.errors import HttpError
                if isinstance(e, HttpError):
                    if e.resp.status == 409:
                        return find_folder(service, name, parent_id)
                    if e.resp.status == 429:
                        time.sleep(2 ** attempt)
                        continue
            except ImportError:
                pass
            logger.error("GDrive create_folder '%s': %s", name, e)
            return None
    return None


def _list_folder_index(service, parent_id):
    """Return {name: (file_id, size)} for all non-trashed files in a Drive folder."""
    index = {}
    page_token = None
    while True:
        try:
            params = {
                "q": f"'{parent_id}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'",
                "fields": "nextPageToken,files(id,name,size)",
                "pageSize": 1000,
            }
            if page_token:
                params["pageToken"] = page_token
            res = service.files().list(**params).execute()
            for f in res.get("files", []):
                index[f["name"]] = (f["id"], int(f.get("size", -1)))
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        except Exception as e:
            logger.warning("GDrive _list_folder_index %s: %s", parent_id, e)
            break
    return index


def _upload_file_smart(service, local_path, parent_id, existing_index, log_func=None):
    """Upload a single file using smart sync: skip if same size, update if changed, create if new."""
    from googleapiclient.http import MediaFileUpload
    local_path = Path(local_path)
    if not local_path.exists():
        return False
    name = local_path.name
    local_size = local_path.stat().st_size
    existing = existing_index.get(name)
    if existing and existing[1] == local_size:
        if log_func:
            log_func(f"  Skipped (unchanged): {name}")
        return True
    import time as _time
    for _attempt in range(4):
        try:
            media = MediaFileUpload(str(local_path), resumable=False)
            if existing:
                fid = existing[0]
                service.files().update(fileId=fid, media_body=media).execute()
                if log_func:
                    log_func(f"  Updated: {name}")
            else:
                meta = {"name": name, "parents": [parent_id]}
                service.files().create(body=meta, media_body=media, fields="id").execute()
                if log_func:
                    log_func(f"  Uploaded: {name}")
            return True
        except Exception as e:
            try:
                from googleapiclient.errors import HttpError
                if isinstance(e, HttpError) and e.resp.status == 429:
                    _time.sleep(2 ** _attempt)
                    continue
            except ImportError:
                pass
            if log_func:
                log_func(f"  [FAIL] {name}: {e}")
            return False
    if log_func:
        log_func(f"  [FAIL] {name}: rate-limited after retries")
    return False


def upload_file(service, local_path, parent_id, log_func=None):
    """Upload a single file (creates new; does not check for existing). Use _upload_file_smart for sync."""
    from googleapiclient.http import MediaFileUpload
    local_path = Path(local_path)
    if not local_path.exists():
        return None
    name = local_path.name
    try:
        media = MediaFileUpload(str(local_path), resumable=False)
        meta = {"name": name, "parents": [parent_id]}
        service.files().create(body=meta, media_body=media, fields="id").execute()
        if log_func:
            log_func(f"  Uploaded: {name}")
        return True
    except Exception as e:
        if log_func:
            log_func(f"  [FAIL] {name}: {e}")
        return False


def upload_folder(service, local_folder, parent_id, log_func=None, folder_cache=None, drive_folder_name=None):
    """Recursively upload a folder using smart sync (skip unchanged, update changed, create new)."""
    if folder_cache is None:
        folder_cache = {}
    local_folder = Path(local_folder)
    if not local_folder.exists():
        return False
    folder_name = drive_folder_name or local_folder.name
    cache_key = (folder_name, parent_id)
    folder_id = folder_cache.get(cache_key) or get_or_create_folder(service, folder_name, parent_id)
    if not folder_id:
        return False
    folder_cache[cache_key] = folder_id
    subfolder_index_cache = {folder_id: _list_folder_index(service, folder_id)}
    ok = True
    for item in sorted(local_folder.rglob("*")):
        if item.is_file():
            rel = item.relative_to(local_folder)
            parts = list(rel.parts)
            cur_parent = folder_id
            for part in parts[:-1]:
                sub_key = (part, cur_parent)
                sub_id = folder_cache.get(sub_key) or get_or_create_folder(service, part, cur_parent)
                if not sub_id:
                    ok = False
                    cur_parent = None
                    break
                folder_cache[sub_key] = sub_id
                if sub_id not in subfolder_index_cache:
                    subfolder_index_cache[sub_id] = _list_folder_index(service, sub_id)
                cur_parent = sub_id
            if cur_parent:
                cur_index = subfolder_index_cache.get(cur_parent, {})
                if not _upload_file_smart(service, item, cur_parent, cur_index, log_func):
                    ok = False
    return ok


def list_folder(service, parent_id):
    results = []
    page_token = None
    while True:
        try:
            params = {
                "q": f"'{parent_id}' in parents and trashed=false",
                "fields": "nextPageToken,files(id,name,mimeType,size)",
                "pageSize": 1000,
            }
            if page_token:
                params["pageToken"] = page_token
            res = service.files().list(**params).execute()
            results.extend(res.get("files", []))
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        except Exception as e:
            logger.warning("GDrive list_folder %s: %s", parent_id, e)
            break
    return results


def download_file(service, file_id, local_path, log_func=None):
    from googleapiclient.http import MediaIoBaseDownload
    local_path = Path(local_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        request = service.files().get_media(fileId=file_id)
        with open(local_path, "wb") as fh:
            dl = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = dl.next_chunk()
        if log_func:
            log_func(f"  Downloaded: {local_path.name}")
        return True
    except Exception as e:
        if log_func:
            log_func(f"  [FAIL] Download {local_path.name}: {e}")
        return False


def download_folder(service, folder_id, local_dest, log_func=None):
    local_dest = Path(local_dest)
    local_dest.mkdir(parents=True, exist_ok=True)
    items = list_folder(service, folder_id)
    ok = True
    for item in items:
        if item["mimeType"] == "application/vnd.google-apps.folder":
            sub_dest = local_dest / item["name"]
            if not download_folder(service, item["id"], sub_dest, log_func):
                ok = False
        else:
            if not download_file(service, item["id"], local_dest / item["name"], log_func):
                ok = False
    return ok


# Dossier racine à la racine « Mon Drive » (nom visible dans Google Drive).
BACKUP_ROOT_FOLDER_NAME = "SLIMEDEALS BACKUP"
_LEGACY_BACKUP_ROOT_NAMES = ("SteaMidra Backups",)


def _find_legacy_backup_root(service):
    """Retourne (nom_affiché, id) du premier dossier legacy trouvé, sinon (None, None)."""
    for legacy in _LEGACY_BACKUP_ROOT_NAMES:
        fid = find_folder(service, legacy, "root")
        if fid:
            return legacy, fid
    return None, None


def _backup_root_folder_id_for_read(service):
    """ID du dossier racine des sauvegardes (nouveau nom ou ancien), sans créer ni renommer."""
    fid = find_folder(service, BACKUP_ROOT_FOLDER_NAME, "root")
    if fid:
        return fid
    _name, old_id = _find_legacy_backup_root(service)
    return old_id


def get_backup_root(service):
    """Crée ou renvoie le dossier racine « SLIMEDEALS BACKUP » ; renomme l’ancien « SteaMidra Backups » si présent."""
    fid = find_folder(service, BACKUP_ROOT_FOLDER_NAME, "root")
    if fid:
        return fid
    legacy_name, old_id = _find_legacy_backup_root(service)
    if old_id:
        try:
            service.files().update(
                fileId=old_id, body={"name": BACKUP_ROOT_FOLDER_NAME}, fields="id"
            ).execute()
            logger.info(
                "Google Drive: dossier renomme de %r vers %r", legacy_name, BACKUP_ROOT_FOLDER_NAME
            )
        except Exception as e:
            logger.warning(
                "GDrive: impossible de renommer %r (%s) - utilisation du dossier existant.",
                legacy_name,
                e,
            )
        return old_id
    return get_or_create_folder(service, BACKUP_ROOT_FOLDER_NAME, "root")


def list_backup_locations(service):
    root_id = _backup_root_folder_id_for_read(service)
    if not root_id:
        return {}
    result = {}
    for loc_item in list_folder(service, root_id):
        if loc_item["mimeType"] != "application/vnd.google-apps.folder":
            continue
        loc_name = loc_item["name"]
        games = []
        for game_item in list_folder(service, loc_item["id"]):
            if game_item["mimeType"] != "application/vnd.google-apps.folder":
                continue
            meta = _fetch_meta_from_folder(service, game_item["id"])
            games.append({
                "folder_id": game_item["id"],
                "folder_name": game_item["name"],
                "app_id": meta.get("app_id"),
                "game_name": meta.get("game_name", game_item["name"]),
                "source_path": meta.get("source_path", ""),
                "backed_up_at": meta.get("backed_up_at", ""),
            })
        result[loc_name] = {"folder_id": loc_item["id"], "games": games}
    return result


def _fetch_meta_from_folder(service, folder_id):
    items = list_folder(service, folder_id)
    for meta_name in ("SlimeDeals_meta.json", "slimedeals_meta.json", "steamidra_meta.json"):
        for item in items:
            if item["name"] == meta_name:
                try:
                    content = service.files().get_media(fileId=item["id"]).execute()
                    return json.loads(content)
                except Exception:
                    pass
    return {}
