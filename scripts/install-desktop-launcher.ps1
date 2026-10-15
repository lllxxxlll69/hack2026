$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $projectDirectory 'Start-Docker.cmd'
$icon = Join-Path $projectDirectory 'assets\docker-launcher.ico'
if (-not (Test-Path -LiteralPath $launcher)) { throw 'Start-Docker.cmd is missing.' }
if (-not (Test-Path -LiteralPath $icon)) { throw 'Generate the launcher icon first.' }
$desktopDirectory = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopDirectory 'Online Dean - Docker.lnk'
if (Test-Path -LiteralPath $shortcutPath) { throw 'Desktop shortcut already exists; it was not overwritten.' }
$shortcutShell = New-Object -ComObject WScript.Shell
$shortcut = $shortcutShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path ([Environment]::SystemDirectory) 'cmd.exe'
$shortcut.Arguments = '/d /c ""' + $launcher + '""'
$shortcut.WorkingDirectory = $projectDirectory
$shortcut.IconLocation = $icon + ',0'
$shortcut.Description = 'Online Dean: start Docker Desktop, FastAPI and PostgreSQL, then open the web app.'
$shortcut.WindowStyle = 1
$shortcut.Save()
Write-Output ('Desktop shortcut created: ' + $shortcutPath)
