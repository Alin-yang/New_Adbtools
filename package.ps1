# ADB工具打包脚本（onedir）
Write-Host "================================" -ForegroundColor Green
Write-Host "ADB Tool Packaging Script (onedir)" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green

# 默认打 onedir：产物是 dist\ADBTool\ 文件夹，启动不需要解压。
# 实测比 onefile 快约 12 秒（onefile 每次启动都要把内嵌 archive 解压到 %TEMP%）。
# 需要单个 exe 文件时用 package_onefile.bat。

$Python = "D:\tool\python\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }
Write-Host "Using Python: $Python" -ForegroundColor Cyan

Write-Host ""
Write-Host "Cleaning old build files..." -ForegroundColor Yellow
foreach ($d in @("build", "build_onedir", "dist", "dist_onedir")) {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}

Write-Host ""
Write-Host "Executing packaging (ADBTool_onedir.spec)..." -ForegroundColor Yellow
& $Python -m PyInstaller ADBTool_onedir.spec --noconfirm --clean

Write-Host ""
Write-Host "================================" -ForegroundColor Green
Write-Host "Packaging completed!" -ForegroundColor Green
Write-Host "Executable location: dist\ADBTool\ADBTool.exe" -ForegroundColor Green
Write-Host "NOTE: 分发时请把整个 dist\ADBTool 文件夹一起打包" -ForegroundColor Yellow
Write-Host "================================" -ForegroundColor Green

Write-Host ""
Write-Host "Opening dist folder..." -ForegroundColor Cyan
Start-Process "dist"

Write-Host "Press Enter to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
