@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0lol_autostart.py" %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>&1
if not errorlevel 1 (
  python "%~dp0lol_autostart.py" %*
  exit /b %ERRORLEVEL%
)

for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
  if exist "%%~D\python.exe" (
    "%%~D\python.exe" "%~dp0lol_autostart.py" %*
    exit /b %ERRORLEVEL%
  )
)

echo Python が見つかりません。
echo 公式サイト python.org から Python 3.10+ を入れてください。
echo インストール時に "Add python.exe to PATH" にチェックを入れてください。
echo 入れた直後は新しいコマンドプロンプトを開いてから再実行してください。
pause
exit /b 1
