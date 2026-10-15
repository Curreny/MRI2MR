param(
    [ValidateRange(1, 65535)]
    [int]$Port = 4177,

    [switch]$SetupOnly,

    [switch]$SkipVesselPilotSetup
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

function Resolve-VesselPilotPython {
    $candidates = [System.Collections.Generic.List[string]]::new()

    if ($env:CONDA_DEFAULT_ENV -eq 'BrainAAL' -and $env:CONDA_PREFIX) {
        $candidates.Add((Join-Path $env:CONDA_PREFIX 'python.exe'))
    }

    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($conda) {
        try {
            $condaInfo = (& conda env list --json 2>$null | ConvertFrom-Json)
            foreach ($environmentRoot in $condaInfo.envs) {
                if ((Split-Path -Leaf $environmentRoot) -eq 'BrainAAL') {
                    $candidates.Add((Join-Path $environmentRoot 'python.exe'))
                }
            }
        } catch {
            Write-Warning "Could not query Conda environments: $($_.Exception.Message)"
        }
    }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw 'BrainAAL Python was not found. Create it from environment.yml or activate the BrainAAL Conda environment, then run this script again.'
}

function Get-VesselPilotRegistration {
    $statePath = Join-Path $agnesHome "data\resource-control\mcp\$agnesProfile.mcp.json"
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return $null
    }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    return $state.servers.'vessel-pilot'
}

function Invoke-AgnesMcpMutation {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & node $cli mcp @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "VesselPilot MCP configuration failed: agnes mcp $($Arguments[0]) exited with code $LASTEXITCODE"
    }
}

function Initialize-VesselPilot {
    $python = Resolve-VesselPilotPython
    $server = (Resolve-Path -LiteralPath (Join-Path $harnessRoot 'integrations\vessel-pilot\server.py')).Path
    $inputRoot = (Resolve-Path -LiteralPath (Join-Path $projectRoot 'workspace')).Path
    $caseRoot = Join-Path $inputRoot 'vessel-pilot'
    New-Item -ItemType Directory -Path $caseRoot -Force | Out-Null

    & $python -B -c 'import nibabel, numpy, pydicom, scipy, SimpleITK, trimesh'
    if ($LASTEXITCODE -ne 0) {
        throw "The BrainAAL environment at $python is missing VesselPilot dependencies. Recreate it from environment.yml."
    }
    Write-Output 'VesselPilot Python dependencies: OK'

    # Deployment policy is rebuilt for every Agnes process, so resolve the executable locally
    # instead of persisting a machine-specific path in the repository.
    $existingAllowlist = @($env:AGNES_MCP_STDIO_ALLOWLIST -split ',' | Where-Object { $_ })
    if ($python -notin $existingAllowlist) {
        $env:AGNES_MCP_STDIO_ALLOWLIST = (@($existingAllowlist) + $python) -join ','
    }

    $tools = @(
        'choose_dicom_folder',
        'inspect_dicom_case',
        'get_vessel_case',
        'start_dicom_conversion',
        'start_vessel_candidate',
        'get_vessel_job',
        'cancel_vessel_job',
        'list_vessel_candidates',
        'evaluate_vessel_candidate',
        'suggest_vessel_parameters',
        'finalize_vessel_case'
    )
    $definitionArguments = @(
        '--name', 'VesselPilot',
        '--stdio', $python,
        '--arg', $server,
        '--arg', '--input-root',
        '--arg', $inputRoot,
        '--arg', '--allow-any-input',
        '--arg', '--case-root',
        '--arg', $caseRoot
    )
    foreach ($tool in $tools) {
        $definitionArguments += @('--allow-tool', $tool)
    }

    $registration = Get-VesselPilotRegistration
    if (-not $registration) {
        Write-Output "Registering VesselPilot with $python"
        Invoke-AgnesMcpMutation -Arguments (@('add', 'vessel-pilot') + $definitionArguments)
        $registration = Get-VesselPilotRegistration
    } else {
        $definition = $registration.definition
        $configuredTools = @($definition.toolPolicy.allow)
        $toolsMatch = -not (Compare-Object -ReferenceObject $tools -DifferenceObject $configuredTools)
        $expectedArgs = @($server, '--input-root', $inputRoot, '--allow-any-input', '--case-root', $caseRoot)
        $argsMatch = -not (Compare-Object -ReferenceObject $expectedArgs -DifferenceObject @($definition.transport.args) -SyncWindow 0)
        $definitionMatches =
            $definition.displayName -eq 'VesselPilot' -and
            $definition.transport.kind -eq 'stdio' -and
            $definition.transport.executable -eq $python -and
            $argsMatch -and
            $toolsMatch

        if (-not $definitionMatches) {
            Write-Output "Updating VesselPilot for this machine: $python"
            if ($registration.desired -eq 'enabled') {
                Invoke-AgnesMcpMutation -Arguments @('disable', 'vessel-pilot', '--expected-revision', $registration.revision)
            }
            Invoke-AgnesMcpMutation -Arguments (@('update', 'vessel-pilot', '--expected-revision', $registration.revision) + $definitionArguments)
            $registration = Get-VesselPilotRegistration
        }
    }

    if (-not $registration) {
        throw 'VesselPilot registration did not appear in the Agnes control plane.'
    }
    if ($registration.trust -ne 'trusted') {
        Invoke-AgnesMcpMutation -Arguments @('trust', 'vessel-pilot', '--expected-revision', $registration.revision)
        $registration = Get-VesselPilotRegistration
    }
    if ($registration.desired -ne 'enabled') {
        Invoke-AgnesMcpMutation -Arguments @('enable', 'vessel-pilot', '--expected-revision', $registration.revision)
        $registration = Get-VesselPilotRegistration
    }

    Write-Output "VesselPilot MCP: configured ($python)"
}

if (-not $SetupOnly) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        throw "Port $Port is already in use by process $($listener.OwningProcess). Stop the existing Web service before starting Agnes."
    }
}

Push-Location $harnessRoot
try {
    if (-not $SkipVesselPilotSetup) {
        Initialize-VesselPilot
    }
    if ($SetupOnly) {
        Write-Output 'Setup complete. Agnes was not started because -SetupOnly was specified.'
        return
    }
    & node $cli serve --home $agnesHome --profile $agnesProfile --cwd $projectRoot --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "Agnes exited with code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
