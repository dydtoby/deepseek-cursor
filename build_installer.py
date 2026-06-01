"""DeepSeek Cursor Proxy 跨平台构建流水线。

用法:
  python build_installer.py              # 完整构建（PyInstaller + ngrok + Windows InnoSetup）
  python build_installer.py --freeze-only # 仅 PyInstaller 冻结
  python build_installer.py --installer-only # 仅生成 Windows 安装程序（需要先冻结）
  python build_installer.py --clean       # 清理构建产物
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
FREEZE_OUTPUT = DIST_DIR / "DeepSeekCursorProxy"
APP_NAME = "DeepSeek Cursor Proxy"
APP_VERSION = "0.1.3"
APP_PUBLISHER = "DeepSeek Cursor Proxy"
APP_INSTALL_FOLDER = "DeepSeekCursorProxy"
INSTALLER_OUTPUT = DIST_DIR / f"DeepSeekCursorProxy-v{APP_VERSION}-Setup.exe"

_regenerate_icon = False

INNO_SETUP_PATHS = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
    str(Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe"),
]

sys.path.insert(0, str(PROJECT_ROOT / "src"))
from deepseek_cursor_proxy.platform_support import (  # noqa: E402
    app_executable_name,
    download_ngrok_binary,
    ngrok_binary_name,
    portable_archive_suffix,
    pyinstaller_add_data_sep,
    system_slug,
)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_inno_setup() -> str | None:
    if sys.platform != "win32":
        return None
    for path in INNO_SETUP_PATHS:
        if Path(path).is_file():
            return path
    return None


def run_cmd(cmd: list[str], cwd: Path | None = None, desc: str = "") -> None:
    print(f"\n{'='*60}")
    print(f"  {desc}")
    print(f"  {' '.join(cmd)}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, cwd=cwd, text=True)
    if result.returncode != 0:
        print(f"\n[ERROR] 命令失败，退出码: {result.returncode}")
        sys.exit(1)


def step_generate_icon() -> Path | None:
    if sys.platform != "win32":
        print("\n[步骤 0/3] 跳过 .ico（非 Windows 平台）")
        return None

    print("\n[步骤 0/3] 准备应用图标...")
    icon_path = PROJECT_ROOT / "assets" / "app_icon.ico"

    if _regenerate_icon:
        from generate_icon import generate_icon

        generate_icon(icon_path)
    elif icon_path.is_file() and icon_path.stat().st_size > 0:
        print(f"  使用现有图标: {icon_path} ({icon_path.stat().st_size:,} bytes)")
    else:
        print("  未找到 assets/app_icon.ico，尝试从 logo.png 生成...")
        from generate_icon import generate_icon

        generate_icon(icon_path)

    if not icon_path.is_file() or icon_path.stat().st_size == 0:
        print(f"\n[ERROR] 图标不可用: {icon_path}")
        print("请将 app_icon.ico 放入 assets/ 目录，或使用 --regenerate-icon 生成。")
        sys.exit(1)
    return icon_path


def step_freeze() -> Path:
    print(f"\n[步骤 1/3] PyInstaller 冻结 ({system_slug()})...")

    output_dir = DIST_DIR / "DeepSeekCursorProxy"
    if output_dir.exists():
        shutil.rmtree(output_dir)

    icon_path = step_generate_icon()
    assets_src = PROJECT_ROOT / "assets"
    add_data = f"{assets_src}{pyinstaller_add_data_sep()}assets"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        "DeepSeekCursorProxy",
        "--onedir",
        "--noconfirm",
        "--clean",
        "--paths",
        str(PROJECT_ROOT / "src"),
        "--collect-submodules",
        "deepseek_cursor_proxy",
        "--add-data",
        add_data,
        "--hidden-import",
        "deepseek_cursor_proxy.gui",
        "--hidden-import",
        "deepseek_cursor_proxy.server",
        "--hidden-import",
        "deepseek_cursor_proxy.config",
        "--hidden-import",
        "deepseek_cursor_proxy.ngrok_manager",
        "--hidden-import",
        "deepseek_cursor_proxy.platform_support",
        "--hidden-import",
        "deepseek_cursor_proxy.tunnel",
        "--hidden-import",
        "deepseek_cursor_proxy.reasoning_store",
        "--hidden-import",
        "deepseek_cursor_proxy.transform",
        "--hidden-import",
        "deepseek_cursor_proxy.streaming",
        "--hidden-import",
        "deepseek_cursor_proxy.trace",
        "--hidden-import",
        "deepseek_cursor_proxy.logging",
        "--hidden-import",
        "deepseek_cursor_proxy.i18n",
        "--hidden-import",
        "yaml",
        str(PROJECT_ROOT / "launcher.py"),
    ]

    if sys.platform in {"win32", "darwin"}:
        cmd.insert(cmd.index("--onedir") + 1, "--windowed")
    if icon_path is not None:
        cmd.extend(["--icon", str(icon_path)])

    run_cmd(cmd, cwd=PROJECT_ROOT, desc="PyInstaller 冻结")

    exe_name = app_executable_name()
    exe_path = output_dir / exe_name
    if not exe_path.is_file():
        print(f"\n[ERROR] 冻结产物未找到: {exe_path}")
        sys.exit(1)

    print(f"  冻结完成: {output_dir}")

    if sys.platform == "win32":
        for script_name in ("install.bat", "uninstall.bat"):
            script_src = PROJECT_ROOT / "scripts" / script_name
            if script_src.is_file():
                shutil.copy2(script_src, output_dir / script_name)
    else:
        install_sh_src = PROJECT_ROOT / "scripts" / "install.sh"
        if install_sh_src.is_file():
            shutil.copy2(install_sh_src, output_dir / "install.sh")
            (output_dir / "install.sh").chmod(0o755)
        service_install_src = PROJECT_ROOT / "scripts" / "install-linux-service.sh"
        if service_install_src.is_file():
            shutil.copy2(service_install_src, output_dir / "install-linux-service.sh")
            (output_dir / "install-linux-service.sh").chmod(0o755)
        service_unit_src = PROJECT_ROOT / "scripts" / "deepseek-cursor-proxy.service"
        if service_unit_src.is_file():
            shutil.copy2(service_unit_src, output_dir / "deepseek-cursor-proxy.service")

    start_sh_src = PROJECT_ROOT / "scripts" / "start-proxy.sh"
    if start_sh_src.is_file():
        shutil.copy2(start_sh_src, output_dir / "start-proxy.sh")
        (output_dir / "start-proxy.sh").chmod(0o755)

    if icon_path is not None and icon_path.is_file():
        shutil.copy2(icon_path, output_dir / "app_icon.ico")

    return output_dir


def step_download_ngrok(freeze_dir: Path) -> Path:
    print("\n[步骤 2/3] 下载 ngrok...")

    binary_name = ngrok_binary_name()
    ngrok_path = freeze_dir / binary_name
    if ngrok_path.is_file():
        print(f"  {binary_name} 已存在: {ngrok_path}")
        return ngrok_path

    def _report(block: int, block_size: int, total: int) -> None:
        downloaded = block * block_size
        if total > 0:
            pct = min(100, int(downloaded * 100 / total))
            print(f"\r  下载中... {pct}% ({downloaded:,} / {total:,} bytes)", end="")

    try:
        ngrok_path = download_ngrok_binary(freeze_dir, report=_report)
        print()
    except Exception as exc:
        print(f"\n[ERROR] ngrok 下载失败: {exc}")
        print("请手动从 https://ngrok.com/download 下载 ngrok 并放入:")
        print(f"  {freeze_dir / binary_name}")
        sys.exit(1)

    print(f"  {binary_name} 已提取: {ngrok_path}")
    return ngrok_path


def step_create_zip(freeze_dir: Path) -> Path:
    print("\n[步骤 4/4] 创建便携版 ZIP...")

    zip_path = (
        DIST_DIR
        / f"DeepSeekCursorProxy-v{APP_VERSION}-portable-{portable_archive_suffix()}.zip"
    )
    if zip_path.is_file():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in freeze_dir.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(freeze_dir.parent))

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  ZIP 已生成: {zip_path} ({size_mb:.1f} MB)")
    return zip_path


def step_create_installer(freeze_dir: Path) -> Path:
    print("\n[步骤 3/3] InnoSetup 打包...")

    iscc = find_inno_setup()
    if iscc is None:
        print("\n[WARNING] 未找到 InnoSetup（仅 Windows 可用）。")
        print(f"\n冻结产物已就绪: {freeze_dir}")
        return freeze_dir

    iss_content = _generate_iss(freeze_dir)
    iss_path = BUILD_DIR / "installer.iss"
    ensure_dir(BUILD_DIR)
    iss_path.write_text(iss_content, encoding="utf-8")

    cmd = [iscc, str(iss_path)]
    run_cmd(cmd, cwd=PROJECT_ROOT, desc="InnoSetup 编译")

    if INSTALLER_OUTPUT.is_file():
        print(f"\n  安装程序已生成: {INSTALLER_OUTPUT}")
    else:
        print("\n[WARNING] 安装程序未在预期位置找到")

    return INSTALLER_OUTPUT


def _generate_iss(freeze_dir: Path) -> str:
    exe_name = app_executable_name()
    setup_icon = str(PROJECT_ROOT / "assets" / "app_icon.ico").replace("/", "\\")
    output_dir = str(DIST_DIR).replace("/", "\\")
    freeze_source = str(freeze_dir).replace("/", "\\")
    return f'''; InnoSetup 脚本 — 由 build_installer.py 自动生成

#define MyAppName "{APP_NAME}"
#define MyAppVersion "{APP_VERSION}"
#define MyAppPublisher "{APP_PUBLISHER}"
#define MyAppExeName "{exe_name}"
#define MyAppInstallFolder "{APP_INSTALL_FOLDER}"

[Setup]
AppId={{{{F1A2B3C4-D5E6-7890-ABCD-EF1234567890}}}}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
DefaultDirName={{localappdata}}\\Programs\\{{#MyAppInstallFolder}}
DefaultGroupName={{#MyAppName}}
AllowNoIcons=yes
OutputDir={output_dir}
OutputBaseFilename=DeepSeekCursorProxy-v{APP_VERSION}-Setup
SetupIconFile={setup_icon}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={{#MyAppName}}
UninstallDisplayIcon={{app}}\\app_icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项:"; Flags: unchecked
Name: "autostart"; Description: "登录 Windows 时自动启动 DeepSeek Cursor Proxy"; GroupDescription: "启动选项:"; Flags: unchecked
Name: "deleteconfig"; Description: "卸载时删除用户配置（~\\.deepseek-cursor-proxy）"; GroupDescription: "卸载选项:"; Flags: unchecked

[Files]
Source: "{freeze_source}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; IconFilename: "{{app}}\\app_icon.ico"
Name: "{{group}}\\卸载 {{#MyAppName}}"; Filename: "{{uninstallexe}}"
Name: "{{commondesktop}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; IconFilename: "{{app}}\\app_icon.ico"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\\Microsoft\\Windows\\CurrentVersion\\Run"; ValueType: string; ValueName: "DeepSeekCursorProxy"; ValueData: """{{app}}\\{{#MyAppExeName}}"""; Flags: uninsdeletevalue; Tasks: autostart

[UninstallDelete]
Type: filesandordirs; Name: "{{userappdata}}\\.deepseek-cursor-proxy"; Tasks: deleteconfig

[Run]
Filename: "{{app}}\\{{#MyAppExeName}}"; Description: "启动 {{#MyAppName}}"; Flags: nowait postinstall skipifsilent
'''


def step_clean() -> None:
    print("\n[清理] 删除构建产物...")
    for path in [DIST_DIR, BUILD_DIR]:
        if path.exists():
            shutil.rmtree(path)
            print(f"  已删除: {path}")
    for spec in PROJECT_ROOT.glob("*.spec"):
        spec.unlink()
        print(f"  已删除: {spec}")


def build_full() -> None:
    print("=" * 60)
    print(f"  {APP_NAME} 构建流水线 v{APP_VERSION} ({system_slug()})")
    print("=" * 60)

    freeze_dir = step_freeze()
    step_download_ngrok(freeze_dir)
    installer_path = step_create_installer(freeze_dir)
    zip_path = step_create_zip(freeze_dir)

    print("\n" + "=" * 60)
    print("  构建完成!")
    print(f"  便携版目录: {freeze_dir}")
    print(f"  便携版 ZIP: {zip_path}")
    if installer_path != freeze_dir:
        print(f"  安装程序: {installer_path}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="DeepSeek Cursor Proxy 构建工具")
    parser.add_argument("--freeze-only", action="store_true", help="仅执行 PyInstaller 冻结")
    parser.add_argument(
        "--installer-only",
        action="store_true",
        help="仅生成 Windows 安装程序（需要先冻结）",
    )
    parser.add_argument("--clean", action="store_true", help="清理所有构建产物")
    parser.add_argument(
        "--regenerate-icon",
        action="store_true",
        help="从 assets/logo.png 重新生成 app_icon.ico（默认使用现有图标）",
    )
    args = parser.parse_args()

    global _regenerate_icon
    _regenerate_icon = args.regenerate_icon

    if args.clean:
        step_clean()
        return

    if args.freeze_only:
        step_freeze()
        return

    if args.installer_only:
        freeze_dir = DIST_DIR / "DeepSeekCursorProxy"
        if not freeze_dir.is_dir():
            print("[ERROR] 未找到冻结产物，请先运行 --freeze-only")
            sys.exit(1)
        step_create_installer(freeze_dir)
        return

    build_full()


if __name__ == "__main__":
    main()
