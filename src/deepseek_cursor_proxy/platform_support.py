"""跨平台路径、二进制名与构建辅助。"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Callable
from urllib.request import urlretrieve

NGROK_CDN_PREFIX = "https://bin.equinox.io/c/bNyj1mQVY4c/"

NGROK_DOWNLOADS: dict[tuple[str, str], tuple[str, str]] = {
    ("windows", "amd64"): (
        f"{NGROK_CDN_PREFIX}ngrok-v3-stable-windows-amd64.zip",
        "ngrok.exe",
    ),
    ("windows", "arm64"): (
        f"{NGROK_CDN_PREFIX}ngrok-v3-stable-windows-arm64.zip",
        "ngrok.exe",
    ),
    ("darwin", "amd64"): (
        f"{NGROK_CDN_PREFIX}ngrok-v3-stable-darwin-amd64.zip",
        "ngrok",
    ),
    ("darwin", "arm64"): (
        f"{NGROK_CDN_PREFIX}ngrok-v3-stable-darwin-arm64.zip",
        "ngrok",
    ),
    ("linux", "amd64"): (
        f"{NGROK_CDN_PREFIX}ngrok-v3-stable-linux-amd64.tgz",
        "ngrok",
    ),
    ("linux", "arm64"): (
        f"{NGROK_CDN_PREFIX}ngrok-v3-stable-linux-arm64.tgz",
        "ngrok",
    ),
}


def system_slug() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def machine_slug() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        return "amd64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return machine


def ngrok_binary_name() -> str:
    return "ngrok.exe" if sys.platform == "win32" else "ngrok"


def app_executable_name() -> str:
    return "DeepSeekCursorProxy.exe" if sys.platform == "win32" else "DeepSeekCursorProxy"


def pyinstaller_add_data_sep() -> str:
    return ";" if sys.platform == "win32" else ":"


def portable_archive_suffix() -> str:
    return f"{system_slug()}-{machine_slug()}"


def ngrok_download_spec() -> tuple[str, str]:
    key = (system_slug(), machine_slug())
    spec = NGROK_DOWNLOADS.get(key)
    if spec is None:
        supported = ", ".join(f"{os_name}/{arch}" for os_name, arch in NGROK_DOWNLOADS)
        raise RuntimeError(
            f"当前平台 {key[0]}/{key[1]} 暂无预置 ngrok 下载地址。"
            f" 支持: {supported}。请从 https://ngrok.com/download 手动安装 ngrok。"
        )
    return spec


def ngrok_config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        )
        return base / "ngrok"
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "ngrok"
        )
    return Path.home() / ".config" / "ngrok"


def legacy_ngrok_config_paths(primary: Path | None = None) -> list[Path]:
    """旧版 ngrok 可能存放 authtoken 的配置路径（不含主配置）。"""
    primary = primary or (ngrok_config_dir() / "ngrok.yml")
    candidates: list[Path] = [
        Path.home() / ".ngrok2" / "ngrok.yml",
    ]
    if sys.platform == "win32":
        appdata = Path(
            os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
        )
        candidates.append(appdata / "ngrok" / "ngrok.yml")

    paths: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate == primary:
            continue
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        paths.append(candidate)
    return paths


def gui_fonts() -> dict[str, tuple[str, int, str] | tuple[str, int]]:
    if sys.platform == "darwin":
        ui = "Helvetica Neue"
        mono = "Menlo"
    elif sys.platform == "win32":
        ui = "Segoe UI"
        mono = "Cascadia Code"
    else:
        ui = "DejaVu Sans"
        mono = "DejaVu Sans Mono"
    return {
        "title": (ui, 16, "bold"),
        "heading": (ui, 13, "bold"),
        "body": (ui, 11),
        "mono": (mono, 10),
        "url": (mono, 11),
        "small": (ui, 9),
    }


def stop_ngrok_processes() -> None:
    binary = ngrok_binary_name()
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/IM", binary, "/F"],
            capture_output=True,
            text=True,
        )
        return

    subprocess.run(
        ["pkill", "-f", "ngrok"],
        capture_output=True,
        text=True,
    )


def make_executable(path: Path) -> None:
    if sys.platform == "win32" or not path.is_file():
        return
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def extract_ngrok_archive(
    archive_path: Path,
    dest_dir: Path,
    *,
    member_name: str,
    report: Callable[[int, int, int], None] | None = None,
) -> Path:
    """从 ngrok 官方 zip/tgz 包中提取二进制。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = archive_path.suffix.lower()
    binary_path = dest_dir / member_name

    if suffix == ".zip":
        with zipfile.ZipFile(archive_path, "r") as archive:
            archive.extract(member_name, dest_dir)
    elif suffix in {".tgz", ".gz"} or archive_path.name.endswith(".tar.gz"):
        with tarfile.open(archive_path, "r:gz") as archive:
            try:
                member = archive.getmember(member_name)
            except KeyError as exc:
                raise RuntimeError(
                    f"ngrok 压缩包中未找到 {member_name}"
                ) from exc
            archive.extract(member, dest_dir)
    else:
        raise RuntimeError(f"不支持的 ngrok 压缩格式: {archive_path}")

    if not binary_path.is_file():
        raise RuntimeError(f"ngrok 二进制未找到: {binary_path}")

    make_executable(binary_path)
    return binary_path


def download_ngrok_binary(
    dest_dir: Path,
    *,
    report: Callable[[int, int, int], None] | None = None,
) -> Path:
    """下载并解压当前平台的 ngrok 到目标目录。"""
    url, member_name = ngrok_download_spec()
    archive_path = dest_dir / Path(url).name
    if report is None:
        urlretrieve(url, archive_path)
    else:
        urlretrieve(url, archive_path, reporthook=report)

    try:
        return extract_ngrok_archive(archive_path, dest_dir, member_name=member_name)
    finally:
        if archive_path.is_file():
            archive_path.unlink()


def find_bundled_ngrok(repo_root: Path, *, frozen: bool) -> str | None:
    """在打包目录或项目 assets 中查找捆绑的 ngrok。"""
    name = ngrok_binary_name()
    candidates: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / name)

    if frozen:
        candidates.append(Path(sys.executable).parent / name)

    candidates.append(repo_root / "assets" / name)

    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def find_ngrok_on_path() -> str | None:
    return shutil.which("ngrok") or (
        shutil.which("ngrok.exe") if sys.platform == "win32" else None
    )
