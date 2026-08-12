param(
    [string]$TunnelId,
    [string]$TunnelClientPath,
    [string]$ExpectedSha256,
    [int]$RelayPort = 8787
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Read-DotEnv([string]$Path) {
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $values }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0 -or $trimmed.StartsWith("#")) { continue }
        if ($trimmed -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $value = $matches[2].Trim()
            if ($value.Length -ge 2) {
                $first = $value.Substring(0, 1)
                $last = $value.Substring($value.Length - 1, 1)
                if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
            }
            $values[$matches[1]] = $value
        }
    }
    return $values
}

function Find-TunnelClient([string]$RequestedPath, [string]$ProjectRoot, [string]$ScriptRoot) {
    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        if (-not (Test-Path -LiteralPath $RequestedPath -PathType Leaf)) {
            throw "The explicit -TunnelClientPath does not identify a file: $RequestedPath"
        }
        return [System.IO.Path]::GetFullPath($RequestedPath)
    }

    $candidates = @(
        (Join-Path $ScriptRoot "tunnel-client.exe"),
        (Join-Path $ProjectRoot "tunnel-client.exe")
    )

    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw "tunnel-client.exe was not found. Download the official client from Platform tunnel settings and place it beside this script, or pass its exact path with -TunnelClientPath."
}

function Get-HttpStatus([string]$Uri, [hashtable]$Headers = @{}) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -Method Get -Headers $Headers -TimeoutSec 4
        return [int]$response.StatusCode
    }
    catch {
        if ($null -ne $_.Exception.Response) {
            try { return [int]$_.Exception.Response.StatusCode } catch { return 0 }
        }
        return 0
    }
}

$plainApiKey = $null
$secureApiKey = $null
try {
    $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    $projectRoot = Split-Path -Parent $scriptRoot
    Set-Location -LiteralPath $projectRoot

    Write-Host "Aster RosyTalk Bridge - Secure MCP Tunnel helper" -ForegroundColor Magenta
    Write-Host "This helper does not create a tunnel, API key, workspace permission, or ChatGPT connection."

    if ($RelayPort -lt 1 -or $RelayPort -gt 65535) { throw "RelayPort must be between 1 and 65535." }
    $values = Read-DotEnv (Join-Path $projectRoot ".env")
    $mcpToken = [string]$values["MCP_TOKEN"]
    if ([string]::IsNullOrWhiteSpace($mcpToken) -or $mcpToken.Length -lt 32 -or $mcpToken -match '\s') {
        throw "A usable MCP_TOKEN was not found. Run Start-Aster-RosyTalk-Bridge.cmd first."
    }

    if ([string]::IsNullOrWhiteSpace($TunnelId)) {
        $TunnelId = Read-Host "Tunnel ID from Platform tunnel settings"
    }
    if ($TunnelId -notmatch '^tunnel_[0-9a-f]{32}$') {
        throw "TunnelId must be tunnel_ followed by exactly 32 lowercase hexadecimal characters."
    }

    Write-Step "Locating the official tunnel client"
    $tunnelClient = Find-TunnelClient $TunnelClientPath $projectRoot $scriptRoot
    $actualSha256 = (Get-FileHash -LiteralPath $tunnelClient -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "Tunnel client: $tunnelClient"
    Write-Host "SHA-256:       $actualSha256"
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256)) {
        $normalizedExpected = $ExpectedSha256.Trim().ToLowerInvariant()
        if ($normalizedExpected -notmatch '^[0-9a-f]{64}$') {
            throw "ExpectedSha256 must contain exactly 64 hexadecimal characters."
        }
        if ($actualSha256 -ne $normalizedExpected) {
            throw "tunnel-client.exe SHA-256 does not match -ExpectedSha256."
        }
        Write-Host "SHA-256 matches the expected value." -ForegroundColor Green
    }
    else {
        Write-Warning "No expected SHA-256 was supplied. Compare the value above with the checksum from the official OpenAI download before running this executable."
        $verified = Read-Host "Type VERIFIED after comparing the official checksum"
        if ($verified -cne "VERIFIED") { throw "Stopped before executing an unverified tunnel client." }
    }
    & $tunnelClient --version
    if ($LASTEXITCODE -ne 0) { throw "tunnel-client --version failed with exit code $LASTEXITCODE." }

    Write-Step "Checking the local relay"
    $healthStatus = Get-HttpStatus "http://127.0.0.1:$RelayPort/healthz"
    if ($healthStatus -ne 200) {
        throw "The local relay is not healthy on port $RelayPort. Keep Start-Aster-RosyTalk-Bridge running, then retry."
    }
    $mcpStatus = Get-HttpStatus "http://127.0.0.1:$RelayPort/mcp" @{ Authorization = "Bearer $mcpToken" }
    if ($mcpStatus -ne 405) {
        throw "The relay did not accept its MCP bearer during a safe GET probe (expected HTTP 405, got $mcpStatus)."
    }

    Write-Step "Reading the runtime API key"
    $secureApiKey = Read-Host "Runtime API key (input is hidden and is not saved)" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureApiKey)
    try {
        $plainApiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    if ([string]::IsNullOrWhiteSpace($plainApiKey)) { throw "A runtime API key is required." }

    $env:CONTROL_PLANE_API_KEY = $plainApiKey
    $env:CONTROL_PLANE_TUNNEL_ID = $TunnelId
    $env:MCP_SERVER_URL = "http://127.0.0.1:$RelayPort/mcp"
    $env:ASTER_ROSYTALK_MCP_AUTH = "Bearer $mcpToken"
    $env:MCP_EXTRA_HEADERS = "Authorization: env:ASTER_ROSYTALK_MCP_AUTH"
    $env:MCP_DISCOVERY_EXTRA_HEADERS = "Authorization: env:ASTER_ROSYTALK_MCP_AUTH"

    Write-Step "Running tunnel diagnostics"
    & $tunnelClient doctor --explain
    if ($LASTEXITCODE -ne 0) {
        throw "tunnel-client doctor failed. Do not disable relay authentication. Run 'tunnel-client help quickstart' and use the current official profile format if this client no longer accepts environment configuration."
    }

    Write-Step "Starting the outbound tunnel"
    Write-Host "Keep this window open during ChatGPT discovery and tool calls. Press Ctrl+C to stop."
    & $tunnelClient run
    if ($LASTEXITCODE -ne 0) { throw "tunnel-client stopped with exit code $LASTEXITCODE." }
}
catch {
    Write-Host ""
    Write-Host "TUNNEL SETUP STOPPED" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "See docs\CONNECT_CHATGPT.md and the current official Secure MCP Tunnel guide." -ForegroundColor Yellow
    exit 1
}
finally {
    $plainApiKey = $null
    $secureApiKey = $null
    Remove-Item Env:CONTROL_PLANE_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:CONTROL_PLANE_TUNNEL_ID -ErrorAction SilentlyContinue
    Remove-Item Env:MCP_SERVER_URL -ErrorAction SilentlyContinue
    Remove-Item Env:ASTER_ROSYTALK_MCP_AUTH -ErrorAction SilentlyContinue
    Remove-Item Env:MCP_EXTRA_HEADERS -ErrorAction SilentlyContinue
    Remove-Item Env:MCP_DISCOVERY_EXTRA_HEADERS -ErrorAction SilentlyContinue
}
