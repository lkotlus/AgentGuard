# requires -version 5.1
$ErrorActionPreference = "Stop"

$PyName = $null
foreach ($candidate in @("python3", "python", "py")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $PyName = $candidate
        break
    }
}

if (-not $PyName) {
    Write-Error "No python binary found on PATH."
    exit 1
}

$path = (Get-Command $PyName).Source
$version = & $PyName --version 2>&1

if (-not (Get-Command "ollama" -ErrorAction SilentlyContinue)) {
    $confirm = Read-Host "Ollama not found. Install it now? [y/N]"
    if ($confirm -match '^[Yy]$') {
        winget install Ollama.Ollama
    } else {
        Write-Error "Ollama is required for AgentGuard, please install it."
        exit 1
    }
}

& $PyName -m venv venv
& "venv\Scripts\$PyName.exe" -m pip install -r requirements.txt

ollama pull qwen2.5:7b

Start-Sleep -Seconds 1
Clear-Host

$Banner = @"

    _                    _    ____                     _
   / \   __ _  ___ _ __ | |_ / ___|_   _  __ _ _ __ __| |
  / _ \ / _` |/ _ \ '_ \| __| |  _| | | |/ _` | '__/ _` |
 / ___ \ (_| |  __/ | | | |_| |_| | |_| | (_| | | | (_| |
/_/   \_\__, |\___|_| |_|\__|\____|\__,_|\__,_|_|  \__,_|
        |___/
"@

Write-Output $Banner
Write-Output ""
& "venv\Scripts\$PyName.exe" main.py -h

Write-Host "`nRemember to run venv\Scripts\Activate.ps1!" -ForegroundColor Red
