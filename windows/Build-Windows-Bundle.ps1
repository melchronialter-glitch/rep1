param(
    [string]$Destination
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptRoot
$projectParent = Split-Path -Parent $projectRoot
if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path $projectParent "Aster-RosyTalk-Bridge-Windows-OneClick.zip"
}
$Destination = [System.IO.Path]::GetFullPath($Destination)
if ([System.IO.Path]::GetExtension($Destination) -ne ".zip") {
    throw "Destination must end in .zip."
}

$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("aster-rosytalk-bundle-" + [Guid]::NewGuid().ToString("N"))
$stagingRoot = Join-Path $temporaryRoot "rosytalk-bridge"

try {
    [void](New-Item -ItemType Directory -Path $stagingRoot -Force)

    $excludeDirectories = @(
        "node_modules", "dist", ".git", ".gradle", ".aster-runtime", ".idea", "build"
    )
    $excludeFiles = @(
        ".env", ".env.*", ".npmrc", ".pypirc", "local.properties",
        "*.jks", "*.keystore", "*.pem", "*.key", "*.pfx", "*.p12", "*.der",
        "id_rsa", "id_rsa.*", "id_ed25519", "id_ed25519.*",
        "*.log", "*.tmp", "*.zip", "tunnel-client.exe"
    )
    $robocopyArguments = @(
        $projectRoot, $stagingRoot, "/E", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/XD"
    ) + $excludeDirectories + @("/XF") + $excludeFiles

    & robocopy.exe @robocopyArguments | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "robocopy failed with exit code $LASTEXITCODE." }

    # .env.* is excluded broadly so backups and local variants cannot leak. Copy back only the
    # shipped placeholder template, which contains no usable credential.
    $environmentExample = Join-Path $projectRoot ".env.example"
    if (Test-Path -LiteralPath $environmentExample -PathType Leaf) {
        Copy-Item -LiteralPath $environmentExample -Destination (Join-Path $stagingRoot ".env.example")
    }

    $forbiddenNames = @(
        ".env", ".npmrc", ".pypirc", "local.properties", "tunnel-client.exe",
        "id_rsa", "id_ed25519"
    )
    $forbiddenExtensions = @(
        ".jks", ".keystore", ".pem", ".key", ".pfx", ".p12", ".der"
    )
    $unsafeFiles = @(Get-ChildItem -LiteralPath $stagingRoot -Recurse -Force -File | Where-Object {
        $name = $_.Name.ToLowerInvariant()
        ($name -in $forbiddenNames) -or
        ($name.StartsWith(".env.") -and $name -ne ".env.example") -or
        ($name.StartsWith("id_rsa.")) -or
        ($name.StartsWith("id_ed25519.")) -or
        ($_.Extension.ToLowerInvariant() -in $forbiddenExtensions)
    })
    if ($unsafeFiles.Count -gt 0) {
        $unsafeList = ($unsafeFiles | ForEach-Object { $_.FullName }) -join [Environment]::NewLine
        throw "Refusing to package possible credentials or private keys:`n$unsafeList"
    }

    $apk = Get-ChildItem -LiteralPath $stagingRoot -Recurse -File -Filter "*.apk" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $apk) {
        $builtApk = Join-Path $projectRoot "android\app\build\outputs\apk\debug\app-debug.apk"
        if (Test-Path -LiteralPath $builtApk -PathType Leaf) {
            $releaseDirectory = Join-Path $stagingRoot "release"
            [void](New-Item -ItemType Directory -Path $releaseDirectory -Force)
            Copy-Item -LiteralPath $builtApk -Destination (Join-Path $releaseDirectory "Aster-RosyTalk-Bridge-debug.apk")
            $apk = Get-Item -LiteralPath (Join-Path $releaseDirectory "Aster-RosyTalk-Bridge-debug.apk")
        }
    }
    if ($null -eq $apk) {
        Write-Warning "No APK is present in the bundle. Build/copy the Android APK before distributing this archive."
    }

    $destinationParent = Split-Path -Parent $Destination
    [void](New-Item -ItemType Directory -Path $destinationParent -Force)
    if (Test-Path -LiteralPath $Destination) {
        throw "Destination already exists: $Destination"
    }

    Compress-Archive -LiteralPath $stagingRoot -DestinationPath $Destination -CompressionLevel Optimal
    Write-Host "Created $Destination" -ForegroundColor Green
    Write-Host "The archive excludes .env variants, local SDK/signing/key files, dependencies, build output, logs, tunnel-client.exe, and existing zip files."
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
