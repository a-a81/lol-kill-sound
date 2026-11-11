@echo off
setlocal
cd /d "%~dp0"

set "TARGET=%~dp0watch-lol-and-start.bat"
set "WORKDIR=%~dp0"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LNK=%STARTUP%\LoL-Kill-Sound-Autostart.lnk"

if not exist "%TARGET%" (
  echo Missing watch-lol-and-start.bat
  pause
  exit /b 1
)

if not exist "%STARTUP%" (
  mkdir "%STARTUP%" 2>nul
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%LNK%'); $s.TargetPath = '%TARGET%'; $s.WorkingDirectory = '%WORKDIR%'; $s.WindowStyle = 1; $s.Description = 'Watch for League and start kill-sound'; $s.Save(); Write-Host 'Created: %LNK%' }"

if errorlevel 1 (
  echo Failed to create Startup shortcut.
  pause
  exit /b 1
)

echo.
echo Startup にショートカットを作成しました。
echo ログイン時に watch-lol-and-start.bat が動き、LoL 起動を待ちます。
echo 無効にするときは Startup フォルダからショートカットを削除してください:
echo   %STARTUP%
echo.
pause
exit /b 0
