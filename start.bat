@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ========================================
echo   小说角色对话
echo ========================================
echo.

rem ---------- 检查 Python ----------
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没找到 python。
    echo        请安装 Python 3.10 及以上，安装时勾选 "Add Python to PATH"。
    echo.
    pause
    exit /b 1
)

rem ---------- 检查 .env ----------
if not exist ".env" (
    if not exist ".env.example" (
        echo [错误] 找不到 .env 也找不到 .env.example。
        pause
        exit /b 1
    )
    copy ".env.example" ".env" >nul
    echo [提示] 已根据 .env.example 生成 .env
    echo        接着会打开记事本，请在 CHAT_API_KEY= 后面填入你的 key。
    echo        填完保存，重新双击本脚本即可。
    echo.
    start notepad .env
    pause
    exit /b 1
)

rem ---------- 检查依赖 ----------
python -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
    echo [提示] 依赖没装全，马上安装，第一次会慢一点...
    echo.
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败。检查一下网络，或者换个 pip 源：
        echo        python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        pause
        exit /b 1
    )
    echo.
)

echo 服务启动中，3 秒后自动打开浏览器...
echo 电脑访问：http://127.0.0.1:8000
echo 手机访问：同一 Wi-Fi 下用下面终端里显示的局域网地址
echo 停止服务：按 Ctrl + C
echo.

rem ---------- 3 秒后再开浏览器，避免页面先于服务加载 ----------
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8000'"

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

echo.
echo 服务已停止。
pause
