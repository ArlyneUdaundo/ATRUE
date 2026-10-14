$ErrorActionPreference = 'Stop'

$dumpPath = 'C:\Users\ariel\OneDrive\Backups\EULA\atrue_db_2026-10-13.dump'
$pgBin = 'C:\Program Files\PostgreSQL\19\bin'
$pgRestore = Join-Path $pgBin 'pg_restore.exe'
$psql = Join-Path $pgBin 'psql.exe'

if (-not (Test-Path -LiteralPath $dumpPath)) {
    throw "Local database backup not found: $dumpPath"
}
if (-not (Test-Path -LiteralPath $pgRestore)) {
    throw "pg_restore not found: $pgRestore"
}
if (-not (Test-Path -LiteralPath $psql)) {
    throw "psql not found: $psql"
}

Write-Host 'This will replace the contents represented in the local dump on Render staging.'
Write-Host 'The Render backup is already saved separately.'

$secureUrl = Read-Host 'Paste the Render External Database URL (input hidden)' -AsSecureString
$urlPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureUrl)

try {
    $env:RENDER_DATABASE_URL = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($urlPointer)
    $renderUri = [Uri]$env:RENDER_DATABASE_URL
    $databaseName = [Uri]::UnescapeDataString($renderUri.AbsolutePath.TrimStart('/'))

    if ($databaseName -ne 'atrue_perf_staging') {
        throw "Safety check stopped: expected database atrue_perf_staging, got '$databaseName'. Nothing was restored."
    }

    Write-Host 'Restoring local database backup to atrue_perf_staging...'
    & $pgRestore `
        --clean `
        --if-exists `
        --no-owner `
        --no-acl `
        --single-transaction `
        --exit-on-error `
        "--dbname=$env:RENDER_DATABASE_URL" `
        $dumpPath

    if ($LASTEXITCODE -ne 0) {
        throw "pg_restore failed with exit code $LASTEXITCODE. Its transaction should have rolled back."
    }

    Write-Host 'Restore completed. Verifying account count and latest accounts migration...'
    & $psql $env:RENDER_DATABASE_URL `
        -v ON_ERROR_STOP=1 `
        -c 'SELECT COUNT(*) AS user_accounts FROM public.accounts_user;' `
        -c "SELECT name AS latest_accounts_migration FROM public.django_migrations WHERE app = 'accounts' ORDER BY applied DESC LIMIT 1;"

    if ($LASTEXITCODE -ne 0) {
        throw "Restore ran, but verification failed with exit code $LASTEXITCODE."
    }
}
finally {
    Remove-Item Env:RENDER_DATABASE_URL -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($urlPointer)
    $secureUrl.Dispose()
}
