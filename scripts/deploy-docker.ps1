param([switch]$CheckOnly, [ValidateRange(5,600)][int]$EngineWaitSeconds = 120)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
$logDirectory = Join-Path $projectDirectory 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logFile = Join-Path $logDirectory ('docker-launch-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
$savedApiPort = $env:API_PORT

function Write-Status([string]$Message) {
    $line = '[' + (Get-Date -Format 'HH:mm:ss') + '] ' + $Message
    Write-Host $line
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
}

function Invoke-Docker {
    param([string[]]$DockerArguments, [int]$TimeoutSeconds = 10, [switch]$ShowOutput)
    $quoted = ($DockerArguments | ForEach-Object {
        if ($_ -match '"') { throw 'Unexpected quote in Docker argument' }
        '"' + $_ + '"'
    }) -join ' '
    $start = New-Object System.Diagnostics.ProcessStartInfo
    if ([IO.Path]::GetExtension($script:DockerTool) -eq '.cmd') {
        $start.FileName = $env:ComSpec
        $start.Arguments = '/d /s /c ""' + $script:DockerTool + '" ' + $quoted + '"'
    } else {
        $start.FileName = $script:DockerTool
        $start.Arguments = $quoted
    }
    $start.WorkingDirectory = $projectDirectory
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    $null = $process.Start()
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while (-not $process.WaitForExit(1000)) {
        if ($timer.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
            # Stop only the command tree we spawned, not Docker Desktop/daemon.
            $taskKill = Join-Path ([Environment]::SystemDirectory) 'taskkill.exe'
            Start-Process -FilePath $taskKill -ArgumentList '/PID', $process.Id, '/T', '/F' -WindowStyle Hidden -Wait | Out-Null
            $process.Dispose()
            return @{Code = 124; Text = 'Docker command timed out.'}
        }
        if ($ShowOutput -and ([int]$timer.Elapsed.TotalSeconds % 15 -eq 0)) {
            Write-Status ('Docker is still working (' + [int]$timer.Elapsed.TotalSeconds + ' seconds)...')
        }
    }
    $result = @{Code = $process.ExitCode; Text = ($stdout.Result + $stderr.Result).Trim()}
    $process.Dispose()
    if ($ShowOutput -and $result.Text) { Write-Status $result.Text }
    return $result
}

function Test-LocalPort([int]$Port) {
    $listener = New-Object System.Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $Port)
    try { $listener.Start(); return $true } catch { return $false } finally { $listener.Stop() }
}

try {
    Write-Status 'Preparing local FastAPI + PostgreSQL deployment. Existing data is preserved.'
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $command) { throw 'Docker CLI is missing. Install Docker Desktop first.' }
    $script:DockerTool = $command.Source
    $python = Join-Path $projectDirectory '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath (Join-Path $projectDirectory '.env'))) {
        if ($CheckOnly) { throw '.env is missing. Run scripts/setup.py first.' }
        if (Test-Path -LiteralPath $python) {
            & $python (Join-Path $PSScriptRoot 'setup.py')
        } elseif (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 (Join-Path $PSScriptRoot 'setup.py')
        } elseif (Get-Command python -ErrorAction SilentlyContinue) {
            & python (Join-Path $PSScriptRoot 'setup.py')
        } else {
            throw 'Python 3 is missing. Install Python, or create .env as described in README.'
        }
        if ($LASTEXITCODE -ne 0) { throw 'Failed to generate .env.' }
    }
    $config = Invoke-Docker -DockerArguments @('compose','config','--quiet')
    if ($config.Code -ne 0) { throw ('Compose configuration failed: ' + $config.Text) }
    $context = Invoke-Docker -DockerArguments @('context','inspect','--format','{{.Endpoints.docker.Host}}')
    if ($context.Code -ne 0 -or $context.Text -notmatch '^npipe:') {
        throw 'Select a local Docker Desktop context first. Remote Docker deployment is intentionally refused.'
    }
    Write-Status 'Compose configuration and local Docker context checked.'
    if ($CheckOnly) { Write-Status 'Check-only complete: no desktop launched or containers changed.'; exit 0 }

    $engine = Invoke-Docker -DockerArguments @('info','--format','{{.OSType}}')
    if ($engine.Code -ne 0) {
        $desktopPaths = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),
            (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
        )
        $desktop = $desktopPaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $desktop) { throw 'Docker Desktop executable not found. Start Docker Desktop manually.' }
        Write-Status 'Starting Docker Desktop. Waiting for its engine...'
        Start-Process -FilePath $desktop -WindowStyle Hidden | Out-Null
        $deadline = (Get-Date).AddSeconds($EngineWaitSeconds)
        do {
            Start-Sleep -Seconds 3
            $engine = Invoke-Docker -DockerArguments @('info','--format','{{.OSType}}') -TimeoutSeconds 5
            if ($engine.Code -eq 0) { break }
        } while ((Get-Date) -lt $deadline)
        if ($engine.Code -ne 0) {
            Write-Status $engine.Text
            throw 'Docker Desktop engine did not start. Check Docker Desktop/WSL2. No reset or volume deletion was performed.'
        }
    }
    if ($engine.Text.Trim() -ne 'linux') { throw 'Switch Docker Desktop to Linux containers first.' }

    # Reuse the current Compose port when this project is already running.
    $existing = Invoke-Docker -DockerArguments @('compose','port','api','8000')
    $apiPort = $null
    if ($existing.Code -eq 0 -and $existing.Text -match '127\.0\.0\.1:(\d+)') {
        $apiPort = [int]$Matches[1]
    } else {
        foreach ($candidate in 8000..8010) {
            if (Test-LocalPort $candidate) { $apiPort = $candidate; break }
        }
    }
    if (-not $apiPort) { throw 'No free local API port in 8000..8010. Close an unused service and retry.' }
    $env:API_PORT = [string]$apiPort
    Write-Status ('Building and starting containers. API port: ' + $apiPort + '. First build may take several minutes.')
    $deployment = Invoke-Docker -DockerArguments @('compose','up','-d','--build','--wait','--wait-timeout','180') -TimeoutSeconds 1200 -ShowOutput
    if ($deployment.Code -ne 0) { throw ('Docker deployment failed: ' + $deployment.Text) }

    $url = 'http://127.0.0.1:' + $apiPort
    $request = [Net.HttpWebRequest]::Create($url + '/api/health')
    $request.Proxy = $null
    $request.Timeout = 5000
    $response = $request.GetResponse()
    $response.Close()
    Write-Status ('READY: ' + $url)
    Write-Status ('Dean desktop server address: ' + $url + '. Credentials are in .env; do not share that file.')
    $ollama = Invoke-Docker -DockerArguments @('compose','exec','-T','api','python','-c',"import urllib.request; urllib.request.urlopen('http://host.docker.internal:11434/api/tags', timeout=3)")
    if ($ollama.Code -ne 0) {
        Write-Status 'WARNING: API is ready, but Ollama is not reachable from Docker. OCR/AI will not work yet. See README: Ollama from container. Network settings were not changed.'
    }
    Start-Process -FilePath $url | Out-Null
    Write-Status 'Done. Containers keep running after this window closes. No existing preview process was stopped.'
    Write-Status ('Log: ' + $logFile)
} catch {
    Write-Status ('ERROR: ' + $_.Exception.Message)
    Write-Status ('Log: ' + $logFile)
    exit 1
} finally {
    $env:API_PORT = $savedApiPort
}
