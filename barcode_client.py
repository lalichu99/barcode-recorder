# -*- coding: utf-8 -*-
"""
Barcode Webcam Recorder — Client
=================================
- Định danh bằng Email thay SĐT
- Hiển thị ngày hết hạn license trong màn hình camera và camera picker
- Tự cài thư viện lần đầu (bootstrap installer)
- Nút "Đổi máy" trong setup window → gọi /request-machine-reset
- Khi license hết hạn → hiện thông báo + link gia hạn thay vì crash
- Có thêm chỗ Đổi / nhập lại license trên máy cũ hoặc máy khác
- FIX: dùng một tk.Tk() ẩn duy nhất, tất cả cửa sổ dùng Toplevel
       để tránh lỗi "pyimage2 doesn't exist" khi dùng ImageTk
- FIX: bỏ toàn bộ font custom của ttk để tránh lỗi TclError:
       expected integer but got "UI"
- Hỗ trợ đăng nhập bằng email + mã xác minh để nhận trial 7 ngày
- AUTO-UPDATE: kiểm tra GitHub Releases, hỏi user, tải + restart
- FIX: tạo mã thanh toán không còn đơ UI (async hoàn toàn)
"""

from __future__ import annotations

# ── Version ───────────────────────────────────────────────────────────────────
APP_VERSION = "1.0.0"   # <-- tăng mỗi lần build exe mới
GITHUB_EXE_NAME = "BarcodeRecorder.exe"
GITHUB_REPO = "lalichu99/barcode-recorder"

# ── Bootstrap: cài thư viện nếu thiếu (chỉ chạy lần đầu) ────────────────────
def _bootstrap() -> None:
    return
    needed = {
        "cv2": "opencv-python",
        "requests": "requests",
        "pyzbar": "pyzbar",
        "PIL": "Pillow",
        "numpy": "numpy",
    }
    missing = [pkg for mod, pkg in needed.items() if importlib.util.find_spec(mod) is None]
    if not missing:
        return

    import tkinter as tk
    from tkinter import ttk
    import subprocess
    import sys

    r = tk.Tk()
    r.title("Đang cài thư viện...")
    r.geometry("480x160")
    r.resizable(False, False)
    f = ttk.Frame(r, padding=20)
    f.pack(fill="both", expand=True)
    ttk.Label(f, text="Đang cài thư viện lần đầu, vui lòng chờ...").pack(anchor="w")
    bar = ttk.Progressbar(f, mode="indeterminate")
    bar.pack(fill="x", pady=(14, 0))
    bar.start(12)
    r.update()
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet"] + missing)
    r.destroy()


_bootstrap()

# ── Imports thật ──────────────────────────────────────────────────────────────
import threading
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import queue
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote

os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_OBSENSOR", "0")
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

import cv2
import numpy as np
import requests
import tkinter as tk
from PIL import Image, ImageTk
from pyzbar.pyzbar import decode as pyzbar_decode
from tkinter import filedialog, messagebox, ttk

try:
    if hasattr(cv2, "setLogLevel"):
        cv2.setLogLevel(0)
except Exception:
    pass


# ── Hằng số ───────────────────────────────────────────────────────────────────
APP_DIR = Path.home() / ".barcode_webcam_app"
CONFIG_FILE = APP_DIR / "config.json"
SERVER_BASE_URL = os.environ.get("LICENSE_SERVER_URL", "https://license-server-pa54.onrender.com")
REQUEST_TIMEOUT = 45
DEFAULT_FPS = 20.0
VIDEO_EXT = ".avi"
FOURCC = "XVID"
WINDOW_NAME = "Barcode Recorder"
ACCEPT_COOLDOWN = 5.0
MAX_CAMERA_IDX = 10

BG_APP = "#f5f3ef"
BG_CARD = "#ffffff"
FG_TITLE = "#1f2937"
FG_TEXT = "#374151"
FG_MUTED = "#6b7280"
FG_ERROR = "#b91c1c"
ACCENT = "#8b6f47"
ACCENT_DARK = "#6f5736"
BORDER = "#ddd6ce"
FIELD_BG = "#ffffff"


# ── Global hidden Tk root (tạo một lần duy nhất) ─────────────────────────────
_TK_ROOT: tk.Tk | None = None


def _apply_styles(root: tk.Misc) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(".", background=BG_APP, foreground=FG_TEXT)
    style.configure("App.TFrame", background=BG_APP)
    style.configure("Card.TFrame", background=BG_CARD, relief="flat")

    style.configure("App.TLabel", background=BG_APP, foreground=FG_TEXT)
    style.configure("Muted.TLabel", background=BG_APP, foreground=FG_MUTED)
    style.configure("Error.TLabel", background=BG_APP, foreground=FG_ERROR)
    style.configure("Title.TLabel", background=BG_APP, foreground=FG_TITLE)
    style.configure("Subtitle.TLabel", background=BG_APP, foreground=FG_TEXT)
    style.configure("Section.TLabelframe", background=BG_APP, bordercolor=BORDER)
    style.configure("Section.TLabelframe.Label", background=BG_APP, foreground=FG_TITLE)

    style.configure(
        "TButton",
        padding=(12, 8),
        background=BG_CARD,
        foreground=FG_TITLE,
        bordercolor=BORDER,
        focusthickness=1,
        focuscolor=ACCENT,
    )
    style.map(
        "TButton",
        background=[("active", "#f3eee7"), ("pressed", "#ece5db")],
        bordercolor=[("active", ACCENT)],
    )

    style.configure(
        "Accent.TButton",
        padding=(14, 9),
        background=ACCENT,
        foreground="white",
        bordercolor=ACCENT_DARK,
    )
    style.map(
        "Accent.TButton",
        background=[("active", "#9a7b50"), ("pressed", ACCENT_DARK)],
        foreground=[("disabled", "#f5f5f5")],
    )

    style.configure(
        "TEntry",
        fieldbackground=FIELD_BG,
        foreground=FG_TITLE,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        insertcolor=FG_TITLE,
        padding=8,
    )
    style.configure(
        "TCombobox",
        fieldbackground=FIELD_BG,
        foreground=FG_TITLE,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=6,
    )
    style.configure(
        "TProgressbar",
        background=ACCENT,
        troughcolor="#ede8e1",
        bordercolor="#ede8e1",
        lightcolor=ACCENT,
        darkcolor=ACCENT,
    )


def _get_root() -> tk.Tk:
    global _TK_ROOT
    if _TK_ROOT is None or not _TK_ROOT.winfo_exists():
        _TK_ROOT = tk.Tk()
        _TK_ROOT.withdraw()
        _apply_styles(_TK_ROOT)
    return _TK_ROOT


def _center_window(win: tk.Toplevel, width: int, height: int) -> None:
    win.update_idletasks()
    screen_w = win.winfo_screenwidth()
    screen_h = win.winfo_screenheight()
    x = max(0, (screen_w - width) // 2)
    y = max(0, (screen_h - height) // 2 - 20)
    win.geometry(f"{width}x{height}+{x}+{y}")


def _toplevel(title: str, geometry: str, resizable: bool = True) -> tk.Toplevel:
    root = _get_root()
    win = tk.Toplevel(root, bg=BG_APP)
    win.title(title)
    win.configure(bg=BG_APP)
    win.geometry(geometry)
    if not resizable:
        win.resizable(False, False)
    win.lift()
    win.focus_force()

    try:
        parts = geometry.lower().split("x")
        if len(parts) >= 2:
            w = int(parts[0])
            h = int(parts[1].split("+")[0])
            _center_window(win, w, h)
    except Exception:
        pass

    return win


def _wait_window(win: tk.Toplevel) -> None:
    win.grab_set()
    _get_root().wait_window(win)


def _make_main_container(win: tk.Toplevel, padding: int = 22) -> ttk.Frame:
    outer = ttk.Frame(win, style="App.TFrame", padding=padding)
    outer.pack(fill="both", expand=True)
    return outer


# ══════════════════════════════════════════════════════════════════════════════
# Config helpers
# ══════════════════════════════════════════════════════════════════════════════
def load_config() -> dict[str, Any]:
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_config(data: dict[str, Any]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_local_license(keep_settings: bool = True) -> None:
    old = load_config()
    if keep_settings:
        kept = {"camera_index": old.get("camera_index"), "save_dir": old.get("save_dir")}
        save_config({k: v for k, v in kept.items() if v is not None})
    else:
        try:
            if CONFIG_FILE.exists():
                CONFIG_FILE.unlink()
        except Exception:
            pass


def default_save_dir() -> str:
    d = Path.home() / "Downloads"
    return str(d) if d.exists() else str(Path.home())


# ══════════════════════════════════════════════════════════════════════════════
# Time helpers
# ══════════════════════════════════════════════════════════════════════════════
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utcnow().replace(microsecond=0).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _fmt_local(dt: datetime | None) -> str:
    if dt is None:
        return "?"
    return dt.astimezone().strftime("%d/%m/%Y %H:%M")


# ══════════════════════════════════════════════════════════════════════════════
# Machine ID
# ══════════════════════════════════════════════════════════════════════════════
def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5, shell=False)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def get_machine_id() -> str:
    guid = ""
    sys_uuid = ""
    mac = str(uuid.getnode()).zfill(12).upper()

    try:
        import winreg  # type: ignore
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
        guid = str(winreg.QueryValueEx(key, "MachineGuid")[0]).strip().upper()
    except Exception:
        pass

    out = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystemProduct).UUID"])
    if out:
        lines = [x.strip() for x in out.splitlines() if x.strip()]
        if lines:
            sys_uuid = lines[-1].upper()

    parts = [guid, mac]
    if sys_uuid not in {"", "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF", "00000000-0000-0000-0000-000000000000"}:
        parts.append(sys_uuid)

    return hashlib.sha256("|".join(parts).encode("utf-8", errors="ignore")).hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
# License API
# ══════════════════════════════════════════════════════════════════════════════
def _post(path: str, payload: dict) -> dict:
    url = f"{SERVER_BASE_URL.rstrip('/')}{path}"
    r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

    data = r.json()
    if not isinstance(data, dict):
        return {
            "ok": False,
            "message": f"Server trả về dữ liệu không hợp lệ tại {path}: {data!r}"
        }
    return data


def _save_session_from_server(email: str, data: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config()
    cfg.update({
        "email": email.strip().lower(),
        "license_key": str(data.get("license_key", "")).strip().upper(),
        "machine_id": get_machine_id(),
        "last_ok_at": _iso_now(),
        "offline_grace_days": data.get("offline_grace_days", 7),
        "expires_at": data.get("expires_at", ""),
    })
    save_config(cfg)
    return cfg


def send_login_code(email: str) -> dict[str, Any]:
    try:
        return _post("/auth/send-code", {"email": email.strip().lower()})
    except Exception as exc:
        return {"ok": False, "message": f"Không kết nối được server: {exc}"}


def verify_email_code(email: str, code: str) -> dict[str, Any]:
    try:
        data = _post("/auth/verify-code", {
            "email": email.strip().lower(),
            "code": code.strip(),
            "machine_id": get_machine_id(),
        })
    except Exception as exc:
        return {"ok": False, "message": f"Không kết nối được server: {exc}"}

    if data.get("ok") and data.get("license_key"):
        _save_session_from_server(email, data)
    return data


def activate_license(email: str, license_key: str) -> dict[str, Any]:
    machine_id = get_machine_id()
    try:
        data = _post("/activate", {
            "email": email.strip().lower(),
            "license_key": license_key.strip().upper(),
            "machine_id": machine_id,
        })
    except Exception as exc:
        return {"ok": False, "message": f"Không kết nối được server: {exc}"}

    if data.get("ok"):
        data = dict(data)
        data["license_key"] = license_key.strip().upper()
        _save_session_from_server(email, data)
    return data


def check_license(config: dict[str, Any]) -> dict[str, Any]:
    email = str(config.get("email", "")).strip().lower()
    license_key = str(config.get("license_key", "")).strip().upper()
    machine_id = get_machine_id()

    if not email or not license_key:
        return {"ok": False, "message": "Chưa có license trong máy này"}

    try:
        data = _post("/check-license", {
            "email": email,
            "license_key": license_key,
            "machine_id": machine_id,
        })
        if data.get("ok"):
            config.update({
                "machine_id": machine_id,
                "last_ok_at": _iso_now(),
                "offline_grace_days": data.get("offline_grace_days", 7),
                "expires_at": data.get("expires_at", config.get("expires_at", "")),
            })
            save_config(config)
        return data

    except Exception as exc:
        last_ok = _parse_dt(str(config.get("last_ok_at", "")))
        grace = int(config.get("offline_grace_days", 7))
        if last_ok is not None:
            deadline = last_ok + timedelta(days=grace)
            if _utcnow() <= deadline:
                return {
                    "ok": True,
                    "offline": True,
                    "message": f"Offline – chạy tạm đến {_fmt_local(deadline)}",
                    "expires_at": config.get("expires_at", ""),
                }
        return {"ok": False, "message": f"Không kiểm tra được license: {exc}"}


def request_machine_reset(email: str) -> dict[str, Any]:
    try:
        return _post("/request-machine-reset", {"email": email.strip().lower()})
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def get_public_config() -> dict[str, Any]:
    try:
        url = f"{SERVER_BASE_URL.rstrip('/')}/public-config"
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {
        "ok": False,
        "renewal_amount": 100000,
        "bank_id": "MB",
        "bank_display_name": "MB Bank",
        "bank_account_no": "",
        "bank_account_name": "",
        "approval_title": "Chờ admin xác nhận trên Telegram",
        "approval_note": "Sau khi chuyển khoản, hệ thống sẽ gửi yêu cầu chờ admin xác nhận trên Telegram.",
        "support_note": "Khi admin duyệt, hệ thống sẽ gia hạn và gửi email thông báo.",
    }


def create_renewal_order(email: str) -> dict[str, Any]:
    return _post("/create-order", {"email": email.strip().lower()})


def confirm_transfer(email: str, order_id: str) -> dict[str, Any]:
    try:
        return _post("/confirm-transfer", {
            "email": email.strip().lower(),
            "order_id": order_id.strip().lower(),
        })
    except Exception as exc:
        return {"ok": False, "message": f"Lỗi kết nối server: {exc}"}


def make_vietqr_url(bank_id: str, account_no: str, account_name: str, amount: int, transfer_content: str) -> str:
    return (
        f"https://img.vietqr.io/image/{bank_id}-{account_no}-compact2.png"
        f"?amount={amount}"
        f"&addInfo={quote(transfer_content)}"
        f"&accountName={quote(account_name)}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Auto-Update (GitHub Releases)
# ══════════════════════════════════════════════════════════════════════════════
def _parse_version(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("v").split("."))
    except Exception:
        return (0,)


def check_for_update() -> dict[str, Any] | None:
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        r = requests.get(url, timeout=10, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        data = r.json()

        latest_tag = str(data.get("tag_name", "0")).lstrip("v")
        if _parse_version(latest_tag) <= _parse_version(APP_VERSION):
            return None

        download_url = ""
        for asset in data.get("assets", []):
            name = str(asset.get("name", ""))
            if name.lower().endswith(".exe"):
                download_url = str(asset.get("browser_download_url", ""))
                break

        if not download_url:
            return None

        return {
            "latest": latest_tag,
            "current": APP_VERSION,
            "download_url": download_url,
            "release_notes": str(data.get("body", "")).strip()[:500],
            "published_at": str(data.get("published_at", "")),
        }
    except Exception:
        return None


def _download_update(url: str, dest: Path, progress_cb=None) -> None:
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb and total > 0:
                        progress_cb(int(downloaded * 100 / total))


def _write_updater_bat(new_exe: Path, current_exe: Path) -> Path:
    bat_path = new_exe.parent / "_updater.bat"
    bat_content = f"""@echo off
timeout /t 3 /nobreak >nul
move /y "{new_exe}" "{current_exe}"
start "" "{current_exe}"
del "%~f0"
"""
    bat_path.write_text(bat_content, encoding="utf-8")
    return bat_path


def show_update_dialog(update_info: dict[str, Any]) -> None:
    latest = update_info["latest"]
    current = update_info["current"]
    notes = update_info.get("release_notes", "")
    download_url = update_info["download_url"]

    confirm = messagebox.askyesno(
        f"Có bản cập nhật mới — v{latest}",
        f"Phiên bản hiện tại: v{current}\n"
        f"Phiên bản mới:      v{latest}\n\n"
        f"{'Ghi chú:\n' + notes + chr(10) + chr(10) if notes else ''}"
        "Bạn có muốn tải và cập nhật ngay không?\n"
        "(App sẽ tự khởi động lại sau khi tải xong)",
        parent=_get_root(),
    )
    if not confirm:
        return

    dl_win = _toplevel("Đang tải cập nhật...", "460x140", resizable=False)
    dl_frame = _make_main_container(dl_win, 20)
    ttk.Label(dl_frame, text=f"Đang tải v{latest}...", style="Title.TLabel").pack(anchor="w")
    pct_var = tk.StringVar(value="0%")
    ttk.Label(dl_frame, textvariable=pct_var, style="Muted.TLabel").pack(anchor="w", pady=(4, 8))
    bar = ttk.Progressbar(dl_frame, mode="determinate", maximum=100)
    bar.pack(fill="x")

    dl_win.update()

    if getattr(sys, "frozen", False):
        current_exe = Path(sys.executable)
    else:
        current_exe = Path(sys.argv[0])

    new_exe = current_exe.parent / f"_update_{latest}.exe"
    err_holder: list[str] = []

    def _do_download():
        try:
            def on_progress(pct: int):
                dl_win.after(0, lambda: (
                    bar.configure(value=pct),
                    pct_var.set(f"{pct}%"),
                ))

            _download_update(download_url, new_exe, progress_cb=on_progress)

            def _finish():
                bar.configure(value=100)
                pct_var.set("100% — Đang khởi động lại...")
                dl_win.update()
                try:
                    bat = _write_updater_bat(new_exe, current_exe)
                    subprocess.Popen(
                        [str(bat)],
                        shell=True,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except Exception as e:
                    messagebox.showerror("Lỗi", f"Không thể chạy updater:\n{e}", parent=dl_win)
                    dl_win.destroy()
                    return
                dl_win.destroy()
                _get_root().quit()
                sys.exit(0)

            dl_win.after(0, _finish)

        except Exception as exc:
            err_holder.append(str(exc))

            def _on_err():
                dl_win.destroy()
                messagebox.showerror(
                    "Tải thất bại",
                    f"Không tải được bản cập nhật:\n{err_holder[0]}\n\n"
                    "Bạn có thể tải thủ công tại:\n" + download_url,
                    parent=_get_root(),
                )

            dl_win.after(0, _on_err)

    threading.Thread(target=_do_download, daemon=True).start()
    _wait_window(dl_win)


def check_update_async() -> None:
    def _worker():
        info = check_for_update()
        if info:
            _get_root().after(0, lambda: show_update_dialog(info))

    threading.Thread(target=_worker, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
# Camera helpers
# ══════════════════════════════════════════════════════════════════════════════
def open_camera(index: int) -> cv2.VideoCapture | None:
    for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
        cap = None
        try:
            cap = cv2.VideoCapture(index, backend)
            if not cap.isOpened():
                cap.release()
                continue
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            ok, frame = cap.read()
            if ok and frame is not None and frame.size > 0:
                return cap
        except Exception:
            pass
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
    return None


def list_cameras(max_idx: int = MAX_CAMERA_IDX) -> list[int]:
    result = []
    for i in range(max_idx + 1):
        cap = open_camera(i)
        if cap is not None:
            result.append(i)
            cap.release()
    return result


def _fit_frame_to_window(frame, window_name: str):
    try:
        _x, _y, ww, wh = cv2.getWindowImageRect(window_name)
        if ww <= 0 or wh <= 0:
            return frame
    except Exception:
        return frame

    h, w = frame.shape[:2]
    if h <= 0 or w <= 0:
        return frame

    scale = min(ww / w, wh / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))

    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    canvas = np.zeros((wh, ww, 3), dtype=np.uint8)
    x0 = (ww - new_w) // 2
    y0 = (wh - new_h) // 2
    canvas[y0:y0 + new_h, x0:x0 + new_w] = resized
    return canvas


def draw_text_clean(
    frame,
    text: str,
    org: tuple[int, int],
    *,
    font_scale: float = 0.75,
    thickness: int = 2,
    text_color: tuple[int, int, int] = (255, 255, 255),
    bg_color: tuple[int, int, int] = (0, 0, 0),
    padding: int = 8,
) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    x, y = org
    x1 = max(0, x - padding)
    y1 = max(0, y - th - padding)
    x2 = min(frame.shape[1] - 1, x + tw + padding)
    y2 = min(frame.shape[0] - 1, y + baseline + padding)
    overlay = frame.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), bg_color, -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)
    cv2.putText(frame, text, (x, y), font, font_scale, text_color, thickness, cv2.LINE_AA)


def draw_recording_stamp(frame, now_dt: datetime, *, current_code: str | None = None) -> None:
    stamp = now_dt.strftime("%d/%m/%Y %H:%M:%S")
    text = f"REC  {stamp}" if not current_code else f"REC  {stamp}  |  {current_code[:36]}"
    draw_text_clean(
        frame,
        text,
        (18, 34),
        font_scale=0.72,
        thickness=2,
        text_color=(255, 255, 255),
        bg_color=(20, 20, 20),
        padding=8,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Voice helpers
# ══════════════════════════════════════════════════════════════════════════════
def speak_text(text: str) -> None:
    safe = text.replace("'", " ").replace('"', " ").strip()
    if not safe:
        return

    ps_script = (
        "Add-Type -AssemblyName System.Speech; "
        "$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$speak.Rate = 0; "
        "$speak.Volume = 100; "
        f"$speak.Speak('{safe}');"
    )

    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        try:
            print(text)
        except Exception:
            pass


def say_start_recording() -> None:
    speak_text("Start recording")


def say_stop_recording() -> None:
    speak_text("Stop recording")


# ══════════════════════════════════════════════════════════════════════════════
# UI helpers
# ══════════════════════════════════════════════════════════════════════════════
def _expires_label(expires_at: str) -> str:
    dt = _parse_dt(expires_at)
    if dt is None:
        return ""
    remaining = (dt - _utcnow()).days
    color_hint = "⚠ " if remaining <= 5 else ""
    return f"{color_hint}Hết hạn: {_fmt_local(dt)}  (còn {max(0, remaining)} ngày)"


# ══════════════════════════════════════════════════════════════════════════════
# show_renewal_window
# ══════════════════════════════════════════════════════════════════════════════
def show_renewal_window(config: dict[str, Any], reason_text: str = "") -> None:
    email = str(config.get("email", "")).strip().lower()
    license_key = str(config.get("license_key", "")).strip().upper()

    win = _toplevel("Gia hạn license", "820x840")
    win.minsize(760, 760)

    frame = _make_main_container(win, 24)

    ttk.Label(frame, text="Gia hạn Barcode Recorder", style="Title.TLabel").pack(anchor="w")
    ttk.Label(
        frame,
        text="Tạo mã đơn ngay trong app. Sau khi chuyển khoản, hệ thống sẽ gửi yêu cầu chờ admin xác nhận trên Telegram.",
        style="Subtitle.TLabel",
        wraplength=760,
        justify="left",
    ).pack(anchor="w", pady=(8, 14))

    if reason_text:
        ttk.Label(
            frame,
            text=reason_text,
            style="Error.TLabel",
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

    ttk.Label(frame, text=f"Email: {email or '(chưa có)'}", style="Muted.TLabel").pack(anchor="w")
    ttk.Label(
        frame,
        text=f"License hiện tại: {license_key or '(chưa có)'}",
        style="Muted.TLabel",
    ).pack(anchor="w", pady=(2, 12))

    status_var = tk.StringVar(value="⏳ Đang tải cấu hình thanh toán, vui lòng chờ...")
    ttk.Label(
        frame,
        textvariable=status_var,
        style="Muted.TLabel",
        wraplength=760,
    ).pack(anchor="w", pady=(0, 10))

    loading_bar = ttk.Progressbar(frame, mode="indeterminate")
    loading_bar.pack(fill="x", pady=(0, 10))
    loading_bar.start(12)

    qr_wrap = ttk.Frame(frame, style="App.TFrame")
    qr_wrap.pack(fill="x", pady=(8, 14))
    qr_label = ttk.Label(qr_wrap, style="App.TLabel", text="")
    qr_label.pack(anchor="center")

    info_box = ttk.LabelFrame(
        frame,
        text="Thông tin chuyển khoản",
        style="Section.TLabelframe",
        padding=16,
    )
    info_box.pack(fill="x", pady=(8, 12))

    bank_name_var = tk.StringVar(value="Ngân hàng: ")
    bank_no_var = tk.StringVar(value="Số tài khoản: ")
    bank_owner_var = tk.StringVar(value="Chủ tài khoản: ")
    amount_var = tk.StringVar(value="Số tiền: ")
    order_var = tk.StringVar(value="Nội dung chuyển khoản: ")
    approval_var = tk.StringVar(value="")
    note_var = tk.StringVar(value="")

    ttk.Label(info_box, textvariable=bank_name_var, style="App.TLabel").pack(anchor="w", pady=2)
    ttk.Label(info_box, textvariable=bank_no_var, style="App.TLabel").pack(anchor="w", pady=2)
    ttk.Label(info_box, textvariable=bank_owner_var, style="App.TLabel").pack(anchor="w", pady=2)
    ttk.Label(info_box, textvariable=amount_var, style="Error.TLabel").pack(anchor="w", pady=4)
    ttk.Label(info_box, textvariable=order_var, style="App.TLabel").pack(anchor="w", pady=(6, 2))
    ttk.Label(info_box, textvariable=approval_var, style="App.TLabel").pack(anchor="w", pady=(8, 2))
    ttk.Label(
        info_box,
        textvariable=note_var,
        style="Muted.TLabel",
        wraplength=720,
        justify="left",
    ).pack(anchor="w", pady=(4, 2))

    btn_row = ttk.Frame(frame, style="App.TFrame")
    btn_row.pack(fill="x", side="bottom", pady=(16, 0))

    order_data: dict[str, Any] = {}
    public_cfg: dict[str, Any] = {}

    btn_confirm: ttk.Button
    btn_reload: ttk.Button
    btn_copy_stk: ttk.Button
    btn_copy_order: ttk.Button

    result_queue: queue.Queue = queue.Queue()

    def _set_buttons_state(state: str) -> None:
        for b in (btn_confirm, btn_reload, btn_copy_stk, btn_copy_order):
            try:
                b.configure(state=state)
            except Exception:
                pass

    def _copy_text(value: str, title: str) -> None:
        win.clipboard_clear()
        win.clipboard_append(value)
        win.update()
        messagebox.showinfo("Đã copy", f"Đã copy {title}:\n{value}", parent=win)

    def _copy_order() -> None:
        oid = str(order_data.get("order_id", "")).strip()
        if oid:
            _copy_text(oid, "mã đơn")

    def _copy_bank() -> None:
        acc = str(public_cfg.get("bank_account_no", "")).strip()
        if acc:
            _copy_text(acc, "số tài khoản")

    def _poll_queue() -> None:
        try:
            while True:
                kind, payload = result_queue.get_nowait()

                if kind == "basic_success":
                    public_cfg_result, order_result = payload
                    bank_id = str(public_cfg_result.get("bank_id", "TCB")).strip()
                    bank_display_name = str(public_cfg_result.get("bank_display_name", bank_id)).strip()
                    bank_account_no = str(public_cfg_result.get("bank_account_no", "")).strip()
                    bank_account_name = str(public_cfg_result.get("bank_account_name", "")).strip()
                    approval_title = str(public_cfg_result.get("approval_title", "Chờ admin xác nhận trên Telegram")).strip()
                    approval_note = str(public_cfg_result.get("approval_note", "")).strip()
                    support_note = str(public_cfg_result.get("support_note", "")).strip()

                    amount = int(order_result.get("amount", 0) or 0)
                    order_id = str(order_result.get("order_id", "")).strip()
                    transfer_content = str(order_result.get("transfer_content", order_id)).strip()

                    order_data.clear()
                    order_data.update(order_result)
                    public_cfg.clear()
                    public_cfg.update(public_cfg_result)

                    bank_name_var.set(f"Ngân hàng: {bank_display_name}")
                    bank_no_var.set(f"Số tài khoản: {bank_account_no}")
                    bank_owner_var.set(f"Chủ tài khoản: {bank_account_name}")
                    amount_var.set(f"Số tiền: {amount:,} VNĐ")
                    order_var.set(f"Nội dung chuyển khoản: {transfer_content}")
                    approval_var.set(approval_title)
                    note_var.set(approval_note + ("\n" if approval_note and support_note else "") + support_note)

                    loading_bar.stop()
                    loading_bar.configure(value=0)
                    qr_label.configure(image="", text="Đang tải mã QR...")
                    qr_label.image = None
                    status_var.set("✅ Đã tạo mã đơn — có thể chuyển khoản ngay, QR đang tải...")
                    _set_buttons_state("normal")

                elif kind == "qr_ready":
                    qr_pil = payload
                    if qr_pil is not None:
                        try:
                            qr_img = ImageTk.PhotoImage(qr_pil, master=win)
                            qr_label.configure(image=qr_img, text="")
                            qr_label.image = qr_img
                            status_var.set("✅ Đã tạo mã đơn — chuyển khoản đúng nội dung bên dưới")
                        except Exception as exc:
                            print("QR PhotoImage error:", exc)
                            qr_label.configure(image="", text="(Không tải được mã QR — chuyển khoản thủ công)")
                            qr_label.image = None
                            status_var.set("✅ Đã tạo mã đơn (QR không tải được)")
                    else:
                        qr_label.configure(image="", text="(Không tải được mã QR — chuyển khoản thủ công)")
                        qr_label.image = None
                        status_var.set("✅ Đã tạo mã đơn (QR không tải được)")

                elif kind == "error":
                    msg = str(payload)
                    loading_bar.stop()
                    _set_buttons_state("normal")
                    status_var.set(f"❌ {msg}")
                    messagebox.showerror("Lỗi", msg, parent=win)

                elif kind == "confirm_done":
                    res = payload
                    _set_buttons_state("normal")
                    ok = bool(res.get("ok", False))
                    msg = str(res.get("message") or "Lỗi không xác định")
                    tg_err = str(res.get("telegram_error") or "").strip()
                    request_id = str(res.get("request_id") or "").strip()

                    detail = msg
                    if request_id:
                        detail += f"\n\nMã yêu cầu: {request_id}"
                    if tg_err:
                        detail += f"\n\nChi tiết lỗi Telegram:\n{tg_err}"

                    if ok:
                        status_var.set(msg)
                        msg_lower = msg.lower()
                        tg_failed = (
                            bool(tg_err)
                            or ("chưa gửi được telegram" in msg_lower)
                            or ("không gửi được telegram" in msg_lower)
                            or ("chưa gửi được thông báo telegram" in msg_lower)
                        )
                        if tg_failed:
                            messagebox.showwarning("Chưa gửi được Telegram", detail, parent=win)
                        else:
                            messagebox.showinfo("Đã gửi xác nhận", detail, parent=win)
                    else:
                        status_var.set(f"❌ {msg}")
                        messagebox.showerror("Lỗi gửi xác nhận", detail, parent=win)

        except queue.Empty:
            pass

        if win.winfo_exists():
            win.after(30, _poll_queue)

    def _reload_order() -> None:
        status_var.set("⏳ Đang tải cấu hình thanh toán...")
        qr_label.configure(image="", text="")
        qr_label.image = None
        loading_bar.start(12)
        _set_buttons_state("disabled")
        win.update_idletasks()

        if not email:
            status_var.set("❌ Chưa có email trong máy này.")
            loading_bar.stop()
            return

        def worker():
            public_cfg_result: dict[str, Any] = {}
            order_result: dict[str, Any] = {}
            fetch_error = ""

            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_cfg = pool.submit(get_public_config)
                fut_order = pool.submit(create_renewal_order, email)

                for fut in as_completed([fut_cfg, fut_order]):
                    try:
                        res = fut.result()
                        if fut is fut_cfg:
                            public_cfg_result = res
                        else:
                            order_result = res
                    except Exception as e:
                        fetch_error = str(e)

            if fetch_error:
                result_queue.put(("error", f"Lỗi mạng: {fetch_error}"))
                return

            if not isinstance(public_cfg_result, dict):
                result_queue.put(("error", "public-config không hợp lệ"))
                return

            if not isinstance(order_result, dict):
                result_queue.put(("error", "create-order trả về dữ liệu không hợp lệ"))
                return

            if not order_result.get("ok", False):
                result_queue.put(("error", str(order_result.get("message", "Tạo đơn thất bại"))))
                return

            result_queue.put(("basic_success", (public_cfg_result, order_result)))

            bank_id = str(public_cfg_result.get("bank_id", "TCB")).strip()
            bank_account_no = str(public_cfg_result.get("bank_account_no", "")).strip()
            bank_account_name = str(public_cfg_result.get("bank_account_name", "")).strip()
            amount = int(order_result.get("amount", 0) or 0)
            order_id = str(order_result.get("order_id", "")).strip()
            transfer_content = str(order_result.get("transfer_content", order_id)).strip()

            qr_url = make_vietqr_url(
                bank_id, bank_account_no, bank_account_name, amount, transfer_content,
            )

            def _fetch_qr():
                qr_pil = None
                try:
                    resp = requests.get(qr_url, timeout=8)
                    resp.raise_for_status()
                    qr_pil = Image.open(BytesIO(resp.content)).convert("RGB")
                    qr_pil.thumbnail((280, 280))
                except Exception as exc:
                    print("QR fetch error:", exc)
                result_queue.put(("qr_ready", qr_pil))

            threading.Thread(target=_fetch_qr, daemon=True).start()

        threading.Thread(target=worker, daemon=True).start()

    def _confirm_transfer() -> None:
        oid = str(order_data.get("order_id", "")).strip()
        if not oid:
            messagebox.showwarning(
                "Chưa có mã đơn",
                "Bạn chưa tạo mã đơn. Hãy bấm 'Tạo lại mã đơn' trước.",
                parent=win,
            )
            return

        if not messagebox.askyesno(
            "Xác nhận đã chuyển khoản",
            (
                f"Bạn xác nhận đã chuyển khoản với nội dung:\n\n  {oid}\n\n"
                "Hệ thống sẽ gửi yêu cầu chờ admin duyệt trên Telegram.\nTiếp tục?"
            ),
            parent=win,
        ):
            return

        status_var.set("⏳ Đang gửi xác nhận lên server...")
        _set_buttons_state("disabled")
        win.update_idletasks()

        def worker():
            try:
                res = confirm_transfer(email, oid)
            except Exception as exc:
                res = {"ok": False, "message": f"Lỗi khi gửi xác nhận lên server: {exc}"}

            if res is None:
                res = {"ok": False, "message": "Server trả về dữ liệu rỗng (None)."}
            elif not isinstance(res, dict):
                res = {"ok": False, "message": f"Server trả về dữ liệu không hợp lệ: {type(res).__name__}"}

            result_queue.put(("confirm_done", res))

        threading.Thread(target=worker, daemon=True).start()

    btn_confirm = ttk.Button(
        btn_row,
        text="✅ Đã chuyển khoản",
        command=_confirm_transfer,
        width=20,
        style="Accent.TButton",
        state="disabled",
    )
    btn_confirm.pack(side="right", padx=(0, 8))

    btn_reload = ttk.Button(
        btn_row,
        text="Tạo lại mã đơn",
        command=_reload_order,
        width=16,
        state="disabled",
    )
    btn_reload.pack(side="right", padx=(0, 8))

    ttk.Button(btn_row, text="Đóng", command=win.destroy, width=12).pack(side="right")

    btn_copy_stk = ttk.Button(
        btn_row, text="Copy STK", command=_copy_bank, width=12, state="disabled"
    )
    btn_copy_stk.pack(side="left")

    btn_copy_order = ttk.Button(
        btn_row, text="Copy mã đơn", command=_copy_order, width=12, state="disabled"
    )
    btn_copy_order.pack(side="left", padx=(8, 0))

    win.after(30, _poll_queue)
    win.after(0, _reload_order)
    _wait_window(win)


# ══════════════════════════════════════════════════════════════════════════════
# show_change_license_window
# ══════════════════════════════════════════════════════════════════════════════
def show_change_license_window(config: dict[str, Any], message_text: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}

    win = _toplevel("Đăng nhập lại", "820x520")
    win.minsize(760, 470)

    frame = _make_main_container(win, 24)

    ttk.Label(frame, text="Đăng nhập bằng email", style="Title.TLabel").pack(anchor="w")
    ttk.Label(
        frame,
        text=(
            "App sẽ gửi mã xác minh về email. Sau khi nhập đúng mã, server sẽ trả về license "
            "đang hoạt động hoặc tự cấp trial 7 ngày nếu email chưa từng dùng trial."
        ),
        style="Subtitle.TLabel",
        wraplength=760,
        justify="left",
    ).pack(anchor="w", pady=(8, 16))

    email_var = tk.StringVar(value=str(config.get("email", "") or ""))
    code_var = tk.StringVar(value="")
    key_var = tk.StringVar(value=str(config.get("license_key", "") or ""))
    status_var = tk.StringVar(value=message_text)

    ttk.Label(frame, text="Email", style="App.TLabel").pack(anchor="w")
    email_entry = ttk.Entry(frame, textvariable=email_var)
    email_entry.pack(fill="x", pady=(4, 12), ipady=4)

    ttk.Label(frame, text="Mã xác minh", style="App.TLabel").pack(anchor="w")
    row_code = ttk.Frame(frame, style="App.TFrame")
    row_code.pack(fill="x", pady=(4, 12))
    code_entry = ttk.Entry(row_code, textvariable=code_var)
    code_entry.pack(side="left", fill="x", expand=True, ipady=4)
    ttk.Button(
        row_code,
        text="Gửi mã",
        command=lambda: _send_code(),
        width=12,
        style="Accent.TButton",
    ).pack(side="left", padx=(10, 0))

    manual_box = ttk.LabelFrame(
        frame,
        text="Hoặc nhập license thủ công",
        style="Section.TLabelframe",
        padding=14,
    )
    manual_box.pack(fill="x", pady=(6, 10))
    ttk.Entry(manual_box, textvariable=key_var).pack(fill="x", ipady=4)

    ttk.Label(
        frame,
        textvariable=status_var,
        style="Error.TLabel",
        wraplength=760,
        justify="left",
    ).pack(anchor="w", pady=(8, 12))

    btn_row = ttk.Frame(frame, style="App.TFrame")
    btn_row.pack(fill="x", side="bottom", pady=(18, 0))

    def _send_code() -> None:
        email = email_var.get().strip().lower()
        if not email:
            messagebox.showwarning("Thiếu dữ liệu", "Bạn chưa nhập email.", parent=win)
            return
        status_var.set("Đang gửi mã xác minh...")
        win.update_idletasks()

        def _worker():
            res = send_login_code(email)
            win.after(0, lambda: status_var.set(str(res.get("message", ""))))
            win.after(0, code_entry.focus_set)

        threading.Thread(target=_worker, daemon=True).start()

    def _submit_verify() -> None:
        email = email_var.get().strip().lower()
        code = code_var.get().strip()

        if not email:
            messagebox.showwarning("Thiếu dữ liệu", "Bạn chưa nhập email.", parent=win)
            return

        if not code:
            current_cfg = load_config()
            saved_email = str(current_cfg.get("email", "")).strip().lower()
            saved_key = str(current_cfg.get("license_key", "")).strip().upper()
            exp_dt = _parse_dt(str(current_cfg.get("expires_at", "")))

            if saved_email == email and saved_key and exp_dt and _utcnow() <= exp_dt:
                res = check_license(current_cfg)
                if res.get("ok"):
                    if res.get("expires_at"):
                        current_cfg["expires_at"] = res.get("expires_at", current_cfg.get("expires_at", ""))
                    if "camera_index" not in current_cfg and "camera_index" in config:
                        current_cfg["camera_index"] = config.get("camera_index")
                    if "save_dir" not in current_cfg:
                        current_cfg["save_dir"] = config.get("save_dir") or default_save_dir()
                    save_config(current_cfg)
                    result.update(current_cfg)
                    win.destroy()
                    return

                if exp_dt and _utcnow() <= exp_dt:
                    if "camera_index" not in current_cfg and "camera_index" in config:
                        current_cfg["camera_index"] = config.get("camera_index")
                    if "save_dir" not in current_cfg:
                        current_cfg["save_dir"] = config.get("save_dir") or default_save_dir()
                    save_config(current_cfg)
                    result.update(current_cfg)
                    win.destroy()
                    return

            messagebox.showwarning(
                "Thiếu dữ liệu",
                (
                    "Bạn chưa nhập mã xác minh.\n\n"
                    "Nếu muốn vào app không cần mã, email phải trùng với license đang lưu trên máy "
                    "và license đó vẫn còn hạn."
                ),
                parent=win,
            )
            return

        status_var.set("Đang xác minh...")
        win.update_idletasks()

        def _worker():
            res = verify_email_code(email, code)
            if not res.get("ok"):
                win.after(0, lambda: status_var.set(str(res.get("message", "Không đăng nhập được."))))
                return
            cfg = load_config()
            if "camera_index" not in cfg and "camera_index" in config:
                cfg["camera_index"] = config.get("camera_index")
            if "save_dir" not in cfg:
                cfg["save_dir"] = config.get("save_dir") or default_save_dir()
            save_config(cfg)

            def _done():
                result.update(cfg)
                win.destroy()

            win.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _submit_manual() -> None:
        email = email_var.get().strip().lower()
        key = key_var.get().strip().upper()
        if not email or not key:
            messagebox.showwarning(
                "Thiếu dữ liệu",
                "Nhập email và license để kích hoạt thủ công.",
                parent=win,
            )
            return

        status_var.set("Đang kích hoạt license...")
        win.update_idletasks()

        def _worker():
            res = activate_license(email, key)
            if not res.get("ok"):
                win.after(0, lambda: status_var.set(str(res.get("message", "Không đổi được license."))))
                return
            cfg = load_config()
            if "camera_index" not in cfg and "camera_index" in config:
                cfg["camera_index"] = config.get("camera_index")
            if "save_dir" not in cfg:
                cfg["save_dir"] = config.get("save_dir") or default_save_dir()
            save_config(cfg)

            def _done():
                result.update(cfg)
                win.destroy()

            win.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _clear_only() -> None:
        if not messagebox.askyesno(
            "Xác nhận",
            "Xóa license đang lưu trên máy này?\n\nCamera và thư mục lưu vẫn được giữ lại.",
            parent=win,
        ):
            return
        clear_local_license(keep_settings=True)
        status_var.set("Đã xóa license cũ khỏi máy này. Hãy đăng nhập lại.")
        code_var.set("")
        key_var.set("")

    ttk.Button(btn_row, text="Đóng", command=win.destroy, width=12).pack(side="right")
    ttk.Button(btn_row, text="Nhập license", command=_submit_manual, width=14).pack(side="right", padx=(0, 8))
    ttk.Button(
        btn_row,
        text="Xác minh & vào app",
        command=_submit_verify,
        width=18,
        style="Accent.TButton",
    ).pack(side="right", padx=(0, 8))
    ttk.Button(btn_row, text="Xóa license cũ", command=_clear_only, width=14).pack(side="left")

    email_entry.focus_set()
    _wait_window(win)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# show_setup_window
# ══════════════════════════════════════════════════════════════════════════════
def show_setup_window(config: dict[str, Any], message_text: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}

    win = _toplevel("Thiết lập ban đầu", "720x520")
    win.minsize(640, 420)

    frame = _make_main_container(win, 24)

    ttk.Label(frame, text="Đăng nhập lần đầu", style="Title.TLabel").pack(anchor="w")
    ttk.Label(
        frame,
        text="Nhập email để nhận mã xác minh và bắt đầu dùng thử 7 ngày.",
        style="Subtitle.TLabel",
        wraplength=650,
        justify="left",
    ).pack(anchor="w", pady=(8, 16))

    email_var = tk.StringVar(value=str(config.get("email", "") or ""))
    code_var = tk.StringVar(value="")
    status_var = tk.StringVar(value=message_text)

    ttk.Label(frame, text="Email", style="App.TLabel").pack(anchor="w")
    email_entry = ttk.Entry(frame, textvariable=email_var)
    email_entry.pack(fill="x", pady=(4, 12), ipady=4)

    ttk.Label(frame, text="Mã xác minh", style="App.TLabel").pack(anchor="w")
    row = ttk.Frame(frame)
    row.pack(fill="x", pady=(4, 12))

    code_entry = ttk.Entry(row, textvariable=code_var)
    code_entry.pack(side="left", fill="x", expand=True, ipady=4)

    def _send():
        email = email_var.get().strip().lower()
        if not email:
            messagebox.showwarning("Thiếu email", "Nhập email trước", parent=win)
            return
        status_var.set("Đang gửi mã...")
        win.update_idletasks()

        def _worker():
            res = send_login_code(email)
            win.after(0, lambda: status_var.set(res.get("message", "")))

        threading.Thread(target=_worker, daemon=True).start()

    ttk.Button(row, text="Gửi mã", command=_send).pack(side="left", padx=8)

    ttk.Label(frame, textvariable=status_var, style="Error.TLabel").pack(anchor="w", pady=8)

    def _submit():
        email = email_var.get().strip().lower()
        code = code_var.get().strip()

        if not email or not code:
            messagebox.showwarning("Thiếu dữ liệu", "Nhập email + mã", parent=win)
            return

        status_var.set("Đang xác minh...")
        win.update_idletasks()

        def _worker():
            res = verify_email_code(email, code)
            if not res.get("ok"):
                win.after(0, lambda: status_var.set(res.get("message", "Lỗi xác minh")))
                return
            cfg = load_config()
            cfg["camera_index"] = 0
            cfg["save_dir"] = default_save_dir()
            save_config(cfg)

            def _done():
                result.update(cfg)
                win.destroy()

            win.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    btn_row = ttk.Frame(frame)
    btn_row.pack(fill="x", side="bottom", pady=20)

    ttk.Button(btn_row, text="Thoát", command=win.destroy).pack(side="right")
    ttk.Button(btn_row, text="Vào app", command=_submit, style="Accent.TButton").pack(side="right", padx=8)

    email_entry.focus_set()
    _wait_window(win)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# show_camera_picker
# ══════════════════════════════════════════════════════════════════════════════
def show_camera_picker(config: dict[str, Any], message: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}

    scan_win = _toplevel("Đang tìm camera...", "420x130", resizable=False)
    f = _make_main_container(scan_win, 18)
    ttk.Label(f, text="Đang tìm camera...", style="App.TLabel").pack(anchor="w")
    bar = ttk.Progressbar(f, mode="indeterminate")
    bar.pack(fill="x", pady=(12, 0))
    bar.start(10)
    scan_win.update()
    cameras = list_cameras()
    bar.stop()
    scan_win.destroy()

    if not cameras:
        _show_no_camera()
        return result

    default_cam = int(config.get("camera_index", cameras[0]))
    if default_cam not in cameras:
        default_cam = cameras[0]

    win = _toplevel("Chọn camera", "720x500")
    win.minsize(640, 420)

    frame = _make_main_container(win, 24)

    ttk.Label(frame, text="Chọn camera", style="Title.TLabel").pack(anchor="w")

    email = config.get("email", "")
    expires_at = config.get("expires_at", "")
    app_ver_text = f"Phiên bản: v{APP_VERSION}"
    ttk.Label(frame, text=f"Tài khoản: {email}  |  {app_ver_text}", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

    exp_text = _expires_label(expires_at)
    exp_dt = _parse_dt(expires_at)
    exp_color_style = "Error.TLabel" if (exp_dt and (exp_dt - _utcnow()).days <= 5) else "App.TLabel"
    if exp_text:
        ttk.Label(frame, text=exp_text, style=exp_color_style).pack(anchor="w", pady=(2, 10))

    cam_var = tk.StringVar(value=str(default_cam))
    ttk.Label(frame, text="Camera", style="App.TLabel").pack(anchor="w")
    ttk.Combobox(
        frame,
        textvariable=cam_var,
        state="readonly",
        values=[str(x) for x in cameras],
    ).pack(fill="x", pady=(4, 10), ipady=3)

    save_dir_var = tk.StringVar(value=config.get("save_dir", "") or default_save_dir())
    ttk.Label(frame, text="Thư mục lưu video", style="App.TLabel").pack(anchor="w")
    row_dir = ttk.Frame(frame, style="App.TFrame")
    row_dir.pack(fill="x", pady=(4, 10))
    ttk.Entry(row_dir, textvariable=save_dir_var).pack(side="left", fill="x", expand=True, ipady=4)
    ttk.Button(
        row_dir,
        text="Chọn...",
        command=lambda: save_dir_var.set(
            filedialog.askdirectory(initialdir=save_dir_var.get()) or save_dir_var.get()
        ),
        width=12,
    ).pack(side="left", padx=(8, 0))

    ttk.Label(
        frame,
        text="Mẹo: Trong màn camera bấm F để full screen, B để quay lại chọn camera, C để đổi camera, Q/ESC để thoát.",
        style="Muted.TLabel",
        wraplength=650,
        justify="left",
    ).pack(anchor="w", pady=(4, 8))

    if message:
        ttk.Label(frame, text=message, style="Error.TLabel", wraplength=650).pack(anchor="w", pady=(6, 0))

    btn_row = ttk.Frame(frame, style="App.TFrame")
    btn_row.pack(fill="x", side="bottom", pady=(18, 0))

    def _submit() -> None:
        cfg = load_config()
        cfg["camera_index"] = int(cam_var.get())
        cfg["save_dir"] = save_dir_var.get().strip() or default_save_dir()
        Path(cfg["save_dir"]).mkdir(parents=True, exist_ok=True)
        save_config(cfg)
        result.update(cfg)
        win.destroy()

    def _renew() -> None:
        result["action"] = "renew"
        win.destroy()

    def _change_license() -> None:
        new_cfg = show_change_license_window(
            load_config(),
            "Nhập license khác để dùng trên máy này.",
        )
        if new_cfg:
            result.update(new_cfg)
            win.destroy()

    ttk.Button(btn_row, text="Thoát", command=win.destroy, width=12).pack(side="right")
    ttk.Button(
        btn_row,
        text="Mở camera",
        command=_submit,
        width=14,
        style="Accent.TButton",
    ).pack(side="right", padx=(0, 8))
    ttk.Button(btn_row, text="Đăng nhập lại", command=_change_license, width=14).pack(side="left")
    ttk.Button(btn_row, text="Gia hạn", command=_renew, width=12).pack(side="left", padx=(8, 0))

    _wait_window(win)
    return result


def _show_no_camera() -> None:
    messagebox.showerror(
        "Không tìm thấy camera",
        "Không tìm thấy camera nào.\n\nKiểm tra:\n- Webcam đã cắm chưa\n- Camera có bị phần mềm khác chiếm không\n- Driver camera đã đúng chưa",
        parent=_get_root(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# Barcode + recording
# ══════════════════════════════════════════════════════════════════════════════
def sanitize(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]+', "_", text.strip())
    return re.sub(r"\s+", "_", text)[:120] or "unknown"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return [x for x in items if not (x in seen or seen.add(x))]


def detect_codes(frame) -> tuple[list[str], list]:
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (640, int(h * 640 / w))) if w > 640 else frame
    objects = pyzbar_decode(small)
    codes = []
    for obj in objects:
        try:
            t = obj.data.decode("utf-8").strip()
        except Exception:
            t = obj.data.decode("latin1", errors="ignore").strip()
        if t:
            codes.append(t)
    return _unique(codes), objects


def draw_codes(frame, objects, scale_x: float = 1.0, scale_y: float = 1.0) -> None:
    for obj in objects:
        x, y, w, h = obj.rect
        x, y, w, h = int(x * scale_x), int(y * scale_y), int(w * scale_x), int(h * scale_y)
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 220, 0), 2)
        try:
            txt = obj.data.decode("utf-8").strip()
        except Exception:
            txt = obj.data.decode("latin1", errors="ignore").strip()
        if txt:
            cv2.putText(frame, txt[:40], (x, max(20, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 0), 2, cv2.LINE_AA)


def run_recorder(config: dict[str, Any]) -> dict[str, Any] | None:
    cam_idx = int(config.get("camera_index", 0))
    save_dir = str(config.get("save_dir", "") or default_save_dir())
    Path(save_dir).mkdir(parents=True, exist_ok=True)

    expires_at = config.get("expires_at", "")
    exp_dt = _parse_dt(expires_at)

    cap = open_camera(cam_idx)
    if cap is None:
        messagebox.showerror("Camera", f"Không mở được camera {cam_idx}.")
        return {"action": "camera_failed"}

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 1280, 720)

    back_btn = {"x": 20, "y": 20, "w": 64, "h": 44}
    mouse_state = {"clicked_back": False}

    def _mouse_cb(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONUP:
            bx, by, bw, bh = back_btn["x"], back_btn["y"], back_btn["w"], back_btn["h"]
            if bx <= x <= bx + bw and by <= y <= by + bh:
                mouse_state["clicked_back"] = True

    cv2.setMouseCallback(WINDOW_NAME, _mouse_cb)

    writer = None
    is_recording = False
    current_code = None
    current_path = None
    status_msg = "Sẵn sàng quét mã"
    status_until = 0.0
    next_accept_at = 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                messagebox.showerror("Camera", "Không đọc được khung hình.")
                return {"action": "camera_failed"}

            h, w = frame.shape[:2]
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 1 or fps > 120:
                fps = DEFAULT_FPS

            codes, objects = detect_codes(frame)
            scale_x = w / (640 if w > 640 else w)
            scale_y = h / (int(h * 640 / w) if w > 640 else h)

            display = frame.copy()
            draw_codes(display, objects, scale_x, scale_y)
            now = time.time()

            if exp_dt and _utcnow() > exp_dt:
                cv2.destroyAllWindows()
                if writer:
                    writer.release()
                cap.release()
                ans = messagebox.askyesnocancel(
                    "License đã hết hạn",
                    f"License đã hết hạn lúc {_fmt_local(exp_dt)}.\n\n"
                    "Yes  = Gia hạn\n"
                    "No   = Đăng nhập / nhập license khác\n"
                    "Cancel = Đóng app",
                )
                if ans is True:
                    return {"action": "renew", "message": "License đã hết hạn."}
                if ans is False:
                    return {"action": "change_license", "message": "License đã hết hạn. Hãy đăng nhập lại hoặc nhập license mới."}
                return {"action": "quit"}

            if now < next_accept_at:
                remaining = max(0.0, next_accept_at - now)
                status_msg = f"Chờ {remaining:.1f}s để quét tiếp"
                status_until = now + 0.2
            elif codes:
                code = codes[0]
                next_accept_at = now + ACCEPT_COOLDOWN

                if not is_recording:
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    path = os.path.join(save_dir, f"{sanitize(code)}_{ts}{VIDEO_EXT}")
                    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*FOURCC), fps, (w, h))
                    if not writer.isOpened():
                        writer = None
                        current_path = None
                        status_msg = "Không tạo được file video"
                        status_until = now + 3
                    else:
                        is_recording = True
                        current_code = code
                        current_path = path
                        status_msg = f"Bắt đầu ghi: {code}"
                        status_until = now + 3
                        say_start_recording()
                else:
                    if code == current_code:
                        if writer:
                            writer.release()
                            writer = None
                        status_msg = f"Kết thúc ghi: {current_code}"
                        status_until = now + 4
                        is_recording = False
                        current_code = None
                        current_path = None
                        say_stop_recording()
                    else:
                        status_msg = f"Đang ghi mã {current_code}. Quét lại đúng mã đó để dừng."
                        status_until = now + 3

            now_dt = datetime.now()

            if is_recording:
                draw_recording_stamp(frame, now_dt, current_code=current_code)
                draw_recording_stamp(display, now_dt, current_code=current_code)

            if is_recording and writer:
                writer.write(frame)

            bx, by, bw, bh = back_btn["x"], back_btn["y"], back_btn["w"], back_btn["h"]
            cv2.rectangle(display, (bx, by), (bx + bw, by + bh), (255, 255, 255), -1)
            cv2.rectangle(display, (bx, by), (bx + bw, by + bh), (40, 40, 40), 2)
            cv2.putText(display, "<-", (bx + 14, by + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (40, 40, 40), 2, cv2.LINE_AA)

            if now < status_until and status_msg:
                draw_text_clean(
                    display,
                    status_msg,
                    (18, max(70, by + bh + 26)),
                    font_scale=0.72,
                    thickness=2,
                    text_color=(255, 255, 255),
                    bg_color=(20, 20, 20),
                    padding=8,
                )

            fitted = _fit_frame_to_window(display, WINDOW_NAME)
            cv2.imshow(WINDOW_NAME, fitted)

            if mouse_state["clicked_back"]:
                mouse_state["clicked_back"] = False
                return {"action": "change_camera"}

            key = cv2.waitKey(1) & 0xFF

            if key in (27, ord("q"), ord("Q")):
                return {"action": "quit"}
            if key in (ord("c"), ord("C")):
                return {"action": "change_camera"}
            if key in (ord("b"), ord("B")):
                return {"action": "change_camera"}
            if key in (ord("f"), ord("F")):
                try:
                    current = cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN)
                    if current == cv2.WINDOW_FULLSCREEN:
                        cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
                    else:
                        cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                except Exception:
                    pass

            try:
                if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                    return {"action": "quit"}
            except Exception:
                pass

    finally:
        if writer:
            writer.release()
        cap.release()
        cv2.destroyAllWindows()


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    _get_root()

    config = load_config()
    checked = check_license(config)

    if not checked.get("ok"):
        msg = str(checked.get("message", ""))

        if config.get("email") or config.get("license_key"):
            ans = messagebox.askyesnocancel(
                "License không hợp lệ",
                f"{msg}\n\n"
                "Yes  = Đăng nhập lại bằng email / mã xác minh\n"
                "No   = Gia hạn license hiện tại\n"
                "Cancel = Thoát",
            )
            if ans is True:
                config = show_change_license_window(config, msg)
                if not config:
                    return
            elif ans is False:
                show_renewal_window(config, msg)
                return
            else:
                return
        else:
            config = show_setup_window(config, msg)
            if not config:
                return

        checked = check_license(config)
        if not checked.get("ok"):
            messagebox.showerror("License", str(checked.get("message", "Không kiểm tra được license.")))
            return

    if checked.get("ok") and checked.get("expires_at"):
        config["expires_at"] = checked["expires_at"]
        save_config(config)

    check_update_async()

    while True:
        picker_result = show_camera_picker(config)
        if not picker_result:
            return

        if picker_result.get("action") == "renew":
            show_renewal_window(load_config())
            return

        config = picker_result

        result = run_recorder(config)
        if not result:
            return

        action = result.get("action", "quit")

        if action == "quit":
            return

        if action == "renew":
            show_renewal_window(load_config(), str(result.get("message", "")))
            return

        if action == "change_license":
            new_cfg = show_change_license_window(load_config(), str(result.get("message", "")))
            if not new_cfg:
                return
            config = new_cfg
            checked = check_license(config)
            if checked.get("ok") and checked.get("expires_at"):
                config["expires_at"] = checked["expires_at"]
                save_config(config)
            continue

        if action == "change_camera":
            continue


if __name__ == "__main__":
    main()
