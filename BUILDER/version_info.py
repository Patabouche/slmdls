# -*- coding: utf-8 -*-
# Métadonnées PE Windows (Propriétés du fichier) — lu par PyInstaller build_sff_gui.spec
# VERSION synchronisée avec sff/strings.py au moment du build.

import importlib.util
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_STRINGS = os.path.join(_HERE, "..", "sff", "strings.py")

_version = "1.1.1"
try:
    _spec = importlib.util.spec_from_file_location("_sff_strings", _STRINGS)
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _version = str(getattr(_mod, "VERSION", _version))
except Exception:
    pass

_parts = [int(x) for x in re.findall(r"\d+", _version)[:4]]
while len(_parts) < 4:
    _parts.append(0)
_filevers = tuple(_parts)
_prodvers = tuple(_parts)
_ver_str = ".".join(str(x) for x in _parts[:3])

from PyInstaller.utils.win32.versioninfo import (  # noqa: E402
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_filevers,
        prodvers=_prodvers,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "SlimeDeals"),
                        StringStruct("FileDescription", "SlimeDeals Launcher"),
                        StringStruct("FileVersion", _ver_str),
                        StringStruct("InternalName", "SteaMidra_GUI"),
                        StringStruct(
                            "LegalCopyright",
                            "Copyright (c) 2025-2026 SlimeDeals. All rights reserved.",
                        ),
                        StringStruct("OriginalFilename", "SteaMidra_GUI.exe"),
                        StringStruct("ProductName", "SlimeDeals Launcher"),
                        StringStruct("ProductVersion", _ver_str),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)
