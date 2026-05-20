# SlimeDeals — téléchargement BuzzHeavier (page HTML + jeton ?t= + CDN)

from __future__ import annotations

import html as html_module
import logging
import re
import ssl
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

import httpx

log = logging.getLogger("sff")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

ProgressCb = Callable[[int, int, str], None]
UiLogCb = Callable[[str], None]

_RE_HX_DOWNLOAD = re.compile(
    r'hx-get="(/[^"]+/download\?t=[^"]+)"',
    re.IGNORECASE,
)
_RE_SIZE_LABEL = re.compile(
    r"Size\s*-\s*([0-9.]+\s*(?:GB|MB|KB|Go|Mo|Ko))",
    re.IGNORECASE,
)
_RE_BUZZ_SIZE = re.compile(
    r"Details:\s*(?:</[^>]+>\s*)?Size\s*-\s*([0-9.]+)\s*(GB|MB|KB|Go|Mo|Ko)",
    re.IGNORECASE,
)
_RE_BUZZ_SIZE_FALLBACK = re.compile(
    r"Size\s*-\s*([0-9.]+)\s*(GB|MB|KB|Go|Mo|Ko)",
    re.IGNORECASE,
)
_RE_CF_CHALLENGE = re.compile(
    r"<title>\s*just a moment\s*\.\.\.\s*</title>|cf-browser-verification",
    re.IGNORECASE,
)

# En dessous : probable page d’erreur HTML, pas une archive jeu
_MIN_ARCHIVE_BYTES = 2 * 1024 * 1024


def _ui(ui_log: UiLogCb | None, msg: str) -> None:
    if not ui_log:
        return
    try:
        ui_log(msg)
    except Exception:
        pass
    log.info("[fixed-dl] %s", msg)


def _url_for_log(url: str) -> str:
    try:
        p = urlparse(url.strip())
        q = "?…" if p.query else ""
        return f"{p.scheme}://{p.netloc}{p.path}{q}"
    except Exception:
        return "<url>"


def _cdn_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass
    return ctx


def _is_retriable_transfer_error(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            httpx.RemoteProtocolError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.ConnectError,
            httpx.TimeoutException,
        ),
    ):
        return True
    msg = str(exc).lower()
    return (
        "complete message body" in msg
        or "connection reset" in msg
        or "broken pipe" in msg
        or "timed out" in msg
    )


def _parse_content_range_total(value: str | None) -> int | None:
    if not value:
        return None
    m = re.search(r"/(\d+)\s*$", value.strip())
    if m:
        return int(m.group(1))
    return None


def _is_ssl_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "ssl" in msg or "certificate" in msg:
        return True
    cause = getattr(exc, "__cause__", None)
    return bool(cause and _is_ssl_error(cause))


def _is_third_party_cdn(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return bool(host) and "buzzheavier" not in host


def _verify_for_url(url: str) -> bool | ssl.SSLContext:
    if _is_third_party_cdn(url):
        return False
    return _cdn_ssl_context()


_PAGE_TIMEOUT = httpx.Timeout(60.0, connect=30.0)
_CDN_TIMEOUT = httpx.Timeout(connect=90.0, read=600.0, write=90.0, pool=90.0)
_MAX_RESUME_ATTEMPTS = 12


def _is_buzzheavier_host(host: str) -> bool:
    h = (host or "").lower()
    return "buzzheavier" in h or h.endswith("bzzhr.to") or h == "bzzhr.to"


def parse_buzzheavier_url(url: str) -> str | None:
    """Extrait l'identifiant fichier depuis buzzheavier.com ou bzzhr.to."""
    if not url:
        return None
    parsed = urlparse(url.strip())
    if not _is_buzzheavier_host(parsed.netloc or ""):
        return None
    parts = [p for p in (parsed.path or "").strip("/").split("/") if p]
    if not parts:
        return None
    if parts[0] in ("download", "preview", "api"):
        return None
    return parts[0]


def resolve_buzzheavier_page_url(catalog_url: str, file_id: str) -> str:
    """URL de page à charger (lien court ou buzzheavier.com)."""
    raw = (catalog_url or "").strip()
    if raw and _is_buzzheavier_host(urlparse(raw).netloc or ""):
        return raw
    return f"https://buzzheavier.com/{file_id}"


def _buzz_page_candidates(catalog_url: str, file_id: str) -> list[str]:
    page_url = (catalog_url or "").strip()
    if not _is_buzzheavier_host(urlparse(page_url).netloc or ""):
        page_url = f"https://buzzheavier.com/{file_id}"
    seen: set[str] = set()
    out: list[str] = []
    for u in (
        page_url,
        f"https://buzzheavier.com/{file_id}",
        f"https://bzzhr.to/{file_id}",
    ):
        u = u.strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _buzz_html_looks_valid(html: str) -> bool:
    if not html or _RE_CF_CHALLENGE.search(html):
        return False
    if re.search(r"\.(?:rar|zip|7z)\b", html, re.IGNORECASE):
        return True
    if _RE_BUZZ_SIZE.search(html) or _RE_BUZZ_SIZE_FALLBACK.search(html):
        return True
    plain = re.sub(r"<[^>]+>", " ", html or "")
    plain = html_module.unescape(re.sub(r"\s+", " ", plain))
    if re.search(r"\.(?:rar|zip|7z)\b", plain, re.IGNORECASE):
        return True
    return bool(_RE_BUZZ_SIZE_FALLBACK.search(plain))


def _httpx_browser_headers() -> dict[str, str]:
    return {
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,fr-FR;q=0.8,fr;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }


def _cookies_to_dict(jar) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for c in jar:
            if getattr(c, "name", None) and getattr(c, "value", None):
                out[str(c.name)] = str(c.value)
    except TypeError:
        try:
            for name, value in jar.items():
                out[str(name)] = str(value)
        except Exception:
            pass
    return out


def _fetch_buzz_page_html(
    catalog_url: str,
    file_id: str,
    ui_log: UiLogCb | None = None,
    cf_session=None,
) -> tuple[str | None, str, int, dict[str, str], object | None]:
    """
    Charge la page BuzzHeavier — curl_cffi (Chrome) d'abord, sinon httpx.
    Retourne (html, url_effective, status, cookies, cf_session).
    """
    last_html = ""
    last_url = resolve_buzzheavier_page_url(catalog_url, file_id)
    last_status = 0
    last_cookies: dict[str, str] = {}
    active_cf = cf_session

    try:
        from curl_cffi import requests as curl_requests

        if active_cf is None:
            active_cf = curl_requests.Session()
        for candidate in _buzz_page_candidates(catalog_url, file_id):
            for impersonate in ("chrome124", "chrome120", "chrome110", "safari17_0"):
                try:
                    resp = active_cf.get(
                        candidate,
                        impersonate=impersonate,
                        timeout=45,
                        allow_redirects=True,
                    )
                except Exception as e:
                    _ui(ui_log, f"curl_cffi {impersonate} : {e}")
                    continue
                last_html = resp.text or ""
                last_url = str(resp.url or candidate)
                last_status = int(resp.status_code or 0)
                last_cookies = _cookies_to_dict(getattr(resp, "cookies", {}))
                _ui(
                    ui_log,
                    f"curl_cffi OK impersonate={impersonate} HTTP {last_status} "
                    f"→ {_url_for_log(last_url)}",
                )
                if last_status == 200 and _buzz_html_looks_valid(last_html):
                    return last_html, last_url, last_status, last_cookies, active_cf
    except ImportError:
        _ui(ui_log, "curl_cffi absent — pip install curl_cffi pour BuzzHeavier")
        active_cf = None
    except Exception as e:
        _ui(ui_log, f"curl_cffi indisponible : {e}")
        active_cf = None

    headers = _httpx_browser_headers()
    for candidate in _buzz_page_candidates(catalog_url, file_id):
        try:
            with httpx.Client(timeout=_PAGE_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(candidate, headers=headers)
                last_html = resp.text or ""
                last_url = str(resp.url or candidate)
                last_status = int(resp.status_code or 0)
                last_cookies = dict(resp.cookies)
                if last_status == 200 and _buzz_html_looks_valid(last_html):
                    return last_html, last_url, last_status, last_cookies, None
        except Exception as e:
            _ui(ui_log, f"httpx page {candidate!r} : {e}")

    html_out = last_html if _buzz_html_looks_valid(last_html) else None
    return html_out, last_url, last_status, last_cookies, active_cf if html_out else None


def _htmx_headers(page_url: str) -> dict[str, str]:
    return {
        "User-Agent": _UA,
        "Accept": "*/*",
        "HX-Request": "true",
        "HX-Current-URL": page_url,
        "Referer": page_url,
        "Accept-Language": "en-US,en;q=0.9",
    }


def _parse_download_paths_from_html(html: str, file_id: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for m in _RE_HX_DOWNLOAD.finditer(html or ""):
        raw = html_module.unescape(m.group(1))
        if raw not in seen:
            seen.add(raw)
            paths.append(raw)
    if not paths:
        paths.append(f"/{file_id}/download")
    alt_paths: list[str] = []
    for p in paths:
        if "alt=true" in p.lower():
            continue
        sep = "&" if "?" in p else "?"
        alt = f"{p}{sep}alt=true"
        if alt not in seen:
            alt_paths.append(alt)
    return paths + alt_paths


def _resolve_cdn_url(
    page_url: str,
    trigger_path: str,
    client: httpx.Client,
    ui_log: UiLogCb | None = None,
    cf_session=None,
) -> str | None:
    trigger_url = urljoin(page_url, trigger_path.lstrip("/"))
    if not trigger_path.startswith("/"):
        trigger_url = urljoin(page_url + "/", trigger_path)

    _ui(ui_log, f"Requête lien signé : {_url_for_log(trigger_url)}")

    if cf_session is not None:
        try:
            resp = cf_session.get(
                trigger_url,
                headers=_htmx_headers(page_url),
                allow_redirects=False,
                impersonate="chrome124",
                timeout=45,
            )
            _ui(
                ui_log,
                f"Réponse curl_cffi HTTP {resp.status_code} — hx-redirect : "
                f"{bool(resp.headers.get('hx-redirect') or resp.headers.get('Hx-Redirect'))}",
            )
            cdn = resp.headers.get("hx-redirect") or resp.headers.get("Hx-Redirect")
            if cdn:
                cdn = cdn.strip()
                if cdn.rstrip("/") != page_url.rstrip("/"):
                    _ui(ui_log, f"CDN obtenu : {_url_for_log(cdn)}")
                    return cdn
            body_snip = (getattr(resp, "text", None) or "")[:200].replace("\n", " ")
            _ui(ui_log, f"Pas de Hx-Redirect curl_cffi (extrait : {body_snip!r}…)")
        except Exception as e:
            _ui(ui_log, f"Résolution CDN curl_cffi : {e}")

    resp = client.get(
        trigger_url,
        headers=_htmx_headers(page_url),
        follow_redirects=False,
    )
    _ui(
        ui_log,
        f"Réponse HTTP {resp.status_code} — hx-redirect : "
        f"{bool(resp.headers.get('hx-redirect') or resp.headers.get('Hx-Redirect'))}",
    )
    cdn = resp.headers.get("hx-redirect") or resp.headers.get("Hx-Redirect")
    if not cdn:
        body_snip = (resp.text or "")[:200].replace("\n", " ")
        _ui(ui_log, f"Pas de Hx-Redirect (extrait : {body_snip!r}…)")
        return None
    cdn = cdn.strip()
    if cdn.rstrip("/") == page_url.rstrip("/"):
        _ui(ui_log, "Hx-Redirect = page d’origine (jeton expiré ?)")
        return None
    _ui(ui_log, f"CDN obtenu : {_url_for_log(cdn)}")
    return cdn


def _looks_like_html(data: bytes) -> bool:
    if not data:
        return False
    s = data.lstrip()[:800].lower()
    return s.startswith(b"<!doctype") or s.startswith(b"<html") or b"<head" in s[:400]


def _archive_magic_ok(data: bytes) -> bool:
    if len(data) < 4:
        return False
    return data.startswith(b"Rar!") or data.startswith(b"PK\x03\x04") or data.startswith(b"PK\x05\x06")


def validate_downloaded_archive(path: Path, expected_bytes: int = 0) -> tuple[bool, str]:
    """Vérifie qu’on a bien une archive et pas une page d’erreur HTML."""
    if not path.is_file():
        return False, "Fichier absent après téléchargement."
    size = path.stat().st_size
    with path.open("rb") as f:
        head = f.read(512)
    if _looks_like_html(head):
        snippet = head[:120].decode("utf-8", errors="replace")
        log.warning("HTML reçu au lieu d’archive : %s", snippet)
        return False, (
            "Le serveur a renvoyé une page web au lieu du fichier du jeu "
            "(lien expiré ou miroir indisponible). Réessaie dans quelques minutes."
        )
    if size < _MIN_ARCHIVE_BYTES:
        return False, (
            f"Fichier trop petit ({size:,} octets) — le téléchargement n’a pas reçu l’archive complète."
        )
    if expected_bytes > 0 and size < int(expected_bytes * 0.02):
        return False, (
            f"Fichier trop petit ({size // (1024 * 1024)} Mo) pour une archive attendue "
            f"d’environ {expected_bytes // (1024 * 1024)} Mo."
        )
    if not _archive_magic_ok(head):
        return False, "Le fichier reçu n’est pas une archive .rar / .zip valide."
    return True, ""


def _partial_dest_path(temp_dir: Path, file_id: str) -> Path:
    temp_dir.mkdir(parents=True, exist_ok=True)
    # 1. Cherche d'abord par file_id (nom attendu par défaut)
    for p in sorted(temp_dir.glob(f"{file_id}.*")):
        if p.is_file():
            return p
    # 2. Cherche n'importe quelle archive dans le dossier
    #    (le nom réel peut venir du Content-Disposition du serveur)
    _ARCHIVE_EXTS = {".rar", ".zip", ".7z", ".tar", ".gz", ".xz"}
    candidates = [
        p for p in temp_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _ARCHIVE_EXTS
    ]
    if candidates:
        # Prend le fichier le plus gros (le plus avancé dans le téléchargement)
        return max(candidates, key=lambda p: p.stat().st_size)
    return temp_dir / f"{file_id}.rar"


def _emit_dl_progress(
    on_progress: ProgressCb | None,
    ui_log: UiLogCb | None,
    downloaded: int,
    total: int,
    est: int,
    last_pct: list[int],
    last_log_mb: list[int],
) -> None:
    if not on_progress:
        return
    if total > 0:
        pct = int(downloaded * 100 / total)
        if pct != last_pct[0]:
            last_pct[0] = pct
            from sff.fixed_games import format_progress_bytes

            on_progress(
                downloaded,
                total,
                f"Téléchargement… {format_progress_bytes(downloaded, total)}",
            )
            if pct % 5 == 0 or pct >= 99:
                _ui(ui_log, f"Progression {pct}% — {format_progress_bytes(downloaded, total)}")
    else:
        mb = downloaded // 1048576
        if mb >= last_log_mb[0] + 5 or downloaded < 524288:
            last_log_mb[0] = mb
            from sff.fixed_games import format_bytes

            on_progress(downloaded, est, f"Téléchargement… {format_bytes(downloaded)}")
            _ui(ui_log, f"Reçu {format_bytes(downloaded)}")


def _stream_url_to_file_curl(
    url: str,
    file_id: str,
    temp_dir: Path,
    headers: dict[str, str],
    cf_session,
    on_progress: ProgressCb | None,
    ui_log: UiLogCb | None,
    expected_bytes: int,
    wipe_partial: bool = False,
) -> Path:
    """Télécharge via curl_cffi (session BuzzHeavier / Cloudflare)."""
    est = expected_bytes if expected_bytes > 0 else 35 * 1024**3
    dest_path = _partial_dest_path(temp_dir, file_id)
    if wipe_partial and dest_path.is_file():
        partial_size = dest_path.stat().st_size
        if partial_size > 5 * 1024 * 1024:
            _ui(
                ui_log,
                f"Nouvelle source CDN — partiel conservé ({partial_size:,} o), reprise en cours…",
            )
        else:
            _ui(ui_log, f"Nouvelle source — suppression de l’ancien partiel ({partial_size:,} o)")
            dest_path.unlink(missing_ok=True)
            dest_path = _partial_dest_path(temp_dir, file_id)
    _ui(ui_log, f"Téléchargement curl_cffi : {_url_for_log(url)}")

    last_err: Exception | None = None
    for resume_try in range(_MAX_RESUME_ATTEMPTS + 1):
        resume_from = dest_path.stat().st_size if dest_path.is_file() else 0
        if resume_from > 0:
            _ui(
                ui_log,
                f"Reprise curl_cffi à {resume_from:,} o "
                f"(essai {resume_try + 1}/{_MAX_RESUME_ATTEMPTS + 1})",
            )
            if on_progress:
                on_progress(
                    resume_from,
                    expected_bytes or est,
                    f"Reprise à {resume_from // 1048576} Mo…",
                )

        req_headers = dict(headers)
        if resume_from > 0:
            req_headers["Range"] = f"bytes={resume_from}-"

        try:
            resp = cf_session.get(
                url,
                headers=req_headers,
                allow_redirects=True,
                stream=True,
                impersonate="chrome124",
                timeout=600,
            )
            ctype = (resp.headers.get("content-type") or "").lower()
            if resume_try == 0 and resume_from == 0:
                _ui(
                    ui_log,
                    f"Réponse curl_cffi — HTTP {resp.status_code}, Content-Type={ctype!r}, "
                    f"URL finale={_url_for_log(str(getattr(resp, 'url', url)))}",
                )
            if "text/html" in ctype and "octet" not in ctype:
                body_head = (getattr(resp, "content", None) or b"")[:512]
                if _looks_like_html(body_head) or _RE_CF_CHALLENGE.search(
                    body_head.decode("utf-8", errors="replace")
                ):
                    raise ValueError(
                        f"Content-Type HTML ({ctype}) — Cloudflare bloque le téléchargement"
                    )

            if resp.status_code == 416:
                if dest_path.is_file() and dest_path.stat().st_size > _MIN_ARCHIVE_BYTES:
                    return dest_path
                raise ValueError("Reprise refusée par le serveur (416).")

            if resume_from > 0 and resp.status_code not in (206, 200):
                resp.raise_for_status()

            if resume_from == 0:
                resp.raise_for_status()

            cd = resp.headers.get("content-disposition", "")
            if cd and resume_from == 0:
                m = re.search(
                    r'filename\*?=(?:UTF-8\'\'\'?)?"?([^";]+)"?',
                    cd,
                    re.IGNORECASE,
                )
                if m:
                    fname = m.group(1).strip()
                    dest_path = temp_dir / fname

            total = int(resp.headers.get("content-length", 0) or 0)
            cr_total = _parse_content_range_total(resp.headers.get("content-range"))
            if cr_total:
                total = cr_total
            elif resume_from > 0 and resp.status_code == 206 and total:
                total = resume_from + total
            elif not total and expected_bytes > 0:
                total = expected_bytes

            if resume_from > 0 and resp.status_code == 200:
                _ui(
                    ui_log,
                    "Le serveur a renvoyé le fichier entier — reprise ignorée, "
                    "nouveau téléchargement.",
                )
                resume_from = 0
                dest_path.unlink(missing_ok=True)
                dest_path = _partial_dest_path(temp_dir, file_id)

            mode = "ab" if resume_from > 0 else "wb"
            downloaded = resume_from
            last_pct = [-1]
            last_log_mb = [-1]
            checked_head = resume_from > 0

            with dest_path.open(mode) as f:
                for chunk in resp.iter_content(chunk_size=524288):
                    if not chunk:
                        continue
                    if not checked_head:
                        checked_head = True
                        if _looks_like_html(chunk[:1024]):
                            raise ValueError("Flux HTML détecté — archive non reçue")
                    f.write(chunk)
                    downloaded += len(chunk)
                    _emit_dl_progress(
                        on_progress,
                        ui_log,
                        downloaded,
                        total,
                        est,
                        last_pct,
                        last_log_mb,
                    )

            final_size = dest_path.stat().st_size if dest_path.is_file() else 0
            if total > 0 and final_size >= total * 0.995:
                if on_progress:
                    on_progress(final_size, total, "Téléchargement terminé.")
                return dest_path
            if total > 0 and final_size < total:
                last_err = RuntimeError(
                    f"Téléchargement incomplet ({final_size:,} / {total:,} o)"
                )
                _ui(ui_log, f"Incomplet : {last_err}")
                continue
            if on_progress:
                on_progress(
                    final_size,
                    total or final_size,
                    "Téléchargement terminé.",
                )
            return dest_path

        except Exception as e:
            last_err = e
            partial = dest_path.stat().st_size if dest_path.is_file() else 0
            if _is_retriable_transfer_error(e) and partial > 1024 * 1024:
                _ui(
                    ui_log,
                    f"Coupure réseau ({type(e).__name__}) à {partial:,} o — "
                    f"nouvelle tentative…",
                )
                continue
            raise

    if last_err:
        raise last_err
    raise RuntimeError("Téléchargement interrompu")


def _stream_url_to_file(
    url: str,
    file_id: str,
    temp_dir: Path,
    headers: dict[str, str],
    verify: ssl.SSLContext | bool,
    cookies: httpx.Cookies | None,
    follow_redirects: bool,
    on_progress: ProgressCb | None,
    ui_log: UiLogCb | None,
    expected_bytes: int,
    wipe_partial: bool = False,
) -> Path:
    est = expected_bytes if expected_bytes > 0 else 35 * 1024**3
    dest_path = _partial_dest_path(temp_dir, file_id)
    if wipe_partial and dest_path.is_file():
        partial_size = dest_path.stat().st_size
        if partial_size > 5 * 1024 * 1024:
            _ui(
                ui_log,
                f"Nouvelle source CDN — partiel conservé ({partial_size:,} o), reprise en cours…",
            )
        else:
            _ui(ui_log, f"Nouvelle source — suppression de l’ancien partiel ({partial_size:,} o)")
            dest_path.unlink(missing_ok=True)
            dest_path = _partial_dest_path(temp_dir, file_id)
    _ui(ui_log, f"Téléchargement : {_url_for_log(url)} (redirects={follow_redirects})")

    last_err: Exception | None = None
    with httpx.Client(
        verify=verify,
        timeout=_CDN_TIMEOUT,
        follow_redirects=follow_redirects,
        http2=False,
        cookies=cookies,
    ) as client:
        for resume_try in range(_MAX_RESUME_ATTEMPTS + 1):
            resume_from = dest_path.stat().st_size if dest_path.is_file() else 0
            if resume_from > 0:
                _ui(
                    ui_log,
                    f"Reprise téléchargement à {resume_from:,} o "
                    f"(essai {resume_try + 1}/{_MAX_RESUME_ATTEMPTS + 1})",
                )
                if on_progress:
                    on_progress(
                        resume_from,
                        expected_bytes or est,
                        f"Reprise à {resume_from // 1048576} Mo…",
                    )

            req_headers = dict(headers)
            if resume_from > 0:
                req_headers["Range"] = f"bytes={resume_from}-"

            try:
                with client.stream("GET", url, headers=req_headers) as resp:
                    ctype = (resp.headers.get("content-type") or "").lower()
                    if resume_try == 0 and resume_from == 0:
                        _ui(
                            ui_log,
                            f"Réponse — HTTP {resp.status_code}, Content-Type={ctype!r}, "
                            f"URL finale={_url_for_log(str(resp.url))}",
                        )
                    if "text/html" in ctype and "octet" not in ctype:
                        raise ValueError(
                            f"Content-Type HTML ({ctype}) — pas un fichier binaire"
                        )

                    if resp.status_code == 416:
                        if dest_path.is_file() and dest_path.stat().st_size > _MIN_ARCHIVE_BYTES:
                            return dest_path
                        raise ValueError("Reprise refusée par le serveur (416).")

                    if resume_from > 0 and resp.status_code not in (206, 200):
                        resp.raise_for_status()

                    if resume_from == 0:
                        resp.raise_for_status()

                    cd = resp.headers.get("content-disposition", "")
                    if cd and resume_from == 0:
                        m = re.search(
                            r'filename\*?=(?:UTF-8\'\'\'?)?"?([^";]+)"?',
                            cd,
                            re.IGNORECASE,
                        )
                        if m:
                            fname = m.group(1).strip()
                            dest_path = temp_dir / fname

                    total = int(resp.headers.get("content-length", 0) or 0)
                    cr_total = _parse_content_range_total(
                        resp.headers.get("content-range")
                    )
                    if cr_total:
                        total = cr_total
                    elif resume_from > 0 and resp.status_code == 206 and total:
                        total = resume_from + total
                    elif not total and expected_bytes > 0:
                        total = expected_bytes

                    if resume_from > 0 and resp.status_code == 200:
                        _ui(
                            ui_log,
                            "Le serveur a renvoyé le fichier entier — reprise ignorée, "
                            "nouveau téléchargement.",
                        )
                        resume_from = 0
                        dest_path.unlink(missing_ok=True)
                        dest_path = _partial_dest_path(temp_dir, file_id)

                    mode = "ab" if resume_from > 0 else "wb"
                    downloaded = resume_from
                    last_pct = [-1]
                    last_log_mb = [-1]
                    checked_head = resume_from > 0

                    with dest_path.open(mode) as f:
                        for chunk in resp.iter_bytes(chunk_size=524288):
                            if chunk and not checked_head:
                                checked_head = True
                                if _looks_like_html(chunk[:1024]):
                                    raise ValueError(
                                        "Flux HTML détecté — archive non reçue"
                                    )
                            f.write(chunk)
                            downloaded += len(chunk)
                            _emit_dl_progress(
                                on_progress,
                                ui_log,
                                downloaded,
                                total,
                                est,
                                last_pct,
                                last_log_mb,
                            )

                final_size = dest_path.stat().st_size if dest_path.is_file() else 0
                if total > 0 and final_size >= total * 0.995:
                    if on_progress:
                        on_progress(final_size, total, "Téléchargement terminé.")
                    return dest_path
                if total > 0 and final_size < total:
                    last_err = RuntimeError(
                        f"Téléchargement incomplet ({final_size:,} / {total:,} o)"
                    )
                    _ui(ui_log, f"Incomplet : {last_err}")
                    continue
                if on_progress:
                    on_progress(
                        final_size,
                        total or final_size,
                        "Téléchargement terminé.",
                    )
                return dest_path

            except Exception as e:
                last_err = e
                partial = dest_path.stat().st_size if dest_path.is_file() else 0
                if _is_retriable_transfer_error(e) and partial > 1024 * 1024:
                    _ui(
                        ui_log,
                        f"Coupure réseau ({type(e).__name__}) à {partial:,} o — "
                        f"nouvelle tentative…",
                    )
                    continue
                raise

    if last_err:
        raise last_err
    raise RuntimeError("Téléchargement interrompu")


def download_buzzheavier(
    file_id: str,
    temp_dir: Path,
    on_progress: ProgressCb | None = None,
    ui_log: UiLogCb | None = None,
    expected_bytes: int = 0,
    catalog_url: str | None = None,
) -> Path | None:
    file_id = (file_id or "").strip().strip("/")
    if not file_id:
        _ui(ui_log, "file_id vide — abandon")
        return None

    page_url = resolve_buzzheavier_page_url(catalog_url or "", file_id)
    _ui(ui_log, f"Démarrage file_id={file_id!r} → {temp_dir}")

    if on_progress:
        on_progress(0, 0, "Préparation du téléchargement…")

    page_html, effective_page, page_status, page_cookies, cf_session = _fetch_buzz_page_html(
        catalog_url or page_url,
        file_id,
        ui_log=ui_log,
    )
    if not page_html:
        err = (
            f"BuzzHeavier inaccessible (HTTP {page_status or '?'}) — "
            "Cloudflare a peut‑être bloqué la page. "
            "Réessaie dans quelques minutes ou vérifie le lien dans le catalogue admin."
        )
        _ui(ui_log, err)
        if on_progress:
            on_progress(0, 0, err)
        return None

    _ui(
        ui_log,
        f"Page OK — {len(page_html)} car., cookies={len(page_cookies)}, "
        f"curl_session={'oui' if cf_session else 'non'}",
    )
    _ui(ui_log, f"URL effective : {_url_for_log(effective_page)}")

    with httpx.Client(timeout=_PAGE_TIMEOUT, follow_redirects=True) as session:
        for name, value in page_cookies.items():
            try:
                session.cookies.set(name, value)
            except Exception:
                pass

        paths = _parse_download_paths_from_html(page_html, file_id)
        _ui(ui_log, f"{len(paths)} lien(s) de téléchargement dans la page")

        attempts: list[tuple[str, str, dict[str, str], bool, bool]] = []

        for i, path in enumerate(paths):
            label = f"Serveur {i + 1}"
            trigger_url = urljoin(effective_page, path.lstrip("/"))
            if on_progress:
                on_progress(0, 0, f"Préparation {label}…")

            cdn_url: str | None = None
            try:
                cdn_url = _resolve_cdn_url(
                    effective_page,
                    path,
                    session,
                    ui_log=ui_log,
                    cf_session=cf_session,
                )
            except Exception as e:
                _ui(ui_log, f"Résolution CDN {label} : {e}")

            hx = _htmx_headers(effective_page)
            attempts.append(
                (
                    f"{label} — via lien signé (redirections)",
                    trigger_url,
                    {**hx, "Accept": "application/octet-stream,*/*;q=0.9,*/*;q=0.8"},
                    True,
                    True,
                )
            )
            if cdn_url:
                attempts.append(
                    (
                        f"{label} — miroir CDN",
                        cdn_url,
                        {
                            **_cdn_headers(trigger_url),
                            "Accept": "application/octet-stream,*/*;q=0.9,*/*;q=0.8",
                        },
                        True,
                        False,
                    )
                )

        cookies = session.cookies
        last_err = "Aucune méthode de téléchargement n’a abouti."
        prev_url: str | None = None
        for label, url, headers, follow, use_curl in attempts:
            wipe = bool(prev_url and prev_url != url)
            prev_url = url
            if on_progress:
                on_progress(0, expected_bytes or 0, f"Connexion ({label})…")
            verify = _verify_for_url(url)
            if verify is False:
                _ui(ui_log, f"{label} — TLS sans vérification (miroir tiers)")
            dest: Path | None = None
            try:
                if use_curl and cf_session is not None and _is_buzzheavier_host(
                    urlparse(url).netloc or ""
                ):
                    dest = _stream_url_to_file_curl(
                        url,
                        file_id,
                        temp_dir,
                        headers,
                        cf_session,
                        on_progress,
                        ui_log,
                        expected_bytes,
                        wipe_partial=wipe,
                    )
                else:
                    dest = _stream_url_to_file(
                        url,
                        file_id,
                        temp_dir,
                        headers,
                        verify,
                        cookies,
                        follow,
                        on_progress,
                        ui_log,
                        expected_bytes,
                        wipe_partial=wipe,
                    )
                ok, err = validate_downloaded_archive(dest, expected_bytes)
                if ok:
                    _ui(ui_log, f"Archive valide : {dest} ({dest.stat().st_size:,} o)")
                    return dest
                last_err = err
                _ui(ui_log, f"{label} rejeté : {err}")
                dest.unlink(missing_ok=True)
            except Exception as e:
                last_err = str(e)
                _ui(ui_log, f"{label} échec : {type(e).__name__}: {e}")
                partial = dest.stat().st_size if dest and dest.is_file() else 0
                if (
                    dest
                    and dest.is_file()
                    and partial > 0
                    and not _is_retriable_transfer_error(e)
                ):
                    dest.unlink(missing_ok=True)
                if _is_ssl_error(e) and verify is not False:
                    try:
                        dest = _stream_url_to_file(
                            url,
                            file_id,
                            temp_dir,
                            headers,
                            False,
                            cookies,
                            follow,
                            on_progress,
                            ui_log,
                            expected_bytes,
                            wipe_partial=wipe,
                        )
                        ok, err = validate_downloaded_archive(dest, expected_bytes)
                        if ok:
                            return dest
                        last_err = err
                        _ui(ui_log, f"{label} (SSL off) rejeté : {err}")
                        dest.unlink(missing_ok=True)
                    except Exception as e2:
                        last_err = str(e2)
                        _ui(ui_log, f"{label} (SSL off) échec : {e2}")

        partial_path = _partial_dest_path(temp_dir, file_id)
        if partial_path.is_file():
            ps = partial_path.stat().st_size
            if ps > 100 * 1024 * 1024:
                last_err = (
                    f"Connexion coupée vers {ps // (1024 * 1024)} Go / "
                    f"{(expected_bytes or est) // (1024 * 1024)} Go. "
                    f"Relance le téléchargement : la reprise automatique reprendra où ça s’est arrêté."
                )
        log.error("buzzheavier download failed %s: %s", file_id, last_err)
        if on_progress:
            on_progress(0, 0, str(last_err))
        return None


def _cdn_headers(referer: str | None) -> dict[str, str]:
    headers = {"User-Agent": _UA}
    if referer:
        headers["Referer"] = referer
        try:
            p = urlparse(referer)
            if p.scheme and p.netloc:
                headers["Origin"] = f"{p.scheme}://{p.netloc}"
        except Exception:
            pass
    return headers
