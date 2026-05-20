# -*- mode: python ; coding: utf-8 -*-

import glob
import os
import sys
from pathlib import Path

block_cipher = None

spec_root = os.path.abspath(SPECPATH)
icon_path = os.path.join(spec_root, 'sff.ico')
_builder_dir = os.path.join(spec_root, 'BUILDER')
_version_info_path = os.path.join(_builder_dir, 'version_info.py')
_app_manifest_path = os.path.join(_builder_dir, 'app.manifest')

# Build « public » : exclut les binaires les plus signalés par l’AV du ZIP distribué.
# Définir SLIMEDEALS_PUBLIC_RELEASE=1 (build_launcher.bat public) ou laisser 0 pour build complet.
_public_release = os.environ.get('SLIMEDEALS_PUBLIC_RELEASE', '').strip().lower() in (
    '1', 'true', 'yes', 'public',
)

def get_win10toast_data():
    try:
        import win10toast
        win10toast_dir = os.path.dirname(win10toast.__file__)
        data_dir = os.path.join(win10toast_dir, 'data')
        if os.path.exists(data_dir):
            return (data_dir, 'win10toast/data')
    except Exception as e:
        print(f"Warning: Could not find win10toast data: {e}")
    return None

datas = [
    ('static', 'static'),
]

# Include third_party tools if present.
# Windows GUI : ne pas empaqueter les arbres Linux-only — surtout gbe_fork_tools_linux
# (PyInstaller Linux imbriqué, chemins > MAX_PATH, .so inutiles) provoque FileNotFoundError au COLLECT.
third_party_dir = os.path.join(spec_root, 'third_party')
if os.path.exists(third_party_dir):
    if sys.platform == 'win32':
        _third_party_skip_win = frozenset({'gbe_fork_tools_linux', 'linux', 'hv'})
        for _tp_entry in sorted(os.listdir(third_party_dir)):
            if _tp_entry in _third_party_skip_win:
                print(
                    f"Note: third_party/{_tp_entry} exclu du build Windows GUI "
                    f"({'VBS.cmd très signalé AV' if _tp_entry == 'hv' else 'outil Linux uniquement'})."
                )
                continue
            _tp_src = os.path.join(third_party_dir, _tp_entry)
            _tp_dest = os.path.join('third_party', _tp_entry)
            if os.path.isdir(_tp_src):
                datas.append((_tp_src, _tp_dest))
            elif os.path.isfile(_tp_src):
                datas.append((_tp_src, 'third_party'))
    else:
        datas.append((third_party_dir, 'third_party'))

# DLC unlocker bundled resources (CreamAPI, SmokeAPI, Koaloader, UplayR1/R2 DLLs)
dlc_resources_dir = os.path.join(spec_root, 'sff', 'dlc_unlockers', 'resources')
if os.path.exists(dlc_resources_dir):
    datas.append((dlc_resources_dir, 'sff/dlc_unlockers/resources'))

if os.path.exists(os.path.join(spec_root, 'sff.png')):
    datas.append(('sff.png', '.'))
if os.path.exists(os.path.join(spec_root, 'sff.ico')):
    datas.append(('sff.ico', '.'))
gui_resources = os.path.join(spec_root, 'sff', 'gui', 'resources')
if os.path.exists(gui_resources):
    datas.append((gui_resources, 'sff/gui/resources'))

# Include locale files for multi-language support
locales_dir = os.path.join(spec_root, 'sff', 'locales')
if os.path.exists(locales_dir):
    datas.append((locales_dir, 'sff/locales'))

# Include fallback depot keys/tokens from sff/lua/
lua_dir = os.path.join(spec_root, 'sff', 'lua')
if os.path.exists(lua_dir):
    datas.append((lua_dir, 'sff/lua'))

# Include fallback depot keys database if present at sff/ level
fallback_db = os.path.join(spec_root, 'sff', 'fallback_depotkeys.json')
if os.path.exists(fallback_db):
    datas.append((fallback_db, 'sff'))

# Include all_games.txt for offline game name resolution in Cloud Saves
all_games_txt = os.path.join(spec_root, 'all_games.txt')
if os.path.exists(all_games_txt):
    datas.append((all_games_txt, '.'))

# Include sff/webui/ folder (HTML/CSS/JS web UI assets)
webui_dir = os.path.join(spec_root, 'sff', 'webui')
if os.path.exists(webui_dir):
    datas.append((webui_dir, 'sff/webui'))

fixed_games_data = os.path.join(spec_root, 'sff', 'data')
if os.path.exists(fixed_games_data):
    datas.append((fixed_games_data, 'sff/data'))

# Include c/ folder (MIDI player library, soundfont, and MIDI files)
c_dir = os.path.join(spec_root, 'c')
if os.path.exists(c_dir):
    datas.append((c_dir, 'c'))

# Google Drive — JSON OAuth téléchargé depuis Google Cloud (non versionné ; inclus si présent au build)
for _gcs in sorted(glob.glob(os.path.join(spec_root, 'client_secret*.json'))):
    datas.append((_gcs, '.'))
    print(f"Including Google OAuth client JSON (datas): {os.path.basename(_gcs)}")

_gdrive_oauth_root = os.path.join(spec_root, 'gdrive_oauth_client.json')
if os.path.exists(_gdrive_oauth_root):
    datas.append((_gdrive_oauth_root, '.'))
    print(f"Including Google OAuth: {os.path.basename(_gdrive_oauth_root)} → bundle racine (_MEIPASS)")

_gdrive_oauth_sff = os.path.join(spec_root, 'sff', 'gdrive_oauth_client.json')
if os.path.exists(_gdrive_oauth_sff):
    datas.append((_gdrive_oauth_sff, 'sff'))
    print("Including Google OAuth: sff/gdrive_oauth_client.json → PyInstaller datas")

_hidden_gc_secrets = []
if os.path.isfile(os.path.join(spec_root, 'sff', '_gc_secrets.py')):
    _hidden_gc_secrets.append('sff._gc_secrets')
    print("PyInstaller: hiddenimport sff._gc_secrets (OAuth embarqué généré par write_gdrive_gc_secrets.py)")

# ROCKSTAR BYPASS — SlimeDealsBPRG (build complet uniquement ; très signalé AV en release publique)
_sdb_dir = os.path.join(spec_root, 'SlimeDealsBPRG')
_sdb_exe = os.path.join(_sdb_dir, 'SlimeDealsBPRG.exe')
if _public_release:
    print(
        "Note: build PUBLIC — SlimeDealsBPRG/ exclu (SLIMEDEALS_PUBLIC_RELEASE). "
        "Utilisez « build_launcher.bat full » pour l’embarquer."
    )
elif os.path.isfile(_sdb_exe):
    datas.append((_sdb_dir, 'SlimeDealsBPRG'))
    print(f"Including SlimeDealsBPRG (datas): {_sdb_dir}")
else:
    print(
        "Note: SlimeDealsBPRG/SlimeDealsBPRG.exe absent — compilez l'outil (voir SlimeDealsBPRG/README.txt) "
        "ou lancez build_simple_gui.bat qui tente un build automatique depuis le dépôt test."
    )

# GreenLuma — archive d'installation auto (build complet uniquement)
_gl_rar = os.path.join(spec_root, 'greenlumafix.rar')
if _public_release:
    print(
        "Note: build PUBLIC — greenlumafix.rar exclu (SLIMEDEALS_PUBLIC_RELEASE). "
        "GreenLuma : installation manuelle ou build « full »."
    )
elif os.path.isfile(_gl_rar):
    datas.append((_gl_rar, '.'))
    print(f"Including greenlumafix.rar (datas): {_gl_rar}")
else:
    print(
        "Note: greenlumafix.rar absent — placez l'archive à la racine de launcher/SFF "
        "avant le build pour l'installation GreenLuma automatique au démarrage."
    )

win10toast_data = get_win10toast_data()
if win10toast_data:
    datas.append(win10toast_data)
    print(f"Including win10toast data from: {win10toast_data[0]}")

# TLS : cacert.pem certifi (httpx / ssl — évite FileNotFoundError si le hook ne suffit pas)
try:
    from PyInstaller.utils.hooks import collect_data_files

    _certifi_files = collect_data_files('certifi')
    if _certifi_files:
        datas.extend(_certifi_files)
        print(f"Including certifi CA bundle ({len(_certifi_files)} data entries).")
except Exception as _cert_ex:
    print(f"Note: certifi collect_data_files: {_cert_ex}")

# Google OAuth — collect_all : fichiers de données + binaires parfois requis (évite ImportError en exe)
_gd_oauth_d, _gd_oauth_b, _gd_oauth_h = [], [], []
try:
    from PyInstaller.utils.hooks import collect_all

    for _pkg in (
        "google_auth_oauthlib",
        "googleapiclient",
        "google_auth_httplib2",
        "httplib2",
        "uritemplate",
        "google.api_core",
    ):
        try:
            _d, _b, _h = collect_all(_pkg)
            _gd_oauth_d += _d
            _gd_oauth_b += _b
            _gd_oauth_h += _h
        except Exception as _ex:
            print(f"Note: collect_all({_pkg}): {_ex}")
except Exception as _ex:
    print(f"Note: Google OAuth collect_all skipped: {_ex}")

datas = datas + _gd_oauth_d

a = Analysis(
    ['Main_gui.py'],
    pathex=[spec_root],
    binaries=_gd_oauth_b,
    datas=datas,
    hiddenimports=[
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.sip',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebChannel',
        'PyQt6.QtNetwork',
        'sff.single_instance',
        'prompt_toolkit',
        'selenium',
        'selenium.webdriver',
        'selenium.webdriver.chrome',
        'selenium.webdriver.chrome.service',
        'selenium.webdriver.chrome.options',
        'selenium.webdriver.common.by',
        'selenium.webdriver.common.keys',
        'selenium.webdriver.support',
        'selenium.webdriver.support.ui',
        'selenium.webdriver.support.expected_conditions',
        'selenium.common.exceptions',
        'steam',
        'steam.client',
        'gevent',
        'sff.manifest.collections',
        'sff.manifest.workshop_tracker',
        'psutil',
        'colorama',
        'httpx',
        'certifi',
        'keyring',
        'keyring.backends',
        'keyring.backends.Windows',
        'keyrings',
        'keyrings.alt',
        'keyrings.alt.file',
        'nacl',
        'nacl.exceptions',
        'nacl.secret',
        'nacl.encoding',
        'pynacl',
        'cryptography',
        'win10toast',
        'sff.store_browser',
        'sff.image_cache',
        'sff.download_manager',

        'sff.cloud_saves',
        'sff.google_drive',
        'sff._gc',
    ]
    + _hidden_gc_secrets
    + [
        'google.auth',
        'google.auth.transport.requests',
        'google.oauth2.credentials',
        'google_auth_oauthlib',
        'google_auth_oauthlib.flow',
        'googleapiclient',
        'googleapiclient.discovery',
        'googleapiclient.http',
        'sff.tray_icon',
        'sff.uri_handler',
        'sff.fix_game',
        'sff.fix_game.service',
        'sff.fix_game.cache',
        'sff.fix_game.goldberg_updater',
        'sff.fix_game.config_generator',
        'sff.fix_game.steamstub_unpacker',
        'sff.fix_game.goldberg_applier',
        'sff.fix_game.online_fix_applier',
        'sff.online_fix_embed',
        'sff.fix_game.gse_tool_updater',
        'sff.linux.steam_process',
        'sff.tools',
        'sff.tools.gbe_token_generator',
        'sff.tools.vdf_key_extractor',
        'sff.tools.capcom_save_fix',
        'py7zr',
        'rarfile',
        'sff.greenluma_setup',
        'bs4',
        'bs4.builder',
        'bs4.builder._html5lib',
        'bs4.builder._lxml',
        'bs4.builder._htmlparser',
    ]
    + _gd_oauth_h,
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

_version_info = None
if sys.platform == 'win32' and os.path.isfile(_version_info_path):
    _version_info = _version_info_path
    print(f"Including Windows version_info: {_version_info_path}")

_app_manifest = _app_manifest_path if (
    sys.platform == 'win32' and os.path.isfile(_app_manifest_path)
) else None
if _app_manifest:
    print(f"Including Windows manifest (asInvoker): {_app_manifest_path}")

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name='SteaMidra_GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_version_info,
    manifest=_app_manifest,
    icon=icon_path if os.path.exists(icon_path) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SteaMidra_GUI',
)
