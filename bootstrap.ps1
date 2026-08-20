# Generate a .env with strong random secrets -- and a few interactively-
# chosen deployment settings -- on first run.
# Run this once before `docker compose up`. See bootstrap.py for details --
# this is a thin PowerShell wrapper so Windows users don't need Python
# installed on the host just to bootstrap secrets. If a .env already
# exists it is left untouched; the prompts below only ever run on that
# first pass, have a default for every question (just press Enter), and
# are skipped entirely (every default used silently) when stdin isn't a
# real console -- piped/CI/non-interactive still works unattended.

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

function Set-EnvValue([string]$Text, [string]$Key, [string]$Value) {
    # A MatchEvaluator scriptblock (not a plain replacement string) so
    # $Value is inserted literally -- PowerShell's -replace operator
    # treats $1/$&/etc. specially in an ordinary replacement string,
    # which a generated secret or a pasted connection string could
    # collide with by accident.
    $pattern = "(?m)^$([regex]::Escape($Key))=.*$"
    return [regex]::Replace($Text, $pattern, { param($m) "$Key=$Value" })
}

function Get-EnvValue([string]$Text, [string]$Key, [string]$Default = "") {
    $pattern = "(?m)^$([regex]::Escape($Key))=(.*)$"
    $match = [regex]::Match($Text, $pattern)
    if ($match.Success) { return $match.Groups[1].Value }
    return $Default
}

function Read-YesNo([string]$Prompt, [bool]$Default) {
    $suffix = if ($Default) { "Y/n" } else { "y/N" }
    $answer = Read-Host "$Prompt [$suffix]"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer.Trim().ToLower() -in @("y", "yes")
}

function Read-Answer([string]$Prompt, [string]$Default = "") {
    $suffix = if ($Default) { " [$Default]" } else { "" }
    $answer = Read-Host "$Prompt$suffix"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer.Trim()
}

function Test-PostgresConnection([string]$Url) {
    # "ok"/"fail"/"unavailable" (docker missing) -- runs a throwaway
    # postgres:17-alpine container rather than requiring a Postgres
    # client installed on the bare host; Docker is already the one hard
    # requirement this whole project has.
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        return "unavailable"
    }
    # psql's own success-stream output (the "SELECT 1" result table, on
    # success) is piped to Out-Null rather than left to print -- every
    # unsuppressed object a function emits becomes part of its return
    # value in PowerShell, so without this the caller's `$result = ...`
    # would capture that table alongside "ok" below. Its error-stream
    # output (the connection error, on failure) is left alone so it's
    # still shown to the user.
    & docker run --rm -e PGCONNECT_TIMEOUT=8 postgres:17-alpine psql $Url -c "SELECT 1;" | Out-Null
    if ($LASTEXITCODE -eq 0) { return "ok" } else { return "fail" }
}

function Read-ExternalDatabaseUrl() {
    # Loops on a failed connection test rather than giving up outright --
    # a typo in the URL is the common case, and re-prompting the one
    # field that's wrong is friendlier than aborting the whole run. A
    # failed test is never a hard stop either way: answering yes below
    # saves the URL as given regardless of what the test said.
    while ($true) {
        $url = Read-Answer "External Postgres connection string (postgresql://user:password@host:5432/rain)"
        if ([string]::IsNullOrWhiteSpace($url)) { return "" }
        Write-Host "Testing the connection..."
        $result = Test-PostgresConnection $url
        if ($result -eq "ok") {
            Write-Host "Connected successfully."
            return $url
        } elseif ($result -eq "unavailable") {
            Write-Host "(Couldn't run a connection test -- docker isn't on PATH here. Continuing without one.)"
            return $url
        }
        if (Read-YesNo "Could not connect with that URL. Continue with it anyway?" $false) {
            return $url
        }
        # Otherwise loop back and ask for the URL again.
    }
}

$text = Get-Content -Raw -Path $examplePath
$text = Set-EnvValue $text "POSTGRES_PASSWORD" (New-Secret 32)
$text = Set-EnvValue $text "APP_SECRET_KEY" (New-Secret 48)

if (-not [Console]::IsInputRedirected) {
    Write-Host ""
    Write-Host "A few questions to configure this deployment (Enter accepts the default)."
    Write-Host ""

    $useDefaults = Read-YesNo "Use the default setup -- RAIN's own built-in Postgres container, local document storage, and a separate worker container?" $true
    if (-not $useDefaults) {
        Write-Host ""
        $profiles = @("local-db", "web-frontend", "worker")

        if (-not (Read-YesNo "Use RAIN's own built-in Postgres container?" $true)) {
            $text = Set-EnvValue $text "POSTGRES_URL" (Read-ExternalDatabaseUrl)
            $profiles = $profiles | Where-Object { $_ -ne "local-db" }
            # RAIN's own Postgres image always has pgvector baked in (see
            # db/Dockerfile), so this is only worth asking once an
            # external instance is in the picture -- and defaults to
            # "no" here, unlike every other question above: it's
            # reserved for a future semantic-search feature nothing uses
            # yet, but a managed/restricted Postgres refusing to create
            # it (a permission error on a typical minimum-privilege
            # role, or the extension not being offered at all -- standard
            # RDS in AWS GovCloud, e.g.) fails the whole migration chain
            # outright, a far worse outcome than just not getting an
            # unused placeholder column.
            if (-not (Read-YesNo "Does that Postgres support the pgvector extension? (reserved for a future semantic-search feature, unused today -- say no if you're not sure, or for most managed/restricted instances)" $false)) {
                $text = Set-EnvValue $text "ENABLE_PGVECTOR" "false"
            }
        }

        if (Read-YesNo "Store documents in S3 (or an S3-compatible service) instead of local disk?" $false) {
            $text = Set-EnvValue $text "S3_BUCKET" (Read-Answer "S3 bucket name")
            $text = Set-EnvValue $text "S3_REGION" (Read-Answer "S3 region (blank is fine for a non-AWS endpoint)")
            $text = Set-EnvValue $text "S3_ENDPOINT_URL" (Read-Answer "S3 endpoint URL (blank for real AWS S3, set it for MinIO/etc.)")
            $accessKeyId = Read-Answer "S3 access key ID (blank to use an IAM role instead of a static key)"
            $text = Set-EnvValue $text "S3_ACCESS_KEY_ID" $accessKeyId
            if ($accessKeyId) {
                $text = Set-EnvValue $text "S3_SECRET_ACCESS_KEY" (Read-Answer "S3 secret access key")
            }
        }

        if (Read-YesNo "Merge the worker (syslog listener, rule engine, notifications) into the app container instead of running it separately?" $false) {
            $text = Set-EnvValue $text "EMBED_WORKER" "true"
            $profiles = $profiles | Where-Object { $_ -ne "worker" }
        }

        # Keeps WEB_FRONTEND and COMPOSE_PROFILES in sync automatically --
        # .env.example documents these as needing to be hand-edited
        # together (Compose profiles can't be toggled from inside a plain
        # KEY=VALUE variable), but there's no reason this script, which is
        # already writing both, can't just do that itself.
        if (-not (Read-YesNo "Use Caddy as RAIN's reverse proxy (automatic HTTPS)? Say no if something else already terminates TLS in front of RAIN (e.g. an ALB, an existing reverse proxy)." $true)) {
            $text = Set-EnvValue $text "WEB_FRONTEND" "false"
            $profiles = $profiles | Where-Object { $_ -ne "web-frontend" }
        }

        $text = Set-EnvValue $text "COMPOSE_PROFILES" ($profiles -join ",")
    }
} else {
    Write-Host "Non-interactive session -- skipping deployment questions, using every default."
}

Set-Content -Path $envPath -Value $text -NoNewline -Encoding utf8

Write-Host ""
Write-Host "Wrote $envPath."

# EMBED_WORKER=true + WEB_FRONTEND=false is what actually makes this a
# single-container deployment (see .env.example's "Minimal mode") --
# docker compose still works for that shape (with the
# docker-compose.minimal.yml overlay), but a bare `docker build` +
# `docker run --env-file .env` needs nothing this repo doesn't already
# have checked out, and -- unlike hand-writing a `docker run -e
# KEY=value` for every setting -- reuses the .env just written instead
# of re-typing POSTGRES_URL/APP_SECRET_KEY/etc. a second time. Read back
# from $text (not the interactive answers themselves) so this reflects
# what's actually in the file even if a later change adds another way
# to set either. Falls back to the recommended docker compose path
# otherwise.
$writtenEmbedWorker = Get-EnvValue $text "EMBED_WORKER"
$writtenWebFrontend = Get-EnvValue $text "WEB_FRONTEND"
if ($writtenEmbedWorker -eq "true" -and $writtenWebFrontend -eq "false") {
    $writtenAppPort = Get-EnvValue $text "APP_PORT" "8000"
    $writtenSyslogPort = Get-EnvValue $text "SYSLOG_PORT" "5514"
    Write-Host ""
    Write-Host "This is a single-container deployment (EMBED_WORKER=true, WEB_FRONTEND=false)."
    Write-Host "If another RAIN instance (this repo's own docker compose stack, or an earlier"
    Write-Host "run of this same command) is already using port $writtenAppPort or $writtenSyslogPort, stop it first --"
    Write-Host "Docker will fail to start this one with `"port is already allocated`" otherwise."
    Write-Host "Next:"
    Write-Host "  docker build -t rain-app ./backend"
    Write-Host "  docker run -d --name rain --env-file .env -p ${writtenAppPort}:${writtenAppPort} -p ${writtenSyslogPort}:${writtenSyslogPort}/tcp -p ${writtenSyslogPort}:${writtenSyslogPort}/udp rain-app"
} else {
    Write-Host "Edit RAIN_DOMAIN in .env if you have a public DNS name for automatic ACME certs."
    Write-Host "Next: docker compose up --build"
}
