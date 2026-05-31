"""DeepSeek Cursor Proxy 构建流水线。

用法:
  python build_installer.py              # 完整构建（PyInstaller + ngrok + InnoSetup）
  python build_installer.py --freeze-only # 仅 PyInstaller 冻结
  python build_installer.py --installer-only # 仅生成安装程序（需要先冻结）
  python build_installer.py --clean       # 清理构建产物
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
FREEZE_OUTPUT = DIST_DIR / "DeepSeekCursorProxy"
INSTALLER_OUTPUT = DIST_DIR / "DeepSeekCursorProxy-Setup.exe"

APP_NAME = "DeepSeek Cursor Proxy"
APP_VERSION = "0.1.1"
APP_PUBLISHER = "DeepSeek Cursor Proxy"
APP_EXE_NAME = "DeepSeekCursorProxy.exe"

# InnoSetup 路径（常见安装位置）
INNO_SETUP_PATHS = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
]

# ngrok 下载 URL
NGROK_DOWNLOAD_URL = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_inno_setup() -> str | None:
    """查找 InnoSetup 编译器。"""
    for path in INNO_SETUP_PATHS:
        if Path(path).is_file():
            return path
    return None


def run_cmd(cmd: list[str], cwd: Path | None = None, desc: str = "") -> None:
    """运行命令并打印输出。"""
    print(f"\n{'='*60}")
    print(f"  {desc}")
    print(f"  {' '.join(cmd)}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, cwd=cwd, text=True)
    if result.returncode != 0:
        print(f"\n[ERROR] 命令失败，退出码: {result.returncode}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 步骤 1: PyInstaller 冻结
# ---------------------------------------------------------------------------


def step_generate_icon() -> Path:
    """生成多尺寸 Windows .ico 文件。"""
    print("\n[步骤 0/3] 生成应用图标...")
    icon_path = PROJECT_ROOT / "assets" / "app_icon.ico"
    sys.path.insert(0, str(PROJECT_ROOT))
    from generate_icon import generate_icon

    generate_icon(icon_path)
    if not icon_path.is_file():
        print(f"\n[ERROR] 图标生成失败: {icon_path}")
        sys.exit(1)
    print(f"  图标路径: {icon_path} ({icon_path.stat().st_size:,} bytes)")
    return icon_path


def step_freeze() -> Path:
    """使用 PyInstaller 将 Python 应用冻结为独立目录。"""
    print("\n[步骤 1/3] PyInstaller 冻结...")

    output_dir = DIST_DIR / "DeepSeekCursorProxy"
    if output_dir.exists():
        shutil.rmtree(output_dir)

    icon_path = step_generate_icon()
    icon_arg = ["--icon", str(icon_path)]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "DeepSeekCursorProxy",
        "--onedir",
        "--windowed",  # Windows GUI 模式（不显示控制台）
        "--noconfirm",
        "--clean",
        "--paths", str(PROJECT_ROOT / "src"),
        "--collect-submodules", "deepseek_cursor_proxy",
        "--add-data", f"{PROJECT_ROOT / 'assets'};assets",
        *icon_arg,
        "--hidden-import", "deepseek_cursor_proxy.gui",
        "--hidden-import", "deepseek_cursor_proxy.server",
        "--hidden-import", "deepseek_cursor_proxy.config",
        "--hidden-import", "deepseek_cursor_proxy.ngrok_manager",
        "--hidden-import", "deepseek_cursor_proxy.tunnel",
        "--hidden-import", "deepseek_cursor_proxy.reasoning_store",
        "--hidden-import", "deepseek_cursor_proxy.transform",
        "--hidden-import", "deepseek_cursor_proxy.streaming",
        "--hidden-import", "deepseek_cursor_proxy.trace",
        "--hidden-import", "deepseek_cursor_proxy.logging",
        "--hidden-import", "deepseek_cursor_proxy.i18n",
        "--hidden-import", "yaml",
        str(PROJECT_ROOT / "launcher.py"),
    ]

    run_cmd(cmd, cwd=PROJECT_ROOT, desc="PyInstaller 冻结")

    # 验证输出
    exe_path = output_dir / f"{APP_EXE_NAME}"
    if not exe_path.is_file():
        print(f"\n[ERROR] 冻结产物未找到: {exe_path}")
        sys.exit(1)

    print(f"  冻结完成: {output_dir}")

    # 复制安装脚本和图标到产物目录
    install_bat_src = PROJECT_ROOT / "scripts" / "install.bat"
    if install_bat_src.is_file():
        shutil.copy2(install_bat_src, output_dir / "install.bat")
    shutil.copy2(icon_path, output_dir / "app_icon.ico")

    return output_dir


# ---------------------------------------------------------------------------
# 步骤 2: 下载 ngrok
# ---------------------------------------------------------------------------


def step_download_ngrok(freeze_dir: Path) -> Path:
    """下载 ngrok.exe 并放入冻结目录。"""
    print("\n[步骤 2/3] 下载 ngrok...")

    ngrok_exe = freeze_dir / "ngrok.exe"
    if ngrok_exe.is_file():
        print(f"  ngrok.exe 已存在: {ngrok_exe}")
        return ngrok_exe

    zip_path = freeze_dir / "ngrok.zip"
    print(f"  下载: {NGROK_DOWNLOAD_URL}")

    def _report(block: int, block_size: int, total: int) -> None:
        downloaded = block * block_size
        if total > 0:
            pct = min(100, int(downloaded * 100 / total))
            print(f"\r  下载中... {pct}% ({downloaded:,} / {total:,} bytes)", end="")

    try:
        urlretrieve(NGROK_DOWNLOAD_URL, zip_path, _report)
        print()
    except Exception as exc:
        print(f"\n[ERROR] ngrok 下载失败: {exc}")
        print("请手动从 https://ngrok.com/download 下载 ngrok.exe")
        print(f"并放入: {freeze_dir}")
        sys.exit(1)

    print("  解压 ngrok...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extract("ngrok.exe", freeze_dir)

    zip_path.unlink()
    print(f"  ngrok.exe 已提取: {ngrok_exe}")
    return ngrok_exe


def step_create_zip(freeze_dir: Path) -> Path:
    """将便携版目录打包为 ZIP。"""
    print("\n[步骤 4/4] 创建便携版 ZIP...")

    zip_path = DIST_DIR / f"DeepSeekCursorProxy-v{APP_VERSION}-portable.zip"
    if zip_path.is_file():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in freeze_dir.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(freeze_dir.parent))

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  ZIP 已生成: {zip_path} ({size_mb:.1f} MB)")
    return zip_path


# ---------------------------------------------------------------------------
# 步骤 3: InnoSetup 打包
# ---------------------------------------------------------------------------


def step_create_installer(freeze_dir: Path) -> Path:
    """使用 InnoSetup 创建 Windows 安装程序。"""
    print("\n[步骤 3/3] InnoSetup 打包...")

    iscc = find_inno_setup()
    if iscc is None:
        print("\n[WARNING] 未找到 InnoSetup 编译器。")
        print("请从 https://jrsoftware.org/isinfo.php 安装 InnoSetup 6。")
        print(f"\n冻结产物已就绪: {freeze_dir}")
        print("你可以手动创建安装程序，或直接分发此文件夹。")
        return freeze_dir

    # 生成临时 .iss 文件
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
    """生成 InnoSetup 脚本。"""
    return f'''; InnoSetup 脚本 — 由 build_installer.py 自动生成
; DeepSeek Cursor Proxy Windows 安装程序

#define MyAppName "{APP_NAME}"
#define MyAppVersion "{APP_VERSION}"
#define MyAppPublisher "{APP_PUBLISHER}"
#define MyAppExeName "{APP_EXE_NAME}"

[Setup]
AppId={{{F1A2B3C4-D5E6-7890-ABCD-EF1234567890}}}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
DefaultDirName={{localappdata}}\\Programs\\{{#MyAppName}}
DefaultGroupName={{#MyAppName}}
AllowNoIcons=yes
OutputDir={DIST_DIR}
OutputBaseFilename=DeepSeekCursorProxy-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={{#MyAppName}}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"

[Files]
Source: "{freeze_dir.as_posix()}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"
Name: "{{group}}\\卸载 {{#MyAppName}}"; Filename: "{{uninstallexe}}"
Name: "{{commondesktop}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; Tasks: desktopicon

[Run]
Filename: "{{app}}\\{{#MyAppExeName}}"; Description: "启动 {{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// 安装后自动运行
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // 安装程序会自动运行 [Run] 部分
  end;
end;
'''


# ---------------------------------------------------------------------------
# 清理
# ---------------------------------------------------------------------------


def step_clean() -> None:
    """清理构建产物。"""
    print("\n[清理] 删除构建产物...")
    for path in [DIST_DIR, BUILD_DIR]:
        if path.exists():
            shutil.rmtree(path)
            print(f"  已删除: {path}")
    for spec in PROJECT_ROOT.glob("*.spec"):
        spec.unlink()
        print(f"  已删除: {spec}")


# ---------------------------------------------------------------------------
# 主流水线
# ---------------------------------------------------------------------------


def build_full() -> None:
    """完整构建流水线。"""
    print("=" * 60)
    print(f"  {APP_NAME} 构建流水线 v{APP_VERSION}")
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
    parser.add_argument(
        "--freeze-only",
        action="store_true",
        help="仅执行 PyInstaller 冻结",
    )
    parser.add_argument(
        "--installer-only",
        action="store_true",
        help="仅生成安装程序（需要先冻结）",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="清理所有构建产物",
    )
    args = parser.parse_args()

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
