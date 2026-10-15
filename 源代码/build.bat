@echo off
chcp 65001 >nul
setlocal
pushd "%~dp0"
echo ========================================
echo    网络优化助手 - 打包脚本 (PySide6版)
echo ========================================
echo.

echo [1/3] 检查Python环境...
python --version
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python 3.7+
    pause
    popd
    exit /b 1
)
echo Python环境正常
echo.

echo [2/3] 安装依赖...
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo 依赖安装失败！
    pause
    popd
    exit /b 1
)
echo.

echo [3/3] 开始打包...
echo.

python -m PyInstaller --noconfirm --clean "网络优化助手.spec"

if errorlevel 1 (
    echo.
    echo 打包失败！
    pause
    popd
    exit /b 1
)

echo.
echo ========================================
echo    打包成功！
echo ========================================
echo.
echo 输出文件位置: dist\网络优化助手.exe
echo.
pause
popd
endlocal
