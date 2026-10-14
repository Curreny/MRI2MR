param(
    [ValidateRange(1, 65535)]
    [int]$Port = 4177,
    [ValidateSet('Debug', 'Info', 'Warn', 'Error', 'Off')]
    [string]$LogLevel = 'Info',
    [string]$LogDirectory
)

$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$harnessRoot = Join-Path $projectRoot 'agnes-harness'
$agnesHome = Join-Path $harnessRoot 'agh-home'
$agnesProfile = 'local-dev'

# Pin the instance even when the calling terminal still has an old AGH_HOME.
$env:AGH_HOME = $agnesHome
$env:AGNES_PROFILE = $agnesProfile

$env:AGNES_AGENT_LOG_LEVEL = $LogLevel.ToLowerInvariant()
if ($LogDirectory) {
    $env:AGNES_AGENT_LOG_DIR = [System.IO.Path]::GetFullPath($LogDirectory)
} else {
    $env:AGNES_AGENT_LOG_DIR = Join-Path $agnesHome 'logs\agent'
}
Write-Output "Agnes home: $agnesHome (profile: $agnesProfile)"
Write-Output "Agent logs: $env:AGNES_AGENT_LOG_DIR\agent.jsonl (minimum level: $LogLevel)"

$cli = Join-Path $harnessRoot 'packages\cli\dist\local\agnes.mjs'
if (-not (Test-Path -LiteralPath $cli -PathType Leaf)) {
    throw 'Agnes CLI build is missing. Run corepack pnpm --filter @agnes/cli build:local from agnes-harness first.'
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    throw "Port $Port is already in use by process $($listener.OwningProcess). Stop the existing Web service before starting Agnes."
}

Push-Location $harnessRoot
try {
    & node $cli serve --home $agnesHome --profile $agnesProfile --cwd $projectRoot --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "Agnes exited with code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
