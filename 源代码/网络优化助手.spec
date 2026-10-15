# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('fonts', 'fonts')],
    hiddenimports=['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyi_rth_network_assistant.py'],
    # 排除本项目用不到的重型 Qt 模块（PDF/QML/Quick/3D/Multimedia/WebEngine 等），
    # 否则 PyInstaller 会把整批 Qt6 dll 打进一个 exe，导致体积从 ~50MB 膨胀到 500MB。
    excludes=[
        'PySide6.Qt3DCore', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput', 'PySide6.Qt3DLogic', 'PySide6.Qt3DRender',
        'PySide6.QtBluetooth', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtLocation',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtNetwork',
        'PySide6.QtNetworkAuth', 'PySide6.QtNfc', 'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
        'PySide6.QtPositioning', 'PySide6.QtQml', 'PySide6.QtQuick',
        'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets', 'PySide6.QtRemoteObjects',
        'PySide6.QtScxml', 'PySide6.QtSensors', 'PySide6.QtSerialBus',
        'PySide6.QtSerialPort', 'PySide6.QtSql', 'PySide6.QtStateMachine',
        'PySide6.QtTest', 'PySide6.QtWebChannel', 'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets', 'PySide6.QtWebSockets',
        'PySide6.QtVirtualKeyboard', 'PySide6.QtXml', 'PySide6.QtXmlPatterns',
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
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='网络优化助手',
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
