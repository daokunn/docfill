#!/usr/bin/env bash
# =============================================================================
# DocFill 桌面图标安装/卸载脚本（随绿色包一起分发）
# 装到当前用户目录，不需要 sudo，适配统信 UOS / 银河麒麟 / 普通发行版
#
# 用法：
#   ./install_desktop.sh            安装桌面图标
#   ./install_desktop.sh uninstall  卸载桌面图标
# =============================================================================
set -euo pipefail

APP_NAME="DocFill"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
EXEC="$APP_DIR/$APP_NAME"
ICON="$APP_DIR/assets/docfill.png"
APPS_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$APPS_DIR/${APP_NAME}.desktop"

# 兼容找不到 docfill.png 时回退到标准图标，避免 .desktop 引用空路径
if [ ! -f "$ICON" ]; then
  ICON="accessories-text-editor"
fi

case "${1:-install}" in
  install)
    if [ ! -x "$EXEC" ]; then
      echo "[错误] 未找到可执行文件 $EXEC"
      echo "       请确保本脚本与 $APP_NAME 在同一目录"
      exit 1
    fi
    mkdir -p "$APPS_DIR"
    cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Name[zh_CN]=$APP_NAME
GenericName=文档智能解析后填充
GenericName[zh_CN]=文档智能解析后填充
Comment=把客户资料文本批量填充到 Word/Excel 模板
Comment[zh_CN]=把客户资料文本批量填充到 Word/Excel 模板
Exec=$EXEC
Path=$APP_DIR
Icon=$ICON
Categories=Office;Utility;Qt;
Terminal=false
StartupNotify=true
StartupWMClass=$APP_NAME
EOF
    chmod +x "$DESKTOP_FILE"
    # 刷新桌面数据库（命令不存在时静默跳过）
    if command -v update-desktop-database >/dev/null 2>&1; then
      update-desktop-database "$APPS_DIR" 2>/dev/null || true
    fi
    echo "已安装桌面图标：$DESKTOP_FILE"
    echo "如应用菜单未立即显示，注销重登一次即可。"
    ;;
  uninstall)
    rm -f "$DESKTOP_FILE"
    if command -v update-desktop-database >/dev/null 2>&1; then
      update-desktop-database "$APPS_DIR" 2>/dev/null || true
    fi
    echo "已卸载桌面图标。"
    ;;
  *)
    echo "用法: $0 [install|uninstall]"
    exit 1
    ;;
esac