@echo off
setlocal EnableExtensions

rem ---------------------------------------------------------------------------
rem  AI Office Workspace - builds the Windows installer (setup.exe)
rem
rem  Usage:
rem    packaging\build.bat [--skip-npm-install] [--skip-installer] [--inno]
rem
rem  Requires: Node.js 18/20+, Python 3.10+
rem            (--inno only: Inno Setup 6.3+)
rem  Output:   packaging\output\AI-Office-Workspace-Setup.exe  <- the installer
rem            site\AI-Office-Workspace-Setup.zip             <- setup.exe in a zip (handout)
rem            packaging\output\AIOfficeWorkspace\             <- the app itself
rem ---------------------------------------------------------------------------

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
pushd "%ROOT%" || goto :no_root

set "OUTPUT=%ROOT%\packaging\output"
set "WORK=%ROOT%\packaging\work"
set "SETUP=%OUTPUT%\AI-Office-Workspace-Setup.exe"
set "SITEZIP=%ROOT%\site\AI-Office-Workspace-Setup.zip"
set "APPEXE=%OUTPUT%\AIOfficeWorkspace\AIOfficeWorkspace.exe"

set "SKIP_NPM=0"
set "SKIP_INSTALLER=0"
set "USE_INNO=0"

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--skip-npm-install" set "SKIP_NPM=1"
if /i "%~1"=="--skip-installer" set "SKIP_INSTALLER=1"
if /i "%~1"=="--inno" set "USE_INNO=1"
shift
goto :parse_args
:args_done

rem -- python -----------------------------------------------------------------
if defined PYTHON goto :have_python
where py >nul 2>nul
if not errorlevel 1 set "PYTHON=py"
if defined PYTHON goto :have_python
where python >nul 2>nul
if not errorlevel 1 set "PYTHON=python"
:have_python
if not defined PYTHON goto :no_python

rem -- 1/7 frontend -----------------------------------------------------------
set "STEP=frontend (npm)"
echo.
echo [1/7] Building the frontend...
where npm >nul 2>nul
if errorlevel 1 goto :no_npm
if "%SKIP_NPM%"=="1" (
    echo       npm install skipped.
) else (
    pushd "frontend"
    call npm install
    if errorlevel 1 goto :fail
    popd
)
pushd "frontend"
call npm run build
if errorlevel 1 goto :fail
popd
if not exist "dist\index.html" (
    echo [ERROR] dist\index.html was not created.
    goto :fail
)

rem -- 2/7 qwebchannel.js -----------------------------------------------------
set "STEP=qwebchannel.js"
echo [2/7] Preparing qwebchannel.js...
%PYTHON% packaging\prepare_qwebchannel.py
if errorlevel 1 goto :fail

rem -- 3/7 python dependencies ------------------------------------------------
set "STEP=Python dependencies"
echo [3/7] Installing the Python dependencies...
%PYTHON% -m pip install -r requirements.txt
if errorlevel 1 goto :fail
%PYTHON% -m pip install -r packaging\requirements-build.txt
if errorlevel 1 goto :fail

rem -- 4/7 icon ---------------------------------------------------------------
set "STEP=icon"
echo [4/7] Generating the application icon...
%PYTHON% packaging\make_icon.py
if errorlevel 1 goto :fail

rem -- 5/7 PyInstaller --------------------------------------------------------
set "STEP=PyInstaller"
echo [5/7] Freezing the application (PyInstaller)...
%PYTHON% -m PyInstaller --noconfirm --clean --distpath "%OUTPUT%" --workpath "%WORK%" packaging\app.spec
if errorlevel 1 goto :fail
if not exist "%APPEXE%" (
    echo [ERROR] PyInstaller output was not found: "%APPEXE%"
    goto :fail
)

if "%SKIP_INSTALLER%"=="1" goto :skip_installer

rem A stale setup.exe must not survive a failed build.
if exist "%SETUP%" del /q "%SETUP%"

if "%USE_INNO%"=="1" goto :build_inno

rem -- 6/7 setup.exe (setup wizard bundled by PyInstaller) --------------------
rem The installer is a normal PyInstaller build of packaging\setup.py: it shows
rem the wizard (install folder, shortcuts), then copies the app that is embedded
rem in it as payload.zip. No external installer tool is needed.
set "STEP=setup.exe"
echo [6/7] Building setup.exe (installer, PyInstaller)...
%PYTHON% -m PyInstaller --noconfirm --clean --distpath "%OUTPUT%" --workpath "%WORK%" packaging\setup.spec
if errorlevel 1 goto :fail
if not exist "%SETUP%" (
    echo [ERROR] setup.exe was not found: "%SETUP%"
    goto :fail
)
goto :make_site

:build_inno
rem Optional alternative: the Inno Setup installer (packaging\installer.iss).
set "STEP=Inno Setup"
echo [6/7] Creating setup.exe (Inno Setup)...
call :find_iscc
if not defined ISCC goto :no_iscc
"%ISCC%" packaging\installer.iss
if errorlevel 1 goto :fail
if not exist "%SETUP%" (
    echo [ERROR] setup.exe was not found: "%SETUP%"
    goto :fail
)
goto :make_site

rem -- 7/7 handout zip --------------------------------------------------------
rem Puts setup.exe into a zip for handing the app over offline.
rem site\index.html does not link to it (the page offers the GitHub Release).
:make_site
set "STEP=handout zip"
echo [7/7] Packaging setup.exe into site\AI-Office-Workspace-Setup.zip...
%PYTHON% packaging\make_site_zip.py
if errorlevel 1 goto :fail

goto :built

:built
echo.
echo Done.
echo   setup.exe   : "%SETUP%"
echo                 ^<-- double-click this one to install
echo   site zip    : "%SITEZIP%"
echo                 ^<-- optional handout copy (the page links to GitHub Releases)
echo   application : "%APPEXE%"
echo                 ^<-- the app itself, not the installer
goto :finish

:skip_installer
echo.
echo Done (without installer).
echo   application : "%APPEXE%"
echo   --skip-installer was given, so setup.exe was not created.
goto :finish

:finish
popd
call :pause_if_clicked
exit /b 0

rem -- error paths ------------------------------------------------------------
:no_root
echo [ERROR] The project folder could not be opened: "%ROOT%"
exit /b 1

:no_python
set "STEP=Python detection"
echo [ERROR] Python was not found. Install Python 3.10+ and run again.
goto :fail

:no_npm
echo [ERROR] npm was not found. Install Node.js 18/20+ and run again.
goto :fail

:no_iscc
set "STEP=Inno Setup"
echo [ERROR] Inno Setup 6 was not found, so setup.exe was not created.
echo         Checked PATH, Program Files\Inno Setup 6,
echo         LocalAppData\Programs\Inno Setup 6 and the uninstall registry entries.
echo         Install it from https://jrsoftware.org/isdl.php and run again,
echo         or drop --inno to build setup.exe with the built-in wizard.
goto :fail

:fail
echo.
echo [ERROR] %STEP% failed. See the messages above.
popd
call :pause_if_clicked
exit /b 1

:pause_if_clicked
rem Keep the window open when the script was started by double-clicking it.
echo "%CMDCMDLINE%" | find /i "/c" >nul
if not errorlevel 1 pause
exit /b 0

rem -- ISCC.exe discovery (--inno only) --------------------------------------
rem Inno Setup 6 installs per user (without administrator rights) by default and
rem puts ISCC.exe under %LOCALAPPDATA%\Programs, so PATH and Program Files are
rem not enough. An install to a custom folder is found via its uninstall entry.
:find_iscc
set "ISCC="
for /f "delims=" %%I in ('where iscc.exe 2^>nul') do if not defined ISCC set "ISCC=%%I"
if defined ISCC goto :eof
call :scan_iscc_in "%ProgramFiles%\Inno Setup 6"
call :scan_iscc_in "%ProgramFiles(x86)%\Inno Setup 6"
call :scan_iscc_in "%LOCALAPPDATA%\Programs\Inno Setup 6"
call :scan_iscc_in "%ProgramFiles%\Inno Setup 5"
call :scan_iscc_in "%ProgramFiles(x86)%\Inno Setup 5"
call :scan_iscc_in "%LOCALAPPDATA%\Programs\Inno Setup 5"
if defined ISCC goto :eof
for %%K in (
    "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1"
    "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1"
    "HKLM\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1"
    "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 5_is1"
    "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 5_is1"
    "HKLM\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 5_is1"
) do call :scan_iscc_reg %%K
goto :eof

:scan_iscc_in
if defined ISCC goto :eof
if "%~1"=="" goto :eof
if exist "%~1\ISCC.exe" set "ISCC=%~1\ISCC.exe"
goto :eof

:scan_iscc_reg
if defined ISCC goto :eof
for /f "tokens=2,*" %%A in ('reg query %1 /v InstallLocation 2^>nul') do call :scan_iscc_in "%%B"
goto :eof
