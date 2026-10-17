<#
.SYNOPSIS
  构建 Windows 桌面版（PyInstaller --onedir）。

.PARAMETER Version
  版本号；不传则读取 tieba_gui.py 里的 VERSION。

.PARAMETER Python
  用于创建构建虚拟环境的 Python 解释器；默认取 PATH 里的 python。

.PARAMETER UpdateShortcut
  构建完成后更新桌面快捷方式（默认只构建，不修改桌面）。
#>
[CmdletBinding()]
param(
    [string]$Version = "",
    [string]$Python = "",
    [switch]$UpdateShortcut
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Gui = Join-Path $Root "tieba_gui.py"
$Assets = Join-Path $Root "assets"

if (-not $Version) {
    $text = Get-Content -LiteralPath $Gui -Raw -Encoding UTF8
    if ($text -match 'VERSION\s*=\s*"([^"]+)"') {
        $Version = $Matches[1]
    } else {
        throw "无法从 tieba_gui.py 读取 VERSION"
    }
}
if (-not $Python) {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { $Python = $command.Source }
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python)) {
    throw "找不到 Python，请用 -Python 指定解释器路径"
}

$BuildRoot = Join-Path $Root ".build"
$Venv = Join-Path $BuildRoot "venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$Dist = Join-Path $BuildRoot "dist_onedir"
$Work = Join-Path $BuildRoot "work_onedir"
$Output = Join-Path $Root "dist\贴吧回复统计_v$Version"

Write-Host "[1/5] 准备构建环境：$Venv"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    & $Python -m venv --system-site-packages $Venv
    if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败" }
}
& $VenvPython -m pip install --disable-pip-version-check --no-input --quiet pyinstaller
if ($LASTEXITCODE -ne 0) { throw "安装 PyInstaller 失败" }

Write-Host "[2/5] 构建 exe（版本 $Version）"
& $VenvPython -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name "贴吧回复统计" `
    --icon (Join-Path $Assets "app.ico") `
    --version-file (Join-Path $Assets "version_info.txt") `
    --paths $Root `
    --exclude-module numpy --exclude-module PIL --exclude-module pandas `
    --exclude-module matplotlib --exclude-module scipy `
    --distpath $Dist --workpath $Work --specpath $BuildRoot `
    $Gui
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败" }

Write-Host "[3/5] 复制发布目录：$Output"
if (Test-Path -LiteralPath $Output) { Remove-Item -LiteralPath $Output -Recurse -Force }
New-Item -ItemType Directory -Path $Output | Out-Null
Copy-Item -Path (Join-Path $Dist "贴吧回复统计\*") -Destination $Output -Recurse -Force
foreach ($name in @("使用说明.txt", "启动.bat", "以管理员身份运行.bat")) {
    $file = Join-Path $Root $name
    if (Test-Path -LiteralPath $file) { Copy-Item -LiteralPath $file -Destination $Output -Force }
}

Write-Host "[4/5] 运行 --selftest"
$env:TIEBA_SELFTEST_OUT = Join-Path $BuildRoot "selftest.xlsx"
& (Join-Path $Output "贴吧回复统计.exe") --selftest
if ($LASTEXITCODE -ne 0) { throw "selftest 失败（退出码 $LASTEXITCODE）" }

if ($UpdateShortcut) {
    Write-Host "[5/5] 更新桌面快捷方式"
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "贴吧楼层回复统计.lnk"))
    $lnk.TargetPath = Join-Path $Output "贴吧回复统计.exe"
    $lnk.WorkingDirectory = $Output
    $lnk.IconLocation = (Join-Path $Output "贴吧回复统计.exe") + ",0"
    $lnk.Save()
} else {
    Write-Host "[5/5] 跳过快捷方式（加 -UpdateShortcut 可更新）"
}

Write-Host "完成：$Output"
