param(
    [ValidateRange(1, 65535)]
    [int]$Port = 4177,
    [ValidateSet('Debug', 'Info', 'Warn', 'Error', 'Off')]
    [string]$LogLevel = 'Info',
    [string]$LogDirectory
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'agnes.config.ps1')

$env:AGNES_AGENT_LOG_LEVEL = $LogLevel.ToLowerInvariant()
if ($LogDirectory) {
    $env:AGNES_AGENT_LOG_DIR = [System.IO.Path]::GetFullPath($LogDirectory)
} elseif (-not $env:AGNES_AGENT_LOG_DIR) {
    $env:AGNES_AGENT_LOG_DIR = Join-Path $env:AGH_HOME 'logs\agent'
}
Write-Output "Agent logs: $env:AGNES_AGENT_LOG_DIR\agent.jsonl (minimum level: $LogLevel)"

$harnessRoot = Join-Path $PSScriptRoot 'agnes-harness'
$cli = Join-Path $harnessRoot 'packages\cli\dist\local\agnes.mjs'
if (-not (Test-Path -LiteralPath $cli -PathType Leaf)) {
    throw 'Agnes CLI build is missing. Run corepack pnpm --filter @agnes/cli build:local from agnes-harness first.'
}

Push-Location $harnessRoot
try {
    & node $cli serve --home $env:AGH_HOME --profile $env:AGNES_PROFILE --cwd $PSScriptRoot --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "Agnes exited with code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
