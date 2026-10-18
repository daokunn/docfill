# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置（onefile 单文件）

构建命令（在项目根目录执行）：
  正式版（无控制台 GUI）：python -m PyInstaller build.spec --noconfirm
  自检版（带控制台，用于打包后验证）：
      $env:APP_CONSOLE="1"; python -m PyInstaller build.spec --noconfirm --distpath build\\probe_dist

体积策略：排除本程序用不到的 Qt 大型模块（Qml/Quick/WebEngine/Multimedia 等）；
稳定策略：保留 ANGLE(libEGL/libGLESv2) 与 opengl32sw 软件渲染库，兼容远程桌面/虚拟机/老显卡。
"""

import os

APP_NAME = "内网离线模板批量填充工具"

# 仅使用 PySide6 的 QtCore / QtGui / QtWidgets，其余子模块全部排除
EXCLUDE_MODULES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2", "PySide6.QtQuickTemplates2",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DAnimation",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtNetwork",
    "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtPrintSupport", "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtUiTools",
    "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtVirtualKeyboard",
    "PySide6.QtNfc", "PySide6.QtRemoteObjects", "PySide6.QtConcurrent",
    "PySide6.QtTextToSpeech", "PySide6.QtAxContainer",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtShaderTools", "PySide6.QtXml",
    # 未使用的标准库/第三方库
    "tkinter", "_tkinter", "unittest", "pydoc", "doctest", "lib2to3",
    "numpy", "pandas",
]

# 内置资源：只读配置 + 初始别名数据（settings.json 不打包，首启自动生成默认配置，避免带入开发机路径）
datas = [
    ("config/rules.json", "config"),
    ("config/defaults.json", "config"),
    ("config/aliases.json", "config"),
    ("data/region_dict.json", "data"),
]

# 二进制文件名中包含以下关键字的剔除（对应 Qt dll / 绑定 pyd）
EXCLUDE_BIN_KEYWORDS = [
    "Qt6Network", "Qt6Qml", "Qt6Quick", "Qt6WebEngine", "Qt6Multimedia",
    "Qt6Charts", "Qt6DataVisualization", "Qt6Sql", "Qt6Bluetooth",
    "Qt6Positioning", "Qt6Location", "Qt6Sensors", "Qt6SerialPort", "Qt6SerialBus",
    "Qt6Designer", "Qt6Help", "Qt6Pdf", "Qt6PrintSupport", "Qt6Svg",
    "Qt6Scxml", "Qt6StateMachine", "Qt6VirtualKeyboard", "Qt6Nfc",
    "Qt6RemoteObjects", "Qt6Concurrent", "Qt6TextToSpeech", "Qt6OpenGL",
    "Qt6ShaderTools", "Qt6WebChannel", "Qt6WebSockets", "Qt63D", "Qt6Xml", "Qt6DBus",
]

# 按目标目录/文件精确剔除的 Qt 插件与资源（POSIX 风格路径比较）
EXCLUDE_BIN_PATHS = [
    "PySide6/plugins/tls",                       # 依赖 Qt6Network
    "PySide6/plugins/networkinformation",
    "PySide6/plugins/position",
    "PySide6/plugins/multimedia",
    "PySide6/plugins/iconengines",               # 仅 qsvgicon
    "PySide6/plugins/imageformats/qsvg.dll",
    "PySide6/plugins/imageformats/qpdf.dll",
    "PySide6/plugins/platforms/qminimal.dll",
    "PySide6/plugins/platforms/qoffscreen.dll",
    "PySide6/translations",                      # Qt 自带多语言包，本程序界面为自研中文
    "PySide6/examples",
]


def _keep_binary(entry):
    """判断 Analysis.binaries 中的条目是否保留"""
    dest = entry[0].replace("\\", "/")
    low = dest.lower()
    for kw in EXCLUDE_BIN_KEYWORDS:
        if kw.lower() in low:
            return False
    for prefix in EXCLUDE_BIN_PATHS:
        p = prefix.lower()
        if low == p or low.startswith(p + "/"):
            return False
    return True


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDE_MODULES,
    noarchive=False,
)

a.binaries = [b for b in a.binaries if _keep_binary(b)]

# 环境变量 APP_CONSOLE=1 时构建带控制台的自检版，默认为无控制台 GUI 正式版
console_mode = os.environ.get("APP_CONSOLE") == "1"

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # 不启用 UPX，避免内网杀软误报
    runtime_tmpdir=None,
    console=console_mode,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
