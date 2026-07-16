@echo off
setlocal
cd /d "%~dp0"

for /f "usebackq delims=" %%V in ("VERSION.txt") do set APP_VERSION=%%V
if "%APP_VERSION%"=="" set APP_VERSION=0.0.0

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist setup_output rmdir /s /q setup_output

python -m PyInstaller --noconfirm --clean --windowed ^
  --name GiamSatDichBenh ^
  --collect-all PyQt6 ^
  --hidden-import PyQt6.QtCharts ^
  app.py
if errorlevel 1 goto :error

rem KHONG sao chep data, backups, Excel hay CSDL vao ban phat hanh.
copy /Y VERSION.txt "dist\GiamSatDichBenh\VERSION.txt" >nul
copy /Y README.md "dist\GiamSatDichBenh\README.md" >nul

where ISCC.exe >nul 2>nul
if not errorlevel 1 (
  ISCC.exe /DMyAppVersion=%APP_VERSION% setup.iss
) else if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" (
  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" /DMyAppVersion=%APP_VERSION% setup.iss
) else if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" /DMyAppVersion=%APP_VERSION% setup.iss
) else (
  echo Khong tim thay Inno Setup 6. Bo qua tao Setup.exe.
)

echo Hoan tat.
echo Portable: dist\GiamSatDichBenh\GiamSatDichBenh.exe
if exist "setup_output\GiamSatDichBenh-Setup-v%APP_VERSION%.exe" echo Setup: setup_output\GiamSatDichBenh-Setup-v%APP_VERSION%.exe
exit /b 0

:error
echo Build that bai.
exit /b 1
