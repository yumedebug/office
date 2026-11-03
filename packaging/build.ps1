#Requires -Version 5.1
<#
.SYNOPSIS
  Builds the Windows installer (setup.exe) for AI Office Workspace.

.DESCRIPTION
  Prefer packaging\build.bat.  This script does the same work and is kept for
  people who already use PowerShell.  All messages are ASCII on purpose so the
  file parses the same way in Windows PowerShell 5.1 and PowerShell 7.

  1. builds the React frontend (npm run build -> dist\)
  2. copies Qt's qwebchannel.js into dist\ (a frozen build cannot write there)
  3. installs the Python requirements and PyInstaller / Pillow
  4. generates packaging\app.ico
  5. freezes the app with PyInstaller (packaging\output\AIOfficeWorkspace\)
  6. builds setup.exe with PyInstaller from packaging\setup.py (built-in wizard)
  7. packs setup.exe into site\AI-Office-Workspace-Setup.zip (the download link)

  Requirements: Node.js 18/20+, Python 3.10+.
  -Inno also needs Inno Setup 6.3+ (https://jrsoftware.org/isdl.php).

.PARAMETER SkipNpmInstall
  Reuse the existing frontend\node_modules instead of running npm install.

.PARAMETER SkipInstaller
  Stop after PyInstaller and leave only the application folder.

.PARAMETER Inno
  Build setup.exe with Inno Setup (packaging\installer.iss) instead of the
  built-in wizard in packaging\setup.py.

.PARAMETER Python
  Python launcher to use ("py" by default, "python" or a full path also work).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipNpmInstall,
    [switch]$SkipInstaller,
    [switch]$Inno,
    [string]$Python = "py"
)

$ErrorActionPreference = "Stop"

$packagingDir = $PSScriptRoot
$rootDir = Split-Path -Parent $packagingDir
$outputDir = Join-Path $packagingDir "output"
$workDir = Join-Path $packagingDir "work"
$appDir = Join-Path $outputDir "AIOfficeWorkspace"
$setupPath = Join-Path $outputDir "AI-Office-Workspace-Setup.exe"
$siteZipPath = Join-Path (Join-Path $rootDir "site") "AI-Office-Workspace-Setup.zip"

function Assert-ExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed (exit code $LASTEXITCODE)"
    }
}

function Invoke-Native {
    param(
        [string]$Step,
        [string]$Executable,
        [string[]]$Arguments
    )
    Write-Host "== $Step ==" -ForegroundColor Cyan
    & $Executable @Arguments
    Assert-ExitCode $Step
}

function Find-Npm {
    # Prefer npm.cmd: the npm.ps1 wrapper fails under restrictive execution
    # policies, which is a common source of confusing build errors.
    $command = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $fallback = Get-Command "npm" -ErrorAction SilentlyContinue
    if ($fallback) { return $fallback.Source }
    return $null
}

function Find-Iscc {
    $candidates = @()
    $command = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    if (${env:ProgramFiles(x86)}) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe")
    }
    if ($env:ProgramFiles) {
        $candidates += (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    }
    # Inno Setup 6 installs per user (no administrator rights) by default on
    # Windows 10/11, which puts ISCC.exe under %LOCALAPPDATA%\Programs.
    if ($env:LOCALAPPDATA) {
        $candidates += (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    }
    # An install to a custom folder is found through its uninstall entry.
    $uninstallKeys = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1"
    )
    foreach ($key in $uninstallKeys) {
        if (-not (Test-Path $key)) { continue }
        $location = (Get-ItemProperty -Path $key -Name "InstallLocation" -ErrorAction SilentlyContinue).InstallLocation
        if ($location) {
            $candidates += (Join-Path $location "ISCC.exe")
        }
    }
    return $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

# -- 1. frontend -------------------------------------------------------------
$npm = Find-Npm
if (-not $npm) {
    throw "npm was not found. Install Node.js 18/20+ and run again."
}

Push-Location (Join-Path $rootDir "frontend")
try {
    if (-not $SkipNpmInstall) {
        Invoke-Native "frontend: npm install" $npm @("install")
    }
    Invoke-Native "frontend: npm run build" $npm @("run", "build")
}
finally {
    Pop-Location
}

$indexPath = Join-Path $rootDir "dist\index.html"
if (-not (Test-Path $indexPath)) {
    throw "dist\index.html was not created. Check the npm run build output."
}

Push-Location $rootDir
try {
    # -- 2. qwebchannel.js ---------------------------------------------------
    Invoke-Native "qwebchannel.js" $Python @("packaging/prepare_qwebchannel.py")

    # -- 3. python dependencies ----------------------------------------------
    Invoke-Native "Python dependencies" $Python @(
        "-m", "pip", "install", "-r", "requirements.txt"
    )
    Invoke-Native "Build dependencies" $Python @(
        "-m", "pip", "install", "-r", "packaging/requirements-build.txt"
    )

    # -- 4. icon -------------------------------------------------------------
    Invoke-Native "application icon" $Python @("packaging/make_icon.py")

    # -- 5. PyInstaller ------------------------------------------------------
    Invoke-Native "PyInstaller" $Python @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath", $outputDir,
        "--workpath", $workDir,
        "packaging/app.spec"
    )
}
finally {
    Pop-Location
}

$appExe = Join-Path $appDir "AIOfficeWorkspace.exe"
if (-not (Test-Path $appExe)) {
    throw "PyInstaller output was not found: $appExe"
}
Write-Host "Application: $appExe" -ForegroundColor Green

if ($SkipInstaller) {
    Write-Host "-SkipInstaller was given; setup.exe was not created." -ForegroundColor Yellow
    exit 0
}

# -- 6. setup.exe ------------------------------------------------------------
# A stale setup.exe must not survive a failed build.
if (Test-Path $setupPath) {
    Remove-Item -LiteralPath $setupPath -Force
}

if ($Inno) {
    # Optional alternative: the Inno Setup installer (packaging\installer.iss).
    $iscc = Find-Iscc
    if (-not $iscc) {
        Write-Warning "Inno Setup 6 was not found, so setup.exe was not created."
        Write-Warning "Checked PATH, Program Files\Inno Setup 6, LocalAppData\Programs\Inno Setup 6 and the uninstall registry entries."
        Write-Warning "Install it from https://jrsoftware.org/isdl.php and run again."
        Write-Warning "Without -Inno, setup.exe is built with the built-in wizard."
        exit 1
    }
    Invoke-Native "Inno Setup" $iscc @((Join-Path $packagingDir "installer.iss"))
}
else {
    # Built-in wizard (packaging\setup.py): install folder page + shortcuts.
    Invoke-Native "setup.exe" $Python @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath", $outputDir,
        "--workpath", $workDir,
        (Join-Path $packagingDir "setup.spec")
    )
}

if (-not (Test-Path $setupPath)) {
    throw "setup.exe was not found: $setupPath"
}

# -- 7. handout zip ----------------------------------------------------------
# Optional copy for handing setup.exe over offline; site\index.html links to the
# GitHub Release instead.
Invoke-Native "handout zip" $Python @((Join-Path $packagingDir "make_site_zip.py"))

Write-Host ""
Write-Host "Done: $setupPath" -ForegroundColor Green
Write-Host "Handout zip (optional): $siteZipPath" -ForegroundColor Green
Write-Host "Double-click that setup.exe to install (no administrator rights required)." -ForegroundColor Green
Write-Host "Do not run $appExe when you want the installer: that is the app itself." -ForegroundColor Green
Write-Host "The build is unsigned, so SmartScreen warns on first launch." -ForegroundColor Yellow
