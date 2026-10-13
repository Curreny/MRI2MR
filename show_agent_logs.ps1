param(
    [ValidateSet('Debug', 'Info', 'Warn', 'Error')]
    [string]$Level = 'Info',
    [string]$SessionId,
    [string]$Tool,
    [string]$Event,
    [ValidateRange(1, 10000)]
    [int]$Tail = 60,
    [string]$LogDirectory,
    [switch]$Follow,
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
if (-not $LogDirectory) {
    . (Join-Path $PSScriptRoot 'agnes.config.ps1')
    $LogDirectory = if ($env:AGNES_AGENT_LOG_DIR) { $env:AGNES_AGENT_LOG_DIR } else { Join-Path $env:AGH_HOME 'logs\agent' }
}
$logPath = Join-Path ([System.IO.Path]::GetFullPath($LogDirectory)) 'agent.jsonl'
$ranks = @{ DEBUG = 0; INFO = 1; WARN = 2; ERROR = 3 }
$minimum = $ranks[$Level.ToUpperInvariant()]
$offset = 0L
$creationTicks = 0L
$partial = ''
$initial = $true
$waiting = $false

function Show-AgentLogLine([string]$Line) {
    try { $row = $Line | ConvertFrom-Json } catch { return }
    if (-not $ranks.ContainsKey([string]$row.level) -or $ranks[[string]$row.level] -lt $minimum) { return }
    if ($SessionId -and $row.sessionId -ne $SessionId) { return }
    if ($Tool -and ([string]$row.tool).IndexOf($Tool, [StringComparison]::OrdinalIgnoreCase) -lt 0) { return }
    if ($Event -and ([string]$row.event).IndexOf($Event, [StringComparison]::OrdinalIgnoreCase) -lt 0) { return }
    if ($AsJson) { Write-Output $Line; return }
    $details = @()
    foreach ($property in $row.PSObject.Properties) {
        if ($property.Name -in @('ts', 'level', 'sessionId', 'event')) { continue }
        $value = if ($property.Value -is [PSCustomObject]) { $property.Value | ConvertTo-Json -Compress -Depth 8 } else { [string]$property.Value }
        $details += "$($property.Name)=$value"
    }
    Write-Output ("[{0}] [{1}] [{2}] {3} {4}" -f $row.ts, $row.level, $row.sessionId, $row.event, ($details -join ' '))
}

do {
    if (Test-Path -LiteralPath $logPath -PathType Leaf) {
        $info = Get-Item -LiteralPath $logPath
        if ($info.Length -lt $offset -or $info.CreationTimeUtc.Ticks -ne $creationTicks) { $offset = 0L; $partial = '' }
        $creationTicks = $info.CreationTimeUtc.Ticks
        $stream = [IO.File]::Open($logPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
        $reader = $null
        try {
            [void]$stream.Seek($offset, [IO.SeekOrigin]::Begin)
            $reader = New-Object IO.StreamReader($stream, [Text.Encoding]::UTF8)
            $chunk = $reader.ReadToEnd()
            $offset = $stream.Position
        } finally {
            if ($reader) { $reader.Dispose() } else { $stream.Dispose() }
        }
        $lines = ($partial + $chunk) -split "`n"
        $partial = $lines[-1]
        $complete = @($lines | Select-Object -SkipLast 1)
        if ($initial) { $complete = @($complete | Select-Object -Last $Tail); $initial = $false }
        foreach ($line in $complete) { if ($line.Trim()) { Show-AgentLogLine $line } }
    } elseif (-not $waiting) {
        Write-Warning "Agent log does not exist yet: $logPath"
        $waiting = $true
    }
    if ($Follow) { Start-Sleep -Milliseconds 300 }
} while ($Follow)
