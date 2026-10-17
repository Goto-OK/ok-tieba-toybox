<#
.SYNOPSIS
  同步核心并构建 Android debug APK（Chaquopy）。

.PARAMETER JavaHome
  JDK 17 路径；默认取 $env:JAVA_HOME 或 E:\android-build\jdk-17.0.12+7。

.PARAMETER AndroidSdk
  Android SDK 路径；默认取 $env:ANDROID_HOME 或 E:\android-build\sdk。

.PARAMETER Gradle
  gradle.bat 路径；默认取 E:\android-build\gradle-8.7\bin\gradle.bat。
#>
[CmdletBinding()]
param(
    [string]$JavaHome = $(if ($env:JAVA_HOME) { $env:JAVA_HOME } else { "E:\android-build\jdk-17.0.12+7" }),
    [string]$AndroidSdk = $(if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { "E:\android-build\sdk" }),
    [string]$Gradle = "E:\android-build\gradle-8.7\bin\gradle.bat",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Project = Join-Path $Root "android\project"
$Output = Join-Path $Root "dist\贴吧统计_debug.apk"

foreach ($item in @($JavaHome, $AndroidSdk, $Gradle)) {
    if (-not (Test-Path -LiteralPath $item)) { throw "路径不存在：$item" }
}
if (-not $Python) {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { $Python = $command.Source }
}
if (-not $Python) { throw "找不到 Python，请用 -Python 指定解释器" }

Write-Host "[1/3] 同步核心到 Android 工程"
& $Python (Join-Path $Root "scripts\sync_android.py")
if ($LASTEXITCODE -ne 0) { throw "同步失败" }

Write-Host "[2/3] Gradle assembleDebug"
$env:JAVA_HOME = $JavaHome
$env:ANDROID_HOME = $AndroidSdk
$env:ANDROID_SDK_ROOT = $AndroidSdk
$env:Path = "$JavaHome\bin;$env:Path"
& $Gradle -p $Project :app:assembleDebug --no-daemon
if ($LASTEXITCODE -ne 0) { throw "Gradle 构建失败" }

Write-Host "[3/3] 复制 APK"
$apk = Join-Path $Project "app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path -LiteralPath $apk)) { throw "找不到 APK：$apk" }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Output) | Out-Null
Copy-Item -LiteralPath $apk -Destination $Output -Force
Write-Host "完成：$Output"
