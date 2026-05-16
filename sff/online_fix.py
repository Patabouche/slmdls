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
Téléchargement et application de correctifs multijoueur (sources distantes).
Smart Matching Hybrid Model: selenium login + container-aware link discovery + recursive frame-piercing.
Includes a strict 50% match threshold to avoid false positives (like "thank you" links).
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from difflib import SequenceMatcher
from io import StringIO
from pathlib import Path
from urllib.parse import quote, unquote, urljoin

import httpx
from colorama import Fore, Style
from tqdm import tqdm

from sff.prompts import prompt_confirm, prompt_secret, prompt_text
from sff.storage.settings import Settings, get_setting, set_setting
from sff.utils import root_folder

# Import statique pour PyInstaller (voir _embedded_online_fix_credentials).
try:
    import sff.online_fix_embed  # noqa: F401
except ImportError:
    pass

logger = logging.getLogger(__name__)


def _stdio_for_progress():
    """Streams utilisés par tqdm : sous GUI / PyInstaller, stderr/stdout peuvent être None."""
    s_err = getattr(sys, "stderr", None)
    if s_err is not None and hasattr(s_err, "write"):
        return s_err
    s_out = getattr(sys, "stdout", None)
    if s_out is not None and hasattr(s_out, "write"):
        return s_out
    return StringIO()


def _stdin_is_interactive() -> bool:
    """True seulement si une vraie console permet la saisie (pas None comme sous Qt)."""
    stdin = getattr(sys, "stdin", None)
    if stdin is None:
        return False
    try:
        return stdin.isatty()
    except (AttributeError, OSError):
        return False


def _safe_log_fragment(s: str) -> str:
    """Evite UnicodeEncodeError sur consoles Windows (cp1252) pour les logs."""
    if not s:
        return ""
    try:
        enc = getattr(getattr(sys, "stderr", None), "encoding", None) or "utf-8"
    except Exception:
        enc = "utf-8"
    try:
        return str(s).encode(enc, errors="replace").decode(enc, errors="replace")
    except Exception:
        return str(s).encode("ascii", errors="replace").decode("ascii")


def _title_match_score(game_name: str, anchor_text: str) -> float:
    """Score 0–1 entre le nom du jeu et le texte du lien (réduit faux positifs type RoadCraft vs Raft)."""
    g = (game_name or "").strip().lower()
    t = (anchor_text or "").strip().lower()
    if not g or not t:
        return 0.0
    base = SequenceMatcher(None, g, t).ratio()
    tokens = re.split(r"[^\w\u0400-\u04FF]+", t)
    tokens = [x for x in tokens if x]
    if g in tokens:
        return max(base, 0.93)
    if t == g or t.startswith(g + " ") or t.startswith(g + "("):
        return max(base, 0.91)
    if len(g) >= 6 and g in t:
        return max(base, 0.78)
    return base


MSG_NO_ONLINE_FIX = "Nous n'avons pas trouvé de correctif multijoueur pour ce jeu."

# Fallback interne : AppID Steam -> URL d'article (si la recherche ne remonte pas le jeu).
ONLINE_FIX_DIRECT_PAGE_BY_STEAM_APPID: dict[str, str] = {
    "648800": "https://online-fix.me/games/survival/16179-raft-po-seti.html",
}


def _direct_online_fix_page_url(app_id, game_name: str) -> str | None:
    """URL d'article à ouvrir directement si la recherche échoue (ex. Raft)."""
    aid = str(app_id).strip() if app_id is not None else ""
    if aid in ONLINE_FIX_DIRECT_PAGE_BY_STEAM_APPID:
        return ONLINE_FIX_DIRECT_PAGE_BY_STEAM_APPID[aid]
    if (game_name or "").strip().lower() == "raft":
        return ONLINE_FIX_DIRECT_PAGE_BY_STEAM_APPID.get("648800")
    return None

CREDENTIALS_FILE = "credentials.json"
ONLINE_FIX_BASE_URL = "https://online-fix.me"

def _get_credentials_path(): return root_folder() / CREDENTIALS_FILE


def _embedded_online_fix_credentials():
    """Identifiants fournis avec la build (online_fix_embed*.py)."""
    for mod_name in ("sff.online_fix_embed_local", "sff.online_fix_embed"):
        try:
            mod = __import__(mod_name, fromlist=["USER"])
        except ImportError:
            continue
        u = (getattr(mod, "USER", "") or "").strip()
        p = (getattr(mod, "PASSWORD", "") or "").strip()
        if u and p:
            return u, p
    return None, None


def online_fix_has_embedded_credentials() -> bool:
    u, p = _embedded_online_fix_credentials()
    return bool(u and p)


def _read_credentials():
    username = get_setting(Settings.ONLINE_FIX_USER)
    password = get_setting(Settings.ONLINE_FIX_PASS)
    if username and password:
        return username, password
    cred_path = _get_credentials_path()
    if cred_path.exists():
        try:
            with open(cred_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                u, p = data.get("username"), data.get("password")
                if u and p:
                    return u, p
        except Exception:
            pass
    eu, ep = _embedded_online_fix_credentials()
    if eu and ep:
        try:
            _save_credentials(eu, ep)
        except Exception:
            pass
        return eu, ep
    return None, None

def _save_credentials(username, password):
    try:
        set_setting(Settings.ONLINE_FIX_USER, username); set_setting(Settings.ONLINE_FIX_PASS, password)
        return True
    except Exception: return False

def _detect_archiver():
    import shutil as sh
    for p in [sh.which("winrar"), r"C:\Program Files\WinRAR\winrar.exe", r"C:\Program Files (x86)\WinRAR\winrar.exe"]:
        if p and os.path.exists(p): return ("winrar", p)
    for p in [sh.which("7z"), r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"]:
        if p and os.path.exists(p): return ("7z", p)
    return (None, None)

def _download_with_session(url, cookies_list, user_agent, save_path):
    """Stream download via HTTPX using browser-grade headers."""
    cookies = {c['name']: c['value'] for c in cookies_list}
    headers = {"User-Agent": user_agent, "Referer": "https://uploads.online-fix.me/"}
    for _attempt in range(3):
        try:
            with httpx.stream("GET", url, cookies=cookies, headers=headers, follow_redirects=True, timeout=None) as response:
                if response.status_code in (403, 404):
                    if _attempt < 2:
                        print(f"{Fore.YELLOW}[!] Server returned {response.status_code}, retrying ({_attempt + 1}/3)...{Style.RESET_ALL}")
                        time.sleep(3)
                        continue
                    print(f"{Fore.RED}[X] Connection rejected by file server: {response.status_code}{Style.RESET_ALL}")
                    return False
                if response.status_code != 200:
                    print(f"{Fore.RED}[X] Connection rejected by file server: {response.status_code}{Style.RESET_ALL}")
                    return False
                try: total = int(response.headers.get("Content-Length", "0"))
                except (ValueError, TypeError): total = 0
                with save_path.open("wb") as f, tqdm(
                    desc="Downloading Fix",
                    total=total or None,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    miniters=1,
                    colour="green",
                    file=_stdio_for_progress(),
                ) as pbar:
                    for chunk in response.iter_bytes(chunk_size=1024*1024):
                        f.write(chunk); pbar.update(len(chunk))
            return True
        except Exception as e:
            print(f"{Fore.RED}[X] Download stream interrupted: {e}{Style.RESET_ALL}"); return False
    return False

def _run_extraction_with_timeout(cmd, timeout=300):
    try:
        startupinfo = subprocess.STARTUPINFO(); startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return (process.returncode == 0, stdout, stderr, None)
        except subprocess.TimeoutExpired: process.kill(); return (False, None, None, "Timeout")
    except Exception as e: return (False, None, None, str(e))

def _extract_archive_with_backup(archive, target, atype, apath, game_name, pwd="online-fix.me"):
    backed_up = []
    try:
        temp_dir = tempfile.mkdtemp(prefix='sff_ext_final_')
        cmd = [apath, "x", f"-p{pwd}", "-y", archive, temp_dir + os.sep] if atype == "winrar" else [apath, "x", f"-p{pwd}", "-y", f"-o{temp_dir}", archive]
        success, _, _, _ = _run_extraction_with_timeout(cmd)
        if not success: return False
        extracted = {}
        for root, _, files in os.walk(temp_dir):
            for f in files:
                ft = os.path.join(root, f); rel = os.path.relpath(ft, temp_dir)
                extracted[rel] = ft
        for rel in extracted:
            gp = os.path.join(target, rel)
            if os.path.isfile(gp):
                bk = gp + ".bak"
                try: 
                    if os.path.exists(bk): os.remove(bk)
                    os.rename(gp, bk); backed_up.append((gp, bk))
                except Exception: pass
        for rel, src in extracted.items():
            dest = os.path.join(target, rel); os.makedirs(os.path.dirname(dest), exist_ok=True); shutil.move(src, dest)
        print(f"{Fore.GREEN}[OK] Fix applied successfully!{Style.RESET_ALL}"); return True
    except Exception as e:
        print(f"{Fore.RED}[X] Installation error: {e}. Recovering...{Style.RESET_ALL}")
        for o, b in backed_up: 
            try: 
                if os.path.exists(o): os.remove(o)
                os.rename(b, o)
            except Exception: pass
        return False
    finally: shutil.rmtree(temp_dir, ignore_errors=True)

def _find_archives_recursive(driver):
    """Pierce through all frames recursively to find .rar/.zip file links."""
    from selenium.webdriver.common.by import By
    results = []
    exts = [".rar", ".zip", ".7z"]

    def scan_current_frame():
        try:
            links = driver.find_elements(By.TAG_NAME, "a")
            for lnk in links:
                try:
                    href = lnk.get_attribute("href") or ""
                    text = (lnk.text or "").strip().lower()
                    full = urljoin(driver.current_url, href)
                    if any(full.lower().endswith(ext) for ext in exts):
                        score = 0
                        if "fix" in full.lower() or "fix" in text: score += 10
                        if "repair" in full.lower() or "repair" in text: score += 10
                        if "generic" in full.lower() or "generic" in text: score += 5
                        results.append((score, full))
                except Exception: pass
        except Exception: pass

    scan_current_frame()
    try:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for i in range(len(frames)):
            try:
                driver.switch_to.frame(i); results.extend(_find_archives_recursive(driver)); driver.switch_to.default_content()
            except Exception:
                try: driver.switch_to.default_content()
                except Exception: pass
    except Exception: pass
    return results

def _run_multiplayer_fix_process(game_name, game_folder, username, password, atype, apath, app_id=None):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = None
    THRESHOLD = 0.5

    def _best_anchor_match():
        try:
            wait.until(EC.presence_of_element_located((By.ID, "dle-content")))
        except Exception:
            pass
        g = (game_name or "").strip().lower()
        anchors = driver.find_elements(By.CSS_SELECTOR, "div#dle-content a")
        if not anchors:
            anchors = driver.find_elements(By.TAG_NAME, "a")
        best_a = None
        best_ratio = 0.0
        for a in anchors:
            try:
                txt = (a.text or "").strip()
                href = a.get_attribute("href") or ""
                if "/page/" in href or "/user/" in href or not txt:
                    continue
                r = _title_match_score(g, txt)
                if r > best_ratio:
                    best_ratio = r
                    best_a = a
            except Exception:
                pass
        return best_a, best_ratio

    try:
        print()
        print(Fore.CYAN + "============================================================" + Style.RESET_ALL)
        print(Fore.CYAN + "  SMART MATCHING ENGINE (NO FALSE POSITIVES)" + Style.RESET_ALL)
        print(Fore.CYAN + "============================================================" + Style.RESET_ALL)
        opts = Options()
        opts.add_argument("--window-size=1280,800"); opts.add_argument("--headless=new")
        opts.add_argument("--log-level=3"); opts.add_argument("--no-sandbox"); opts.add_argument("--disable-gpu")
        driver = webdriver.Chrome(options=opts); wait = WebDriverWait(driver, 15)
        print(Fore.GREEN + "[OK] Secure engine ready" + Style.RESET_ALL)
        q = quote(re.sub(r"[^\w\s]", "", game_name))
        driver.get(f"{ONLINE_FIX_BASE_URL}/index.php?do=search&subaction=search&story={q}")
        best, best_r = _best_anchor_match()

        aid = str(app_id).strip() if app_id is not None else ""
        if aid.isdigit() and int(aid) > 0 and (not best or best_r < THRESHOLD):
            logger.debug("mpfix: second pass search by Steam app id %s", aid)
            driver.get(f"{ONLINE_FIX_BASE_URL}/index.php?do=search&subaction=search&story={quote(aid)}")
            time.sleep(1.2)
            b2, r2 = _best_anchor_match()
            if b2 and r2 > best_r:
                best, best_r = b2, r2

        direct_url = _direct_online_fix_page_url(app_id, game_name)
        used_direct_article = False
        if not best or best_r < THRESHOLD:
            if direct_url:
                logger.info("multiplayer fix: opening fallback curated article (search miss)")
                driver.get(direct_url)
                time.sleep(1.8)
                try:
                    wait.until(EC.presence_of_element_located((By.ID, "dle-content")))
                except Exception:
                    pass
                used_direct_article = True
            else:
                reason = (
                    f"No legitimate results found. Best was '{best.text.strip()}' ({best_r*100:.0f}%)"
                    if best
                    else "No results found"
                )
                logger.debug("mpfix search: %s", _safe_log_fragment(reason))
                print(Fore.RED + MSG_NO_ONLINE_FIX + Style.RESET_ALL)
                return False

        if used_direct_article:
            print(
                Fore.GREEN
                + "[OK] Article cible (correspondance directe — "
                + _safe_log_fragment(game_name or "jeu")
                + ")"
                + Style.RESET_ALL
            )
            time.sleep(1)
        else:
            print(
                Fore.GREEN
                + f"[OK] Target verified: {_safe_log_fragment(best.text.strip())} ({best_r*100:.0f}%)"
                + Style.RESET_ALL
            )
            driver.execute_script("arguments[0].click();", best)
            time.sleep(2)
        # Authentication
        if driver.find_elements(By.NAME, "login_name"):
            print(Fore.CYAN + "Authenticating session..." + Style.RESET_ALL)
            driver.find_element(By.NAME, "login_name").send_keys(username)
            driver.find_element(By.NAME, "login_password").send_keys(password)
            driver.find_element(By.NAME, "login_password").send_keys(Keys.ENTER)
            time.sleep(5)
        print(Fore.CYAN + "establishing link to file server..." + Style.RESET_ALL)
        xpath = "//a[contains(text(),'Скачать фикс с сервера')] | //button[contains(text(),'Скачать фикс с сервера')]"
        btn = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
        btn_href = btn.get_attribute("href") or ""
        archives = []; _dl_cookies = None
        _ua = driver.execute_script("return navigator.userAgent")
        # Optimisation: try pure-httpx path first — follow loot.raxwars.com redirect via httpx.Client
        # (headless Chrome handles it too, but if httpx already has the listing we skip the window step)
        if btn_href:
            try:
                _chrome_cks = {c['name']: c['value'] for c in driver.get_cookies()}
                with httpx.Client(follow_redirects=True, timeout=15) as _client:
                    _r = _client.get(btn_href, cookies=_chrome_cks,
                                     headers={"User-Agent": _ua, "Referer": "https://online-fix.me/"})
                    _final = str(_r.url)
                    logger.debug("Redirect chain final URL [%d]: %s", _r.status_code, _final)
                    if "uploads.online-fix.me" in _final.lower() and _r.status_code == 200:
                        _all_cks = {k: str(v) for k, v in _client.cookies.items()}
                        _dl_cookies = [{'name': k, 'value': v} for k, v in _all_cks.items()]
                        _found = []

                        def _score_archive(url):
                            s = 0
                            u = unquote(url).lower()
                            if "fix" in u: s += 10
                            if "repair" in u: s += 10
                            if "generic" in u: s += 5
                            return s

                        def _parse_listing(html, base):
                            for _pm in re.finditer(r'href="([^"]+\.(?:rar|zip|7z))"', html, re.IGNORECASE):
                                _ph = urljoin(base, _pm.group(1))
                                _found.append((_score_archive(_ph), _ph))

                        # Scan root listing
                        _parse_listing(_r.text, _final)
                        # Also scan any subdirectory whose name contains "fix" or "repair"
                        _subdirs = [s for s in re.findall(r'href="([^"]+/)"', _r.text)
                                    if not s.startswith('../') and s not in ('/', './')]
                        for _sd in _subdirs:
                            if "fix" in unquote(_sd).lower() or "repair" in unquote(_sd).lower():
                                _sd_url = urljoin(_final, _sd)
                                try:
                                    _r2 = _client.get(_sd_url, headers={"User-Agent": _ua, "Referer": _final})
                                    if _r2.status_code == 200:
                                        _parse_listing(_r2.text, _sd_url)
                                except Exception as _e2:
                                    logger.debug("Subdir scan %s: %s", _sd, _e2)
                        if _found:
                            archives = _found
                            print(Fore.GREEN + "[OK] Archives found via httpx redirect follow (ad bypassed)" + Style.RESET_ALL)
            except Exception as _e:
                logger.debug("httpx bypass attempt: %s", _e)
        if not archives:
            # Browser path: headless Chrome follows loot.raxwars.com redirect natively
            driver.execute_script("arguments[0].click();", btn)
            try: wait.until(lambda d: len(d.window_handles) > 1)
            except Exception: pass
            for h in driver.window_handles:
                driver.switch_to.window(h)
                if "uploads.online-fix.me" in driver.current_url.lower(): break
            logger.debug("File server URL: %s", driver.current_url)
            print(Fore.YELLOW + "[!] Waiting for Cloudflare/server resolution (up to 30s)..." + Style.RESET_ALL)
            start_wait = time.time()
            while (time.time() - start_wait) < 30:
                # Check for 401 Unauthorized or login screen on server
                src = driver.page_source or ""
                if "401 Authorization Required" in src or "Log in to go to the folder" in src:
                     print(Fore.RED + "[X] Access denied by file server (Session Sync Failed)." + Style.RESET_ALL)
                     return False
                # Refresh on transient 403/404 from the server
                if "403 Forbidden" in src or "404 Not Found" in src:
                    driver.refresh(); time.sleep(2); continue
                archives = _find_archives_recursive(driver)
                if archives: break
                # Navigate to folder if found
                try:
                    folders = driver.find_elements(By.PARTIAL_LINK_TEXT, "Fix Repair")
                    if folders: driver.execute_script("arguments[0].click();", folders[0]); time.sleep(3)
                except Exception: pass
                time.sleep(2)
        if not archives:
            logger.debug("mpfix: no archive files on file server listing")
            print(Fore.RED + MSG_NO_ONLINE_FIX + Style.RESET_ALL)
            return False
        archives.sort(key=lambda x: x[0], reverse=True); target_url = archives[0][1]
        print()
        print(Fore.CYAN + "=" * 60 + Style.RESET_ALL)
        print(Fore.CYAN + f"  SECURE DOWNLOAD: {unquote(target_url.split('/')[-1])}" + Style.RESET_ALL)
        print(Fore.CYAN + "=" * 60 + Style.RESET_ALL)
        temp_file = Path(tempfile.gettempdir()) / f"final_{tempfile.mktemp()[-8:]}.rar"
        _download_cks = _dl_cookies if _dl_cookies else driver.get_cookies()
        if _download_with_session(target_url, _download_cks, _ua, temp_file):
            success = _extract_archive_with_backup(str(temp_file), str(game_folder), atype, apath, game_name)
            if temp_file.exists(): temp_file.unlink()
            return success
        return False
    except Exception as e:
        print(Fore.RED + f"[X] Search/Navigation failed: {e}{Style.RESET_ALL}"); return False
    finally:
        if driver: driver.quit()

def apply_multiplayer_fix(game_name, game_folder, app_id=None):
    username, password = _read_credentials()
    if not username or not password:
        if _stdin_is_interactive():
            username = prompt_text("\nMultiplayer fix username:")
            password = prompt_secret("Password:")
            if not username or not password:
                return False
            _save_credentials(username, password)
        else:
            print(
                Fore.RED
                + "[X] Compte multijoueur indisponible : aucun identifiant intégré ni enregistré."
                + Style.RESET_ALL
            )
            return False
    atype, apath = _detect_archiver()
    if not atype:
        print(Fore.RED + "[X] No archive tool found. Install 7-Zip or WinRAR to apply the fix." + Style.RESET_ALL)
        return False
    # Pre-flight: verify site is reachable before launching ChromeDriver
    print(Fore.CYAN + "Checking network connectivity..." + Style.RESET_ALL)
    try:
        httpx.get(ONLINE_FIX_BASE_URL, timeout=10, follow_redirects=True)
    except Exception as _conn_err:
        print(
            Fore.RED
            + "[X] Connexion impossible au service multijoueur. Verifie ta connexion internet, "
            "desactive le VPN si besoin, et reessaie."
            + Style.RESET_ALL
        )
        logger.debug("multiplayer fix pre-flight failed: %s", _safe_log_fragment(str(_conn_err)))
        return False
    return _run_multiplayer_fix_process(game_name, game_folder, username, password, atype, apath, app_id)
