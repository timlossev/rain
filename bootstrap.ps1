# Generate a .env with strong random secrets on first run.
# Run this once before `docker compose up`. See bootstrap.py for details --
# this is a thin PowerShell wrapper so Windows users don't need Python
# installed on the host just to bootstrap secrets.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envPath = Join-Path $root ".env"
$examplePath = Join-Path $root ".env.example"

if (Test-Path $envPath) {
    Write-Host ".env already exists at $envPath, leaving it untouched."
    exit 0
}

if (-not (Test-Path $examplePath)) {
    throw "missing template: $examplePath"
}

function New-Secret([int]$Bytes) {
    # RandomNumberGenerator.Fill() is .NET Core/.NET 5+ only. Windows
    # PowerShell 5.1 runs on .NET Framework, where RandomNumberGenerator
    # is abstract -- Create() + the instance method GetBytes() is the
    # API that works on both .NET Framework and .NET Core/PowerShell 7.
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($buffer)
    } finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($buffer) -replace '\+', '-' -replace '/', '_' -replace '=', ''
}

$text = Get-Content -Raw -Path $examplePath
$text = $text -replace 'POSTGRES_PASSWORD=', ("POSTGRES_PASSWORD=" + (New-Secret 32))
$text = $text -replace 'APP_SECRET_KEY=', ("APP_SECRET_KEY=" + (New-Secret 48))

Set-Content -Path $envPath -Value $text -NoNewline -Encoding utf8

Write-Host "Wrote $envPath with freshly generated secrets."
Write-Host "Edit RAIN_DOMAIN in .env if you have a public DNS name for automatic ACME certs."
Write-Host "Next: docker compose up --build"
