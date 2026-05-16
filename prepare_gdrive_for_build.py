#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Appelé par les scripts de build avant PyInstaller : génère ``sff/_gc_secrets.py`` si possible.

Ne fait pas échouer le build par défaut (préserve les builds sans Google Drive).
Pour forcer la présence d’OAuth : ``set SFF_STRICT_GDRIVE_BUILD=1`` puis build.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Répertoire launcher/SFF (où se trouvent les .spec et ce script)
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import write_gdrive_gc_secrets as _w  # noqa: E402


def main() -> None:
    strict = _w.strict_from_environ()
    ok = _w.prepare_embedded_oauth(_ROOT, strict=strict)
    if strict and not ok:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
