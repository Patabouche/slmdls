"""
Logs de crash / fermeture brutale — dossier ``debugcrash`` à côté de l'exe (ou racine dev).
"""

from __future__ import annotations

import atexit
import faulthandler
import logging
import sys
import threading
import time
import traceback
from pathlib import Path

_log = logging.getLogger(__name__)
_installed = False
_fault_file = None


def debugcrash_dir() -> Path:
    from sff.utils import root_folder

    p = root_folder(outside_internal=True) / "debugcrash"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _write_crash_file(prefix: str, body: str) -> Path:
    path = debugcrash_dir() / f"{prefix}_{_stamp()}.log"
    try:
        path.write_text(body, encoding="utf-8")
    except Exception as exc:
        _log.warning("debugcrash write failed: %s", exc)
    return path


def write_crash_report(title: str, body: str) -> Path:
    """Écrit un rapport horodaté dans debugcrash/."""
    header = f"=== {title} === {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
    return _write_crash_file("crash", header + (body or ""))


def install_debug_crash_logging(*, logger: logging.Logger | None = None) -> Path:
    """
    À appeler au tout début du GUI :
    - fichier session dans debugcrash/
    - faulthandler (segfault / abort)
    - excepthook + threading.excepthook
    """
    global _installed, _fault_file
    if _installed:
        return debugcrash_dir()

    d = debugcrash_dir()
    session_log = d / f"session_{_stamp()}.log"
    latest_log = d / "latest_session.log"

    root_logger = logger or logging.getLogger("sff")
    root_logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s::%(name)s::%(levelname)s::%(message)s",
        datefmt="%m/%d/%Y %I:%M:%S %p",
    )
    for target in (session_log, latest_log):
        try:
            fh = logging.FileHandler(target, encoding="utf-8")
            fh.setFormatter(fmt)
            fh.setLevel(logging.DEBUG)
            root_logger.addHandler(fh)
        except Exception as exc:
            _log.warning("debugcrash FileHandler %s: %s", target, exc)

    try:
        _fault_file = open(d / "faulthandler_latest.log", "w", encoding="utf-8")  # noqa: SIM115
        faulthandler.enable(file=_fault_file, all_threads=True)
    except Exception as exc:
        _log.warning("faulthandler: %s", exc)

    _orig_excepthook = sys.excepthook

    def _excepthook(exc_type, exc_val, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
        try:
            root_logger.critical("Exception non gérée:\n%s", msg)
        except Exception:
            pass
        write_crash_report("uncaught_exception", msg)
        try:
            legacy = Path("crash.log")
            with legacy.open("a", encoding="utf-8") as f:
                f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n{msg}")
        except Exception:
            pass
        if _orig_excepthook is not _excepthook:
            _orig_excepthook(exc_type, exc_val, exc_tb)

    sys.excepthook = _excepthook

    if hasattr(threading, "excepthook"):

        def _thread_hook(args):
            msg = "".join(
                traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
            )
            write_crash_report(
                f"thread_{getattr(args, 'thread', None)}",
                msg,
            )

        threading.excepthook = _thread_hook  # type: ignore[assignment]

    def _on_exit():
        try:
            root_logger.info("[debugcrash] Processus terminé (fermeture normale).")
        except Exception:
            pass

    atexit.register(_on_exit)
    _installed = True
    root_logger.info("[debugcrash] Dossier logs : %s", d)
    return d


def install_qt_message_logging() -> None:
    """Capture les messages Qt critiques (à appeler après QApplication)."""
    try:
        from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:
        return

    def _handler(mode, context, message):
        text = str(message)
        if mode in (QtMsgType.QtFatalMsg, QtMsgType.QtCriticalMsg):
            write_crash_report(f"qt_{mode.name}", text)

    qInstallMessageHandler(_handler)
