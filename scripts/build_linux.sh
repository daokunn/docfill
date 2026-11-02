#!/usr/bin/env bash
# =============================================================================
# DocFill 信创 Linux 一键打包脚本
# 产物：dist/DocFill-linux-{架构}-{版本}-{日期}.tar.gz
#       解压即用，内含 install_desktop.sh 可装桌面图标
#
# 用法：
#   bash scripts/build_linux.sh            # 正式版（无控制台）
#   bash scripts/build_linux.sh --probe    # 自检版（带控制台，便于排查启动问题）
#
# 可用环境变量覆盖默认值：
#   PYTHON=python3.11            指定解释器
#   PIP_INDEX=https://...        指定 PyPI 源（默认华为云，信创内网友好）
#   SKIP_VENV=1                  跳过虚拟环境，用当前解释器
#   SKIP_TEST=1                  跳过 pytest（默认强制测试，失败中止打包）
#   KEEP_DIST=1                  保留上一次 dist/build，不清理
# =============================================================================
set -euo pipefail

APP_NAME="DocFill"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

PIP_INDEX="${PIP_INDEX:-https://mirrors.huaweicloud.com/repository/pypi/simple}"

# ---------- 架构 ----------
RAW_ARCH="$(uname -m)"
case "$RAW_ARCH" in
  x86_64|amd64) ARCH="x86_64" ;;
  aarch64|arm64) ARCH="aarch64" ;;
  *) ARCH="$RAW_ARCH"; echo "[警告] 未见过的架构 $RAW_ARCH，产物名按原样使用" ;;
esac

# ---------- 版本号 ----------
VERSION="$(grep -oE "ProductVersion', '[^']+'" version_info.txt 2>/dev/null | sed -E "s/.*'([^']+)'/\1/" | head -1 || true)"
if [ -z "$VERSION" ]; then
  VERSION="$(grep -oE "filevers=\([0-9, ]+\)" version_info.txt 2>/dev/null | grep -oE "[0-9]+" | head -3 | paste -sd. - || true)"
fi
[ -z "$VERSION" ] && VERSION="1.0.0"
DATE="$(date +%Y%m%d)"

PROBE_ARG="${1:-}"
CONSOLE_ENV=""
if [ "$PROBE_ARG" = "--probe" ]; then
  CONSOLE_ENV="APP_CONSOLE=1"
  TAG="-probe"
else
  TAG=""
fi

echo "============================================================"
echo " $APP_NAME 信创 Linux 打包"
echo " 架构: $ARCH   版本: $VERSION   日期: $DATE   自检: ${PROBE_ARG:-否}"
echo "============================================================"

# ---------- 1. Python 解释器 ----------
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "[错误] 未找到 $PYTHON，请先安装 Python 3.10+（信创机可用系统包管理器装 python3）"
  exit 1
fi
PY_VER="$("$PYTHON" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
echo "[1/6] Python: $PYTHON ($PY_VER)"
if [ "$(printf '%s\n' 3.10 "$PY_VER" | sort -V | head -1)" != "3.10" ]; then
  echo "[错误] 需要 Python >= 3.10，当前 $PY_VER"; exit 1
fi

# ---------- 2. 虚拟环境 ----------
VENV_DIR=".venv-linux"
if [ "${SKIP_VENV:-0}" = "1" ]; then
  echo "[2/6] 跳过虚拟环境（SKIP_VENV=1）"
else
  echo "[2/6] 创建虚拟环境 $VENV_DIR"
  "$PYTHON" -m venv "$VENV_DIR"
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  PYTHON=python
fi

# ---------- 3. 依赖 ----------
echo "[3/6] 安装依赖（源: $PIP_INDEX）"
"$PYTHON" -m pip install --upgrade pip setuptools wheel -q -i "$PIP_INDEX"
"$PYTHON" -m pip install -r requirements-dev.txt -q -i "$PIP_INDEX"

# ---------- 4. 测试 ----------
if [ "${SKIP_TEST:-0}" = "1" ]; then
  echo "[4/6] 跳过测试（SKIP_TEST=1）"
else
  echo "[4/6] 运行 pytest（失败中止打包；可 SKIP_TEST=1 跳过）"
  if ! "$PYTHON" -m pytest -q; then
    echo "[错误] 测试未通过，中止打包。请先修复测试再打包。"
    exit 1
  fi
fi

# ---------- 5. PyInstaller ----------
echo "[5/6] PyInstaller 打包（onedir 绿色目录）"
if [ "${KEEP_DIST:-0}" != "1" ]; then
  rm -rf build dist
fi
# shellcheck disable=SC2086
env $CONSOLE_ENV "$PYTHON" -m PyInstaller build.spec --noconfirm

if [ ! -d "dist/$APP_NAME" ]; then
  echo "[错误] 打包后未找到 dist/$APP_NAME，构建失败"; exit 1
fi

# 拷入桌面图标脚本
if [ -f "scripts/install_desktop.sh" ]; then
  cp scripts/install_desktop.sh "dist/$APP_NAME/"
  chmod +x "dist/$APP_NAME/install_desktop.sh"
fi

# ---------- 6. tar.gz 绿色包 ----------
echo "[6/6] 生成 tar.gz 绿色包"
TARBALL="dist/${APP_NAME}-linux-${ARCH}-${VERSION}-${DATE}${TAG}.tar.gz"
tar -czf "$TARBALL" -C dist "$APP_NAME"
SIZE="$(du -h "$TARBALL" | cut -f1)"

# ---------- 字体软检查 ----------
echo ""
echo "------------------------------------------------------------"
echo " 字体检查（中文字体缺失会导致界面方块字）"
if fc-list :lang=zh 2>/dev/null | grep -qi .; then
  echo " [OK] 检测到中文字体"
else
  echo " [警告] 未检测到中文字体，建议安装: sudo apt install fonts-noto-cjk  或  fonts-wqy-microhei"
fi

echo ""
echo "============================================================"
echo " 打包完成"
echo "============================================================"
echo " 绿色包 : $TARBALL  ($SIZE)"
echo " 目录   : dist/$APP_NAME/"
echo ""
echo " 部署到信创机："
echo "   1) 拷贝 $TARBALL 到目标机器"
echo "   2) tar -xzf $(basename "$TARBALL")"
echo "   3) cd $APP_NAME && ./install_desktop.sh    # 装桌面图标（可选）"
echo "   4) ./$APP_NAME                              # 直接启动"
echo ""
echo " 卸载桌面图标：./install_desktop.sh uninstall"
echo " 排查启动问题：用 --probe 重新打包，或在目标机终端运行 ./$APP_NAME 看报错"