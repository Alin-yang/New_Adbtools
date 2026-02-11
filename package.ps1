# ADB工具打包脚本
Write-Host "================================" -ForegroundColor Green
Write-Host "ADB Tool Packaging Script" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green

Write-Host "Cleaning old build files..." -ForegroundColor Yellow
if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}
if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}

Write-Host "Generating SPEC configuration file..." -ForegroundColor Yellow
python generate_spec.py

Write-Host "Executing packaging..." -ForegroundColor Yellow
pyinstaller ADBTool.spec

Write-Host ""
Write-Host "================================" -ForegroundColor Green
Write-Host "Packaging completed!" -ForegroundColor Green
Write-Host "Executable location: dist\ADBTool.exe" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green

Write-Host "Opening dist folder..." -ForegroundColor Cyan
Start-Process "dist"

Write-Host "Press Enter to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")