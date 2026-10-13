param(
    [Parameter(Mandatory = $true)]
    [string]$AgnesHome
)

$ErrorActionPreference = 'Stop'

$source = Join-Path $PSScriptRoot 'skill\SKILL.md'
$resolvedHome = (Resolve-Path -LiteralPath $AgnesHome).Path
$targetDir = Join-Path $resolvedHome 'skills\vessel-pilot'
$target = Join-Path $targetDir 'SKILL.md'

New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
Copy-Item -LiteralPath $source -Destination $target -Force

if ((Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash -ne
    (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash) {
    throw "VesselPilot Skill copy did not match its source: $target"
}

Write-Output "VesselPilot Skill installed at $target"
