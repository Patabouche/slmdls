#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Génère ``sff/_gc_secrets.py`` pour embarquer client_id / client_secret dans l'exe.

À lancer **avant** PyInstaller. ``prepare_gdrive_for_build.py`` est invoqué par les scripts
de build ; tu peux aussi lancer ce module à la main.

Sources (ordre) ::
  1. Chemin JSON passé en argument
  2. ``gdrive_oauth_client.json`` — racine SFF puis ``sff/``
 Fichiers ``client_secret*.json`` — racine SFF puis ``sff/``
  3. ``SLIMEDEALS_GDRIVE_CLIENT_*`` / ``STEAMIDRA_GDRIVE_CLIENT_*`` (compat.)

Exemple ::
    python write_gdrive_gc_secrets.py
    python write_gdrive_gc_secrets.py "C:\\chemin\\client_secret.json"

Mode strict (CI) : variable ``SFF_STRICT_GDRIVE_BUILD=1`` — échec si aucune source.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path


def _extract_from_dict(raw: dict) -> tuple[str, str]:
    ins = raw.get("installed") if isinstance(raw.get("installed"), dict) else raw
    if not isinstance(ins, dict):
        return "", ""
    cid = str(ins.get("client_id") or ins.get("clientId") or "").strip()
    csec = str(ins.get("client_secret") or ins.get("clientSecret") or "").strip()
    return cid, csec


def _try_load_json_file(p: Path) -> tuple[str, str]:
    if not p.is_file():
        return "", ""
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return _extract_from_dict(raw)
    except Exception as e:
        print(f"Erreur lecture {p}: {e}", file=sys.stderr)
    return "", ""


def oauth_candidate_paths(spec_root: Path) -> list[Path]:
    """Chemins à tester dans l'ordre (sans doublons)."""
    sff_dir = spec_root / "sff"
    ordered: list[Path] = [
        spec_root / "gdrive_oauth_client.json",
        sff_dir / "gdrive_oauth_client.json",
    ]
    ordered.extend(sorted(spec_root.glob("client_secret*.json")))
    ordered.extend(sorted(sff_dir.glob("client_secret*.json")))
    seen: set[str] = set()
    out: list[Path] = []
    for p in ordered:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def resolve_oauth_credentials(
    spec_root: Path,
    json_path_arg: str = "",
) -> tuple[str, str]:
    """Résout client_id / client_secret depuis un fichier ou l'environnement."""
    if json_path_arg.strip():
        cid, csec = _try_load_json_file(Path(json_path_arg).expanduser())
        if cid and csec:
            return cid, csec

    for p in oauth_candidate_paths(spec_root):
        cid, csec = _try_load_json_file(p)
        if cid and csec:
            return cid, csec

    cid = (
        os.environ.get("SLIMEDEALS_GDRIVE_CLIENT_ID", "")
        or os.environ.get("STEAMIDRA_GDRIVE_CLIENT_ID", "")
    ).strip()
    csec = (
        os.environ.get("SLIMEDEALS_GDRIVE_CLIENT_SECRET", "")
        or os.environ.get("STEAMIDRA_GDRIVE_CLIENT_SECRET", "")
    ).strip()
    return cid, csec


def write_gc_secrets_module(sff_dir: Path, cid: str, csec: str) -> Path:
    out = sff_dir / "_gc_secrets.py"
    b64_ci = base64.b64encode(cid.encode("utf-8")).decode("ascii")
    b64_cs = base64.b64encode(csec.encode("utf-8")).decode("ascii")
    body = f'''# -*- coding: utf-8 -*-
# Généré par write_gdrive_gc_secrets.py — NE PAS COMMITER sur un dépôt public.
import base64

_CID = base64.b64decode("{b64_ci}").decode("utf-8")
_CSEC = base64.b64decode("{b64_cs}").decode("utf-8")
'''
    sff_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    return out


def prepare_embedded_oauth(
    spec_root: Path | None = None,
    *,
    strict: bool = False,
    json_path_arg: str = "",
) -> bool:
    """Écrit ``sff/_gc_secrets.py`` si des identifiants sont trouvés. Retourne True si écrit."""
    root = spec_root or Path(__file__).resolve().parent
    sff_dir = root / "sff"
    cid, csec = resolve_oauth_credentials(root, json_path_arg=json_path_arg)
    if not cid or not csec:
        msg = (
            "[GDRIVE] Aucune source OAuth (gdrive_oauth_client.json, client_secret*.json, "
            "variables SLIMEDEALS_GDRIVE_CLIENT_* / STEAMIDRA_*). "
            "_gc_secrets.py non regenere ; l'exe pourra exiger un JSON sous %APPDATA%\\SlimeDeals."
        )
        if strict:
            print(msg, file=sys.stderr)
            return False
        print(msg)
        return False

    out = write_gc_secrets_module(sff_dir, cid, csec)
    print(f"[GDRIVE] Identifiants embarques pour PyInstaller -> {out}")
    return True


def strict_from_environ() -> bool:
    return os.environ.get("SFF_STRICT_GDRIVE_BUILD", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Écrit sff/_gc_secrets.py pour le build PyInstaller")
    ap.add_argument(
        "json_path",
        nargs="?",
        default="",
        help="Fichier JSON OAuth (format Google « installed » ou racine plate)",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    if not prepare_embedded_oauth(root, strict=False, json_path_arg=args.json_path.strip()):
        print(
            "Aucun identifiant : fournis un JSON OAuth, ou place gdrive_oauth_client.json / "
            "client_secret*.json à la racine SFF ou dans sff/, ou définit les variables d'environnement.",
            file=sys.stderr,
        )
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
