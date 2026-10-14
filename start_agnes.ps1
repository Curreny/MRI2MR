param(
    [ValidateRange(1, 65535)]
    [int]$Port = 4177
)

$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$harnessRoot = Join-Path $projectRoot 'agnes-harness'
$agnesHome = Join-Path $harnessRoot 'agh-home'
$agnesProfile = 'local-dev'

# Pin the instance even when the calling terminal still has an old AGH_HOME.
$env:AGH_HOME = $agnesHome
$env:AGNES_PROFILE = $agnesProfile

$env:AGNES_AGENT_LOG_LEVEL = 'off'
Remove-Item Env:AGNES_AGENT_LOG_DIR -ErrorAction SilentlyContinue
Write-Output "Agnes home: $agnesHome (profile: $agnesProfile)"

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
