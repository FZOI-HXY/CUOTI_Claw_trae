@echo off
chcp 65001 >nul
title Claw 错题管理系统 - 独立桌面应用
echo ========================================
echo Claw 错题管理系统 - 独立桌面应用
echo ========================================
echo.
echo 前提: 请确保后端服务已启动
echo 启动命令 (在 backend/ 目录下):
echo   python main.py
echo 默认地址: http://127.0.0.1:8500
echo.
echo 正在启动桌面应用...
echo.
cd /d "%~dp0"
python main.py
pause
