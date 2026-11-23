# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置（Windows / 银河麒麟 Linux 双平台，同一份 spec）

构建命令（都在项目根目录执行）：

  Windows（onefile 单文件 exe）：
      python -m PyInstaller build.spec --noconfirm
      自检版（带控制台，用于打包后验证）：
        $env:APP_CONSOLE="1"; python -m PyInstaller build.spec --noconfirm --distpath build\\probe_dist

  Windows 文件夹版（onedir，启动更快，适合内网批量部署）：
      $env:APP_ONEDIR="1"; python -m PyInstaller build.spec --noconfirm
      产物在 dist/DocFill/ 目录，整个目录拷走即可用（不要只拷 exe）。

  银河麒麟 / Linux arm64（onedir 绿色目录）：
      python3 -m PyInstaller build.spec --noconfirm
      自检版：
        APP_CONSOLE=1 python3 -m PyInstaller build.spec --noconfirm --distpath build/probe_dist
      产物在 dist/DocFill/ 目录，双击其中的 DocFill 即可运行；
      再执行同目录下的 install_desktop.sh 装桌面图标，观感等同 exe。
  一键打包：bash scripts/build_linux.sh        # 正式版
            bash scripts/build_linux.sh --probe # 带控制台自检版
  产物为 dist/DocFill-linux-{架构}-{版本}-{日期}.tar.gz，解压即用。

为什么两个平台用不同的打包形态：
  - Windows 用 onefile：单个 exe 好分发，这是你现在的用法，保持不变
  - Linux 用 onedir：onefile 每次启动都要把依赖解压到 /tmp，
    在信创机器上容易受权限策略和安全软件拦截，且启动明显变慢；
    onedir 是目录形态，配 .desktop 图标后使用体验一致

体积策略：排除本程序用不到的 Qt 大型模块（Qml/Quick/WebEngine/Multimedia 等）。
稳定策略：
  - Windows 保留 ANGLE(libEGL/libGLESv2) 与 opengl32sw 软件渲染库，
    兼容远程桌面/虚拟机/老显卡
  - Linux 刻意保留 Qt6DBus 与 Svg/iconengines：xcb 平台插件和桌面主题图标
    依赖它们，裁掉会出现「could not load the Qt platform plugin "xcb"」
    或图标全变空白。信创环境稳定性优先于体积。
"""

import os
import sys

APP_NAME = "DocFill"
IS_WINDOWS = sys.platform.startswith("win")

SPEC_DIR = globals().get("SPECPATH", os.path.abspath("."))
ASSETS_DIR = os.path.join(SPEC_DIR, "assets")
ICON_PATH = os.path.join(ASSETS_DIR, "docfill.ico")
PNG_ICON_PATH = os.path.join(ASSETS_DIR, "docfill.png")
SPLASH_PATH = os.path.join(ASSETS_DIR, "splash.png")
VERSION_PATH = os.path.join(SPEC_DIR, "version_info.txt")

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
    # 项目只处理纯文本变量模板，不读写图片；python-docx 的图片分支会用到 PIL，
    # 但本程序从不走该分支。排除后 PYZ 少 75 个模块、二进制少 4MB+。
    "PIL",
    # 标准库里用不到的大块（异步/多进程/邮件），本项目均为同步单进程流程
    "asyncio", "multiprocessing", "email",
]

if not IS_WINDOWS:
    # Linux 上 Svg 必须保留：桌面主题图标靠它渲染，
    # 排除后 QListWidget/QPushButton 的图标会变成空白方块。
    # Network 一并保留：Qt 内部有引用，裁掉可能在加载插件时报缺库。
    for module in ("PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtNetwork"):
        if module in EXCLUDE_MODULES:
            EXCLUDE_MODULES.remove(module)

# 内置资源：只读配置 + 初始别名数据 + 图标
# （settings.json 不打包，首启自动生成默认配置，避免带入开发机路径）
datas = [
    ("config/rules.json", "config"),
    ("config/defaults.json", "config"),
    ("config/aliases.json", "config"),
    ("data/region_dict.json", "data"),
    ("assets/docfill.ico", "assets"),
    ("assets/docfill.png", "assets"),   # Linux 桌面图标用 png，.ico 在 Linux 支持参差
    ("assets/splash.png", "assets"),
]

# 二进制文件名中包含以下关键字的剔除（对应 Qt 动态库 / 绑定扩展）
EXCLUDE_BIN_KEYWORDS = [
    "Qt6Network", "Qt6Qml", "Qt6Quick", "Qt6WebEngine", "Qt6Multimedia",
    "Qt6Charts", "Qt6DataVisualization", "Qt6Sql", "Qt6Bluetooth",
    "Qt6Positioning", "Qt6Location", "Qt6Sensors", "Qt6SerialPort", "Qt6SerialBus",
    "Qt6Designer", "Qt6Help", "Qt6Pdf", "Qt6PrintSupport", "Qt6Svg",
    "Qt6Scxml", "Qt6StateMachine", "Qt6VirtualKeyboard", "Qt6Nfc",
    "Qt6RemoteObjects", "Qt6Concurrent", "Qt6TextToSpeech", "Qt6OpenGL",
    "Qt6ShaderTools", "Qt6WebChannel", "Qt6WebSockets", "Qt63D", "Qt6Xml", "Qt6DBus",
]

if not IS_WINDOWS:
    # Qt6DBus：Linux 上 xcb 平台插件与原生对话框依赖它，裁掉可能起不来
    # Qt6Network / Qt6Svg：同上，保留以免加载插件时报缺库
    for keyword in ("Qt6DBus", "Qt6Network", "Qt6Svg"):
        if keyword in EXCLUDE_BIN_KEYWORDS:
            EXCLUDE_BIN_KEYWORDS.remove(keyword)

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
    # ---------- 启动提速：剔除用不到的大文件 ----------
    # onefile 每次启动都要把下面这些解压到临时目录，体积直接决定首屏速度。
    "PySide6/opengl32sw.dll",                    # 软件 OpenGL 后备渲染器 7.3MB，纯表格界面用不到
    "PIL/_avif.cp311-win_amd64.pyd",             # AVIF 解码器 4.1MB，本项目只处理 PNG/ICO
    "PIL/_webp.cp311-win_amd64.pyd",             # WebP 解码器 0.2MB，同上
    "PySide6/plugins/imageformats/qtiff.dll",    # TIFF 0.3MB
    "PySide6/plugins/imageformats/qwebp.dll",    # WebP 0.3MB
]

if not IS_WINDOWS:
    # Linux 下动态库是 .so，上面那些 .dll 路径不会命中；
    # 同时必须保留 iconengines(qsvgicon) 和 imageformats/qsvg，否则图标全空白。
    EXCLUDE_BIN_PATHS = [
        "PySide6/plugins/tls",
        "PySide6/plugins/networkinformation",
        "PySide6/plugins/position",
        "PySide6/plugins/multimedia",
        "PySide6/translations",
        "PySide6/examples",
        # qpdf 依赖已被排除的 Qt6Pdf，留着会报缺库
        "PySide6/plugins/imageformats/libqpdf.so",
        "PySide6/plugins/platforms/libqminimal.so",
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
# APP_ONEDIR=1 时打文件夹版（Windows）：免去每次启动解压 33MB，启动更快。
# 默认仍打单文件 exe——双击即用，适合小白用户分发。
onedir_mode = os.environ.get("APP_ONEDIR") == "1"

# icon / version 只在 Windows 有意义：
# PyInstaller 在非 Windows 平台会自动忽略并给出警告，不会报错，
# 这里显式置 None 只是为了构建日志干净。
icon_arg = ICON_PATH if (IS_WINDOWS and os.path.exists(ICON_PATH)) else None
version_arg = VERSION_PATH if (IS_WINDOWS and os.path.exists(VERSION_PATH)) else None

pyz = PYZ(a.pure)

if IS_WINDOWS and onedir_mode:
    # ---------- Windows：onedir 文件夹版（启动快，无需 Splash）----------
    # 文件夹版不经过 onefile 解压，主窗口直接加载，因此不加启动图：
    # 加了反而要在主窗口出现后再关掉它，多此一举。
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,     # onedir：可执行文件与依赖分离
        name=APP_NAME,
        icon=icon_arg,
        version=version_arg,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=console_mode,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
elif IS_WINDOWS:
    # ---------- Windows：onefile 单文件 exe ----------
    extra_args = []
    if not console_mode:
        # 启动图：onefile 解压期间先显示品牌画面，减少"怎么还没打开"的错觉。
        # Splash 依赖 tkinter：构建机若没装 tkinter（如精简版 Python），实例化会
        # SystemExit 中断构建。此时降级为"无启动图"继续打包——主程序里对
        # pyi_splash 的 import 已有 try/except，运行不受影响。
        _splash_ok = False
        try:
            import tkinter as _tk  # noqa: F401
            _splash_ok = True
        except Exception:
            print("[build.spec] tkinter 不可用，跳过启动图（不影响 exe 运行）")
        if _splash_ok:
            from PyInstaller.building.splash import Splash

            splash = Splash(
                SPLASH_PATH,
                binaries=a.binaries,
                datas=a.datas,
                text_pos=(30, 322),
                text_size=10,
                text_color="#E5E7EB",
                always_on_top=True,
            )
            extra_args = [splash, splash.binaries]

    exe = EXE(
        pyz,
        a.scripts,
        *extra_args,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        icon=icon_arg,
        version=version_arg,
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
else:
    # ---------- Linux / 银河麒麟：onedir 绿色目录 ----------
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,     # onedir 模式：可执行文件与依赖分离
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=console_mode,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
