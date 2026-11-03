#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI Office Workspace - セットアップウィザード（setup.exe の中身）.

``packaging/build.bat`` がこのファイルを PyInstaller で ``setup.exe`` に固める
（``packaging/setup.spec``）。アプリ一式は ``payload.zip`` として setup.exe に同梱
されるので、インストール先の PC に Python もインターネット接続も要らない。

画面の流れ:

    ようこそ -> インストール先 -> ショートカット -> インストール中 -> 完了

- インストール先は画面で選べる（既定は ``%LOCALAPPDATA%\\Programs\\AI Office Workspace``）。
- デスクトップ／スタートメニューのショートカットはチェックボックスで選ぶ（既定は両方 ON）。
- アンインストール情報を HKCU に登録するので、
  「設定 -> アプリ -> インストールされているアプリ」から削除できる。

このファイルはアプリ本体（main.py）の実行時には読み込まれない。
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import traceback
import winreg
import zipfile
from pathlib import Path
from typing import Callable, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_NAME = "AI Office Workspace"
APP_VERSION = "1.0.3"
APP_EXE_NAME = "AIOfficeWorkspace.exe"

#: Key under HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall.
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AIOfficeWorkspace"

SHORTCUT_NAME = f"{APP_NAME}.lnk"

#: Colours shared with the application window so setup does not look foreign.
C_BG = "#111318"
C_PANEL = "#1B1E25"
C_FIELD = "#20242C"
C_BORDER = "#343943"
C_TEXT = "#F2F3F5"
C_MUTED = "#A0A6B2"
C_ACCENT = "#5B8DEF"
C_ACCENT_HOVER = "#6F9BF3"
C_ERROR = "#F2777A"
C_OK = "#6FCF97"

FONT_FAMILY = "Yu Gothic UI"
FONT = (FONT_FAMILY, 10)
FONT_SMALL = (FONT_FAMILY, 9)
FONT_BOLD = (FONT_FAMILY, 11, "bold")
FONT_TITLE = (FONT_FAMILY, 16, "bold")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def bundle_dir() -> Path:
    """Directory that holds the bundled files (``payload.zip`` / ``app.ico``)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


PAYLOAD_PATH = bundle_dir() / "payload.zip"
ICON_PATH = bundle_dir() / "app.ico"

_payload_size: Optional[int] = None


def payload_size() -> int:
    """Uncompressed size of the application files (bytes)."""
    global _payload_size
    if _payload_size is None:
        try:
            with zipfile.ZipFile(PAYLOAD_PATH) as archive:
                _payload_size = sum(member.file_size for member in archive.infolist())
        except (OSError, zipfile.BadZipFile):
            _payload_size = 0
    return _payload_size


def format_size(value: int) -> str:
    if value >= 1024 * 1024 * 1024:
        return f"{value / (1024 * 1024 * 1024):.1f} GB"
    return f"{value / (1024 * 1024):.0f} MB"


def free_space(path: Path) -> Optional[int]:
    """Free bytes on the volume that holds ``path`` (works for missing folders)."""
    candidate = path
    while True:
        try:
            return shutil.disk_usage(candidate).free
        except OSError:
            if candidate.parent == candidate:
                return None
            candidate = candidate.parent


def default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "Programs" / APP_NAME


def _shell_folder(name: str, fallback: Path) -> Path:
    """Read a shell folder (Desktop, Programs, ...) from the registry.

    A redirected Desktop (OneDrive) is not ``%USERPROFILE%\\Desktop``, so the
    Explorer setting is the only reliable source.
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            value, _ = winreg.QueryValueEx(key, name)
        expanded = os.path.expandvars(str(value))
        if expanded:
            return Path(expanded)
    except OSError:
        pass
    return fallback


def desktop_dir() -> Path:
    return _shell_folder("Desktop", Path.home() / "Desktop")


def start_menu_dir() -> Path:
    fallback = (
        Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
    )
    return _shell_folder("Programs", fallback)


# ---------------------------------------------------------------------------
# Shell helpers (shortcuts / uninstall command)
# ---------------------------------------------------------------------------


def _ps_quote(value: object) -> str:
    """Embed a value in a PowerShell single-quoted string."""
    return str(value).replace("'", "''")


def _run_powershell(command: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def create_shortcut(link_path: Path, target: Path) -> None:
    """Create a ``.lnk`` that starts ``target`` (icon and working dir included)."""
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.exists():
        try:
            link_path.unlink()
        except OSError:
            pass
    command = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$link = $shell.CreateShortcut('{_ps_quote(link_path)}'); "
        f"$link.TargetPath = '{_ps_quote(target)}'; "
        f"$link.WorkingDirectory = '{_ps_quote(target.parent)}'; "
        f"$link.IconLocation = '{_ps_quote(target)},0'; "
        f"$link.Description = '{_ps_quote(APP_NAME)}'; "
        "$link.Save()"
    )
    result = _run_powershell(command)
    if result.returncode != 0 or not link_path.exists():
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"ショートカットを作成できませんでした: {link_path}")


def uninstall_command(target: Path, shortcuts: list[Path]) -> str:
    """Command line stored as ``UninstallString``.

    A PowerShell one-liner instead of a generated ``uninstall.cmd``: it is not
    locked while running, so it can delete the folder it was started from.
    """
    removals = "; ".join(
        f"Remove-Item -LiteralPath '{_ps_quote(path)}' -Recurse -Force "
        "-ErrorAction SilentlyContinue"
        for path in [*shortcuts, target]
    )
    script = (
        "Start-Sleep -Milliseconds 800; "
        "Get-Process -Name 'AIOfficeWorkspace' -ErrorAction SilentlyContinue | "
        "Stop-Process -Force -ErrorAction SilentlyContinue; "
        "Start-Sleep -Milliseconds 400; "
        f"{removals}; "
        f"Remove-Item -LiteralPath 'HKCU:\\{UNINSTALL_KEY}' -Recurse -Force "
        "-ErrorAction SilentlyContinue"
    )
    return f'powershell.exe -NoProfile -WindowStyle Hidden -Command "{script}"'


def write_uninstall_entry(target: Path, shortcuts: list[Path], size_kb: int) -> None:
    exe = target / APP_EXE_NAME
    key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_WRITE)
    with key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(target))
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, f"{exe},0")
        winreg.SetValueEx(
            key, "UninstallString", 0, winreg.REG_SZ, uninstall_command(target, shortcuts)
        )
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, max(size_kb, 1))


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def install(
    target: Path,
    create_desktop: bool,
    create_start_menu: bool,
    report: Callable[[str, float], None],
) -> list[str]:
    """Copy the application to ``target``; returns non-fatal warnings."""
    if not PAYLOAD_PATH.exists():
        raise RuntimeError(f"インストール用のデータが見つかりません: {PAYLOAD_PATH}")

    target = target.expanduser()
    if target.exists() and not target.is_dir():
        raise RuntimeError(f"インストール先にファイルがあります: {target}")

    report("準備しています...", 0.01)
    target.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []

    # An older copy of the app is replaced completely so no stale DLL remains.
    # Settings and logins live in %APPDATA%, so nothing of the user is lost.
    if (target / APP_EXE_NAME).exists():
        report("前のバージョンを削除しています...", 0.03)
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(PAYLOAD_PATH) as archive:
        members = archive.infolist()
        total = sum(max(member.file_size, 1) for member in members)
        done = 0
        for member in members:
            fraction = 0.05 + 0.80 * (done / total)
            report(f"コピーしています... {member.filename}", fraction)
            archive.extract(member, target)
            done += max(member.file_size, 1)
    report("コピーしています...", 0.85)

    app_exe = target / APP_EXE_NAME
    if not app_exe.exists():
        raise RuntimeError(f"アプリ本体が見つかりません: {app_exe}")

    desktop_link = desktop_dir() / SHORTCUT_NAME
    start_link = start_menu_dir() / SHORTCUT_NAME
    shortcuts: list[Path] = []

    report("ショートカットを作成しています...", 0.88)
    for wanted, link, label in (
        (create_desktop, desktop_link, "デスクトップ"),
        (create_start_menu, start_link, "スタートメニュー"),
    ):
        if not wanted:
            continue
        try:
            create_shortcut(link, app_exe)
            shortcuts.append(link)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            warnings.append(f"{label}のショートカットを作成できませんでした（{exc}）")

    report("アンインストール情報を登録しています...", 0.94)
    try:
        write_uninstall_entry(target, shortcuts, payload_size() // 1024)
    except OSError as exc:
        warnings.append(f"アンインストール情報を登録できませんでした（{exc}）")

    report("完了しました。", 1.0)
    return warnings


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------


class SetupWizard(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} セットアップ")
        self.configure(bg=C_BG)
        self.resizable(False, False)
        self._apply_icon()
        self._center()

        self.target = tk.StringVar(value=str(default_install_dir()))
        self.create_desktop = tk.BooleanVar(value=True)
        self.create_start_menu = tk.BooleanVar(value=True)
        self.launch_after = tk.BooleanVar(value=True)

        self._step = "welcome"
        self._queue: Optional[queue.Queue] = None
        self._installed_exe: Optional[Path] = None

        self._build_layout()
        self.pages: dict[str, tk.Frame] = {}
        for name, builder in (
            ("welcome", self._build_welcome),
            ("folder", self._build_folder),
            ("options", self._build_options),
            ("installing", self._build_installing),
            ("done", self._build_done),
        ):
            frame = tk.Frame(self.body, bg=C_BG)
            builder(frame)
            self.pages[name] = frame

        self._show("welcome")
        self._update_folder_note()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    # -- window ------------------------------------------------------------

    def _apply_icon(self) -> None:
        if ICON_PATH.exists():
            try:
                self.iconbitmap(default=str(ICON_PATH))
            except tk.TclError:
                pass

    def _center(self) -> None:
        width, height = 720, 480
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 3)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _build_layout(self) -> None:
        header = tk.Frame(self, bg=C_BG)
        header.pack(fill="x", padx=28, pady=(22, 0))
        tk.Label(header, text=APP_NAME, font=FONT_TITLE, bg=C_BG, fg=C_TEXT).pack(
            anchor="w"
        )
        tk.Label(
            header,
            text=f"セットアップ  {APP_VERSION}",
            font=FONT_SMALL,
            bg=C_BG,
            fg=C_MUTED,
        ).pack(anchor="w")

        tk.Frame(self, bg=C_BORDER, height=1).pack(fill="x", padx=28, pady=(14, 0))

        footer = tk.Frame(self, bg=C_PANEL)
        footer.pack(fill="x", side="bottom")
        inner = tk.Frame(footer, bg=C_PANEL)
        inner.pack(fill="x", padx=24, pady=14)

        self.status = tk.Label(
            inner, text="", font=FONT_SMALL, bg=C_PANEL, fg=C_MUTED, anchor="w"
        )
        self.status.pack(side="left", fill="x", expand=True)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Setup.Horizontal.TProgressbar",
            troughcolor=C_BG,
            background=C_ACCENT,
            bordercolor=C_BG,
            lightcolor=C_ACCENT,
            darkcolor=C_ACCENT,
        )
        self.progress = ttk.Progressbar(
            inner,
            orient="horizontal",
            length=210,
            mode="determinate",
            maximum=1000,
            style="Setup.Horizontal.TProgressbar",
        )
        self.progress.pack(side="left", padx=(12, 16))

        self.next_btn = self._button(inner, "次へ", self._on_next, primary=True)
        self.cancel_btn = self._button(inner, "キャンセル", self._on_cancel)
        self.back_btn = self._button(inner, "戻る", self._on_back)
        self.next_btn.pack(side="right", padx=(8, 0))
        self.cancel_btn.pack(side="right", padx=(8, 0))
        self.back_btn.pack(side="right")

        self.body = tk.Frame(self, bg=C_BG)
        self.body.pack(fill="both", expand=True, padx=28, pady=16)

    def _button(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None],
        primary: bool = False,
    ) -> tk.Button:
        background = C_ACCENT if primary else C_FIELD
        foreground = "#FFFFFF" if primary else C_TEXT
        active = C_ACCENT_HOVER if primary else C_BORDER
        return tk.Button(
            parent,
            text=text,
            command=command,
            font=FONT,
            bg=background,
            fg=foreground,
            activebackground=active,
            activeforeground=foreground,
            disabledforeground="#5A6068",
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=18,
            pady=6,
            cursor="hand2",
        )

    # -- pages -------------------------------------------------------------

    def _build_welcome(self, frame: tk.Frame) -> None:
        tk.Label(
            frame,
            text=f"{APP_NAME} をこのパソコンにインストールします。",
            font=(FONT_FAMILY, 12),
            bg=C_BG,
            fg=C_TEXT,
            wraplength=620,
            justify="left",
        ).pack(anchor="w", pady=(4, 14))
        for line in (
            "・インストール先のフォルダは次の画面で選べます",
            "・デスクトップとスタートメニューにショートカットを作成できます",
            "・管理者権限は必要ありません（現在のユーザーにのみインストールします）",
        ):
            tk.Label(
                frame, text=line, font=FONT, bg=C_BG, fg=C_MUTED, anchor="w"
            ).pack(anchor="w", pady=2)
        tk.Label(
            frame,
            text=(
                "設定とログイン情報は %APPDATA%\\AI Office Workspace に保存され、\n"
                "アンインストールしても残ります。"
            ),
            font=FONT_SMALL,
            bg=C_BG,
            fg=C_MUTED,
            justify="left",
        ).pack(anchor="w", pady=(20, 0))

    def _build_folder(self, frame: tk.Frame) -> None:
        tk.Label(
            frame, text="インストール先フォルダ", font=FONT_BOLD, bg=C_BG, fg=C_TEXT
        ).pack(anchor="w", pady=(4, 10))

        row = tk.Frame(frame, bg=C_BG)
        row.pack(fill="x")
        tk.Entry(
            row,
            textvariable=self.target,
            font=FONT,
            bg=C_FIELD,
            fg=C_TEXT,
            insertbackground=C_TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=C_BORDER,
            highlightcolor=C_ACCENT,
        ).pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
        tk.Button(
            row,
            text="参照...",
            command=self._choose_folder,
            font=FONT,
            bg=C_FIELD,
            fg=C_TEXT,
            activebackground=C_BORDER,
            activeforeground=C_TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=14,
            pady=5,
            cursor="hand2",
        ).pack(side="left")

        self.folder_note = tk.Label(
            frame,
            text="",
            font=FONT_SMALL,
            bg=C_BG,
            fg=C_MUTED,
            justify="left",
            wraplength=620,
        )
        self.folder_note.pack(anchor="w", pady=(12, 0))

        self.target.trace_add("write", lambda *_: self._update_folder_note())

    def _build_options(self, frame: tk.Frame) -> None:
        tk.Label(
            frame, text="ショートカット", font=FONT_BOLD, bg=C_BG, fg=C_TEXT
        ).pack(anchor="w", pady=(4, 12))
        for text, variable in (
            ("デスクトップにショートカットを作成", self.create_desktop),
            ("スタートメニューにショートカットを作成", self.create_start_menu),
            ("インストール後にアプリを起動する", self.launch_after),
        ):
            tk.Checkbutton(
                frame,
                text=text,
                variable=variable,
                font=FONT,
                bg=C_BG,
                fg=C_TEXT,
                activebackground=C_BG,
                activeforeground=C_TEXT,
                selectcolor=C_FIELD,
                anchor="w",
                relief="flat",
                bd=0,
                highlightthickness=0,
                cursor="hand2",
            ).pack(anchor="w", pady=4)

        tk.Label(
            frame,
            text=(
                "インストール先のフォルダには、アプリ本体だけをコピーします。\n"
                "アンインストールは「設定 -> アプリ -> インストールされているアプリ」から行えます。"
            ),
            font=FONT_SMALL,
            bg=C_BG,
            fg=C_MUTED,
            justify="left",
        ).pack(anchor="w", pady=(22, 0))

    def _build_installing(self, frame: tk.Frame) -> None:
        tk.Label(
            frame, text="インストールしています", font=FONT_BOLD, bg=C_BG, fg=C_TEXT
        ).pack(anchor="w", pady=(4, 10))
        self.install_detail = tk.Label(
            frame,
            text="",
            font=FONT,
            bg=C_BG,
            fg=C_MUTED,
            wraplength=620,
            justify="left",
        )
        self.install_detail.pack(anchor="w")

    def _build_done(self, frame: tk.Frame) -> None:
        self.done_title = tk.Label(
            frame,
            text="インストールが完了しました。",
            font=(FONT_FAMILY, 12, "bold"),
            bg=C_BG,
            fg=C_OK,
        )
        self.done_title.pack(anchor="w", pady=(4, 12))
        self.done_detail = tk.Label(
            frame,
            text="",
            font=FONT,
            bg=C_BG,
            fg=C_MUTED,
            wraplength=620,
            justify="left",
        )
        self.done_detail.pack(anchor="w")

    # -- navigation --------------------------------------------------------

    def _show(self, step: str) -> None:
        self._step = step
        for name, frame in self.pages.items():
            if name == step:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

        if step == "welcome":
            self.back_btn.configure(state="disabled")
            self.next_btn.configure(text="次へ", state="normal")
            self.cancel_btn.configure(state="normal")
            self.status.configure(text="")
            self.progress.configure(value=0)
        elif step == "folder":
            self.back_btn.configure(state="normal")
            self.next_btn.configure(text="次へ", state="normal")
            self.cancel_btn.configure(state="normal")
            self._update_folder_note()
        elif step == "options":
            self.back_btn.configure(state="normal")
            self.next_btn.configure(text="インストール", state="normal")
            self.cancel_btn.configure(state="normal")
        elif step == "installing":
            self.back_btn.configure(state="disabled")
            self.next_btn.configure(state="disabled")
            self.cancel_btn.configure(state="disabled")
        elif step == "done":
            self.back_btn.configure(state="disabled")
            self.next_btn.configure(text="完了", state="normal")
            self.cancel_btn.configure(state="disabled")
            self.status.configure(text="インストールが完了しました。")
            self.progress.configure(value=1000)

    def _on_next(self) -> None:
        if self._step == "welcome":
            self._show("folder")
        elif self._step == "folder":
            if self._check_target():
                self._show("options")
        elif self._step == "options":
            self._start_install()
        elif self._step == "done":
            self._finish()

    def _on_back(self) -> None:
        if self._step == "folder":
            self._show("welcome")
        elif self._step == "options":
            self._show("folder")

    def _on_cancel(self) -> None:
        if self._step == "done":
            self.destroy()
            return
        if self._queue is not None:
            return
        if messagebox.askokcancel(
            APP_NAME, "セットアップを中止しますか？", parent=self
        ):
            self.destroy()

    # -- folder page -------------------------------------------------------

    def _choose_folder(self) -> None:
        current = Path(os.path.expandvars(self.target.get().strip())).expanduser()
        initial = current if current.is_dir() else default_install_dir()
        chosen = filedialog.askdirectory(
            parent=self,
            title="インストール先フォルダを選択",
            initialdir=str(initial),
            mustexist=False,
        )
        if chosen:
            self.target.set(str(Path(chosen)))

    def _update_folder_note(self) -> None:
        label = getattr(self, "folder_note", None)
        if label is None:
            return
        raw = self.target.get().strip()
        if not raw:
            label.configure(text="インストール先フォルダを入力してください。", fg=C_MUTED)
            return

        path = Path(os.path.expandvars(raw)).expanduser()
        need = payload_size()
        lines = [f"必要な容量: 約 {format_size(need)}"]

        available = free_space(path if path.exists() else path.parent)
        if available is not None:
            lines.append(f"空き容量: {format_size(available)}")
            if need and available < need:
                label.configure(text="\n".join(lines), fg=C_ERROR)
                return

        if (path / APP_EXE_NAME).exists():
            lines.append(
                "このフォルダには既にインストールされています。"
                "上書きインストールします（設定は残ります）。"
            )

        label.configure(text="\n".join(lines), fg=C_MUTED)

    def _check_target(self) -> bool:
        raw = self.target.get().strip()
        if not raw:
            messagebox.showerror(
                APP_NAME, "インストール先フォルダを入力してください。", parent=self
            )
            return False

        path = Path(os.path.expandvars(raw)).expanduser()
        if not path.is_absolute():
            messagebox.showerror(
                APP_NAME,
                "フルパスで指定してください（例: C:\\Program Files\\AI Office Workspace）。",
                parent=self,
            )
            return False
        if path.exists() and not path.is_dir():
            messagebox.showerror(
                APP_NAME,
                f"同じ名前のファイルがあります:\n{path}\n\nフォルダを指定してください。",
                parent=self,
            )
            return False

        self.target.set(str(path))

        if path.exists() and not (path / APP_EXE_NAME).exists():
            try:
                occupied = any(path.iterdir())
            except OSError:
                occupied = True
            if occupied and not messagebox.askokcancel(
                APP_NAME,
                f"このフォルダは空ではありません:\n{path}\n\n"
                "このフォルダにインストールしますか？",
                parent=self,
            ):
                return False
        return True

    # -- install -----------------------------------------------------------

    def _start_install(self) -> None:
        target = Path(self.target.get())
        self._show("installing")
        self.progress.configure(value=0)
        self.status.configure(text="準備しています...")
        self.install_detail.configure(text=f"インストール先: {target}")

        self._queue = queue.Queue()
        threading.Thread(
            target=self._install_worker,
            args=(
                target,
                self.create_desktop.get(),
                self.create_start_menu.get(),
                self._queue,
            ),
            daemon=True,
        ).start()
        self.after(80, self._poll_progress)

    def _install_worker(
        self,
        target: Path,
        desktop: bool,
        start_menu: bool,
        events: queue.Queue,
    ) -> None:
        def report(message: str, fraction: float) -> None:
            events.put(("progress", (message, fraction)))

        try:
            warnings = install(target, desktop, start_menu, report)
        except Exception:  # noqa: BLE001 - shown in the wizard, never a traceback
            events.put(("error", traceback.format_exc()))
            return
        events.put(("done", (target, warnings)))

    def _poll_progress(self) -> None:
        events = self._queue
        if events is None:
            return
        while True:
            try:
                kind, payload = events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                message, fraction = payload
                self.status.configure(text=message)
                self.progress.configure(
                    value=max(0, min(1000, int(fraction * 1000)))
                )
            elif kind == "done":
                self._queue = None
                target, warnings = payload
                self._install_finished(target, warnings)
                return
            elif kind == "error":
                self._queue = None
                self._install_failed(payload)
                return
        self.after(80, self._poll_progress)

    def _install_finished(self, target: Path, warnings: list[str]) -> None:
        self._installed_exe = target / APP_EXE_NAME
        lines = [f"インストール先: {target}", ""]
        if self.create_desktop.get():
            lines.append("デスクトップにショートカットを作成しました。")
        if self.create_start_menu.get():
            lines.append("スタートメニューにショートカットを作成しました。")
        lines.append("")
        lines.append("「設定 -> アプリ」からアンインストールできます。")
        if warnings:
            lines.append("")
            lines.extend(f"※ {warning}" for warning in warnings)
        self.done_detail.configure(text="\n".join(lines))
        self._show("done")

    def _install_failed(self, details: str) -> None:
        messagebox.showerror(
            APP_NAME,
            "インストールに失敗しました。\n\n"
            "・フォルダへの書き込み権限があるか確認してください。\n"
            "・別のフォルダを選んで再実行してください。\n\n"
            f"{details.strip().splitlines()[-1] if details.strip() else ''}",
            parent=self,
        )
        self._show("options")

    def _finish(self) -> None:
        exe = self._installed_exe
        if self.launch_after.get() and exe is not None:
            try:
                subprocess.Popen([str(exe)], cwd=str(exe.parent))
            except OSError as exc:
                messagebox.showwarning(
                    APP_NAME, f"アプリを起動できませんでした:\n{exc}", parent=self
                )
        self.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _enable_dpi_awareness() -> None:
    """Crisp text on high-DPI displays (no-op when unavailable)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (ImportError, AttributeError, OSError):
        pass


def main() -> int:
    _enable_dpi_awareness()
    if not PAYLOAD_PATH.exists():
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            APP_NAME,
            "インストール用のデータが見つかりません:\n"
            f"{PAYLOAD_PATH}\n\n"
            "packaging\\build.bat で setup.exe を作成してください。",
        )
        root.destroy()
        return 1

    wizard = SetupWizard()
    wizard.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
