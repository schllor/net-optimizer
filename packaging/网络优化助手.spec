# -*- mode: python ; coding: utf-8 -*-

import os

_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
_SRC = os.path.join(_ROOT, "src")
_ICON = os.path.join(_SRC, "assets", "icons", "app.ico")


a = Analysis(
    [os.path.join(_SRC, 'main.py')],
    pathex=[_SRC],
    binaries=[],
    datas=[(os.path.join(_SRC, 'assets'), 'assets')],
    hiddenimports=[
        'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
        'PySide6.QtSvg',       # icons.py 的 QSvgRenderer
        'PySide6.QtNetwork',  # 下载器/测速/公网 IP 查询；之前误放入 excludes
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(SPECPATH, 'pyi_rth_network_assistant.py')],
    # 排除本项目用不到的重型 Qt 模块（PDF/QML/Quick/3D/Multimedia/WebEngine 等），
    # 否则 PyInstaller 会把整批 Qt6 dll 打进一个 exe，导致体积从 ~50MB 膨胀到 500MB。
    excludes=[
        'PySide6.Qt3DCore', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput', 'PySide6.Qt3DLogic', 'PySide6.Qt3DRender',
        'PySide6.QtBluetooth', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtLocation',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
        'PySide6.QtNetworkAuth', 'PySide6.QtNfc', 'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
        'PySide6.QtPositioning', 'PySide6.QtQml', 'PySide6.QtQuick',
        'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets', 'PySide6.QtRemoteObjects',
        'PySide6.QtScxml', 'PySide6.QtSensors', 'PySide6.QtSerialBus',
        'PySide6.QtSerialPort', 'PySide6.QtSql', 'PySide6.QtStateMachine',
        'PySide6.QtTest', 'PySide6.QtWebChannel', 'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets', 'PySide6.QtWebSockets',
        'PySide6.QtVirtualKeyboard', 'PySide6.QtXml', 'PySide6.QtXmlPatterns',
        # 标准库中未被引用的重型模块
        'tkinter', 'unittest', 'pydoc', 'doctest', 'lib2to3', 'test',
        'distutils', 'setuptools', 'pip', 'wheel', 'pdb', 'cProfile',
        'pstats', 'turtle', 'turtledemo', 'ensurepip', 'venv', 'xmlrpc',
        'multiprocessing',
    ],
    noarchive=False,
    optimize=0,
)
# PyInstaller can pick up ICU DLLs from unrelated packages in the build
# environment. Qt on Windows resolves its compatible ICU from the OS; the
# bundled ICU 78 files expose suffixed symbols and break Qt6Core loading.
a.binaries = [
    entry for entry in a.binaries
    if entry[0].lower() not in {"icuuc.dll", "icudt78.dll"}
]

# ---------------------------------------------------------------- 体积裁剪
# PySide6 的 hook 会把整个 PySide6 目录下的 DLL/插件/翻译一并收集，
# 仅靠上面的模块 excludes 拦不住。本程序是纯 QWidgets 应用（窗口绘制 +
# 系统命令），下面这些组件从未被加载，按文件名精确剔除：
#   - opengl32sw.dll（约 20MB）：Qt 的软件 OpenGL 回退，只在 OpenGL 渲染时加载
#   - Qt6Quick/Qml/Pdf/VirtualKeyboard/Network/Svg：被插件间接带入，代码从未 import
#   - imageformats / iconengines：程序不加载任何图片或 SVG 资源
#   - translations：未使用 QTranslator
#   - qdirect2d：Windows 下统一使用 qwindows 平台插件
_UNUSED_QT_FILES = {
    'pyside6\\opengl32sw.dll',
    'pyside6\\qt6quick.dll', 'pyside6\\qt6quickwidgets.dll',
    'pyside6\\qt6quickcontrols2.dll', 'pyside6\\qt6quicktemplates2.dll',
    'pyside6\\qt6qml.dll', 'pyside6\\qt6qmlmodels.dll',
    'pyside6\\qt6qmlworkerscript.dll', 'pyside6\\qt6qmlcore.dll',
    'pyside6\\qt6pdf.dll', 'pyside6\\qt6pdfwidgets.dll',
    'pyside6\\qt6virtualkeyboard.dll',
    # QtNetwork、QtSvg 现在是必需的（下载器/测速/icons.py），下方不再列出
    'pyside6\\qt6opengl.dll', 'pyside6\\qt6openglwidgets.dll',
    'pyside6\\plugins\\platforms\\qdirect2d.dll',
}
_UNUSED_QT_DIRS = (
    'pyside6\\plugins\\iconengines\\',
    'pyside6\\plugins\\platforminputcontexts\\',
    'pyside6\\plugins\\generic\\',
    'pyside6\\translations\\',
)
# QtNetwork 可能需要 TLS/NetworkInformation 插件，不再排除
# QtSvg 需要 imageformats/qsvg 插件，不再排除


def _keep_qt_entry(entry):
    key = entry[0].replace('/', '\\').lower()
    return key not in _UNUSED_QT_FILES and not key.startswith(_UNUSED_QT_DIRS)


a.binaries = [e for e in a.binaries if _keep_qt_entry(e)]
a.datas = [e for e in a.datas if _keep_qt_entry(e)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='网络优化助手',
    icon=_ICON if os.path.exists(_ICON) else None,
    manifest=os.path.join(SPECPATH, 'app.manifest'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
