#!/usr/bin/env python3
"""AI Office Workspace.

A Windows desktop application that shows the official web sites of the AI
assistants on the left and a local Office-like editor (spreadsheet / document /
presentation) plus the official Google Docs / Sheets / Slides sites on the
right.

The Python side owns windows, browser tabs, web profiles, extraction of AI
answers, file dialogs and persistence.  The React side owns the editors and all
data conversion.  They talk through QWebChannel.
"""

from __future__ import annotations

import base64
import copy
import json
import logging
import sys
import threading
import uuid
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import (
    QFile,
    QIODevice,
    QObject,
    QSaveFile,
    QSize,
    QStandardPaths,
    QTimer,
    QUrl,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QPalette,
)
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

#: True inside a PyInstaller build (the installed setup.exe build).
FROZEN = bool(getattr(sys, "frozen", False))


def _resource_dir() -> Path:
    r"""Directory holding the read-only application files.

    In a PyInstaller build the frontend build and the default config live in
    ``_MEIPASS`` (one-file) or ``_internal`` next to the executable (one-folder),
    which is read-only once installed under ``%LOCALAPPDATA%\Programs``.
    """
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


BASE_DIR = _resource_dir()
DIST_DIR = BASE_DIR / "dist"
FRONTEND_DIR = BASE_DIR / "frontend"
PROFILES_DIR = BASE_DIR / "profiles"
BUNDLED_CONFIG_PATH = BASE_DIR / "config.json"

AI_ORDER = ("ChatGPT", "Claude", "DeepSeek", "Qwen")
GOOGLE_ORDER = ("Google Docs", "Google Sheets", "Google Slides")
#: The AI column only hosts the assistants.  Google's official sites sit next
#: to the local Office editor on the right, where files produced there belong.
WEB_ORDER = AI_ORDER
AI_SLUGS = {
    "ChatGPT": "chatgpt",
    "Claude": "claude",
    "DeepSeek": "deepseek",
    "Qwen": "qwen",
    "Google Docs": "google-docs",
    "Google Sheets": "google-sheets",
    "Google Slides": "google-slides",
}
GOOGLE_SITE_DEFAULTS = {
    "Google Docs": "https://docs.google.com/document/u/0/",
    "Google Sheets": "https://docs.google.com/spreadsheets/u/0/",
    "Google Slides": "https://docs.google.com/presentation/u/0/",
}
MODES = ("spreadsheet", "document", "slides")
MODE_LABELS = {"spreadsheet": "Excel", "document": "Word", "slides": "Slide"}

#: Files the three editors can import, keyed by lower-case suffix.
IMPORT_EXTENSIONS = {
    ".xlsx": "spreadsheet",
    ".xls": "spreadsheet",
    ".csv": "spreadsheet",
    ".tsv": "spreadsheet",
    ".docx": "document",
    ".pptx": "slides",
}

#: The payload is base64 encoded inside a runJavaScript() call, so keep the
#: file small enough that the editor stays responsive.
MAX_IMPORT_BYTES = 20 * 1024 * 1024

DEFAULT_CONFIG: dict[str, Any] = {
    "app_name": "AI Office Workspace",
    "window_width": 1500,
    "window_height": 900,
    "theme": "dark",
    "ai_sites": {
        "ChatGPT": "https://chatgpt.com/",
        "Claude": "https://claude.ai/",
        "DeepSeek": "https://chat.deepseek.com/",
        "Qwen": "https://chat.qwen.ai/",
    },
    "google_sites": GOOGLE_SITE_DEFAULTS.copy(),
}

EMPTY_PROJECT: dict[str, Any] = {
    "format": "ai-office-workspace",
    "version": 1,
    "activeMode": "spreadsheet",
    "spreadsheet": {"sheets": []},
    "document": None,
    "slides": [],
    "metadata": {"title": "Untitled"},
}

C_BG = "#0F1115"
C_SUB = "#14171D"
C_PANEL = "#1B1F27"
C_BORDER = "#272C36"
C_TEXT = "#ECEEF2"
C_MUTED = "#98A1B0"
C_ACCENT = "#6E9BF5"
C_OK = "#6FCF97"
C_ERROR = "#F2777A"

#: Default share of the width given to the AI column.  The taskbar window is
#: deliberately narrow (about one third) so the local Office editor, which is
#: the main workspace, gets the remaining 70 %.
AI_COLUMN_RATIO = 0.3
UI_STATE_LAYOUT_VERSION = 2

QSS_TEMPLATE = """
QWidget {
    background-color: %(bg)s;
    color: %(text)s;
    font-family: "Segoe UI Variable Text", "Segoe UI", "Yu Gothic UI", "Meiryo", sans-serif;
    font-size: 12px;
}
QMainWindow, QDialog {
    background-color: %(bg)s;
}
QTabBar {
    background: transparent;
}
QTabBar::tab {
    background: transparent;
    color: %(muted)s;
    padding: 6px 16px;
    margin: 4px 2px;
    border: 1px solid transparent;
    border-radius: 7px;
    min-width: 56px;
}
QTabBar::tab:hover {
    color: %(text)s;
    background-color: %(panel)s;
}
QTabBar::tab:selected {
    color: #FFFFFF;
    background-color: %(accent)s;
    border-color: %(accent)s;
}
QTabBar#googleTabs::tab:selected {
    color: %(text)s;
    background-color: #2A3346;
    border-color: #3B4A66;
}
QFrame#navBar {
    background-color: %(sub)s;
    border-bottom: 1px solid %(border)s;
}
QFrame#officeHeader {
    background-color: %(sub)s;
    border-bottom: 1px solid %(border)s;
}
QFrame#errorBanner {
    background-color: #2A1E22;
    border: 1px solid #5A3138;
    border-radius: 8px;
}
QToolButton {
    background-color: transparent;
    color: %(muted)s;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 5px 11px;
}
QToolButton:hover {
    background-color: %(panel)s;
    color: %(text)s;
}
QToolButton:disabled {
    color: #59606C;
}
QToolButton:checked {
    background-color: #21304C;
    color: #B9CDFF;
    border: 1px solid #354C77;
}
QToolButton#navButton {
    font-size: 14px;
    padding: 2px 7px;
    min-width: 20px;
}
QToolButton#accentButton {
    background-color: #22304D;
    border: 1px solid #344C78;
    color: #C8D9FF;
}
QToolButton#accentButton:hover {
    background-color: #2B3D61;
    color: #FFFFFF;
}
QPushButton {
    background-color: %(panel)s;
    color: %(text)s;
    border: 1px solid %(border)s;
    border-radius: 7px;
    padding: 6px 13px;
}
QPushButton:hover {
    border-color: %(accent)s;
    color: %(accent)s;
}
QPushButton:pressed {
    background-color: #161A21;
}
QPushButton#primaryButton {
    background-color: %(accent)s;
    border: 1px solid %(accent)s;
    color: #0F1115;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background-color: #86ACF7;
    color: #0F1115;
}
QLabel {
    background: transparent;
}
QLabel#mutedLabel {
    color: %(muted)s;
}
QSplitter::handle {
    background: transparent;
}
QSplitter::handle:horizontal {
    width: 8px;
}
QSplitter::handle:horizontal:hover {
    background-color: #33415A;
}
QStatusBar {
    background-color: %(sub)s;
    border-top: 1px solid %(border)s;
    color: %(muted)s;
}
QStatusBar::item {
    border: none;
}
QPlainTextEdit, QLineEdit {
    background-color: %(panel)s;
    color: %(text)s;
    border: 1px solid %(border)s;
    border-radius: 7px;
    selection-background-color: %(accent)s;
    padding: 6px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #303744;
    border-radius: 5px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #445066;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #303744;
    border-radius: 5px;
    min-width: 28px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QMenu {
    background-color: %(panel)s;
    color: %(text)s;
    border: 1px solid %(border)s;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 5px;
}
QMenu::item:selected {
    background-color: #223052;
}
"""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def configure_logging() -> None:
    """Log to stderr only; no log files are created for normal operation."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def app_data_dir() -> Path:
    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not location:
        location = str(Path.home() / ".ai-office-workspace")
    path = Path(location)
    path.mkdir(parents=True, exist_ok=True)
    return path


def documents_dir() -> Path:
    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DocumentsLocation
    )
    base = Path(location) if location else Path.home()
    path = base / "AI Office Workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    """Writable config.json.

    A frozen build ships config.json as a read-only template inside the
    installation, so the editable copy lives in the per-user data folder
    (``%APPDATA%\\AI Office Workspace\\config.json``).
    """
    if FROZEN:
        return app_data_dir() / "config.json"
    return BUNDLED_CONFIG_PATH


def profile_store_dir() -> Path:
    """Directory for the per-service QWebEngine profiles (cookies, cache).

    Installed builds must not write below the installation folder, therefore
    the profiles move to the per-user data folder.  A source checkout keeps
    using the repository-local ``profiles/`` directory.
    """
    path = app_data_dir() / "profiles" if FROZEN else PROFILES_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def icon_path() -> Path:
    """Application icon (generated by ``packaging/make_icon.py``)."""
    if FROZEN:
        return BASE_DIR / "app.ico"
    return BASE_DIR / "packaging" / "app.ico"


def ensure_user_config() -> Optional[str]:
    """Copy the bundled config.json to the writable folder on first launch."""
    if not FROZEN:
        return None

    target = config_path()
    if target.exists():
        return None
    if not BUNDLED_CONFIG_PATH.exists():
        return None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            BUNDLED_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8"
        )
    except OSError as exc:
        return f"config.json を {target} へコピーできませんでした: {exc}"
    return None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def js_data(value: Any) -> str:
    """Serialise a Python value into a JavaScript literal.

    ``json.dumps`` output is valid JavaScript except for the U+2028/U+2029 line
    separators, which are escaped explicitly.  Non-ASCII text is kept as-is to
    avoid inflating large payloads.
    """
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def atomic_write_json(path: Path, data: Any) -> None:
    """Write UTF-8 JSON without ever leaving a half written file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    qfile = QSaveFile(str(path))
    if not qfile.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(f"{path} を開けませんでした: {qfile.errorString()}")
    try:
        written = qfile.write(payload)
        if written != len(payload):
            raise OSError(f"{path} への書き込みが不完全です")
        if not qfile.commit():
            raise OSError(f"{path} を保存できませんでした: {qfile.errorString()}")
    except BaseException:
        if qfile.isOpen():
            qfile.cancelWriting()
        raise


def read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def load_config() -> tuple[dict[str, Any], list[str]]:
    """Load config.json, falling back to the built-in defaults on any problem."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    warnings: list[str] = []
    path = config_path()

    if not path.exists():
        warnings.append(
            "config.json が見つからないため、既定の設定で起動しました。"
        )
        return config, warnings

    try:
        raw = read_json_file(path)
    except (OSError, ValueError) as exc:
        warnings.append(
            f"config.json を読み込めませんでした（{exc}）。既定の設定を使用します。"
        )
        return config, warnings

    if not isinstance(raw, dict):
        warnings.append(
            "config.json の内容がオブジェクトではないため、既定の設定を使用します。"
        )
        return config, warnings

    app_name = raw.get("app_name")
    if isinstance(app_name, str) and app_name.strip():
        config["app_name"] = app_name.strip()

    theme = raw.get("theme")
    if isinstance(theme, str) and theme.strip():
        config["theme"] = theme.strip()

    for key, default_value in (("window_width", 1500), ("window_height", 900)):
        value = raw.get(key)
        if isinstance(value, int) and 800 <= value <= 8000:
            config[key] = value
        elif value is not None:
            warnings.append(f"config.json の {key} が不正なため {default_value} を使用します。")

    sites = raw.get("ai_sites")
    if sites is not None and not isinstance(sites, dict):
        warnings.append("config.json の ai_sites が不正なため既定の URL を使用します。")
        sites = None
    if isinstance(sites, dict):
        for name in AI_ORDER:
            url = sites.get(name)
            # The old GLM URL must never be reused for Claude. Existing
            # installations keep their browser profile, but Claude always
            # points at the official Claude site.
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                config["ai_sites"][name] = url.strip()
            elif url is not None:
                warnings.append(
                    f"config.json の ai_sites.{name} が URL ではないため既定値を用います。"
                )
        config["ai_sites"]["Claude"] = DEFAULT_CONFIG["ai_sites"]["Claude"]

    # Only the four supported sites are used; other names are ignored.
    config["ai_sites"] = {name: config["ai_sites"][name] for name in AI_ORDER}
    google_sites = raw.get("google_sites")
    if google_sites is not None and not isinstance(google_sites, dict):
        warnings.append("config.json の google_sites が不正なため既定の URL を使用します。")
        google_sites = None
    if isinstance(google_sites, dict):
        for name in GOOGLE_ORDER:
            url = google_sites.get(name)
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                config["google_sites"][name] = url.strip()
            elif url is not None:
                warnings.append(
                    f"config.json の google_sites.{name} が URL ではないため既定値を用います。"
                )
    config["google_sites"] = {
        name: config["google_sites"][name] for name in GOOGLE_ORDER
    }
    return config, warnings


# ---------------------------------------------------------------------------
# qwebchannel.js (taken from Qt itself, never hand written)
# ---------------------------------------------------------------------------


def read_qwebchannel_js() -> Optional[str]:
    """Return the official qwebchannel.js shipped inside the Qt libraries."""
    resource = QFile(":/qtwebchannel/qwebchannel.js")
    if resource.exists() and resource.open(QIODevice.OpenModeFlag.ReadOnly):
        try:
            return bytes(resource.readAll()).decode("utf-8")
        finally:
            resource.close()

    # Fallback: some PySide6 wheels ship the file inside the package.
    try:
        import PySide6  # noqa: PLC0415 - optional fallback

        package_root = Path(PySide6.__file__).resolve().parent
        for candidate in package_root.rglob("qwebchannel.js"):
            try:
                text = candidate.read_text(encoding="utf-8")
            except OSError:
                continue
            if "QWebChannel" in text:
                return text
    except Exception:  # pragma: no cover - defensive only
        logging.getLogger(__name__).exception("qwebchannel.js の探索に失敗しました")
    return None


def prepare_environment() -> Optional[str]:
    """Check the built frontend and materialise qwebchannel.js.

    Returns an error message when the application cannot be started.
    """
    index = DIST_DIR / "index.html"
    if not index.exists():
        if FROZEN:
            return (
                "アプリの画面データが見つかりません。\n\n"
                f"探索した場所: {index}\n\n"
                "インストールが壊れています。setup.exe でもう一度インストールしてください。"
            )
        return (
            "フロントエンドのビルドが見つかりません。\n\n"
            f"探索した場所: {index}\n\n"
            "次のコマンドでビルドしてください。\n"
            "    cd frontend\n"
            "    npm install\n"
            "    npm run build\n"
        )

    if FROZEN:
        # The installation folder is read-only: the build (packaging/build.bat)
        # must have copied Qt's own qwebchannel.js into dist/.
        if not (DIST_DIR / "qtwebchannel.js").exists():
            return (
                "qtwebchannel.js が同梱されていません。\n\n"
                "配布物を作り直してください（packaging\\build.bat）。"
            )
        return None

    script = read_qwebchannel_js()
    if script is None:
        return (
            "Qt が提供する qwebchannel.js を取得できませんでした。\n\n"
            "PySide6 のインストールが不完全である可能性があります。"
        )

    targets = (DIST_DIR / "qtwebchannel.js", FRONTEND_DIR / "public" / "qtwebchannel.js")
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_text(encoding="utf-8") != script:
                target.write_text(script, encoding="utf-8")
        except OSError as exc:
            if target.parent == DIST_DIR:
                return f"{target} へ qwebchannel.js を書き込めませんでした: {exc}"
            logging.getLogger(__name__).warning(
                "qwebchannel.js を %s へコピーできませんでした: %s", target, exc
            )
    return None


# ---------------------------------------------------------------------------
# AI answer extraction
# ---------------------------------------------------------------------------

#: Selectors for the assistant messages.  ChatGPT, Claude and Qwen use
#: selectors that are stable enough to be used directly.  DeepSeek could be
#: verified, therefore only clearly-marked candidates plus a generic heuristic
#: are used, and the manual fallbacks remain the reliable path.
EXTRACTION_CONFIG: dict[str, dict[str, Any]] = {
    "ChatGPT": {
        "selector": '[data-message-author-role="assistant"]',
        "fallbacks": [
            'article[data-testid^="conversation-turn"] [class*="markdown"]',
            '[class*="markdown"]',
        ],
    },
    "Qwen": {
        "selector": ".markdown-body",
        "fallbacks": ['[class*="markdown-body"]', '[class*="markdown"]'],
    },
    "Claude": {
        "selector": '[data-testid="assistant-message"]',
        "fallbacks": [
            '[data-is-streaming="false"]',
            '[class*="markdown"]',
            '[class*="message"] [class*="content"]',
            '[class*="chat"] [class*="content"]',
        ],
    },
    "DeepSeek": {
        # Candidate only - not verified against the live site.
        "selector": "",
        "fallbacks": [
            ".ds-markdown",
            '[class*="markdown"]',
            '[class*="message"] [class*="content"]',
        ],
    },
}

EXTRACT_JS_TEMPLATE = r"""
(function () {
  var cfg = __CONFIG_JSON__;
  var NOISE_LINES = /^(copy|copy code|edit|regenerate|retry|share|like|dislike|read aloud|コピー|編集|再生成|再試行|共有|音声で読み上げ)$/i;
  var SKIP_TAGS = /^(SCRIPT|STYLE|NOSCRIPT|SVG|CANVAS|BUTTON|INPUT|TEXTAREA|SELECT|FORM|IMG|VIDEO|AUDIO|IFRAME)$/;
  var BLOCK_TAGS = /^(DIV|P|LI|UL|OL|H1|H2|H3|H4|H5|H6|PRE|BLOCKQUOTE|TABLE|THEAD|TBODY|TR|SECTION|ARTICLE|HEADER|FOOTER|MAIN|HR)$/;

  function collectText(root) {
    var out = "";
    function walk(node) {
      if (!node) { return; }
      if (node.nodeType === 3) {
        out += node.nodeValue;
        return;
      }
      if (node.nodeType !== 1) { return; }
      var tag = node.tagName ? node.tagName.toUpperCase() : "";
      if (SKIP_TAGS.test(tag)) { return; }
      if (node.getAttribute) {
        var hidden = node.getAttribute("aria-hidden");
        var role = node.getAttribute("role");
        if (hidden === "true" || role === "button" || role === "toolbar" || role === "menu") {
          return;
        }
        if (node.getAttribute("contenteditable") === "true" && node.querySelector && node.querySelector("[contenteditable]")) {
          // keep editing surfaces readable, nothing to skip here
        }
      }
      if (tag === "BR") {
        out += "\n";
        return;
      }
      var isBlock = BLOCK_TAGS.test(tag);
      if (isBlock && out && !/\n$/.test(out)) { out += "\n"; }
      for (var i = 0; i < node.childNodes.length; i += 1) { walk(node.childNodes[i]); }
      if (isBlock && out && !/\n$/.test(out)) { out += "\n"; }
    }
    walk(root);
    return out;
  }

  function normalise(text) {
    var lines = String(text).replace(/\r\n?/g, "\n").split("\n");
    var kept = [];
    for (var i = 0; i < lines.length; i += 1) {
      var line = lines[i].replace(/\u00a0/g, " ").replace(/[ \t]+$/g, "");
      if (NOISE_LINES.test(line.trim())) { continue; }
      kept.push(line);
    }
    return kept.join("\n")
      .replace(/\n{3,}/g, "\n\n")
      .replace(/[ \t]{2,}/g, " ")
      .trim();
  }

  function queryAll(selector) {
    try {
      return Array.prototype.slice.call(document.querySelectorAll(selector));
    } catch (e) {
      return [];
    }
  }

  try {
    var candidates = [];
    var strategy = "none";

    if (cfg.selector) {
      candidates = queryAll(cfg.selector);
      if (candidates.length > 0) { strategy = cfg.selector; }
    }

    if (candidates.length === 0) {
      var fallbacks = cfg.fallbacks || [];
      for (var i = 0; i < fallbacks.length; i += 1) {
        var found = queryAll(fallbacks[i]);
        if (found.length > 0) {
          candidates = found;
          strategy = fallbacks[i];
          break;
        }
      }
    }

    if (candidates.length === 0) {
      return JSON.stringify({ ok: false, reason: "no-dom", text: "" });
    }

    var leaves = candidates.filter(function (element) {
      return !candidates.some(function (other) {
        return other !== element && element.contains(other);
      });
    });
    if (leaves.length === 0) { leaves = candidates; }

    var text = "";
    for (var j = leaves.length - 1; j >= 0; j -= 1) {
      var candidateText = normalise(collectText(leaves[j]));
      if (candidateText.length >= 12) {
        text = candidateText;
        break;
      }
    }

    if (!text) {
      return JSON.stringify({ ok: false, reason: "empty", text: "" });
    }
    return JSON.stringify({ ok: true, text: text, strategy: strategy });
  } catch (error) {
    return JSON.stringify({ ok: false, reason: "exception", text: "", detail: String(error) });
  }
})()
"""


def build_extraction_script(ai_name: str) -> str:
    config = EXTRACTION_CONFIG.get(ai_name, {"selector": "", "fallbacks": []})
    return EXTRACT_JS_TEMPLATE.replace("__CONFIG_JSON__", js_data(config))


SELECTION_JS = (
    "(function(){ try { var s = window.getSelection ? window.getSelection().toString() : '';"
    " return s == null ? '' : String(s); } catch (e) { return ''; } })()"
)


# ---------------------------------------------------------------------------
# Project validation
# ---------------------------------------------------------------------------


def _clean_sheet(sheet: Any) -> Optional[dict[str, Any]]:
    if not isinstance(sheet, dict):
        return None
    name = sheet.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    cleaned: dict[str, Any] = {"name": name.strip()}
    for key in ("id", "order", "row", "column", "config", "status", "hide", "color"):
        if key in sheet:
            cleaned[key] = sheet[key]
    celldata = sheet.get("celldata")
    if isinstance(celldata, list):
        cleaned["celldata"] = celldata
    return cleaned


def _clean_slide(slide: Any, used_ids: set[str]) -> Optional[dict[str, Any]]:
    if not isinstance(slide, dict):
        return None
    slide_id = slide.get("id")
    if not isinstance(slide_id, str) or not slide_id.strip() or slide_id in used_ids:
        slide_id = f"slide-{uuid.uuid4().hex[:10]}"
    used_ids.add(slide_id)
    layout = slide.get("layout")
    if layout not in ("title-content", "title-only", "section", "blank"):
        layout = "title-content"
    background = slide.get("background")
    if not isinstance(background, str) or not background.strip():
        background = "#FFFFFF"
    title = slide.get("title")
    body = slide.get("body")
    return {
        "id": slide_id,
        "title": title if isinstance(title, str) else "",
        "body": body if isinstance(body, str) else "",
        "background": background,
        "layout": layout,
    }


def normalize_project(raw: Any) -> dict[str, Any]:
    """Validate a project file and return a cleaned copy.

    Raises:
        ValueError: when the file is not a project of this application.
    """
    if not isinstance(raw, dict):
        raise ValueError("プロジェクトのルートがオブジェクトではありません。")

    fmt = raw.get("format")
    if fmt not in (None, "ai-office-workspace"):
        raise ValueError("AI Office Workspace のプロジェクトファイルではありません。")

    version = raw.get("version", 1)
    if version != 1:
        raise ValueError(f"未対応のプロジェクトバージョンです: {version}")

    active_mode = raw.get("activeMode")
    if active_mode not in MODES:
        active_mode = "spreadsheet"

    spreadsheet = raw.get("spreadsheet")
    sheet_list: list[Any] = []
    if isinstance(spreadsheet, dict) and isinstance(spreadsheet.get("sheets"), list):
        sheet_list = spreadsheet["sheets"]
    elif isinstance(spreadsheet, list):
        sheet_list = spreadsheet
    sheets = [s for s in (_clean_sheet(item) for item in sheet_list) if s is not None]

    document = raw.get("document")
    if not isinstance(document, dict) or document.get("type") != "doc":
        document = None

    slides_raw = raw.get("slides")
    used_ids: set[str] = set()
    slides: list[dict[str, Any]] = []
    if isinstance(slides_raw, list):
        for item in slides_raw:
            cleaned = _clean_slide(item, used_ids)
            if cleaned is not None:
                slides.append(cleaned)

    metadata = raw.get("metadata")
    title = "Untitled"
    if isinstance(metadata, dict) and isinstance(metadata.get("title"), str):
        title = metadata["title"].strip() or "Untitled"

    return {
        "format": "ai-office-workspace",
        "version": 1,
        "activeMode": active_mode,
        "spreadsheet": {"sheets": sheets},
        "document": document,
        "slides": slides,
        "metadata": {"title": title},
    }


def parse_office_result(raw: Any) -> dict[str, Any]:
    """Normalise whatever the JavaScript API returned into a result dict."""
    if raw is None:
        return {"ok": False, "error": "エディタから応答がありませんでした。"}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {"ok": False, "error": f"エディタの応答を解析できません: {raw[:200]}"}
        if isinstance(parsed, dict):
            return parsed
        return {"ok": True, "value": parsed}
    if isinstance(raw, dict):
        return raw
    return {"ok": True, "value": raw}


# ---------------------------------------------------------------------------
# Web pages and views
# ---------------------------------------------------------------------------


class AiPage(QWebEnginePage):
    """A page that opens new windows (OAuth popups) with the same profile."""

    def __init__(self, profile: QWebEngineProfile, parent: QObject, window: "MainWindow"):
        super().__init__(profile, parent)
        self._window = window

    def createWindow(  # noqa: N802 - Qt naming
        self, window_type: QWebEnginePage.WebWindowType
    ) -> QWebEnginePage:
        view = QWebEngineView()
        page = AiPage(self.profile(), view, self._window)
        view.setPage(page)
        view.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        view.setWindowTitle("AI Office Workspace - popup")
        view.resize(1024, 780)
        view.show()
        self._window.register_popup(view)
        return page

    def acceptNavigationRequest(  # noqa: N802 - Qt naming
        self, url: QUrl, nav_type: QWebEnginePage.NavigationType, is_main_frame: bool
    ) -> bool:
        scheme = url.scheme().lower()
        if scheme in ("mailto", "tel", "magnet"):
            QDesktopServices.openUrl(url)
            return False
        return True


class OfficePage(QWebEnginePage):
    """Page for the local React editor: only local content may be loaded."""

    LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

    def acceptNavigationRequest(  # noqa: N802 - Qt naming
        self, url: QUrl, nav_type: QWebEnginePage.NavigationType, is_main_frame: bool
    ) -> bool:
        scheme = url.scheme().lower()
        if url.isLocalFile() or scheme in ("about", "data", "blob", "javascript"):
            return True
        if scheme in ("http", "https") and url.host() in self.LOOPBACK_HOSTS:
            return True
        if scheme in ("http", "https"):
            # Links inside documents open in the default browser, never inside
            # the editor view (which would replace the editor itself).
            QDesktopServices.openUrl(url)
            return False
        return False


class _QuietStaticHandler(SimpleHTTPRequestHandler):
    """Serves dist/ without writing request logs to stderr."""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class StaticFileServer:
    """Loopback HTTP server used only if Qt cannot load ES modules from disk.

    Nothing is uploaded or downloaded: the server binds to 127.0.0.1 on an
    ephemeral port and only exposes the built ``dist`` directory.
    """

    def __init__(self, directory: Path) -> None:
        handler = partial(_QuietStaticHandler, directory=str(directory))
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="ai-office-static-server",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def url(self) -> QUrl:
        port = self._server.server_address[1]
        return QUrl(f"http://127.0.0.1:{port}/index.html")

    def stop(self) -> None:
        try:
            self._server.shutdown()
        except RuntimeError:  # pragma: no cover - already stopped
            pass
        self._server.server_close()


class ProfileStore:
    """Keeps persistent, per-service web profiles alive for the whole run."""

    def __init__(self) -> None:
        self._profiles: dict[str, QWebEngineProfile] = {}

    def get(self, slug: str, directory: Path) -> QWebEngineProfile:
        existing = self._profiles.get(slug)
        if existing is not None:
            return existing
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "cache").mkdir(parents=True, exist_ok=True)
        profile = QWebEngineProfile(slug, QApplication.instance())
        profile.setPersistentStoragePath(str(directory))
        profile.setCachePath(str(directory / "cache"))
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        profile.setHttpCacheMaximumSize(64 * 1024 * 1024)
        settings = profile.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalStorageEnabled, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.PluginsEnabled, False
        )
        self._profiles[slug] = profile
        return profile


# ---------------------------------------------------------------------------
# Python <-> JavaScript bridge
# ---------------------------------------------------------------------------


class OfficeBridge(QObject):
    """Object registered into the Office editor page only."""

    readyChanged = Signal(bool)
    changed = Signal()
    statusArrived = Signal(str)
    errorArrived = Signal(str)
    saveRequested = Signal()
    modeArrived = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._ready = False

    @Slot()
    def editorReady(self) -> None:  # noqa: N802 - called from JavaScript
        self._ready = True
        self.readyChanged.emit(True)

    @Slot()
    def contentChanged(self) -> None:  # noqa: N802 - called from JavaScript
        self.changed.emit()

    @Slot(str)
    def showStatus(self, message: str) -> None:  # noqa: N802 - called from JavaScript
        self.statusArrived.emit(message)

    @Slot(str)
    def reportError(self, message: str) -> None:  # noqa: N802 - called from JavaScript
        self.errorArrived.emit(message)

    @Slot()
    def requestSave(self) -> None:  # noqa: N802 - called from JavaScript
        self.saveRequested.emit()

    @Slot(str)
    def modeChanged(self, mode: str) -> None:  # noqa: N802 - called from JavaScript
        self.modeArrived.emit(mode)


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------


class InsertResponseDialog(QDialog):
    """Choose how an AI answer should be brought into the editor."""

    ACTIONS = (
        ("text", "Insert as Text", "現在のモードへテキストとして挿入します。"),
        ("table", "Convert to Table", "Markdown 表 / CSV / TSV を Excel のセルへ展開します。"),
        ("document", "Convert to Document", "見出しやリストを解析して Word へ挿入します。"),
        ("slides", "Convert to Slides", "見出し構造からスライドを生成して追加します。"),
    )

    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Insert AI Response")
        self.setMinimumWidth(560)
        self._action = "cancel"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("AI の回答をどの形式で挿入しますか？")
        title.setStyleSheet(f"color:{C_TEXT}; font-size:14px; font-weight:600;")
        layout.addWidget(title)

        preview = QPlainTextEdit()
        preview.setPlainText(text if len(text) <= 4000 else text[:4000] + "\n…")
        preview.setReadOnly(True)
        preview.setMinimumHeight(150)
        preview.setStyleSheet(
            f"background-color:{C_PANEL}; color:{C_MUTED}; border:1px solid {C_BORDER};"
        )
        layout.addWidget(preview, 1)

        for key, label, description in self.ACTIONS:
            button = QPushButton(f"{label}    —  {description}")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, k=key: self._choose(k))
            layout.addWidget(button)

        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def _choose(self, key: str) -> None:
        self._action = key
        self.accept()

    def selected_action(self) -> str:
        return self._action


class ManualPasteDialog(QDialog):
    """Fallback when the DOM of an AI site cannot be read."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI の回答を貼り付け")
        self.setMinimumSize(620, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        hint = QLabel(
            "AI 画面からコピーした回答を貼り付けてください。\n"
            "内容はテキストとしてのみ扱われ、HTML として実行されることはありません。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{C_MUTED};")
        layout.addWidget(hint)
        self.editor = QPlainTextEdit()
        self.editor.setMinimumHeight(240)
        layout.addWidget(self.editor, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("キャンセル")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("この内容を使う")
        ok.setObjectName("primaryButton")
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        layout.addLayout(row)

    def text(self) -> str:
        return self.editor.toPlainText()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self, config: dict[str, Any], warnings: list[str]) -> None:
        super().__init__()
        self.config = config
        self.log = logging.getLogger("ai-office-workspace")

        self.profiles = ProfileStore()
        self.ai_views: dict[str, QWebEngineView] = {}
        #: Google sites live on the right and are created the first time their
        #: tab is opened, so startup only loads the visible pages.
        self.google_views: dict[str, QWebEngineView] = {}
        self.google_panels: dict[str, QWidget] = {}
        self.google_nav: dict[str, dict[str, Any]] = {}
        self._popups: list[QWebEngineView] = []

        self.current_path: Optional[Path] = None
        self.dirty = False
        self._office_ready = False
        self._closing = False
        self._pending_restore: Optional[dict[str, Any]] = None
        self._startup_restore = True
        self._ai_error_url: dict[str, str] = {}
        self._download_profiles: set[str] = set()
        self._download_import_offered: set[str] = set()
        self._local_server: Optional[StaticFileServer] = None
        self._office_via_http = False
        self._save_in_progress = False
        self._restoring_ui = False

        self.setWindowTitle(config["app_name"])
        self.resize(
            int(config["window_width"]),
            int(config["window_height"]),
        )
        self.setMinimumSize(QSize(1100, 650))

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(3000)
        self.autosave_timer.timeout.connect(self._run_autosave)

        self._build_ui()
        self._build_office_editor()
        self._install_shortcuts()
        self._restore_ui_state()
        self._update_window_title()
        self.set_status("Ready")

        if warnings:
            self.set_status(warnings[0], "error")
            QTimer.singleShot(0, lambda: self._show_startup_warnings(warnings))

    # -- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        # Status bar first: web views created below may emit signals while the
        # rest of the window is still being assembled.
        self._build_statusbar()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        # Qt WebEngine repaints asynchronously.  Resizing its native surface on
        # every mouse move makes the two panes flash; a rubber-band resize keeps
        # the drag smooth and applies the new sizes once, on release.
        self.splitter.setOpaqueResize(False)
        self.splitter.addWidget(self._build_ai_panel())
        self.splitter.addWidget(self._build_office_panel())
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 7)
        width = int(self.config["window_width"])
        ai_width = max(340, int(width * AI_COLUMN_RATIO))
        self.splitter.setSizes([ai_width, max(640, width - ai_width)])
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        root.addWidget(self.splitter, 1)

    def _build_statusbar(self) -> None:
        status = QStatusBar()
        status.setSizeGripEnabled(True)
        self.setStatusBar(status)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("mutedLabel")
        status.addWidget(self.status_label, 1)
        self.ai_status_label = QLabel("")
        self.ai_status_label.setObjectName("mutedLabel")
        status.addPermanentWidget(self.ai_status_label)
        self.mode_status_label = QLabel("")
        self.mode_status_label.setObjectName("mutedLabel")
        status.addPermanentWidget(self.mode_status_label)

    def _build_ai_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.ai_tabs = QTabBar()
        self.ai_tabs.setObjectName("aiTabs")
        self.ai_tabs.setExpanding(True)
        self.ai_tabs.setDrawBase(False)
        self.ai_tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ai_tabs.setCursor(Qt.CursorShape.PointingHandCursor)
        for name in AI_ORDER:
            self.ai_tabs.addTab(name)
        self.ai_tabs.setToolTip("AI の公式サイトをアプリ内の別タブで開きます。")
        layout.addWidget(self.ai_tabs)
        # Connected after the tabs exist so the first insertion cannot fire a
        # signal while the rest of the window is still being built.
        self.ai_tabs.currentChanged.connect(self._on_ai_tab_changed)

        nav = QFrame()
        nav.setObjectName("navBar")
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(8, 4, 8, 4)
        nav_layout.setSpacing(4)

        self.back_button = self._make_nav_button("◀", "戻る")
        self.back_button.clicked.connect(self._ai_back)
        self.forward_button = self._make_nav_button("▶", "進む")
        self.forward_button.clicked.connect(self._ai_forward)
        self.reload_button = self._make_nav_button("⟳", "再読み込み")
        self.reload_button.clicked.connect(self._ai_reload)
        nav_layout.addWidget(self.back_button)
        nav_layout.addWidget(self.forward_button)
        nav_layout.addWidget(self.reload_button)

        self.url_label = QLabel("")
        self.url_label.setObjectName("mutedLabel")
        self.url_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.url_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        nav_layout.addWidget(self.url_label, 1)

        self.external_button = self._make_nav_button("↗", "既定のブラウザで開く")
        self.external_button.clicked.connect(self._open_current_ai_external)
        nav_layout.addWidget(self.external_button)
        layout.addWidget(nav)

        self.error_banner = QFrame()
        self.error_banner.setObjectName("errorBanner")
        banner_layout = QHBoxLayout(self.error_banner)
        banner_layout.setContentsMargins(12, 8, 12, 8)
        banner_layout.setSpacing(10)
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color:{C_ERROR};")
        banner_layout.addWidget(self.error_label, 1)
        retry = QPushButton("再読み込み")
        retry.clicked.connect(self._retry_failed_ai_page)
        banner_layout.addWidget(retry)
        open_external = QPushButton("ブラウザで開く")
        open_external.clicked.connect(self._force_open_error_url)
        banner_layout.addWidget(open_external)
        self.error_banner.setVisible(False)
        layout.addWidget(self.error_banner)

        self.ai_stack = QStackedWidget()
        layout.addWidget(self.ai_stack, 1)

        return panel

    def _make_nav_button(self, text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("navButton")
        button.setText(text)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _create_web_view(self, name: str) -> QWebEngineView:
        slug = AI_SLUGS[name]
        profile_path = profile_store_dir() / slug
        # Reuse the old GLM browser profile once, so existing Claude users do
        # not lose their local session when upgrading from the previous name.
        if name == "Claude" and not profile_path.exists():
            legacy_profile = profile_store_dir() / "glm"
            if legacy_profile.exists():
                profile_path = legacy_profile
        profile = self.profiles.get(slug, profile_path)
        self._install_download_handler(profile, slug)
        view = QWebEngineView()
        page = AiPage(profile, view, self)
        view.setPage(page)
        # Registered before setUrl(): loadStarted may fire while the request
        # is being started, and the navigation bar reads from this dict.
        self.ai_views[name] = view
        view.loadStarted.connect(lambda n=name: self._on_ai_load_started(n))
        view.loadProgress.connect(lambda value, n=name: self._on_ai_load_progress(n, value))
        view.loadFinished.connect(lambda ok, n=name: self._on_ai_load_finished(n, ok))
        view.urlChanged.connect(lambda url, n=name: self._on_ai_url_changed(n, url))
        url = self.config["ai_sites"][name] if name in AI_ORDER else self.config["google_sites"][name]
        view.setUrl(QUrl(url))
        return view

    def _ensure_ai_view(self, name: str) -> QWebEngineView:
        """Create an AI view the first time its tab is opened.

        Keeping the other assistants unloaded makes startup much lighter: a
        ChatGPT-like page is several MB of JavaScript each, and most sessions
        only use one or two of them.
        """
        view = self.ai_views.get(name)
        if view is None:
            view = self._create_web_view(name)
            self.ai_stack.addWidget(view)
        return view

    # -- Google tabs (right pane) -----------------------------------------

    def _on_right_tab_changed(self, index: int) -> None:
        if index <= 0:
            self.right_stack.setCurrentIndex(0)
            self.set_status("Ready")
            return
        if index - 1 >= len(GOOGLE_ORDER):
            return
        name = GOOGLE_ORDER[index - 1]
        panel = self.google_panels.get(name)
        if panel is None:
            panel = self._create_google_panel(name)
        self.right_stack.setCurrentWidget(panel)
        self.set_status(f"{name} を開いています…", "busy")

    def _create_google_panel(self, name: str) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        nav = QFrame()
        nav.setObjectName("navBar")
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(8, 4, 8, 4)
        nav_layout.setSpacing(4)

        back = self._make_nav_button("◀", "戻る")
        forward = self._make_nav_button("▶", "進む")
        reload_button = self._make_nav_button("⟳", "再読み込み")
        external = self._make_nav_button("↗", "既定のブラウザで開く")
        nav_layout.addWidget(back)
        nav_layout.addWidget(forward)
        nav_layout.addWidget(reload_button)

        url_label = QLabel("")
        url_label.setObjectName("mutedLabel")
        url_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        url_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        nav_layout.addWidget(url_label, 1)
        nav_layout.addWidget(external)

        view = QWebEngineView()
        page = AiPage(self.profiles.get(AI_SLUGS[name], profile_store_dir() / AI_SLUGS[name]), view, self)
        view.setPage(page)
        slug = AI_SLUGS[name]
        self._install_download_handler(page.profile(), slug)

        self.google_views[name] = view
        self.google_panels[name] = panel
        self.google_nav[name] = {
            "back": back,
            "forward": forward,
            "reload": reload_button,
            "url": url_label,
        }

        back.clicked.connect(view.back)
        forward.clicked.connect(view.forward)
        reload_button.clicked.connect(view.reload)
        external.clicked.connect(
            lambda: self._open_google_external(name)
        )
        view.urlChanged.connect(lambda url, n=name: self._on_google_url_changed(n, url))
        view.loadStarted.connect(lambda n=name: self._on_google_load_started(n))
        view.loadFinished.connect(lambda ok, n=name: self._on_google_load_finished(n, ok))

        layout.addWidget(nav)
        layout.addWidget(view, 1)
        self.right_stack.addWidget(panel)
        back.setEnabled(False)
        forward.setEnabled(False)
        view.setUrl(QUrl(self.config["google_sites"][name]))
        return panel

    def _on_google_url_changed(self, name: str, url: QUrl) -> None:
        widgets = self.google_nav.get(name)
        if widgets is None:
            return
        widgets["url"].setText(url.toString())
        view = self.google_views.get(name)
        if view is not None:
            history = view.history()
            widgets["back"].setEnabled(history.canGoBack())
            widgets["forward"].setEnabled(history.canGoForward())

    def _on_google_load_started(self, name: str) -> None:
        if self.google_panels.get(name) is self.right_stack.currentWidget():
            self.set_status(f"Loading {name}...", "busy")

    def _on_google_load_finished(self, name: str, ok: bool) -> None:
        if self.google_panels.get(name) is not self.right_stack.currentWidget():
            return
        if ok:
            self.set_status(f"{name} を開きました", "ok")
        else:
            self.set_status(f"Error: {name} を読み込めませんでした", "error")

    def _open_google_external(self, name: str) -> None:
        view = self.google_views.get(name)
        if view is not None:
            url = view.url()
            if url.isValid() and not url.isEmpty():
                QDesktopServices.openUrl(url)

    def _build_office_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(600)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("officeHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(4)

        # Google's official sites belong to the local workspace, not to the
        # assistant column.  "Office" is the local editor; the three Google
        # tabs reuse the same pane, so files can be handled in one place.
        self.right_tabs = QTabBar()
        self.right_tabs.setObjectName("googleTabs")
        self.right_tabs.setExpanding(True)
        self.right_tabs.setDrawBase(False)
        self.right_tabs.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.right_tabs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.right_tabs.addTab("Office")
        self.right_tabs.setTabToolTip(0, "ローカルの Excel / Word / Slide エディタ")
        for index, name in enumerate(GOOGLE_ORDER, start=1):
            self.right_tabs.addTab(name)
            self.right_tabs.setTabToolTip(index, f"{name} の公式サイトを右ペインで開きます")
        self.right_tabs.currentChanged.connect(self._on_right_tab_changed)
        header_layout.addWidget(self.right_tabs)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(4)
        self.office_action_buttons: list[QToolButton] = []

        self.reload_office_button = self._make_toolbar_button(
            "更新", "エディタを再読み込みします（内容は保持されます）", self.reload_office
        )
        self.insert_selection_button = self._make_toolbar_button(
            "選択テキスト", "AI 画面で選択した文字列を取得します", self.insert_selection
        )
        self.insert_ai_button = self._make_toolbar_button(
            "AI回答を挿入", "現在の AI の最新回答を取得します (Ctrl+Shift+I)", self.insert_ai_response
        )
        self.insert_ai_button.setObjectName("accentButton")
        self.save_button = self._make_toolbar_button("保存", "プロジェクトを保存 (Ctrl+S)", self.save_project)
        self.open_button = self._make_toolbar_button("開く", "保存済みプロジェクトを開く (Ctrl+O)", self.open_project)
        self.new_button = self._make_toolbar_button("新規作成", "新しいプロジェクト (Ctrl+N)", self.new_project)

        for button in (
            self.reload_office_button,
            self.insert_selection_button,
            self.insert_ai_button,
        ):
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        for button in (self.new_button, self.open_button, self.save_button):
            toolbar.addWidget(button)
        header_layout.addLayout(toolbar)
        layout.addWidget(header)

        self.office_container = QWidget()
        self.office_container_layout = QVBoxLayout(self.office_container)
        self.office_container_layout.setContentsMargins(0, 0, 0, 0)
        self.office_container_layout.setSpacing(0)

        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self.office_container)
        layout.addWidget(self.right_stack, 1)
        return panel

    def _make_toolbar_button(
        self, text: str, tooltip: str, slot: Callable[[], None]
    ) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        self.office_action_buttons.append(button)
        return button

    def _build_office_editor(self) -> None:
        slug = "office"
        profile = self.profiles.get(slug, profile_store_dir() / slug)
        self.office_view = QWebEngineView(self.office_container)
        self.office_page = OfficePage(profile, self.office_view)
        self.office_view.setPage(self.office_page)

        settings = self.office_page.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True
        )

        self.office_channel = QWebChannel(self.office_page)
        self.bridge = OfficeBridge(self)
        self.office_channel.registerObject("officeBridge", self.bridge)
        self.office_page.setWebChannel(self.office_channel)

        self.bridge.readyChanged.connect(self._on_editor_ready)
        self.bridge.changed.connect(self._on_editor_changed)
        self.bridge.statusArrived.connect(self._on_bridge_status)
        self.bridge.errorArrived.connect(self._on_bridge_error)
        self.bridge.saveRequested.connect(self.save_project)
        self.bridge.modeArrived.connect(self._on_js_mode_changed)

        self.office_view.loadStarted.connect(self._on_office_load_started)
        self.office_view.loadFinished.connect(self._on_office_load_finished)

        self.office_container_layout.addWidget(self.office_view, 1)
        self.office_view.setUrl(self._office_entry_url())

        self._set_office_actions_enabled(False)

    def _office_entry_url(self) -> QUrl:
        if self._office_via_http and self._local_server is not None:
            return self._local_server.url()
        return QUrl.fromLocalFile(str(DIST_DIR / "index.html"))

    def _start_http_fallback(self) -> None:
        """Load the built editor over loopback HTTP.

        Some Qt WebEngine builds refuse to evaluate ES modules loaded from a
        ``file://`` URL, which leaves a blank page.  Serving the same local
        files from an ephemeral loopback port is a drop-in remedy; it is only
        started when the on-disk load fails to expose the JavaScript API.
        """
        try:
            self._local_server = StaticFileServer(DIST_DIR)
            self._local_server.start()
        except OSError as exc:
            self.log.error("ローカル静的サーバーを開始できませんでした: %s", exc)
            self.set_status("Error: エディタを読み込めません", "error")
            return
        self._office_via_http = True
        self._office_ready = False
        self.set_status("Loading editor (local server)...", "busy")
        self.office_view.setUrl(self._office_entry_url())

    def _install_shortcuts(self) -> None:
        shortcuts = (
            ("保存", "Ctrl+S", self.save_project),
            ("開く", "Ctrl+O", self.open_project),
            ("新規作成", "Ctrl+N", self.new_project),
            ("Excel", "Ctrl+1", lambda: self.set_editor_mode("spreadsheet")),
            ("Word", "Ctrl+2", lambda: self.set_editor_mode("document")),
            ("Slide", "Ctrl+3", lambda: self.set_editor_mode("slides")),
            ("AI回答を挿入", "Ctrl+Shift+I", self.insert_ai_response),
        )
        for text, key, slot in shortcuts:
            action = QAction(text, self)
            action.setShortcut(QKeySequence(key))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(slot)
            self.addAction(action)
            action.setParent(self)

    # -- helpers -----------------------------------------------------------

    def set_status(self, message: str, level: str = "info") -> None:
        if not hasattr(self, "status_label"):
            return
        colour = {
            "info": C_MUTED,
            "busy": C_ACCENT,
            "ok": C_OK,
            "error": C_ERROR,
        }.get(level, C_MUTED)
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color:{colour};")

    def _update_window_title(self) -> None:
        name = self.current_path.name if self.current_path else "Untitled"
        mark = "*" if self.dirty else ""
        self.setWindowTitle(f"{name}{mark} — {self.config['app_name']}")

    def _show_startup_warnings(self, warnings: list[str]) -> None:
        for warning in warnings:
            self.log.warning(warning)
        QMessageBox.warning(self, self.config["app_name"], "\n\n".join(warnings))

    def _set_office_actions_enabled(self, enabled: bool) -> None:
        for button in self.office_action_buttons:
            if button is self.open_button or button is self.new_button:
                continue
            button.setEnabled(enabled)

    def current_ai_name(self) -> str:
        index = self.ai_tabs.currentIndex()
        if 0 <= index < len(WEB_ORDER):
            return WEB_ORDER[index]
        return WEB_ORDER[0]

    def current_ai_view(self) -> QWebEngineView:
        return self._ensure_ai_view(self.current_ai_name())

    def register_popup(self, view: QWebEngineView) -> None:
        self._popups.append(view)
        view.destroyed.connect(lambda _obj=None, v=view: self._forget_popup(v))

    def _forget_popup(self, view: QWebEngineView) -> None:
        try:
            self._popups.remove(view)
        except ValueError:
            pass

    # -- AI tab behaviour --------------------------------------------------

    def _on_ai_tab_changed(self, index: int) -> None:
        if index < 0 or not hasattr(self, "ai_stack"):
            return
        if index >= len(WEB_ORDER):
            return
        name = WEB_ORDER[index]
        view = self._ensure_ai_view(name)
        self.ai_stack.setCurrentWidget(view)
        self.ai_status_label.setText(name)
        self.error_banner.setVisible(bool(self._ai_error_url.get(name)))
        self._refresh_navigation_state()
        self._save_ui_state()

    def _refresh_navigation_state(self) -> None:
        if not hasattr(self, "back_button"):
            return
        index = self.ai_tabs.currentIndex()
        if index < 0 or index >= len(WEB_ORDER):
            return
        view = self.ai_views.get(WEB_ORDER[index])
        if view is None:
            return
        history = view.history()
        self.back_button.setEnabled(history.canGoBack())
        self.forward_button.setEnabled(history.canGoForward())
        self.url_label.setText(view.url().toString())

    def _on_ai_url_changed(self, name: str, url: QUrl) -> None:
        if name == self.current_ai_name():
            self.url_label.setText(url.toString())
            self._refresh_navigation_state()

    def _ai_back(self) -> None:
        self.current_ai_view().back()

    def _ai_forward(self) -> None:
        self.current_ai_view().forward()

    def _ai_reload(self) -> None:
        view = self.current_ai_view()
        self._ai_error_url.pop(self.current_ai_name(), None)
        self._refresh_navigation_state()
        view.reload()

    def _on_ai_load_started(self, name: str) -> None:
        if name == self.current_ai_name():
            self.set_status(f"Loading site... ({name})", "busy")
        self._refresh_navigation_state()

    def _on_ai_load_progress(self, name: str, value: int) -> None:
        if name == self.current_ai_name():
            self.set_status(f"Loading AI... ({name}) {value}%", "busy")

    def _on_ai_load_finished(self, name: str, ok: bool) -> None:
        if ok:
            self._ai_error_url.pop(name, None)
            if name == self.current_ai_name():
                self.error_banner.setVisible(False)
                self.set_status("Ready", "info")
        else:
            view = self._ensure_ai_view(name)
            url = view.url().toString()
            self._ai_error_url[name] = url
            if name == self.current_ai_name() and hasattr(self, "error_banner"):
                self.error_label.setText(
                    f"{name} のページを読み込めませんでした。\n{url}\n"
                    "ネットワーク、プロキシ、またはサービス側の制限を確認してください。"
                )
                self.error_banner.setVisible(True)
                self.set_status(f"Error: {name} の読み込みに失敗しました", "error")
        self._refresh_navigation_state()

    def _retry_failed_ai_page(self) -> None:
        name = self.current_ai_name()
        self._ai_error_url.pop(name, None)
        self.error_banner.setVisible(False)
        self._ensure_ai_view(name).reload()

    def _force_open_error_url(self) -> None:
        url = self._ai_error_url.get(self.current_ai_name())
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _open_current_ai_external(self) -> None:
        url = self.current_ai_view().url()
        if url.isValid() and not url.isEmpty():
            QDesktopServices.openUrl(url)

    # -- AI downloads ------------------------------------------------------

    def _install_download_handler(self, profile: QWebEngineProfile, slug: str) -> None:
        """Save files an AI page offers for download.

        Without a handler Qt cancels the download silently, which is why a
        file generated inside the built-in browser never reached the editor.
        """
        if slug in self._download_profiles:
            return
        signal = getattr(profile, "downloadRequested", None)
        if signal is None:
            self.log.warning(
                "この Qt ビルドではダウンロードを捕捉できません（%s）", slug
            )
            return
        self._download_profiles.add(slug)
        signal.connect(self._on_download_requested)

    def _download_directory(self) -> Path:
        directory = documents_dir() / "downloads"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _unique_download_path(self, name: str) -> Path:
        directory = self._download_directory()
        safe_name = Path(name).name or "download"
        candidate = directory / safe_name
        stem, suffix = candidate.stem, candidate.suffix
        counter = 2
        while candidate.exists():
            candidate = directory / f"{stem} ({counter}){suffix}"
            counter += 1
        return candidate

    def _on_download_requested(self, download: Any) -> None:
        name = "download"
        try:
            name = Path(str(download.downloadFileName())).name or "download"
        except Exception:  # noqa: BLE001 - Qt objects must never break the UI
            pass

        target = self._unique_download_path(name)

        # Connect before accept(): a very small file can finish immediately.
        state_changed = getattr(download, "stateChanged", None)
        if state_changed is not None:
            state_changed.connect(
                lambda _state, d=download, p=target: self._on_download_state(d, p)
            )
        else:
            finished = getattr(download, "isFinishedChanged", None)
            if finished is not None:
                finished.connect(
                    lambda d=download, p=target: self._on_download_state(d, p)
                )

        try:
            if hasattr(download, "setDownloadDirectory"):
                download.setDownloadDirectory(str(target.parent))
                download.setDownloadFileName(target.name)
            else:  # Qt older than 6.5
                download.setPath(str(target))
            download.accept()
        except Exception as exc:  # noqa: BLE001 - Qt objects must never break the UI
            self.log.error("ダウンロードを開始できませんでした: %s", exc)
            self.set_status("Error: ダウンロードを開始できませんでした", "error")
            return

        self.set_status(f"Downloading {target.name} ...", "busy")

    def _on_download_state(self, download: Any, path: Path) -> None:
        state = getattr(download, "state", None)
        if not callable(state):
            return
        value = state()
        name = getattr(value, "name", "") or str(value)
        if name.endswith("Completed") and str(path) not in self._download_import_offered:
            self._download_import_offered.add(str(path))
            self.set_status(f"Downloaded: {path.name}", "ok")
            # Give Qt a tick to flush the file before checking its size.  This
            # also makes the confirmation reliable for very small downloads.
            QTimer.singleShot(100, lambda p=path: self._offer_download_import(p))
        elif name.endswith("Interrupted"):
            self.set_status(f"Error: ダウンロードに失敗しました（{path.name}）", "error")

    def _offer_download_import(self, path: Path) -> None:
        """Offer to pull a freshly downloaded file into the matching editor."""
        if IMPORT_EXTENSIONS.get(path.suffix.lower()) is None:
            return
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size <= 0:
            self.set_status(
                f"Error: ダウンロードしたファイルを確認できません（{path.name}）",
                "error",
            )
            return
        if size > MAX_IMPORT_BYTES:
            self.set_status("Error: ファイルが大きすぎるため取り込めません", "error")
            return

        box = QMessageBox(self)
        box.setWindowTitle("ダウンロードしたファイル")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"{path.name} をダウンロードしました。")
        box.setInformativeText(
            "エディタで開きますか？\n"
            "既存の内容は残したまま末尾に追加し、取り込んだシートへ移動します。"
        )
        open_button = box.addButton(
            "開いて取り込む", QMessageBox.ButtonRole.AcceptRole
        )
        box.addButton("保存だけ", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_button:
            self.import_file_into_editor(path)

    def import_file_into_editor(self, path: Path) -> None:
        """Send a local Office file to the React side for import."""
        if not self._ensure_editor():
            return
        try:
            payload = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError as exc:
            self.log.warning("取り込むファイルを読み込めませんでした: %s", exc)
            self.set_status("Error: ファイルを読み込めません", "error")
            return
        self.set_status(f"Importing {path.name} ...", "busy")
        self._office_request("importFile", (path.name, payload))

    # -- Office editor -----------------------------------------------------

    def _office_eval(self, expression: str, callback: Optional[Callable[[Any], None]] = None) -> None:
        if not hasattr(self, "office_page"):
            return
        script = (
            "(function(){try{return (" + expression + ");}"
            "catch(e){console.error('office call failed',e);"
            "return JSON.stringify({ok:false,error:String(e)});}})()"
        )
        try:
            self.office_page.runJavaScript(script, callback or (lambda _result: None))
        except RuntimeError as exc:
            # The page can already be gone while the application shuts down.
            self.log.warning("runJavaScript を実行できませんでした: %s", exc)

    def _office_request(
        self,
        method: str,
        args: tuple[Any, ...] = (),
        callback: Optional[Callable[[Any], None]] = None,
    ) -> None:
        arguments = ", ".join(js_data(arg) for arg in args)
        expression = (
            "window.officeEditor && typeof window.officeEditor." + method + " === 'function'"
            f" ? window.officeEditor.{method}({arguments}) : null"
        )
        self._office_eval(expression, callback)

    def _ensure_editor(self) -> bool:
        if self._office_ready:
            return True
        QMessageBox.warning(
            self,
            "Office エディタ",
            "Office エディタがまだ初期化されていません。\n"
            "しばらく待つか、「更新」でエディタを再読み込みしてください。",
        )
        self.set_status("Error: エディタ未初期化", "error")
        return False

    def _on_office_load_started(self) -> None:
        self._office_ready = False
        self._set_office_actions_enabled(False)
        self.set_status("Loading editor...", "busy")

    def _on_office_load_finished(self, ok: bool) -> None:
        if not ok:
            self.set_status("Error: エディタの読み込みに失敗しました", "error")
            QMessageBox.critical(
                self,
                "Office エディタ",
                "Office エディタを読み込めませんでした。\n"
                f"{DIST_DIR / 'index.html'}\n\n"
                "フロントエンドをビルドし直してください: npm run build",
            )
            return

        # Ask the page whether its API exists yet; never assume readiness by
        # sleeping.  The check is retried briefly because React commits its
        # first render asynchronously after the load event.
        self._poll_editor_ready(20)

    def _poll_editor_ready(self, remaining: int) -> None:
        if self._closing:
            return

        def check(raw: Any) -> None:
            if bool(raw):
                self._on_editor_ready()
                return
            if remaining <= 0:
                if not self._office_via_http:
                    # Retry once through the loopback server before giving up.
                    self._start_http_fallback()
                    return
                self.set_status("Error: エディタ API が初期化されていません", "error")
                return
            QTimer.singleShot(250, lambda: self._poll_editor_ready(remaining - 1))

        self._office_eval(
            "window.officeEditor && typeof window.officeEditor.isReady === 'function'"
            " ? window.officeEditor.isReady() : false",
            check,
        )

    def _on_editor_ready(self) -> None:
        if self._office_ready:
            return
        self._office_ready = True
        self._set_office_actions_enabled(True)
        self.set_status("Ready")

        if self._pending_restore is not None:
            data = self._pending_restore
            self._pending_restore = None
            self._apply_project_data(data, "reload")
            return

        if self._startup_restore:
            self._startup_restore = False
            autosave = self._load_autosave()
            if autosave is not None:
                self._apply_project_data(autosave, "autosave", mark_dirty=False)
            else:
                self._sync_mode_buttons("spreadsheet")

    def _on_editor_changed(self) -> None:
        if not self.dirty:
            self.dirty = True
            self._update_window_title()
        self.autosave_timer.start()

    def _on_bridge_status(self, message: str) -> None:
        self.set_status(message)

    def _on_bridge_error(self, message: str) -> None:
        self.set_status(f"Error: {message}", "error")

    def _on_js_mode_changed(self, mode: str) -> None:
        if mode in MODES:
            self._sync_mode_buttons(mode)

    def _sync_mode_buttons(self, mode: str) -> None:
        # The local Excel / Word / Slide tabs live inside the React editor.
        # Qt only mirrors the active mode in the status bar and makes sure the
        # "Office" pane is showing (e.g. after Ctrl+2 while a Google tab is open).
        self.mode_status_label.setText(MODE_LABELS.get(mode, mode))
        if hasattr(self, "right_tabs") and self.right_tabs.currentIndex() != 0:
            self.right_tabs.setCurrentIndex(0)

    def set_editor_mode(self, mode: str) -> None:
        if mode not in MODES:
            return
        if not self._office_ready:
            self._sync_mode_buttons(mode)
            return

        def done(raw: Any) -> None:
            result = parse_office_result(raw)
            if result.get("ok"):
                self._sync_mode_buttons(mode)
            else:
                self._on_bridge_error(str(result.get("error", "モードを切り替えられません")))

        self._office_request("setMode", (mode,), done)
        self._sync_mode_buttons(mode)

    # -- AI answer extraction ---------------------------------------------

    def insert_ai_response(self) -> None:
        if not self._ensure_editor():
            return
        name = self.current_ai_name()
        view = self._ensure_ai_view(name)
        self.set_status("Extracting response...", "busy")
        view.page().runJavaScript(build_extraction_script(name), self._on_extracted)

    def _on_extracted(self, raw: Any) -> None:
        result: dict[str, Any] = {"ok": False, "reason": "unknown"}
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    result = parsed
            except ValueError:
                result = {"ok": False, "reason": "invalid"}

        text = result.get("text") if isinstance(result.get("text"), str) else ""
        if result.get("ok") and text.strip():
            self.set_status(f"Extracted response ({len(text)} chars)", "ok")
            self._show_insert_menu(text)
            return

        self.set_status("Extracting response failed", "error")
        self._offer_extraction_fallback(result)

    def _offer_extraction_fallback(self, result: dict[str, Any]) -> None:
        reason = result.get("reason", "unknown")
        detail = result.get("detail")
        message = (
            "AI の回答を自動で取得できませんでした。\n"
            f"理由: {reason}\n"
            "AI サイトの画面構成が変わった可能性があります。\n\n"
            "代替の方法を選んでください。"
        )
        if detail:
            message += f"\n\n詳細: {detail}"

        box = QMessageBox(self)
        box.setWindowTitle("AI 回答の取得")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(message)
        use_selection = box.addButton(
            "選択テキストを使用", QMessageBox.ButtonRole.AcceptRole
        )
        paste_manual = box.addButton("手動で貼り付け", QMessageBox.ButtonRole.ActionRole)
        box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()

        if clicked is use_selection:
            self.insert_selection()
        elif clicked is paste_manual:
            self._open_manual_paste()

    def insert_selection(self) -> None:
        if not self._ensure_editor():
            return
        view = self.current_ai_view()
        self.set_status("Extracting response...", "busy")
        view.page().runJavaScript(SELECTION_JS, self._on_selection_extracted)

    def _on_selection_extracted(self, raw: Any) -> None:
        text = raw if isinstance(raw, str) else ""
        if text.strip():
            self.set_status(f"Selected text ({len(text)} chars)", "ok")
            self._show_insert_menu(text)
            return

        self.set_status("Error: AI 画面でテキストが選択されていません", "error")
        box = QMessageBox(self)
        box.setWindowTitle("選択テキスト")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            "AI 画面でテキストが選択されていません。\n"
            "文字列を選択してから再実行するか、手動で貼り付けてください。"
        )
        paste = box.addButton("手動で貼り付け", QMessageBox.ButtonRole.ActionRole)
        box.addButton("閉じる", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is paste:
            self._open_manual_paste()

    def _open_manual_paste(self) -> None:
        dialog = ManualPasteDialog(self)
        if not dialog.exec():
            return
        text = dialog.text()
        if not text.strip():
            self.set_status("Error: テキストが空です", "error")
            return
        self._show_insert_menu(text)

    def _show_insert_menu(self, text: str) -> None:
        if not self._ensure_editor():
            return
        dialog = InsertResponseDialog(text, self)
        if not dialog.exec():
            self.set_status("Ready")
            return
        self._apply_ai_action(text, dialog.selected_action())

    def _apply_ai_action(self, text: str, action: str) -> None:
        if action not in ("text", "table", "document", "slides"):
            self.set_status("Ready")
            return

        def on_plan(raw: Any) -> None:
            plan = parse_office_result(raw)
            if not plan.get("ok"):
                error = plan.get("error") or plan.get("message") or "変換できませんでした。"
                self.set_status(f"Error: {error}", "error")
                QMessageBox.warning(self, "AI 回答の挿入", str(error))
                return

            if plan.get("needsConfirm"):
                message = plan.get("message") or "続行しますか？"
                confirm = QMessageBox(self)
                confirm.setWindowTitle("確認")
                confirm.setIcon(QMessageBox.Icon.Question)
                confirm.setText(str(message))
                confirm.setStandardButtons(
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                confirm.setDefaultButton(QMessageBox.StandardButton.No)
                confirm.exec()
                clicked = confirm.clickedButton()
                answer = (
                    confirm.standardButton(clicked)
                    if clicked is not None
                    else QMessageBox.StandardButton.NoButton
                )
                if answer != QMessageBox.StandardButton.Yes:
                    self.set_status("Ready")
                    return

            self.set_status("Inserting AI response...", "busy")

            def on_applied(raw_result: Any) -> None:
                result = parse_office_result(raw_result)
                if result.get("ok"):
                    message = result.get("message") or "AI 回答を挿入しました。"
                    self.set_status(str(message), "ok")
                else:
                    error = result.get("error") or "挿入に失敗しました。"
                    self.set_status(f"Error: {error}", "error")
                    QMessageBox.warning(self, "AI 回答の挿入", str(error))

            self._office_request("applyAiResponse", (text, action, True), on_applied)

        self._office_request("planAiResponse", (text, action), on_plan)

    # -- saving / loading --------------------------------------------------

    def _autosave_path(self) -> Path:
        return app_data_dir() / "autosave.json"

    def _ui_state_path(self) -> Path:
        return app_data_dir() / "ui_state.json"

    def _run_autosave(self) -> None:
        if not self._office_ready:
            return

        def on_content(raw: Any) -> None:
            if not isinstance(raw, str):
                return
            try:
                data = json.loads(raw)
                if not isinstance(data, dict):
                    return
                data.setdefault("metadata", {})
                data["metadata"]["title"] = (
                    self.current_path.stem if self.current_path else "Untitled"
                )
                atomic_write_json(self._autosave_path(), data)
                self.set_status("Saved (auto)", "ok")
            except (OSError, ValueError) as exc:
                self.log.warning("自動保存に失敗しました: %s", exc)
                self.set_status(f"Error: 自動保存に失敗しました", "error")

        self._office_request("getAllContent", (), on_content)

    def _load_autosave(self) -> Optional[dict[str, Any]]:
        path = self._autosave_path()
        if not path.exists():
            return None
        try:
            return normalize_project(read_json_file(path))
        except (OSError, ValueError) as exc:
            self.log.warning("自動保存データを読み込めませんでした: %s", exc)
            return None

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("未保存の変更")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("保存されていない変更があります。")
        box.setInformativeText("保存しますか？破棄しますか？")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        box.exec()
        clicked = box.clickedButton()
        answer = (
            box.standardButton(clicked)
            if clicked is not None
            else QMessageBox.StandardButton.NoButton
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Discard:
            return True
        self.save_project()
        return False

    def save_project(self) -> None:
        if self._save_in_progress:
            return
        if not self._ensure_editor():
            return
        if self.current_path is None:
            self.save_project_as()
            return
        self._save_to_path(self.current_path)

    def save_project_as(self) -> None:
        if not self._ensure_editor():
            return
        suggested = (
            str(self.current_path)
            if self.current_path
            else str(documents_dir() / "Untitled.aiow.json")
        )
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "プロジェクトを保存",
            suggested,
            "AI Office Workspace (*.json);;すべてのファイル (*)",
        )
        if not path:
            return
        self._save_to_path(Path(path))

    def _save_to_path(self, path: Path, close_after: bool = False) -> None:
        self._save_in_progress = True
        self.set_status("Saving...", "busy")

        def on_content(raw: Any) -> None:
            try:
                if not isinstance(raw, str):
                    self.set_status("Error: エディタからデータを取得できません", "error")
                    return
                try:
                    data = json.loads(raw)
                    if not isinstance(data, dict):
                        raise ValueError("エディタのデータ形式が不正です")
                except ValueError as exc:
                    self.set_status("Error: 保存データを作成できません", "error")
                    QMessageBox.critical(self, "保存エラー", str(exc))
                    return

                data["format"] = "ai-office-workspace"
                data["version"] = 1
                metadata = data.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}
                metadata["title"] = path.stem
                metadata["updatedAt"] = utc_now()
                data["metadata"] = metadata

                try:
                    atomic_write_json(path, data)
                except OSError as exc:
                    self.set_status("Error: 保存に失敗しました", "error")
                    QMessageBox.critical(
                        self,
                        "保存エラー",
                        f"{path}\n\n{exc}\n\n書き込み権限のあるフォルダを指定してください。",
                    )
                    return

                self.current_path = path
                self.dirty = False
                self._update_window_title()
                self._save_ui_state()
                self.set_status(f"Saved: {path.name}", "ok")

                if close_after:
                    self._closing = True
                    self.close()
            finally:
                self._save_in_progress = False

        self._office_request("getAllContent", (), on_content)

    def open_project(self) -> None:
        if not self._ensure_editor():
            return
        if not self._confirm_discard():
            return
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "プロジェクトを開く",
            str(documents_dir()),
            "AI Office Workspace (*.json);;すべてのファイル (*)",
        )
        if not path:
            return
        try:
            data = normalize_project(read_json_file(Path(path)))
        except (OSError, ValueError) as exc:
            QMessageBox.critical(
                self,
                "読み込みエラー",
                f"{path}\n\n{exc}\n\nファイルが破損しているか、形式が異なります。",
            )
            self.set_status("Error: プロジェクトを読み込めません", "error")
            return
        self.current_path = Path(path)
        self.dirty = False
        self._apply_project_data(data, "file")
        self._update_window_title()

    def new_project(self) -> None:
        if not self._ensure_editor():
            return
        if not self._confirm_discard():
            return
        self.current_path = None
        self.dirty = False
        self._apply_project_data(copy.deepcopy(EMPTY_PROJECT), "new")
        self._update_window_title()

    def _apply_project_data(
        self,
        data: dict[str, Any],
        source: str,
        mark_dirty: bool = False,
    ) -> None:
        if not self._office_ready:
            self._pending_restore = data
            return

        def on_applied(raw: Any) -> None:
            result = parse_office_result(raw)
            if not result.get("ok"):
                self.set_status("Error: プロジェクトを復元できません", "error")
                QMessageBox.warning(
                    self,
                    "復元エラー",
                    str(result.get("error", "プロジェクトを復元できませんでした。")),
                )
                return
            self.dirty = mark_dirty
            self._update_window_title()
            mode = data.get("activeMode", "spreadsheet")
            self._sync_mode_buttons(mode)
            label = {
                "autosave": "前回の作業データを復元しました",
                "file": "プロジェクトを開きました",
                "new": "新しいプロジェクトを作成しました",
                "reload": "エディタを再読み込みしました",
            }.get(source, "読み込みました")
            self.set_status(label, "ok")

        self._office_request("setContent", (data,), on_applied)

    def reload_office(self) -> None:
        if not self._ensure_editor():
            return

        def on_content(raw: Any) -> None:
            parsed: Optional[dict[str, Any]] = None
            if isinstance(raw, str):
                try:
                    candidate = json.loads(raw)
                    if isinstance(candidate, dict):
                        parsed = candidate
                except ValueError:
                    parsed = None

            if parsed is None:
                # Reloading without a snapshot would silently discard the
                # current work, so the reload is cancelled instead.
                self.set_status(
                    "Error: 再読み込みを中止しました（内容を取得できません）", "error"
                )
                QMessageBox.warning(
                    self,
                    "更新",
                    "現在の編集内容を取得できなかったため、再読み込みを中止しました。\n"
                    "データを失わないための措置です。",
                )
                return

            self._pending_restore = parsed
            self._office_ready = False
            self._set_office_actions_enabled(False)
            self.set_status("Loading editor...", "busy")
            self.office_view.reload()

        self._office_request("getAllContent", (), on_content)

    # -- UI state ----------------------------------------------------------

    def _restore_ui_state(self) -> None:
        self._restoring_ui = True
        try:
            self._restore_ui_state_inner()
        finally:
            self._restoring_ui = False

    def _restore_ui_state_inner(self) -> None:
        path = self._ui_state_path()
        state: dict[str, Any] = {}
        if path.exists():
            try:
                raw = read_json_file(path)
                if isinstance(raw, dict):
                    state = raw
            except (OSError, ValueError) as exc:
                self.log.warning("UI 状態を読み込めませんでした: %s", exc)

        saved_path = state.get("currentPath")
        if isinstance(saved_path, str) and saved_path:
            self.current_path = Path(saved_path)

        sizes = state.get("splitter")
        layout_version = state.get("layoutVersion")
        if (
            layout_version == UI_STATE_LAYOUT_VERSION
            and isinstance(sizes, list)
            and len(sizes) == 2
            and all(isinstance(value, int) and value > 0 for value in sizes)
        ):
            self.splitter.setSizes(sizes)

        tab_index = state.get("aiTab")
        if isinstance(tab_index, int) and 0 <= tab_index < len(WEB_ORDER):
            self.ai_tabs.setCurrentIndex(tab_index)
        else:
            self.ai_tabs.setCurrentIndex(0)
        self._on_ai_tab_changed(self.ai_tabs.currentIndex())

        right_tab = state.get("rightTab")
        if isinstance(right_tab, int) and 0 <= right_tab <= len(GOOGLE_ORDER):
            self.right_tabs.setCurrentIndex(right_tab)

    def _save_ui_state(self) -> None:
        if self._restoring_ui:
            return
        state = {
            "layoutVersion": UI_STATE_LAYOUT_VERSION,
            "splitter": self.splitter.sizes(),
            "aiTab": self.ai_tabs.currentIndex(),
            "rightTab": self.right_tabs.currentIndex(),
            "currentPath": str(self.current_path) if self.current_path else "",
        }
        try:
            atomic_write_json(self._ui_state_path(), state)
        except OSError as exc:
            self.log.warning("UI 状態を保存できませんでした: %s", exc)

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        if not hasattr(self, "_splitter_timer"):
            self._splitter_timer = QTimer(self)
            self._splitter_timer.setSingleShot(True)
            self._splitter_timer.setInterval(400)
            self._splitter_timer.timeout.connect(self._save_ui_state)
        self._splitter_timer.start()

    # -- shutdown ----------------------------------------------------------

    def _confirm_close(self) -> bool:
        if not self.dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("終了の確認")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("保存されていない変更があります。")
        box.setInformativeText("保存してから終了しますか？")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        box.exec()
        clicked = box.clickedButton()
        answer = (
            box.standardButton(clicked)
            if clicked is not None
            else QMessageBox.StandardButton.NoButton
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Discard:
            return True

        if self.current_path is None:
            path, _selected = QFileDialog.getSaveFileName(
                self,
                "プロジェクトを保存",
                str(documents_dir() / "Untitled.aiow.json"),
                "AI Office Workspace (*.json);;すべてのファイル (*)",
            )
            if not path:
                return False
            self.current_path = Path(path)
        self._save_to_path(self.current_path, close_after=True)
        return False

    def _finalize_close(self, raw: Any) -> None:
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    metadata = data.get("metadata")
                    if not isinstance(metadata, dict):
                        metadata = {}
                    metadata["title"] = (
                        self.current_path.stem if self.current_path else "Untitled"
                    )
                    data["metadata"] = metadata
                    atomic_write_json(self._autosave_path(), data)
            except (OSError, ValueError) as exc:
                self.log.warning("終了時の自動保存に失敗しました: %s", exc)
        self._save_ui_state()
        self._closing = True
        self.close()

    def _stop_local_server(self) -> None:
        if self._local_server is not None:
            self._local_server.stop()
            self._local_server = None

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._closing:
            self._save_ui_state()
            self._stop_local_server()
            event.accept()
            return

        if not self._confirm_close():
            event.ignore()
            return

        if self._office_ready:
            event.ignore()
            self._office_request("getAllContent", (), self._finalize_close)
            return

        self._save_ui_state()
        self._stop_local_server()
        event.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C_BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(C_TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(C_SUB))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(C_PANEL))
    palette.setColor(QPalette.ColorRole.Text, QColor(C_TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(C_PANEL))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(C_TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(C_ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(C_PANEL))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(C_TEXT))
    return palette


def apply_dark_title_bar(window: QMainWindow) -> None:
    """Ask Windows 10/11 to draw the native title bar dark.

    This is cosmetic and entirely optional: any failure leaves the standard
    title bar in place.  It keeps the window from having a bright white frame
    around the dark UI.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes  # noqa: PLC0415 - Windows only

        hwnd = int(window.winId())
        enabled = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new/old)
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)
            )
            if result == 0:
                break
    except Exception:  # noqa: BLE001 - purely cosmetic
        logging.getLogger(__name__).debug("ダークタイトルバーを適用できませんでした")


def main() -> int:
    configure_logging()
    log = logging.getLogger("ai-office-workspace")

    QApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True
    )
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    icon = QIcon(str(icon_path()))
    if not icon.isNull():
        app.setWindowIcon(icon)
    # No organization name: QStandardPaths then resolves AppDataLocation to
    # %APPDATA%/AI Office Workspace without an extra nesting level.
    app.setApplicationName("AI Office Workspace")
    app.setApplicationDisplayName("AI Office Workspace")

    config_problem = ensure_user_config()
    config, warnings = load_config()
    if config_problem:
        warnings.insert(0, config_problem)
    app.setApplicationName(config["app_name"])

    app.setPalette(dark_palette())
    app.setStyleSheet(
        QSS_TEMPLATE
        % {
            "bg": C_BG,
            "sub": C_SUB,
            "panel": C_PANEL,
            "border": C_BORDER,
            "text": C_TEXT,
            "muted": C_MUTED,
            "accent": C_ACCENT,
        }
    )

    problem = prepare_environment()
    if problem:
        QMessageBox.critical(None, config["app_name"], problem)
        return 1

    try:
        window = MainWindow(config, warnings)
    except Exception as exc:  # pragma: no cover - startup failure only
        log.exception("起動に失敗しました")
        QMessageBox.critical(
            None,
            config["app_name"],
            f"起動中にエラーが発生しました。\n\n{exc}",
        )
        return 1

    window.show()
    apply_dark_title_bar(window)
    exit_code = app.exec()

    # Destroy the window (and therefore its pages) before the profiles, which
    # are parented to the application object.
    try:
        window.close()
        window.deleteLater()
        app.processEvents()
    except RuntimeError:  # pragma: no cover - already destroyed
        pass
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
