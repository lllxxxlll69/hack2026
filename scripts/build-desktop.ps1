param([string]$Name = 'OnlineDean')
$ErrorActionPreference = 'Stop'
if ($Name -notmatch '^[A-Za-z][A-Za-z0-9-]{0,50}$') { throw 'Invalid build name' }
$projectDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
& '.\.venv\Scripts\python.exe' 'scripts\create-app-icon.py'
if ($LASTEXITCODE -ne 0) { throw 'Desktop icon generation failed' }
$savedBuildPath = $env:PATH
try {
    # The host's Poppler ICU shadows the Windows ICU expected by Qt 6.12.
    # Restrict only this build process, never the user's persistent PATH.
    $pythonRuntime = & '.\.venv\Scripts\python.exe' -c 'import sys; print(sys.base_prefix)'
    $windowsDirectory = [Environment]::GetFolderPath('Windows')
    $env:PATH = "$projectDirectory\.venv\Scripts;$pythonRuntime;$windowsDirectory\System32;$windowsDirectory;$windowsDirectory\System32\Wbem"
    & '.\.venv\Scripts\python.exe' -m PyInstaller --clean --noconfirm --windowed --name $Name --icon 'assets\online-dean.ico' --paths $projectDirectory --add-data 'web\cap.svg;web' --add-data 'web\brand.svg;web' --add-data 'web\icons.svg;web' 'desktop\main.py'
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
} finally {
    $env:PATH = $savedBuildPath
}
Write-Output "Desktop build: dist\$Name\$Name.exe"
$testReport = Join-Path $projectDirectory "output\$Name-startup.json"
$testStarted = [DateTime]::UtcNow
$builtExecutable = Join-Path $projectDirectory "dist\$Name\$Name.exe"
$smokeProcess = Start-Process -FilePath $builtExecutable -ArgumentList '--self-test-output', ('"{0}"' -f $testReport) -WindowStyle Hidden -PassThru
if (-not $smokeProcess.WaitForExit(30000)) {
    $smokeProcess.Kill()
    throw 'Qt startup test timed out. The build is not verified.'
}
if ($smokeProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $testReport)) { throw 'Qt startup test failed' }
$reportFile = Get-Item -LiteralPath $testReport
if ($reportFile.LastWriteTimeUtc -lt $testStarted.AddSeconds(-2)) { throw 'Qt test report is stale' }
$report = Get-Content -LiteralPath $testReport -Raw | ConvertFrom-Json
if (-not ($report.window_created -and $report.rendered -and $report.frozen -and $report.login_verified)) { throw 'Qt rendering or login button test failed' }
Write-Output "Verified packaged Qt $($report.qt_version): window rendered and login button opens workspace (offline test)."
