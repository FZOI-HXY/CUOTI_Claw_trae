@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ===========================================
echo   Claw 错题管理系统 - 一键构建脚本
echo   目标平台: Windows 10 22H2 x64
echo ===========================================
echo.

:: 激活虚拟环境 (如果存在)
if exist "venv\Scripts\activate.bat" (
    echo [*] 激活虚拟环境...
    call venv\Scripts\activate.bat
)

:: 安装依赖
echo [*] 检查依赖...
python -m pip install -r requirements.txt --quiet
echo [+] 依赖检查完成
echo.

:: 执行打包
echo [*] 开始打包...
python build.py %*
echo.

:: 暂停查看结果
if %ERRORLEVEL% NEQ 0 (
    echo [!] 构建失败，请检查上方输出
    pause
    exit /b 1
)

echo [+] 构建成功!
echo.
echo 输出文件: %cd%\dist\Claw.exe
echo.
echo 可选操作:
echo   dist\Claw.exe          直接运行
echo   build.py --console     带控制台构建（调试模式）
echo   build.py --clean       清理后重新构建

timeout /t 5 >nul
exit /b 0
