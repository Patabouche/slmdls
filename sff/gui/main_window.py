# SlimeDeals - Steam game setup and manifest tool (SFF)
# Copyright (c) 2025-2026 Midrag (https://github.com/Midrags)
#
# This file is part of SlimeDeals.
#
# SlimeDeals is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SlimeDeals is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SlimeDeals.  If not, see <https://www.gnu.org/licenses/>.
import logging
import re
import sys
from html import escape as html_escape
from pathlib import Path

from PyQt6.QtCore import QObject, QPoint, QThread, QTimer, QUrl, pyqtSignal, Qt
from PyQt6.QtGui import QDesktopServices, QTextCursor, QColor, QFont, QFontMetrics, QPainter
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QTabWidget,
)

from sff.gui.log_window import GlobalLogWindow, QtLogHandler
from sff.gui.themes import THEMES
from sff.i18n import T
from sff.mandatory_update_gui import (
    MANDATORY_UPDATE_FIRST_POLL_MS,
    MANDATORY_UPDATE_POLL_INTERVAL_MS,
)
from sff.strings import VERSION
from sff.structs import MainMenu, MainReturnCode

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
logger = logging.getLogger(__name__)


class StreamEmitter(QObject):
    text_written = pyqtSignal(str)

    def write(self, text):
        if text:
            self.text_written.emit(text)

    def flush(self):
        pass


class GenericWorker(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, func):
        super().__init__()
        self.func = func

    def run(self):
        try:
            result = self.func()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit(None)


def _arrow_style_url(path):
    s = str(path.resolve()).replace("\\", "/")
    return f'"{s}"' if " " in s else s


_RESOURCES_DIR = Path(__file__).resolve().parent / "resources"


class GameComboBox(QComboBox):
    """ComboBox with visible arrow that points down when closed, up when open."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup_open = False
        self._down_path = _RESOURCES_DIR / "arrow_down.png"
        self._up_path = _RESOURCES_DIR / "arrow_up.png"
        self._update_arrow()

    def showPopup(self):
        self._popup_open = True
        self._update_arrow()
        super().showPopup()

    def hidePopup(self):
        super().hidePopup()
        self._popup_open = False
        self._update_arrow()

    def _update_arrow(self):
        if not self._down_path.exists() or not self._up_path.exists():
            return
        p = self._up_path if self._popup_open else self._down_path
        url = _arrow_style_url(p)
        self.setStyleSheet(
            f"QComboBox::down-arrow {{ image: url({url}); width: 14px; height: 14px; }}"
            "QComboBox::drop-down {"
            " subcontrol-origin: padding; subcontrol-position: center right;"
            " width: 24px; min-width: 24px; border: none; }"
        )


class LauncherNewsTicker(QWidget):
    """Banderole défilante (annonces serveur) entre Discord et le bloc utilisateur."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._msg = ""
        self._scroll = 0
        self._cycle = 400
        self._timer = QTimer(self)
        self._timer.setInterval(32)
        self._timer.timeout.connect(self._tick)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(22)
        self.setMinimumWidth(80)
        self.setStyleSheet(
            "LauncherNewsTicker{ border-radius:5px;"
            "border:1px solid rgba(114,137,218,0.38); }"
        )

    def set_message(self, text: str):
        t = (text or "").strip()
        self._msg = t
        self._scroll = 0
        if not t:
            self.setVisible(False)
            self._timer.stop()
            self.update()
            return
        f = QFont()
        f.setPointSize(9)
        f.setWeight(600)
        fm = QFontMetrics(f)
        gap = 56
        self._cycle = max(160, fm.horizontalAdvance(t) + gap)
        self.setMinimumWidth(min(420, 120 + fm.horizontalAdvance(t) // 4))
        self.setVisible(True)
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def _tick(self):
        if self._msg:
            self._scroll = (self._scroll + 1) % self._cycle
            self.update()

    def paintEvent(self, event):
        if not self._msg:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.fillRect(self.rect(), QColor(21, 23, 34, 235))
        f = QFont()
        f.setPointSize(9)
        f.setWeight(600)
        p.setFont(f)
        fm = p.fontMetrics()
        w, h = self.width(), self.height()
        baseline = (h + fm.ascent() - fm.descent()) // 2
        p.setPen(QColor("#c5cee0"))
        cy = max(1, self._cycle)
        off = self._scroll % cy
        x = float(-off)
        while x < w + cy:
            p.drawText(QPoint(int(x), baseline), self._msg)
            x += cy


def _launcher_auth_strictly_free() -> bool:
    """True si auth.json indique le seul plan FREE (même logique que le WebUI / web_bridge)."""
    import json

    p = Path.home() / ".slimedeals" / "auth.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return True
    r = str(data.get("rank") or "free").strip().lower().replace(" ", "_")
    if not r or r in ("none", "null"):
        r = "free"
    return r == "free"


class SFFMainWindow(QMainWindow):
    _launcher_banner_payload = pyqtSignal(object)

    def __init__(self, ui, steam_path):
        super().__init__()
        self.ui = ui
        self.steam_path = steam_path
        from sff.storage.settings import get_setting
        from sff.structs import Settings as _S
        _saved_theme = get_setting(_S.THEME)
        self._current_theme = _saved_theme if (_saved_theme and _saved_theme in THEMES) else "dark"
        self._music_muted = False
        self._game_list = []
        self._stream_emitter = StreamEmitter()
        self._log_window = GlobalLogWindow(self)
        self._log_handler = QtLogHandler()
        self._log_handler.setFormatter(
            __import__('logging').Formatter("%(name)s — %(message)s")
        )
        self._log_handler.setLevel(__import__('logging').DEBUG)
        self._log_handler.record_emitted.connect(self._log_window.append_record)
        self._log_handler.record_emitted.connect(self._forward_log_to_web)
        __import__('logging').getLogger().addHandler(self._log_handler)
        self._stream_emitter.text_written.connect(self._forward_stdout_to_web)
        self._stream_emitter.text_written.connect(self._log_window.append_text)
        self._worker = None
        self._worker_thread = None
        self.setWindowTitle(f"SlimeDeals — {VERSION}")
        self.setMinimumSize(960, 700)
        self.resize(1020, 780)
        from sff.gui.gui_prompts import update_parent
        update_parent(self)
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        # ── Top bar fine (hauteur compacte, tout sur une ligne) ──
        top_wrap = QFrame()
        top_wrap.setObjectName("topChromeStrip")
        top_wrap.setMaximumHeight(34)
        top_wrap.setStyleSheet(
            "#topChromeStrip {"
            "  background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "    stop:0 rgba(22,17,30,0.98), stop:1 rgba(14,11,20,0.96));"
            "  border: none;"
            "  border-bottom: 1px solid rgba(165, 233, 1, 0.12);"
            "}"
        )
        toggle_bar = QHBoxLayout(top_wrap)
        toggle_bar.setContentsMargins(6, 2, 6, 2)
        toggle_bar.setSpacing(8)

        site_btn = QPushButton("SlimeDeals")
        site_btn.setObjectName("topLinkSite")
        site_btn.setToolTip("Ouvrir le site SlimeDeals")
        site_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        site_btn.setFixedHeight(24)
        site_btn.setStyleSheet(
            "#topLinkSite {"
            "  color: #ecfdf5;"
            "  font-weight: 700;"
            "  font-size: 11px;"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "    stop:0 rgba(126, 200, 227, 0.35), stop:1 rgba(97, 31, 176, 0.38));"
            "  border: 1px solid rgba(126, 200, 227, 0.45);"
            "  border-radius: 6px;"
            "  padding: 2px 10px;"
            "}"
            "#topLinkSite:hover {"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "    stop:0 rgba(165, 233, 1, 0.35), stop:1 rgba(126, 200, 227, 0.42));"
            "  border-color: rgba(165, 233, 1, 0.55);"
            "}"
            "#topLinkSite:pressed { background: rgba(97, 31, 176, 0.5); }"
        )
        site_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://slimedeals.fr")))

        discord_btn = QPushButton("Discord")
        discord_btn.setObjectName("topLinkDiscord")
        discord_btn.setToolTip("Rejoindre le Discord SlimeDeals")
        discord_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        discord_btn.setFixedHeight(24)
        discord_btn.setStyleSheet(
            "#topLinkDiscord {"
            "  color: #eef2ff;"
            "  font-weight: 700;"
            "  font-size: 11px;"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "    stop:0 rgba(88, 101, 242, 0.5), stop:1 rgba(71, 82, 196, 0.45));"
            "  border: 1px solid rgba(139, 156, 255, 0.4);"
            "  border-radius: 6px;"
            "  padding: 2px 10px;"
            "}"
            "#topLinkDiscord:hover {"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "    stop:0 rgba(129, 142, 255, 0.6), stop:1 rgba(88, 101, 242, 0.5));"
            "}"
            "#topLinkDiscord:pressed { background: rgba(67, 76, 180, 0.65); }"
        )
        discord_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://discord.gg/c2pRJKjvgE")))

        # Logout button (hidden until authenticated)
        self._logout_btn = QPushButton("Déconnexion")
        self._logout_btn.setObjectName("topLinkLogout")
        self._logout_btn.setToolTip("Se déconnecter du compte SlimeDeals")
        self._logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._logout_btn.setFixedHeight(24)
        self._logout_btn.setStyleSheet(
            "#topLinkLogout {"
            "  color: #fecdd3;"
            "  font-weight: 700;"
            "  font-size: 10px;"
            "  background: rgba(225, 29, 72, 0.18);"
            "  border: 1px solid rgba(251, 113, 133, 0.35);"
            "  border-radius: 6px;"
            "  padding: 2px 8px;"
            "}"
            "#topLinkLogout:hover { background: rgba(225, 29, 72, 0.3); }"
            "#topLinkLogout:pressed { background: rgba(159, 18, 57, 0.4); }"
        )
        self._logout_btn.setVisible(False)
        self._logout_btn.clicked.connect(self._do_logout)

        # Pseudo + quota + rang : une seule ligne horizontale
        self._user_bar_widget = QFrame()
        self._user_bar_widget.setObjectName("userBarCard")
        self._user_bar_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._user_bar_widget.setMaximumHeight(28)
        self._user_bar_widget.setStyleSheet(
            "#userBarCard {"
            "  background: rgba(26, 20, 38, 0.75);"
            "  border: 1px solid rgba(165, 233, 1, 0.18);"
            "  border-radius: 8px;"
            "}"
        )
        card_outer = QHBoxLayout(self._user_bar_widget)
        card_outer.setContentsMargins(6, 0, 8, 0)
        card_outer.setSpacing(8)

        self._user_emoji_lbl = QLabel("👤")
        self._user_emoji_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._user_emoji_lbl.setFixedSize(22, 22)
        self._user_emoji_lbl.setStyleSheet(
            "QLabel {"
            "  background: rgba(97, 31, 176, 0.35);"
            "  border: 1px solid rgba(165, 233, 1, 0.22);"
            "  border-radius: 11px;"
            "  font-size: 11px;"
            "}"
        )

        self._user_name_btn = QPushButton()
        self._user_name_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._user_name_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._user_name_btn.setToolTip("Profil du compte — abonnement Stripe")
        self._user_name_btn.setStyleSheet(
            "QPushButton {"
            "  font-size: 13px;"
            "  font-weight: 700;"
            "  border: none;"
            "  background: transparent;"
            "  padding: 0;"
            "  color: #f4f4f8;"
            "  text-align: left;"
            "}"
            "QPushButton:hover { color: #ffffff; text-decoration: underline; }"
        )
        self._user_name_btn.clicked.connect(self._show_account_profile_dialog)
        self._user_name_btn.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self._user_name_btn.setMaximumHeight(24)

        self._user_quota_lbl = QLabel()
        self._user_quota_lbl.setStyleSheet(
            "QLabel {"
            "  font-size: 9px;"
            "  font-weight: 700;"
            "  background: rgba(148, 163, 184, 0.12);"
            "  color: #e2e8f0;"
            "  padding: 1px 6px;"
            "  border-radius: 4px;"
            "  border: 1px solid rgba(148, 163, 184, 0.22);"
            "}"
        )
        self._user_quota_lbl.setMaximumHeight(20)
        self._user_quota_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        self._user_rank_lbl = QLabel()
        self._user_rank_lbl.setStyleSheet(
            "QLabel {"
            "  font-size: 9px;"
            "  font-weight: 800;"
            "  background: rgba(148, 163, 184, 0.1);"
            "  color: #cbd5e1;"
            "  padding: 1px 6px;"
            "  border-radius: 4px;"
            "  border: 1px solid rgba(148, 163, 184, 0.2);"
            "}"
        )
        self._user_rank_lbl.setMaximumHeight(20)
        self._user_rank_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        card_outer.addWidget(self._user_emoji_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        card_outer.addWidget(self._user_name_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._notif_container = QWidget()
        self._notif_container.setFixedSize(38, 26)
        self._notif_container.setVisible(False)
        self._notif_btn = QPushButton("🔔", self._notif_container)
        self._notif_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._notif_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._notif_btn.setGeometry(4, 1, 28, 24)
        self._notif_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; font-size: 15px; border-radius: 8px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.09); }"
        )
        self._notif_btn.setToolTip("Notifications compte (abonnements, annulations…)")
        self._notif_btn.clicked.connect(self._show_notifications_dialog)
        self._notif_badge = QLabel("", self._notif_container)
        self._notif_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._notif_badge.setStyleSheet(
            "QLabel { background: #ef4444; color: white; font-size: 9px; font-weight: 800; "
            "border-radius: 9px; padding: 1px 5px; min-height: 14px; }"
        )
        self._notif_badge.hide()
        self._notif_badge.raise_()

        card_outer.addWidget(self._notif_container, 0, Qt.AlignmentFlag.AlignVCenter)
        card_outer.addWidget(self._user_quota_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        card_outer.addWidget(self._user_rank_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        self._user_triple_anim_timer = QTimer(self)
        self._user_triple_anim_timer.timeout.connect(self._tick_user_triple_name_color)
        self._user_triple_anim_phase = 0
        self._user_triple_name_colors = (
            "#fcd34d",
            "#fbbf24",
            "#fb7185",
            "#f472b6",
            "#c084fc",
            "#818cf8",
            "#38bdf8",
            "#2dd4bf",
        )
        self._user_bar_widget.setVisible(False)

        self._news_ticker = LauncherNewsTicker()
        self._last_banner_key = None
        toggle_bar.addWidget(site_btn)
        toggle_bar.addWidget(discord_btn)
        toggle_bar.addWidget(self._news_ticker, 1)
        toggle_bar.addWidget(self._user_bar_widget)
        toggle_bar.addWidget(self._logout_btn)
        root_layout.addWidget(top_wrap)

        self._launcher_banner_payload.connect(self._apply_launcher_banner_payload)
        self._banner_poll_timer = QTimer(self)
        self._banner_poll_timer.setInterval(1100)
        self._banner_poll_timer.timeout.connect(self._poll_launcher_banner_tick)
        self._banner_poll_timer.start()
        QTimer.singleShot(350, self._poll_launcher_banner_tick)

        self._mandatory_update_poll_busy = False
        self._mandatory_update_timer = QTimer(self)
        self._mandatory_update_timer.setInterval(MANDATORY_UPDATE_POLL_INTERVAL_MS)
        self._mandatory_update_timer.timeout.connect(self._on_mandatory_update_poll)
        QTimer.singleShot(MANDATORY_UPDATE_FIRST_POLL_MS, self._on_mandatory_update_poll)
        self._mandatory_update_timer.start()

        # ── Classic tab UI (hidden by default — new UI is primary) ──
        self.tabs = QTabWidget()
        self.tabs.setVisible(False)
        root_layout.addWidget(self.tabs)

        # ── New Web UI (visible by default) ──
        self._web_view = QWebEngineView()
        # Évite une ancienne version de index.html / CSS servie depuis le cache WebEngine après mise à jour des fichiers locaux.
        try:
            self._web_view.page().profile().setHttpCacheType(
                QWebEngineProfile.HttpCacheType.NoCache
            )
        except Exception:
            pass
        root_layout.addWidget(self._web_view)
        self._web_channel = QWebChannel()
        from sff.gui.web_bridge import WebBridge
        self._web_bridge = WebBridge(ui=ui, steam_path=steam_path, parent=self)
        self._web_channel.registerObject("bridge", self._web_bridge)
        self._web_view.page().setWebChannel(self._web_channel)
        # Allow loading Steam CDN images from local file:// page
        self._web_view.page().settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self._web_ui_active = True
        self._web_ui_loaded = False
        self._authenticated = False       # set only after server-verified auth
        self._current_username = ""
        self._current_rank = "free"       # brut serveur ; affichage via launcher_rank_bucket
        self._profile_sync_timer: QTimer | None = None  # rafraîchit rang / free_claim depuis le serveur
        self._notif_items_cache: list = []
        main_tab_widget = QWidget()
        main_tab_layout = QVBoxLayout(main_tab_widget)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        scroll.setWidget(scroll_widget)
        main_tab_layout.addWidget(scroll, stretch=1)
        self.tabs.addTab(main_tab_widget, "Main")
        from sff.gui.help_buttons import add_help_button
        add_help_button(
            layout,
            "Main Hub",
            "SlimeDeals - Accueil\n\n"
            "Game / Path:\n"
            "  Select a Steam game from the dropdown or browse to a game\n"
            "  folder outside Steam. Used by all Game Actions below.\n\n"
            "Game Actions:\n"
            "  - Crack game (gbe_fork): Replace steam_api DLLs with Goldberg\n"
            "    Emulator so the game runs without Steam ownership.\n"
            "  - Remove SteamStub: Strip Valve's SteamStub DRM wrapper from\n"
            "    a game executable using Steamless.\n"
            "  - UserGameStats: Download achievement data for the selected game.\n"
            "  - DLC check: See which DLCs exist and which are unlocked.\n"
            "  - Workshop item: Download a Steam Workshop mod by ID.\n"
            "  - Open Workshop: Browse the Workshop for the selected game.\n"
            "  - Check mod updates: See if downloaded Workshop mods have\n"
            "    newer versions available.\n"
            "  - Multiplayer fix: apply integrated multiplayer patches.\n"
            "  - Fixes & Bypasses: Apply community-maintained fixes.\n"
            "  - DLC Unlockers: Manage CreamAPI / SmokeAPI / other DLC\n"
            "    unlocker DLLs for the selected game.\n"
            "  - SteamAutoCrack: Run the SteamAutoCrack CLI tool on the game.\n\n"
            "Lua / Manifest Processing:\n"
            "  - Download Games: Parse a .lua file and download all game\n"
            "    files (depots, manifests, ACF) to your Steam library.\n"
            "  - Download manifests only: Download just the .manifest files\n"
            "    without game content.\n"
            "  - Recent .lua files: Re-open a previously used .lua file.\n"
            "  - Update all manifests: Refresh manifests for all previously\n"
            "    downloaded games.\n\n"
            "Library & Steam Tools:\n"
            "  - Manage AppList Profiles: Create, switch, save, merge,\n"
            "    delete, or rename GreenLuma AppList profiles.\n"
            "  - Offline mode fix: Patch config.vdf so Steam starts in\n"
            "    offline mode reliably.\n"
            "  - Mute: Toggle background music on/off.\n"
            "  - Remove game from library: Remove a game's ACF and AppList entry.\n"
            "  - Context menu: Ajouter/supprimer SlimeDeals dans l Explorateur Windows\n"
            "    right-click menu.",
            parent_widget=self,
        )
        from sff.gui.store_tab import StoreTab
        from sff.gui.downloads_tab import DownloadsTab
        from sff.gui.fix_game_tab import FixGameTab
        from sff.gui.tools_tab import ToolsTab
        from sff.gui.cloud_saves_tab import CloudSavesTab
        from sff.download_manager import DownloadManager
        # Shared download manager — used by both the tracking tab and
        # the backend (process_lua_full) so downloads show up in the UI.
        self._download_manager = DownloadManager()
        self.ui.download_manager = self._download_manager
        self.store_tab = StoreTab(steam_path=steam_path, ui=self.ui, run_tool_fn=self._run_tool)
        self.tabs.addTab(self.store_tab, "Store")
        self.downloads_tab = DownloadsTab(download_manager=self._download_manager)
        self.tabs.addTab(self.downloads_tab, "Download Tracking")
        self.fix_game_tab = FixGameTab(steam_path=steam_path)
        self.tabs.addTab(self.fix_game_tab, "Fix Game")
        self.tools_tab = ToolsTab(steam_path)
        self.tabs.addTab(self.tools_tab, "Tools")
        self.cloud_saves_tab = CloudSavesTab(steam_path)
        self.tabs.addTab(self.cloud_saves_tab, "Cloud Saves")
        # ── Game / path ──────────────────────────────────────────
        path_group = QGroupBox(T("Game / path"))
        path_layout = QVBoxLayout(path_group)
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel(T("Path:")))
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(
            T("Game folder (for outside Steam) or leave empty for Steam games")
        )
        path_row.addWidget(self.path_edit)
        browse_btn = QPushButton("...")
        browse_btn.setFixedWidth(36)
        browse_btn.clicked.connect(self._browse_path)
        path_row.addWidget(browse_btn)
        path_layout.addLayout(path_row)
        source_row = QHBoxLayout()
        self.radio_steam = QRadioButton(T("Steam games"))
        self.radio_steam.setChecked(True)
        self.radio_outside = QRadioButton(T("Games outside of Steam"))
        self.radio_steam.toggled.connect(self._on_source_changed)
        self.radio_outside.toggled.connect(self._on_source_changed)
        source_row.addWidget(self.radio_steam)
        source_row.addWidget(self.radio_outside)
        source_row.addStretch()
        path_layout.addLayout(source_row)
        game_row = QHBoxLayout()
        game_row.addWidget(QLabel(T("Game:")))
        self.game_combo = GameComboBox()
        self.game_combo.setMinimumWidth(280)
        game_row.addWidget(self.game_combo)
        refresh_btn = QPushButton(T("Refresh list"))
        refresh_btn.clicked.connect(self._refresh_game_list)
        game_row.addWidget(refresh_btn)
        quick_cc_btn = QPushButton("Quick ColdClient")
        quick_cc_btn.setToolTip("Ouvre l'onglet Fix Game avec le mode ColdClient pré-rempli pour le jeu sélectionné")
        quick_cc_btn.clicked.connect(self._quick_coldclient)
        game_row.addWidget(quick_cc_btn)
        game_row.addStretch()
        path_layout.addLayout(game_row)
        outside_row = QHBoxLayout()
        self._outside_name_label = QLabel("Nom du jeu :")
        outside_row.addWidget(self._outside_name_label)
        self.outside_name_edit = QLineEdit()
        self.outside_name_edit.setPlaceholderText("For search (e.g. game or site name)")
        outside_row.addWidget(self.outside_name_edit)
        self._outside_appid_label = QLabel("App ID :")
        outside_row.addWidget(self._outside_appid_label)
        self.outside_appid_edit = QLineEdit()
        self.outside_appid_edit.setPlaceholderText("Optional")
        self.outside_appid_edit.setMaximumWidth(80)
        outside_row.addWidget(self.outside_appid_edit)
        outside_row.addStretch()
        path_layout.addLayout(outside_row)
        for w in (
            self._outside_name_label,
            self.outside_name_edit,
            self._outside_appid_label,
            self.outside_appid_edit,
        ):
            w.setVisible(False)
        layout.addWidget(path_group)
        # ── Game Actions (need selected game) ────────────────────
        game_actions_group = QGroupBox(T("Game Actions"))
        ga_layout = QVBoxLayout(game_actions_group)
        ga_layout.setSpacing(6)
        _TOOLTIPS = {
            T("Crack game (gbe_fork)"): "Remplace les DLLs steam_api par l'émulateur Goldberg pour jouer sans posséder le jeu sur Steam",
            T("Remove SteamStub (Steamless)"): "SteamStub est une protection Valve intégrée dans le .exe du jeu — elle vérifie que tu le possèdes sur Steam au lancement. Steamless la supprime directement de l'exécutable.",
            T("UserGameStats"): "Télécharge les données de succès et statistiques pour ce jeu",
            T("DLC check"): "Affiche les DLCs disponibles pour ce jeu et indique lesquels sont déjà déverrouillés",
            T("Workshop item"): "Télécharge un mod Steam Workshop en entrant son identifiant",
            T("Open Workshop"): "Ouvre le navigateur Steam Workshop pour ce jeu",
            T("Check mod updates"): "Vérifie si les mods Workshop téléchargés ont des mises à jour disponibles",
            T("Multiplayer fix"): "Applique les patches multijoueur en ligne — compte préconfiguré dans le launcher, aucune saisie",
            T("Fixes & Bypasses"): "Applique des correctifs et contournements maintenus par la communauté",
            T("DLC Unlockers"): "Gère les DLLs de déverrouillage DLC : CreamAPI, SmokeAPI et autres",
            T("SteamAutoCrack"): "Lance l'outil SteamAutoCrack en ligne de commande sur ce jeu",
        }
        row1 = QHBoxLayout()
        row1.setSpacing(4)
        for label, choice in [
            (T("Crack game (gbe_fork)"), MainMenu.CRACK_GAME),
            (T("Remove SteamStub (Steamless)"), MainMenu.REMOVE_DRM),
            (T("UserGameStats"), MainMenu.DL_USER_GAME_STATS),
            (T("DLC check"), MainMenu.DLC_CHECK),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(_TOOLTIPS.get(label, ""))
            btn.clicked.connect(lambda checked=False, c=choice: self._run_game_action(c))
            row1.addWidget(btn)
        row1.addStretch()
        ga_layout.addLayout(row1)
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        for label, choice in [
            (T("Workshop item"), MainMenu.DL_WORKSHOP_ITEM),
            (T("Open Workshop"), None),
            (T("Check mod updates"), MainMenu.CHECK_MOD_UPDATES),
            (T("Multiplayer fix"), MainMenu.MULTIPLAYER_FIX),
            (T("Fixes & Bypasses"), MainMenu.CRACK_FIX),
            (T("HyperVisor (HVAuto)"), MainMenu.HV_FIX),
            (T("DLC Unlockers"), MainMenu.MANAGE_DLC_UNLOCKERS),
            (T("SteamAutoCrack"), None),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(_TOOLTIPS.get(label, ""))
            if choice is not None:
                btn.clicked.connect(lambda checked=False, c=choice: self._run_game_action(c))
            elif label == T("SteamAutoCrack"):
                btn.clicked.connect(self._run_steam_auto_gui)
            else:
                btn.clicked.connect(self._open_workshop)
            row2.addWidget(btn)
        row2.addStretch()
        ga_layout.addLayout(row2)
        layout.addWidget(game_actions_group)
        # ── Lua / Manifest Processing ────────────────────────────
        lua_group = QGroupBox(T("Lua / Manifest Processing"))
        lua_layout = QVBoxLayout(lua_group)
        lua_row = QHBoxLayout()
        for label, func in [
            (T("Download Games"), lambda: self.ui.process_lua_full()),
            (T("Download manifests only"), lambda: self.ui.process_lua_minimal()),
            (T("Recent .lua files"), lambda: self.ui.recent_files_menu()),
            (T("Update all manifests"), lambda: self.ui.update_all_manifests()),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked=False, f=func: self._run_tool(f))
            lua_row.addWidget(btn)
        lua_row.addStretch()
        lua_layout.addLayout(lua_row)
        layout.addWidget(lua_group)
        # ── Library & Steam Tools ────────────────────────────────
        tools_group = QGroupBox(T("Library & Steam Tools"))
        tools_layout = QVBoxLayout(tools_group)
        tools_row1 = QHBoxLayout()
        for label, func in [
            (T("Manage AppList Profiles"), lambda: self.ui.applist_menu()),
            (T("Offline mode fix"), lambda: self.ui.offline_fix_menu()),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked=False, f=func: self._run_tool(f))
            tools_row1.addWidget(btn)
        self._mute_btn = QPushButton("Muet")
        self._mute_btn.clicked.connect(self._toggle_mute)
        tools_row1.addWidget(self._mute_btn)
        tools_row1.addStretch()
        tools_layout.addLayout(tools_row1)
        if sys.platform == "win32":
            tools_row2 = QHBoxLayout()
            for label, func in [
                (T("Remove game from library"), lambda: self.ui.remove_game_menu()),
                (T("Context menu"), lambda: self.ui.manage_context_menu()),
            ]:
                btn = QPushButton(label)
                btn.clicked.connect(lambda checked=False, f=func: self._run_tool(f))
                tools_row2.addWidget(btn)
            tools_row2.addStretch()
            tools_layout.addLayout(tools_row2)
        layout.addWidget(tools_group)
        # ── Log ──────────────────────────────────────────────────
        log_group = QGroupBox(T("Log"))
        log_layout = QVBoxLayout(log_group)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(160)
        log_layout.addWidget(self.log_text)
        clear_btn = QPushButton(T("Clear log"))
        clear_btn.clicked.connect(self.log_text.clear)
        log_layout.addWidget(clear_btn)
        layout.addWidget(log_group)
        # ── Menu bar ─────────────────────────────────────────────
        menubar = self.menuBar()
        settings_action = menubar.addAction(T("Settings"))
        settings_action.triggered.connect(self._show_settings)
        theme_menu = menubar.addMenu(T("Theme"))
        for key, (name, _) in THEMES.items():
            action = theme_menu.addAction(name)
            action.triggered.connect(lambda checked=False, k=key: self._set_theme(k))
        help_menu = menubar.addMenu(T("Help"))
        help_menu.addAction(T("About")).triggered.connect(self._show_about)
        help_menu.addAction(T("Check for updates")).triggered.connect(
            lambda: self._run_tool(lambda: self.ui.check_updates(self.ui.os_type))
        )
        help_menu.addAction(T("Scan game library")).triggered.connect(
            lambda: self._run_tool(lambda: self.ui.scan_library_menu())
        )
        help_menu.addAction(T("Analytics dashboard")).triggered.connect(
            lambda: self._run_tool(lambda: self.ui.analytics_dashboard_menu())
        )
        logs_action = menubar.addAction("Logs")
        logs_action.triggered.connect(self._show_log_window)
        self._stream_emitter.text_written.connect(self._append_log)
        # Only persist the Qt fallback theme if there was no saved theme or the saved
        # theme is a known Qt theme. Web-only themes (photo themes, extra color themes)
        # are not in THEMES but must not be overwritten here.
        _should_save = _saved_theme is None or _saved_theme in THEMES
        self._set_theme(self._current_theme, save=_should_save)
        self._on_source_changed()
        self._refresh_game_list()
        # Start with new web UI by default — hide menu bar
        menubar.setVisible(False)
        self._web_ui_loaded = False
        # ── Auth check ──
        QTimer.singleShot(0, self._start_auth_check)
        self._tray = None
        self._save_watcher_timer = QTimer(self)
        self._save_watcher_timer.timeout.connect(self._run_background_save_watcher)
        self._start_save_watcher()

    # ── Path / game source helpers ───────────────────────────────

    def _browse_path(self):
        path = QFileDialog.getExistingDirectory(self, "Select game folder")
        if path:
            self.path_edit.setText(path)
            if self.radio_outside.isChecked() and not self.outside_name_edit.text().strip():
                self.outside_name_edit.setText(Path(path).name)

    def _on_source_changed(self):
        from_steam = self.radio_steam.isChecked()
        self.game_combo.setEnabled(from_steam)
        self.path_edit.setEnabled(not from_steam)
        for w in (
            self._outside_name_label,
            self.outside_name_edit,
            self._outside_appid_label,
            self.outside_appid_edit,
        ):
            w.setVisible(not from_steam)

    def _refresh_game_list(self):
        from sff.game_specific import GameHandler
        from sff.storage.vdf import get_steam_libs
        self.game_combo.clear()
        self._game_list = []
        injection = self.ui.app_list_man or self.ui.sls_man
        if not injection:
            self.game_combo.addItem("(Unsupported on this OS)", None)
            return
        steam_libs = get_steam_libs(self.steam_path)
        lib_path = steam_libs[0] if steam_libs else self.steam_path
        handler = GameHandler(self.steam_path, lib_path, self.ui.provider, injection)
        self._game_list = handler.get_game_list()
        if not self._game_list:
            self.game_combo.addItem("(No games found)", None)
            return
        for name, acf in self._game_list:
            self.game_combo.addItem(name, acf)

    def _quick_coldclient(self):
        """Switch to Fix Game tab with ColdClient mode pre-filled from the selected game."""
        from sff.fix_game.service import EmuMode
        acf = self._get_selected_acf()
        if acf is None:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No Game Selected",
                                "Please select a game from the dropdown first.")
            return
        game_path = str(getattr(acf, "path", "") or "")
        app_id = str(getattr(acf, "app_id", "") or "")
        self.fix_game_tab.prefill(game_path, app_id, EmuMode.COLDCLIENT_SIMPLE)
        # switch to Fix Game tab
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "Fix Game":
                self.tabs.setCurrentIndex(i)
                break

    def _get_selected_acf(self):
        from sff.game_specific import ACFInfo
        if self.radio_steam.isChecked():
            return self.game_combo.currentData()
        path_str = self.path_edit.text().strip()
        if not path_str:
            return None
        path = Path(path_str).resolve()
        if not path.is_dir():
            return None
        name = self.outside_name_edit.text().strip() or path.name
        app_id = self.outside_appid_edit.text().strip() or "0"
        return ACFInfo(app_id, path)

    # ── Web UI toggle ────────────────────────────────────────────

    def _toggle_web_ui(self):
        """Toggle between classic tab UI and new web-based UI."""
        self._web_ui_active = not self._web_ui_active

        if self._web_ui_active:
            # Load web UI on first use
            if not self._web_ui_loaded:
                self._load_web_ui()
                self._web_ui_loaded = True
            self.tabs.setVisible(False)
            self._web_view.setVisible(True)
            self.menuBar().setVisible(False)
        else:
            self.tabs.setVisible(True)
            self._web_view.setVisible(False)
            self.menuBar().setVisible(True)

    def _get_webui_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys._MEIPASS) / "sff" / "webui"
        # Même dossier que le paquet `sff` réellement importé (évite une autre copie du dépôt sur le PATH).
        import sff as _sff_pkg

        return Path(_sff_pkg.__file__).resolve().parent / "webui"

    def _load_web_ui(self):
        """Load index.html into the QWebEngineView."""
        index_path = self._get_webui_dir() / "index.html"
        if index_path.exists():
            try:
                ver = int(index_path.stat().st_mtime)
            except OSError:
                ver = 0
            resolved = str(index_path.resolve())
            url = QUrl.fromLocalFile(resolved)
            url.setQuery(f"v={ver}")
            self._web_view.setUrl(url)
        else:
            import logging
            logging.getLogger(__name__).error("Web UI not found at %s", index_path)

    def _load_auth_page(self):
        """Show the login/register page."""
        auth_path = self._get_webui_dir() / "auth.html"
        if auth_path.exists():
            try:
                ver = int(auth_path.stat().st_mtime)
            except OSError:
                ver = 0
            url = QUrl.fromLocalFile(str(auth_path.resolve()))
            url.setQuery(f"v={ver}")
            self._web_view.setUrl(url)
        else:
            import logging
            logging.getLogger(__name__).error("Auth page not found at %s", auth_path)

    def _start_auth_check(self):
        """Always show the auth page first; the page JS calls auth_check_saved()."""
        self._load_auth_page()

    def _user_name_btn_style(self, color: str, font_weight: str = "700") -> None:
        self._user_name_btn.setStyleSheet(
            "QPushButton { font-size: 13px; font-weight: %s; border: none; background: transparent; "
            "padding: 0; color: %s; text-align: left; }"
            "QPushButton:hover { text-decoration: underline; color: #ffffff; }"
            % (font_weight, color)
        )

    def _stop_user_triple_anim(self) -> None:
        self._user_triple_anim_timer.stop()

    def _tick_user_triple_name_color(self) -> None:
        colors = self._user_triple_name_colors
        c = colors[self._user_triple_anim_phase % len(colors)]
        self._user_triple_anim_phase += 1
        self._user_name_btn.setStyleSheet(
            "QPushButton { font-size: 13px; font-weight: 800; border: none; background: transparent; "
            "padding: 0; color: %s; text-align: left; }"
            "QPushButton:hover { text-decoration: underline; }"
            % (c,)
        )

    def _user_bar_quota_text(self, rank: str) -> str:
        """Compteur jeux distincts : Monstre / 24H PASS / Triple (illimite)."""
        from sff.launcher_ranks import launcher_rank_bucket, paid_install_slot_cap_for_bucket
        from sff.premium_manifest_lock import paid_distinct_game_count_for_steam

        bucket = launcher_rank_bucket(rank)
        cap = paid_install_slot_cap_for_bucket(bucket)
        sp = getattr(self, "steam_path", None)
        if bucket == "triple":
            u = paid_distinct_game_count_for_steam(sp) if sp else 0
            return f"{u}/illimité"
        if cap is not None and bucket in ("monstre", "pass24h"):
            u = paid_distinct_game_count_for_steam(sp) if sp else 0
            return f"{u}/{cap}"
        return ""

    def _set_user_bar_display(self, username: str, rank: str) -> None:
        """Barre du haut : pseudo + quota jeux + rang FREE / 24H PASS / MONSTRE / TRIPLE MONSTRE."""
        from sff.launcher_ranks import launcher_rank_bucket

        self._stop_user_triple_anim()
        name = username or ""
        bucket = launcher_rank_bucket(rank)
        self._user_name_btn.setText(name)

        quota_txt = self._user_bar_quota_text(rank)
        self._user_quota_lbl.setText(quota_txt)
        self._user_quota_lbl.setVisible(bool(quota_txt))
        if quota_txt:
            self._user_quota_lbl.setStyleSheet(
                "QLabel { font-size: 9px; font-weight: 700; background: rgba(148, 163, 184, 0.12); "
                "color: #e2e8f0; padding: 1px 6px; border-radius: 4px; "
                "border: 1px solid rgba(148, 163, 184, 0.22); }"
            )

        if bucket == "free":
            self._user_bar_widget.setToolTip(
                "Plan FREE — 1 jeu au choix parmi le catalogue (onglet Télécharger)"
            )
            self._user_name_btn_style("#4ade80")
            self._user_rank_lbl.setText("FREE")
            self._user_rank_lbl.setStyleSheet(
                "QLabel { font-size: 9px; font-weight: 800; background: rgba(74, 222, 128, 0.16); "
                "color: #bbf7d0; padding: 1px 6px; border-radius: 4px; "
                "border: 1px solid rgba(74, 222, 128, 0.35); letter-spacing: 0.04em; }"
            )
        elif bucket == "triple":
            self._user_bar_widget.setToolTip(
                "TRIPLE MONSTRE — palier le plus haut : jeux Steam illimites au choix "
                "(recherche par lien dans Telecharger). Online FIX, ROCKSTAR BYPASS et sauvegardes cloud."
            )
            self._user_triple_anim_phase = 0
            self._tick_user_triple_name_color()
            self._user_triple_anim_timer.start(420)
            self._user_rank_lbl.setText("TRIPLE MONSTRE")
            self._user_rank_lbl.setStyleSheet(
                "QLabel { font-size: 9px; font-weight: 800; background: rgba(196, 181, 253, 0.18); "
                "color: #ede9fe; padding: 1px 6px; border-radius: 4px; "
                "border: 1px solid rgba(167, 139, 250, 0.4); letter-spacing: 0.06em; }"
            )
        elif bucket == "pass24h":
            self._user_bar_widget.setToolTip(
                "24H PASS — jusqu'a 8 jeux distincts sur ce PC via le launcher "
                "(reinstaller un jeu deja en liste ne consomme pas de slot). "
                "Pas d'Online FIX, pas de ROCKSTAR BYPASS ni sauvegardes cloud (reserves au Triple Monstre)."
            )
            self._user_name_btn_style("#5eead4")
            self._user_rank_lbl.setText("24H PASS")
            self._user_rank_lbl.setStyleSheet(
                "QLabel { font-size: 9px; font-weight: 800; background: rgba(45, 212, 191, 0.16); "
                "color: #99f6e4; padding: 1px 6px; border-radius: 4px; "
                "border: 1px solid rgba(45, 212, 191, 0.38); letter-spacing: 0.05em; }"
            )
        else:
            # bucket == "monstre" (ou rang payant non reconnu, traite comme Monstre)
            self._user_bar_widget.setToolTip(
                "MONSTRE — jusqu'a 10 jeux distincts sur ce PC via le launcher "
                "(reinstaller un jeu deja en liste ne consomme pas de slot). "
                "Pas d'Online FIX ni ROCKSTAR BYPASS (reserves au Triple Monstre). Pas de sauvegardes cloud."
            )
            self._user_name_btn_style("#fdba74")
            self._user_rank_lbl.setText("MONSTRE")
            self._user_rank_lbl.setStyleSheet(
                "QLabel { font-size: 9px; font-weight: 800; background: rgba(251, 146, 60, 0.16); "
                "color: #fed7aa; padding: 1px 6px; border-radius: 4px; "
                "border: 1px solid rgba(251, 146, 60, 0.38); letter-spacing: 0.04em; }"
            )

    def _on_auth_success(self, username: str, rank: str = "free"):
        """Called ONLY from WebBridge.auth_success after server verification.
        Never call this directly — auth must go through the verified bridge path."""
        import logging as _log
        _log.getLogger(__name__).info(
            "[Auth] Accès accordé pour : %s (rang=%s)", username, rank
        )
        self._authenticated = True
        self._current_username = username
        self._current_rank = rank or "free"
        # Show user info + logout button in top bar (rang visible à droite, avant Déconnexion)
        self._set_user_bar_display(username, self._current_rank)
        self._user_bar_widget.setVisible(True)
        self._notif_container.setVisible(True)
        self._logout_btn.setVisible(True)
        self._load_web_ui()
        self._web_ui_loaded = True
        if self._profile_sync_timer is None:
            self._profile_sync_timer = QTimer(self)
            self._profile_sync_timer.setInterval(90_000)
            self._profile_sync_timer.timeout.connect(self._on_profile_sync_tick)
        if not self._profile_sync_timer.isActive():
            self._profile_sync_timer.start()
        QTimer.singleShot(2500, self._on_profile_sync_tick)
        QTimer.singleShot(900, self._refresh_launcher_notifications)

    def _on_profile_sync_tick(self) -> None:
        if self._authenticated and getattr(self, "_web_bridge", None):
            self._web_bridge.sync_launcher_profile()
        self._refresh_launcher_notifications()

    def _apply_rank_from_server(self, username: str, rank: str) -> None:
        """Après un /verify : met à jour la barre du haut sans recharger la page web."""
        if not self._authenticated:
            return
        if username:
            self._current_username = username
        self._current_rank = rank or "free"
        self._set_user_bar_display(self._current_username, self._current_rank)

    def _show_account_profile_dialog(self) -> None:
        """Profil compte + lien portail Stripe pour abonnements payants."""
        from datetime import datetime

        from sff.gui.web_bridge import _load_auth, launcher_fetch_billing_portal
        from sff.launcher_ranks import launcher_rank_bucket

        auth = _load_auth()
        uname = (self._current_username or auth.get("username") or "").strip()
        rank = self._current_rank or auth.get("rank") or "free"
        bucket = launcher_rank_bucket(rank)
        plan_labels = {
            "free": "Gratuit (catalogue)",
            "triple": "Triple Monstre",
            "pass24h": "Pass 24 h",
            "monstre": "Monstre",
        }
        plan_human = plan_labels.get(bucket, str(rank))
        re_raw = auth.get("rank_expires_at")
        exp_line = ""
        if re_raw is not None and str(re_raw).strip() != "":
            try:
                ts = int(re_raw)
                if ts > 0:
                    exp_line = datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")
            except (TypeError, ValueError, OSError):
                exp_line = ""

        dlg = QDialog(self)
        dlg.setWindowTitle("Mon compte SlimeDeals")
        lay = QVBoxLayout(dlg)

        body_html = (
            f"<p style='margin-bottom:12px;'><b>Pseudo</b><br>{uname}</p>"
            f"<p style='margin-bottom:12px;'><b>Palier</b><br>{plan_human}</p>"
        )
        info = QLabel(body_html)
        info.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(info)

        if bucket == "free" and auth.get("free_claimed"):
            fc = QLabel(
                f"<p><b>Jeu catalogue Free</b><br>App ID <code>{auth.get('free_claimed')}</code></p>"
            )
            fc.setTextFormat(Qt.TextFormat.RichText)
            lay.addWidget(fc)

        quota = self._user_bar_quota_text(rank)
        if quota:
            ql = QLabel(f"<p><b>Jeux distincts sur ce PC</b><br>{quota}</p>")
            ql.setTextFormat(Qt.TextFormat.RichText)
            lay.addWidget(ql)

        if exp_line:
            el = QLabel(f"<p><b>Fin de période affichée (rang)</b><br>{exp_line}</p>")
            el.setTextFormat(Qt.TextFormat.RichText)
            lay.addWidget(el)

        hint = QLabel(
            "Avec un abonnement payé via Stripe, ouvre le portail ci-dessous pour la carte, "
            "les factures ou l’arrêt du renouvellement."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #94a3b8; font-size: 12px;")
        lay.addWidget(hint)

        btn_row = QHBoxLayout()
        portal_btn = QPushButton("Gérer mon abonnement (Stripe)…")
        portal_btn.setToolTip("Ouvre le portail client Stripe dans le navigateur")
        close_btn = QPushButton("Fermer")
        btn_row.addWidget(portal_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        def _open_portal() -> None:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                out = launcher_fetch_billing_portal()
            finally:
                QApplication.restoreOverrideCursor()
            if not out.get("ok"):
                QMessageBox.warning(
                    dlg,
                    "Portail Stripe",
                    (out.get("error") or "Impossible de contacter le serveur."),
                )
                return
            if not out.get("has_portal"):
                QMessageBox.information(
                    dlg,
                    "Abonnement",
                    "Aucun paiement Stripe n’est lié à ce compte logiciel.\n\n"
                    "Si ton palier vient d’une invitation Discord ou d’une offre sans carte bancaire ici, "
                    "il n’y a pas de portail de facturation.",
                )
                return
            url = (out.get("url") or "").strip()
            if url.startswith("http"):
                QDesktopServices.openUrl(QUrl(url))

        portal_btn.clicked.connect(_open_portal)
        close_btn.clicked.connect(dlg.accept)

        dlg.resize(440, 360)
        dlg.exec()

    def _update_notif_badge(self, n: int) -> None:
        if n <= 0:
            self._notif_badge.clear()
            self._notif_badge.hide()
            return
        txt = "9+" if n > 9 else str(n)
        self._notif_badge.setText(txt)
        self._notif_badge.adjustSize()
        self._notif_badge.show()
        x = self._notif_container.width() - self._notif_badge.width() + 4
        self._notif_badge.move(max(10, x), -4)
        self._notif_badge.raise_()

    def _refresh_launcher_notifications(self) -> None:
        if not getattr(self, "_authenticated", False):
            return
        try:
            from sff.launcher_session import fetch_launcher_notifications

            data = fetch_launcher_notifications()
        except Exception as exc:
            logging.getLogger(__name__).debug("notifications: %s", exc)
            return
        if not data.get("ok"):
            return
        self._notif_items_cache = data.get("items") or []
        unread = data.get("unread")
        if unread is None:
            unread = sum(1 for x in self._notif_items_cache if not x.get("read"))
        self._update_notif_badge(int(unread))

    def _format_notif_time(self, iso_s: str) -> str:
        if not iso_s:
            return ""
        s = str(iso_s).strip()
        try:
            from datetime import datetime

            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return s[:16]

    def _show_notifications_dialog(self) -> None:
        self._refresh_launcher_notifications()
        dlg = QDialog(self)
        dlg.setWindowTitle("Notifications SlimeDeals")
        dlg.setMinimumSize(520, 400)
        lay = QVBoxLayout(dlg)

        intro = QLabel(
            "Ici tu retrouves les alertes liées à ton compte : merci après un achat, annulation programmée, "
            "fin d’abonnement ou échec de paiement. Clique <b>Lu</b> pour faire disparaître le point rouge."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setStyleSheet("color:#cbd5e1;font-size:12px;margin-bottom:4px;")
        lay.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_l = QVBoxLayout(inner)
        inner_l.setSpacing(10)
        items = list(self._notif_items_cache or [])
        unread_ids: list[int] = []

        if not items:
            empty = QLabel("Aucune notification pour le moment.")
            empty.setStyleSheet("color:#94a3b8;padding:28px;")
            inner_l.addWidget(empty)
        else:
            for it in items:
                if not it.get("read"):
                    try:
                        unread_ids.append(int(it["id"]))
                    except (TypeError, KeyError, ValueError):
                        pass
                card = QFrame()
                is_unread = not it.get("read")
                border_c = "rgba(165,233,1,0.35)" if is_unread else "rgba(148,163,184,0.18)"
                card.setStyleSheet(
                    f"QFrame {{ background: rgba(22,18,32,0.95); border:1px solid {border_c}; "
                    "border-radius:12px; padding: 2px; }}"
                )
                cv = QVBoxLayout(card)
                head = QHBoxLayout()
                title_l = QLabel(f"<span style='font-weight:800;font-size:13px;'>{html_escape(it.get('title') or '')}</span>")
                title_l.setTextFormat(Qt.TextFormat.RichText)
                head.addWidget(title_l, 1)
                when = self._format_notif_time(it.get("created_at") or "")
                if when:
                    wh = QLabel(when)
                    wh.setStyleSheet("color:#64748b;font-size:11px;")
                    head.addWidget(wh, 0, Qt.AlignmentFlag.AlignRight)
                cv.addLayout(head)
                body_raw = (it.get("body") or "").replace("**", "")
                body_l = QLabel()
                body_l.setPlainText(body_raw)
                body_l.setWordWrap(True)
                body_l.setStyleSheet("color:#e2e8f0;font-size:12px;")
                cv.addWidget(body_l)
                btn_row = QHBoxLayout()
                btn_row.addStretch()
                mark_btn = QPushButton("Lu ✓" if is_unread else "Déjà lu")
                mark_btn.setEnabled(is_unread)
                mark_btn.setToolTip("Marquer comme lu et retirer du compteur rouge")

                def _make_mark(nid: int, button: QPushButton) -> None:
                    def _go() -> None:
                        from sff.launcher_session import mark_launcher_notifications_read

                        out = mark_launcher_notifications_read([nid])
                        if out.get("ok"):
                            button.setText("Déjà lu")
                            button.setEnabled(False)
                            card.setStyleSheet(
                                "QFrame { background: rgba(22,18,32,0.95); border:1px solid rgba(148,163,184,0.18); "
                                "border-radius:12px; padding: 2px; }"
                            )
                            self._refresh_launcher_notifications()
                        else:
                            QMessageBox.warning(
                                dlg,
                                "Notifications",
                                out.get("error") or "Impossible de mettre à jour.",
                            )

                    return _go

                mark_btn.clicked.connect(_make_mark(int(it["id"]), mark_btn))
                btn_row.addWidget(mark_btn)
                cv.addLayout(btn_row)
                inner_l.addWidget(card)

        inner_l.addStretch()
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        foot = QHBoxLayout()
        close_all = QPushButton("Fermer")
        mark_all = QPushButton("Tout marquer comme lu")
        mark_all.setEnabled(bool(unread_ids))
        foot.addWidget(mark_all)
        foot.addStretch()
        foot.addWidget(close_all)
        lay.addLayout(foot)

        def _mark_all() -> None:
            from sff.launcher_session import mark_launcher_notifications_read

            if not unread_ids:
                return
            out = mark_launcher_notifications_read(unread_ids)
            if out.get("ok"):
                self._refresh_launcher_notifications()
                dlg.accept()
            else:
                QMessageBox.warning(dlg, "Notifications", out.get("error") or "Erreur serveur.")

        mark_all.clicked.connect(_mark_all)
        close_all.clicked.connect(dlg.accept)
        dlg.exec()

    def _on_mandatory_update_poll(self):
        """Revérifie GitHub toutes les 5 min (premier passage ~10 s après ouverture de la fenêtre)."""
        import sys

        from sff.mandatory_update_gui import (
            run_mandatory_version_gate_if_outdated,
            update_disabled_by_env,
        )

        if sys.platform != "win32" or update_disabled_by_env():
            return
        if self._mandatory_update_poll_busy:
            return
        self._mandatory_update_poll_busy = True
        try:
            run_mandatory_version_gate_if_outdated(self)
        finally:
            self._mandatory_update_poll_busy = False

    def _poll_launcher_banner_tick(self):
        import threading

        def work():
            try:
                from sff.launcher_session import fetch_launcher_banner

                data = fetch_launcher_banner()
            except Exception:
                data = None
            self._launcher_banner_payload.emit(data)

        threading.Thread(target=work, daemon=True).start()

    def _apply_launcher_banner_payload(self, d):
        if d is None:
            return
        if not isinstance(d, dict):
            return
        if d.get("rev") is None:
            return
        try:
            rev = int(d["rev"])
        except (TypeError, ValueError):
            return
        if rev < 0:
            return
        text = str(d.get("text") or "")
        key = (rev, text)
        if key == self._last_banner_key:
            return
        self._last_banner_key = key
        self._news_ticker.set_message(text)

    def _do_logout(self):
        """Disconnect the user: wipe saved token and return to login page."""
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Déconnexion",
            "Se déconnecter de SlimeDeals ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self._profile_sync_timer is not None and self._profile_sync_timer.isActive():
            self._profile_sync_timer.stop()
        # Wipe saved auth
        from sff.gui.web_bridge import _clear_auth
        _clear_auth()
        self._authenticated = False
        self._current_username = ""
        self._current_rank = "free"
        # Hide user info
        self._stop_user_triple_anim()
        self._user_bar_widget.setVisible(False)
        self._user_name_btn.setText("")
        self._user_quota_lbl.setText("")
        self._user_quota_lbl.setVisible(False)
        self._user_rank_lbl.setText("")
        self._user_bar_widget.setToolTip("")
        self._notif_container.setVisible(False)
        self._update_notif_badge(0)
        self._notif_items_cache = []
        self._logout_btn.setVisible(False)
        # Return to auth page
        self._web_ui_loaded = False
        self._load_auth_page()

    # ── Worker management ────────────────────────────────────────

    def _start_worker(self, func, label: str = "action", on_done=None):
        if self._worker_thread is not None and self._worker_thread.isRunning():
            QMessageBox.information(self, "Busy", "An action is already running.")
            return
        self._append_log(f"\n--- Running: {label} ---\n")
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = self._stream_emitter  # type: ignore[assignment]
        sys.stderr = self._stream_emitter  # type: ignore[assignment]
        self._worker = GenericWorker(func)
        self._worker_thread = QThread()
        self._worker.moveToThread(self._worker_thread)
        def _on_finish(_result):
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            if self._worker_thread:
                self._worker_thread.quit()
                self._worker_thread.wait()
            self._worker_thread = None
            self._worker = None
            self._append_log(f"--- Done: {label} ---\n")
            if on_done:
                on_done()
        self._worker.finished.connect(_on_finish)
        self._worker.error.connect(lambda msg: self._append_log(f"Error: {msg}\n"))
        self._worker_thread.started.connect(self._worker.run)
        self._worker_thread.start()

    def _open_workshop(self):
        acf = self._get_selected_acf()
        if acf is None:
            QMessageBox.warning(
                self,
                "No game selected",
                "Select a Steam game from the list or set a path for a game outside of Steam.",
            )
            return
        app_id = acf.app_id
        if not app_id:
            QMessageBox.warning(self, "No app ID", "Could not determine the game's App ID.")
            return
        from sff.gui.workshop_browser import open_workshop_browser
        open_workshop_browser(app_id, self)

    def _run_game_action(self, choice):
        from sff.structs import MainMenu
        acf = self._get_selected_acf()
        if acf is None:
            QMessageBox.warning(
                self,
                "No game selected",
                "Select a Steam game from the list or set a path for a game outside of Steam.",
            )
            return
        label = str(getattr(choice, "value", choice))
        # Steamless: ask user to pick the exe directly so we never touch the Steam API
        # on a background thread (that's what causes WinError 2)
        if choice == MainMenu.REMOVE_DRM:
            exe_path_str, _ = QFileDialog.getOpenFileName(
                self,
                "Select game executable",
                str(acf.path),
                "Executables (*.exe)",
            )
            if not exe_path_str:
                return
            exe_path = Path(exe_path_str)
            self._start_worker(
                lambda: self.ui.run_steamless_direct(acf, exe_path), label
            )
            return
        self._start_worker(
            lambda: self.ui.run_game_action_with_selection(choice, acf), label
        )

    def _run_steam_auto_gui(self):
        from sff.steamauto import get_steamauto_cli_path, run_steamauto
        if get_steamauto_cli_path() is None:
            QMessageBox.critical(
                self,
                "SteamAutoCrack not found",
                "SteamAutoCrack CLI is missing. Place the Steam-auto-crack repo in "
                "third_party/SteamAutoCrack and build the CLI into third_party/SteamAutoCrack/cli/.",
            )
            return
        acf = self._get_selected_acf()
        if acf is None:
            QMessageBox.warning(
                self,
                "No game selected",
                "Select a Steam game from the list or set a path for a game outside of Steam.",
            )
            return
        game_path = acf.path
        app_id = acf.app_id or "0"
        def _job():
            run_steamauto(game_path, app_id, print_func=print)
        self._start_worker(_job, label="SteamAutoCrack")

    def _run_steam_auto_with_acf(self, acf):
        """Web UI entry point — ACF already resolved, runs on main thread via _start_worker."""
        import json
        from sff.steamauto import run_steamauto
        game_path = acf.path
        app_id = acf.app_id or "0"
        def _job():
            run_steamauto(game_path, app_id, print_func=print)
        def _done():
            if hasattr(self, '_web_bridge') and self._web_bridge:
                self._web_bridge.task_finished.emit(json.dumps({
                    "task": "steam_auto", "success": True,
                    "message": "SteamAutoCrack completed"
                }))
        self._start_worker(_job, label="SteamAutoCrack", on_done=_done)

    def _run_tool(self, func):
        label = getattr(func, "__name__", "tool")
        self._start_worker(func, label)

    # ── Log ──────────────────────────────────────────────────────

    def _show_log_window(self):
        self._log_window.show()
        self._log_window.raise_()
        self._log_window.activateWindow()

    def _append_log(self, text):
        text = _ANSI_RE.sub("", text)
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)
        self.log_text.insertPlainText(text)
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)

    # ── Theme ────────────────────────────────────────────────────

    def _set_theme(self, key, save=True):
        self._current_theme = key
        _, style = THEMES[key]
        self.setStyleSheet(style)
        self.game_combo._update_arrow()
        if save:
            from sff.storage.settings import set_setting
            from sff.structs import Settings as _S
            set_setting(_S.THEME, key)

    # ── Log forwarding to web UI ────────────────────────────────

    def _forward_log_to_web(self, levelno: int, html: str):
        """Forward log records to the web bridge so the web UI log panel shows them."""
        if hasattr(self, '_web_bridge') and self._web_bridge:
            import logging
            lvl = 'INFO'
            if levelno <= logging.DEBUG:
                lvl = 'DEBU'
            elif levelno <= logging.INFO:
                lvl = 'INFO'
            elif levelno <= logging.WARNING:
                lvl = 'WARN'
            else:
                lvl = 'ERRO'
            # Strip HTML tags for the web UI (it applies its own formatting)
            import re
            text = re.sub(r'<[^>]+>', '', html).strip()
            # Remove the leading HH:MM:SS timestamp already embedded by QtLogHandler
            # to avoid double-timestamps when the JS log panel adds its own.
            text = re.sub(r'^\d{2}:\d{2}:\d{2}\s*', '', text)
            self._web_bridge.log_message.emit(text)

    def _forward_stdout_to_web(self, text: str):
        """Forward _stream_emitter stdout lines to the web UI log panel."""
        if hasattr(self, '_web_bridge') and self._web_bridge:
            text = _ANSI_RE.sub("", text).strip()
            if text:
                self._web_bridge.log_message.emit(f'[INFO] {text}')

    # ── Music mute ───────────────────────────────────────────────

    def _toggle_mute(self):
        if self.ui.midi_player is None:
            return
        self._music_muted = not self._music_muted
        self.ui.midi_player.set_muted(self._music_muted)
        self._mute_btn.setText("Unmute" if self._music_muted else "Mute")

    # ── Settings dialog ──────────────────────────────────────────

    def _show_settings(self):
        from sff.storage.settings import (
            clear_setting,
            export_settings,
            get_setting,
            import_settings,
            load_all_settings,
            set_setting,
        )
        from sff.structs import SettingCustomTypes, Settings
        dlg = QDialog(self)
        dlg.setWindowTitle("Paramètres")
        dlg.setMinimumSize(620, 500)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Double-clic pour modifier. Sélectionne et appuie sur Suppr pour effacer."))
        win_only = {Settings.APPLIST_FOLDER, Settings.GL_VERSION}
        linux_only = {Settings.SLS_CONFIG_LOCATION}
        skip: set[Settings] = set()
        if sys.platform == "win32":
            skip = linux_only
        elif sys.platform == "linux":
            skip = win_only
        lw = QListWidget()
        saved = load_all_settings()
        settings_order: list[Settings] = [s for s in Settings if s not in skip]
        def _refresh_list():
            nonlocal saved
            saved = load_all_settings()
            lw.clear()
            for s in settings_order:
                raw = saved.get(s.key_name)
                if raw is None:
                    val_str = "(unset)"
                elif s.hidden:
                    val_str = "[ENCRYPTED]"
                elif s.type == dict:
                    val_str = "(managed internally)"
                else:
                    val_str = str(raw)
                item = QListWidgetItem(f"{s.clean_name}: {val_str}")
                item.setData(Qt.ItemDataRole.UserRole, s)
                lw.addItem(item)
        _refresh_list()
        layout.addWidget(lw)
        btn_row = QHBoxLayout()
        edit_btn = QPushButton("Modifier")
        delete_btn = QPushButton("Supprimer")
        export_btn = QPushButton("Exporter")
        import_btn = QPushButton("Importer")
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addStretch()
        btn_row.addWidget(export_btn)
        btn_row.addWidget(import_btn)
        layout.addLayout(btn_row)
        close_btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn.rejected.connect(dlg.reject)
        layout.addWidget(close_btn)
        def _edit_setting():
            item = lw.currentItem()
            if not item:
                return
            s: Settings = item.data(Qt.ItemDataRole.UserRole)
            if s.type == dict:
                QMessageBox.information(dlg, "Info", f"{s.clean_name} is managed automatically.")
                return
            if s.type == bool:
                cur = get_setting(s)
                new_val = QMessageBox.question(
                    dlg,
                    s.clean_name,
                    f"Enable {s.clean_name}?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes if cur else QMessageBox.StandardButton.No,
                ) == QMessageBox.StandardButton.Yes
                set_setting(s, new_val)
            elif isinstance(s.type, list):
                names = [e.value for e in s.type]
                chosen, ok = QInputDialog.getItem(dlg, s.clean_name, "Select:", names, 0, False)
                if ok and chosen:
                    set_setting(s, chosen)
            elif s.type == SettingCustomTypes.DIR:
                path = QFileDialog.getExistingDirectory(dlg, s.clean_name)
                if path:
                    set_setting(s, str(Path(path).resolve()))
            elif s.type == SettingCustomTypes.FILE:
                path, _ = QFileDialog.getOpenFileName(dlg, s.clean_name)
                if path:
                    set_setting(s, str(Path(path).resolve()))
            elif s.type == str:
                if s.hidden:
                    val, ok = QInputDialog.getText(
                        dlg, s.clean_name, f"Enter {s.clean_name}:", QLineEdit.EchoMode.Password,
                    )
                else:
                    cur_val = get_setting(s) or ""
                    val, ok = QInputDialog.getText(
                        dlg, s.clean_name, f"Enter {s.clean_name}:", QLineEdit.EchoMode.Normal, str(cur_val),
                    )
                if ok:
                    set_setting(s, val)
            else:
                cur_val = get_setting(s) or ""
                val, ok = QInputDialog.getText(
                    dlg, s.clean_name, f"Enter {s.clean_name}:", QLineEdit.EchoMode.Normal, str(cur_val),
                )
                if ok:
                    set_setting(s, val)
            _refresh_list()
            self._apply_setting_live(s, dlg)
        def _delete_setting():
            item = lw.currentItem()
            if not item:
                return
            s: Settings = item.data(Qt.ItemDataRole.UserRole)
            if QMessageBox.question(
                dlg, "Delete", f"Clear {s.clean_name}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes:
                clear_setting(s)
                _refresh_list()
                self._apply_setting_live(s, dlg)
        def _export():
            path, _ = QFileDialog.getSaveFileName(dlg, "Export settings", "settings_export.json", "JSON (*.json)")
            if path:
                ok = export_settings(Path(path), include_sensitive=False)
                if ok:
                    QMessageBox.information(dlg, "Exported", f"Settings exported to {path}")
                else:
                    QMessageBox.warning(dlg, "Error", "Failed to export settings.")
        def _import():
            path, _ = QFileDialog.getOpenFileName(dlg, "Import settings", "", "JSON (*.json)")
            if not path:
                return
            if QMessageBox.question(
                dlg, "Import", "This will overwrite existing settings. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
            ok, msg = import_settings(Path(path))
            if ok:
                QMessageBox.information(dlg, "Imported", msg)
                _refresh_list()
            else:
                QMessageBox.warning(dlg, "Error", msg)
        edit_btn.clicked.connect(_edit_setting)
        lw.itemDoubleClicked.connect(lambda _: _edit_setting())
        delete_btn.clicked.connect(_delete_setting)
        export_btn.clicked.connect(_export)
        import_btn.clicked.connect(_import)
        dlg.exec()

    def _apply_setting_live(self, s, parent_widget=None):
        from sff.structs import Settings
        if s == Settings.PLAY_MUSIC:
            from sff.storage.settings import get_setting
            val = get_setting(Settings.PLAY_MUSIC)
            if val:
                self.ui.kill_midi_player()
                self.ui.init_midi_player()
            else:
                self.ui.kill_midi_player()
        elif s == Settings.APPLIST_FOLDER:
            try:
                from sff.app_injector.applist import AppListManager
                import sys
                if sys.platform == "win32":
                    self.ui.app_list_man = AppListManager(
                        self.ui.steam_path, self.ui.provider
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to reinit AppListManager: {e}")
        elif s == Settings.STEAM_PATH:
            from sff.storage.settings import get_setting
            new_path = (get_setting(Settings.STEAM_PATH) or "").strip()
            if new_path:
                p = Path(new_path)
                self.steam_path = p
                br = getattr(self, "_web_bridge", None)
                if br is not None:
                    br._steam_path = p
                if hasattr(self.ui, "steam_path"):
                    try:
                        self.ui.steam_path = str(p)
                    except Exception:
                        pass
                if getattr(self, "_authenticated", False):
                    self._set_user_bar_display(self._current_username, self._current_rank)
            if parent_widget:
                QMessageBox.information(
                    parent_widget,
                    "Restart Recommended",
                    "Steam path changed. Please redémarrer SlimeDeals pour appliquer les changements to take full effect.",
                )
        elif s == Settings.LANGUAGE:
            from sff.i18n import set_language
            from sff.storage.settings import get_setting
            set_language(get_setting(Settings.LANGUAGE))
        elif s == Settings.SAVE_WATCHER_INTERVAL:
            self._start_save_watcher()

    # ── Tray / close-to-tray ────────────────────────────────────

    def set_tray(self, tray):
        self._tray = tray

    def force_quit(self):
        self._save_watcher_timer.stop()
        if self._tray is not None:
            self._tray.minimize_to_tray = False
        self.close()

    def closeEvent(self, event):
        if self._tray is not None and self._tray.minimize_to_tray:
            event.ignore()
            self.hide()
        else:
            self._save_watcher_timer.stop()
            event.accept()

    # ── Background save watcher ──────────────────────────────────

    def _start_save_watcher(self):
        from sff.storage.settings import get_setting
        from sff.structs import Settings as _S
        try:
            interval_min = int(get_setting(_S.SAVE_WATCHER_INTERVAL) or 10)
        except (ValueError, TypeError):
            interval_min = 10
        self._save_watcher_timer.stop()
        if interval_min > 0:
            self._save_watcher_timer.start(interval_min * 60 * 1000)

    def _run_background_save_watcher(self):
        import threading
        t = threading.Thread(target=self._do_background_save_backup, daemon=True)
        t.start()

    def _do_background_save_backup(self):
        import json
        from sff.storage.settings import get_setting
        from sff.structs import Settings as _S
        steam32_id = (get_setting(_S.STEAM32_ID) or "").strip()
        steam_path = (get_setting(_S.STEAM_PATH) or "").strip() or getattr(self, "steam_path", None)
        if isinstance(steam_path, Path):
            steam_path = str(steam_path)
        elif steam_path:
            steam_path = str(steam_path).strip()
        provider_config_raw = get_setting(_S.LAST_BACKUP_PROVIDER_CONFIG)
        if not steam32_id or not steam_path:
            return
        try:
            if provider_config_raw:
                cfg = json.loads(provider_config_raw)
                if str(cfg.get("provider", "")).lower() == "gdrive_api" and _launcher_auth_strictly_free():
                    return
                self._cloud_save_backup(cfg, steam_path, steam32_id)
            else:
                self._local_save_backup(steam_path, steam32_id)
        except Exception:
            logger.debug('Save watcher error', exc_info=True)

    def _local_save_backup(self, steam_path, steam32_id):
        from sff.cloud_saves import CloudSaves
        userdata_dir = Path(steam_path) / 'userdata' / str(steam32_id)
        if not userdata_dir.exists():
            return
        cs = CloudSaves()
        backed_up = 0
        for app_dir in userdata_dir.iterdir():
            if not app_dir.is_dir():
                continue
            remote_dir = app_dir / 'remote'
            if not remote_dir.exists():
                continue
            all_files = [f for f in remote_dir.rglob('*') if f.is_file()]
            if not all_files:
                continue
            last_mtime = max(f.stat().st_mtime for f in all_files)
            existing = cs.get_backups(app_dir.name)
            if existing:
                newest_ts = max(b.timestamp for b in existing)
                if last_mtime <= newest_ts:
                    continue
            cs.backup(app_dir.name, str(remote_dir))
            backed_up += 1
        if backed_up:
            logger.debug('Save watcher (local): backed up %d game(s)', backed_up)

    def _cloud_save_backup(self, cfg, steam_path, steam32_id):
        from sff.cloud_saves import (
            scan_all_save_locations,
            backup_save_location_local,
            backup_save_location_rclone,
            backup_save_location_gdrive,
        )
        entries = scan_all_save_locations(steam_path=steam_path, steam32_id=steam32_id)
        if not entries:
            return
        provider = cfg.get('provider', 'local').lower()
        backed_up = 0
        if provider == 'local':
            dest_path = cfg.get('dest_path', '')
            if not dest_path:
                return
            for entry in entries:
                if backup_save_location_local(entry, dest_path):
                    backed_up += 1
        elif provider == 'rclone':
            import subprocess
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import sys as _sys
            rclone_exe = cfg.get('rclone_exe', '')
            remote_dest = cfg.get('remote_dest', '')
            if not rclone_exe:
                from sff.utils import root_folder
                _bundled = root_folder() / "third_party" / "rclone" / ("rclone.exe" if _sys.platform == "win32" else "rclone")
                if _bundled.exists():
                    rclone_exe = str(_bundled)
            if not rclone_exe or not remote_dest:
                return
            unique_locs = list({e['location'] for e in entries})
            _no_window = {'creationflags': 0x08000000} if _sys.platform == 'win32' else {}
            for loc in unique_locs:
                subprocess.run(
                    [rclone_exe, 'mkdir',
                     remote_dest.rstrip('/') + f'/SlimeDealsAllSaves/{loc}'],
                    capture_output=True, stdin=subprocess.DEVNULL, timeout=30, **_no_window,
                )
            with ThreadPoolExecutor(max_workers=10) as ex:
                futures = {ex.submit(backup_save_location_rclone, e, rclone_exe, remote_dest): e for e in entries}
                for fut in as_completed(futures):
                    try:
                        if fut.result():
                            backed_up += 1
                    except Exception:
                        pass
        elif provider == 'gdrive_api':
            from sff.google_drive import get_service, get_backup_root, is_authenticated, get_or_create_folder
            from concurrent.futures import ThreadPoolExecutor, as_completed
            if not is_authenticated():
                return
            svc = get_service()
            if not svc:
                return
            root_id = get_backup_root(svc)
            if not root_id:
                return
            folder_cache = {}
            for loc in {e['location'] for e in entries}:
                loc_id = get_or_create_folder(svc, loc, root_id)
                if loc_id:
                    folder_cache[(loc, root_id)] = loc_id
            with ThreadPoolExecutor(max_workers=10) as ex:
                futures = {ex.submit(backup_save_location_gdrive, e, get_service(), root_id,
                                     None, dict(folder_cache)): e for e in entries}
                for fut in as_completed(futures):
                    try:
                        if fut.result():
                            backed_up += 1
                    except Exception:
                        pass
        if backed_up:
            logger.debug('Save watcher (%s): backed up %d entries', provider, backed_up)

    # ── About ────────────────────────────────────────────────────

    def _show_about(self):
        QMessageBox.about(
            self,
            "À propos de SlimeDeals",
            f"SlimeDeals\nVersion {VERSION}\n\n"
            "https://github.com/Patabouche/slmdls/releases",
        )
