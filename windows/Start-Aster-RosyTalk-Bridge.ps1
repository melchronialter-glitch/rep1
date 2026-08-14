param(
    [string]$LanAddress,
    [int]$Port = 8787,
    [switch]$RotateTokens
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function New-SecretHex {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return ([System.BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
}

function Read-DotEnv([string]$Path) {
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $values
    }

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

function Test-UsableSecret([object]$Value) {
    if ($null -eq $Value) { return $false }
    $secret = [string]$Value
    return $secret.Length -ge 32 -and $secret -notmatch '\s'
}

function Test-PrivateIPv4([string]$Address) {
    $parsed = $null
    if (-not [System.Net.IPAddress]::TryParse($Address, [ref]$parsed)) { return $false }
    $octets = $parsed.GetAddressBytes()
    if ($octets.Length -ne 4) { return $false }
    if ($octets[0] -eq 10) { return $true }
    if ($octets[0] -eq 192 -and $octets[1] -eq 168) { return $true }
    if ($octets[0] -eq 172 -and $octets[1] -ge 16 -and $octets[1] -le 31) { return $true }
    return $false
}

function Find-LanCandidates {
    $found = @()
    try {
        $configs = Get-NetIPConfiguration -ErrorAction Stop | Where-Object {
            $_.NetAdapter.Status -eq "Up" -and $null -ne $_.IPv4DefaultGateway
        }
        foreach ($config in $configs) {
            foreach ($entry in @($config.IPv4Address)) {
                if ($null -ne $entry -and (Test-PrivateIPv4 ([string]$entry.IPAddress))) {
                    $found += [PSCustomObject]@{
                        Address = [string]$entry.IPAddress
                        Adapter = [string]$config.InterfaceAlias
                        Index = [int]$config.InterfaceIndex
                    }
                }
            }
        }
    }
    catch {
        # The DNS fallback below covers systems without NetTCPIP cmdlets.
    }

    if ($found.Count -eq 0) {
        foreach ($address in [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName())) {
            if (Test-PrivateIPv4 $address.IPAddressToString) {
                $found += [PSCustomObject]@{
                    Address = $address.IPAddressToString
                    Adapter = "active network"
                    Index = -1
                }
            }
        }
    }

    return @($found | Sort-Object Address -Unique)
}

try {
    $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
    $projectRoot = Split-Path -Parent $scriptRoot
    Set-Location -LiteralPath $projectRoot

    Write-Host "Aster RosyTalk Bridge - Windows launcher" -ForegroundColor Magenta
    Write-Host "The bridge is restricted to the selected Android package and current visible window."
    Write-Host "This starts and tests the laptop side only; the physical phone must still pass its own browser and bridge connection checks."

    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "package.json") -PathType Leaf)) {
        throw "Keep the windows folder inside the extracted rosytalk-bridge project, beside package.json."
    }
    if ($Port -lt 1 -or $Port -gt 65535) {
        throw "Port must be between 1 and 65535."
    }

    Write-Step "Checking Node.js"
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -eq $nodeCommand -or $null -eq $npmCommand) {
        throw "Node.js 20 or newer is required. Install the current LTS release from https://nodejs.org/ and run this launcher again."
    }

    $nodeVersionText = (& $nodeCommand.Source -p "process.versions.node").Trim()
    if ([version]$nodeVersionText -lt [version]"20.0.0") {
        throw "Node.js $nodeVersionText is too old. Install Node.js 20 or newer."
    }
    Write-Host "Node.js $nodeVersionText"

    Write-Step "Selecting the laptop address visible to the phone"
    $selectedAdapter = "manual"
    $selectedIndex = -1
    if ([string]::IsNullOrWhiteSpace($LanAddress)) {
        $candidates = @(Find-LanCandidates)
        if ($candidates.Count -eq 0) {
            throw "No private IPv4 address was found. Re-run with -LanAddress 192.168.x.x using this laptop's trusted Wi-Fi address."
        }

        if ($candidates.Count -gt 1) {
            Write-Host "Choose the Wi-Fi/Ethernet address shared with the phone:"
            for ($index = 0; $index -lt $candidates.Count; $index += 1) {
                Write-Host ("  [{0}] {1}  ({2})" -f ($index + 1), $candidates[$index].Address, $candidates[$index].Adapter)
            }
            $answer = Read-Host "Network [1]"
            if ([string]::IsNullOrWhiteSpace($answer)) { $answer = "1" }
            $choice = 0
            if (-not [int]::TryParse($answer, [ref]$choice) -or $choice -lt 1 -or $choice -gt $candidates.Count) {
                throw "That network choice is not valid."
            }
            $selected = $candidates[$choice - 1]
        }
        else {
            $selected = $candidates[0]
        }
        $LanAddress = [string]$selected.Address
        $selectedAdapter = [string]$selected.Adapter
        $selectedIndex = [int]$selected.Index
    }
    elseif (-not (Test-PrivateIPv4 $LanAddress)) {
        throw "LanAddress must be a private IPv4 address such as 192.168.x.x, 10.x.x.x, or 172.16-31.x.x."
    }
    Write-Host "Using $LanAddress ($selectedAdapter)"

    $networkCategory = "Unknown"
    if ($selectedIndex -ge 0) {
        try {
            $profile = Get-NetConnectionProfile -InterfaceIndex $selectedIndex -ErrorAction Stop
            $networkCategory = [string]$profile.NetworkCategory
        }
        catch {
            $networkCategory = "Unknown"
        }
    }
    if ($networkCategory -ne "Private") {
        Write-Warning "Windows reports this network as '$networkCategory'. Local ws:// traffic is unencrypted."
        $trustAnswer = Read-Host "Type TRUSTED only if this is your own controlled network"
        if ($trustAnswer -cne "TRUSTED") {
            throw "Stopped without starting the relay. Use a Private trusted network or configure WSS."
        }
    }

    Write-Step "Preparing independent local secrets"
    $envPath = Join-Path $projectRoot ".env"
    $existing = Read-DotEnv $envPath
    $phoneToken = $null
    $mcpToken = $null
    if (-not $RotateTokens -and (Test-UsableSecret $existing["PHONE_TOKEN"])) {
        $phoneToken = [string]$existing["PHONE_TOKEN"]
    }
    if (-not $RotateTokens -and (Test-UsableSecret $existing["MCP_TOKEN"])) {
        $mcpToken = [string]$existing["MCP_TOKEN"]
    }
    if ($null -eq $phoneToken) { $phoneToken = New-SecretHex }
    if ($null -eq $mcpToken) { $mcpToken = New-SecretHex }
    while ($mcpToken -eq $phoneToken) { $mcpToken = New-SecretHex }

    $envLines = @(
        "HOST=0.0.0.0",
        "PORT=$Port",
        "PHONE_TOKEN=$phoneToken",
        "MCP_TOKEN=$mcpToken",
        "MCP_ALLOW_UNAUTHENTICATED_LOCAL=false",
        "REQUEST_TIMEOUT_MS=15000",
        "ALLOWED_HOSTS=127.0.0.1,localhost,$LanAddress"
    )
    $temporaryEnvPath = "$envPath.tmp"
    [System.IO.File]::WriteAllLines($temporaryEnvPath, $envLines, (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporaryEnvPath -Destination $envPath -Force
    Write-Host "Saved .env. Existing valid tokens are reused unless -RotateTokens is supplied."

    Write-Step "Installing and compiling the relay"
    & $npmCommand.Source ci --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE." }
    & $npmCommand.Source run build
    if ($LASTEXITCODE -ne 0) { throw "The relay build failed with exit code $LASTEXITCODE." }

    $windowsHost = Join-Path $projectRoot "dist\relay\src\windows-host.js"
    if (-not (Test-Path -LiteralPath $windowsHost -PathType Leaf)) {
        throw "The build did not create dist\relay\src\windows-host.js."
    }

    $env:HOST = "0.0.0.0"
    $env:PORT = [string]$Port
    $env:PHONE_TOKEN = $phoneToken
    $env:MCP_TOKEN = $mcpToken
    $env:MCP_ALLOW_UNAUTHENTICATED_LOCAL = "false"
    $env:REQUEST_TIMEOUT_MS = "15000"
    $env:ALLOWED_HOSTS = "127.0.0.1,localhost,$LanAddress"
    $env:PHONE_LAN_ADDRESS = $LanAddress

    Write-Step "Starting the relay"
    Write-Host "If Windows Firewall asks, allow Node.js on PRIVATE networks only." -ForegroundColor Yellow
    Write-Host "Startup will probe /healthz through both loopback and the selected LAN address $LanAddress."
    Write-Host "A passing laptop LAN probe does not prove that the phone can cross Wi-Fi isolation or Windows Firewall."
    & $nodeCommand.Source $windowsHost
    if ($LASTEXITCODE -ne 0) { throw "The relay stopped with exit code $LASTEXITCODE." }
}
catch {
    Write-Host ""
    Write-Host "SETUP STOPPED" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Do not send .env or either token when requesting help."
    exit 1
}
