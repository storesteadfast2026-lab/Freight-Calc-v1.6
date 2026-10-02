param([string]$ProjectRoot = 'C:\Docker-Projects\Freight-Calc-v1.6')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Run-Compose([string[]]$Arguments) {
    $output = & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($Arguments -join ' ') failed ($LASTEXITCODE)." }
    return $output
}
function Sha([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
function Save-Utf8([string]$Path, [string]$Value) {
    [System.IO.File]::WriteAllText($Path, $Value, [System.Text.UTF8Encoding]::new($false))
}
function StatusValue($Value) {
    if ($null -eq $Value) { return 'Unavailable' }
    return [string]$Value
}

$project = [System.IO.Path]::GetFullPath($ProjectRoot)
$continuity = Join-Path $project 'continuity'
$stage = Join-Path $continuity ('.snapshot_' + [guid]::NewGuid().ToString('N'))
$previousLocation = Get-Location
try {
    if (-not (Test-Path -LiteralPath (Join-Path $project 'docker-compose.yml') -PathType Leaf)) {
        throw "Calculator App project root is unavailable: $project"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $project 'app/manage.py') -PathType Leaf)) {
        throw 'Django application is missing. Snapshot refused.'
    }
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    Set-Location -LiteralPath $project
    $running = @(Run-Compose @('ps','--status','running','--services'))
    if ('web' -notin $running -or 'db' -notin $running) { throw 'web and db must be running.' }
    Run-Compose @('exec','-T','web','python','manage.py','check') | Out-Null
    Run-Compose @('exec','-T','web','python','manage.py','migrate','--check','--noinput') | Out-Null
    Run-Compose @('exec','-T','web','python','manage.py','makemigrations','--check','--dry-run') | Out-Null
    $raw = (Run-Compose @('exec','-T','web','python','manage.py','export_continuity_state') | Out-String).Trim()
    try { $state = $raw | ConvertFrom-Json } catch { throw 'Live database export was not valid JSON.' }
    if (-not $state.generated_at -or $null -eq $state.counts -or
        $null -eq $state.products_by_calculator_customer -or $state.migrations_pending.Count -ne 0) {
        throw 'Live database export is incomplete or migrations are pending.'
    }
    Save-Utf8 (Join-Path $stage 'DB_STATE.json') ($raw + "`n")

    $codeRoot = Join-Path $stage 'code'
    New-Item -ItemType Directory -Path $codeRoot -Force | Out-Null
    $codeHashes = New-Object 'System.Collections.Generic.List[object]'
    foreach ($directory in @('app/apps','app/config','app/templates','app/static')) {
        $full = Join-Path $project $directory
        if (-not (Test-Path -LiteralPath $full -PathType Container)) { continue }
        foreach ($file in (Get-ChildItem -LiteralPath $full -File -Recurse)) {
            if ($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw "Symlink or reparse point in source tree: $($file.FullName)"
            }
            $relative = $file.FullName.Substring($project.Length).TrimStart('\','/').Replace('\','/')
            if ($relative -match '(^|/)(tests?|__pycache__|\.git|\.venv[^/]*|node_modules|media|logs?|tmp|cache)/' -or
                $relative -match '(^|/)(settings|secrets?|credentials?)/' -or
                $file.Name -match '^(\.env|.*\.(key|pem|p12|sqlite3?|db|log))$' -or
                $file.Extension -notin @('.py','.html','.css','.js')) { continue }
            $content = [System.IO.File]::ReadAllText($file.FullName, [System.Text.UTF8Encoding]::new($false, $true))
            if ($content -match '-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----' -or
                $content -match '(?im)^\s*(?:SECRET_KEY|API_KEY|ACCESS_TOKEN|PASSWORD|PRIVATE_KEY)\s*=\s*["''][^"'']+["'']') {
                throw "Potential embedded secret in $relative. Snapshot refused."
            }
            $destination = Join-Path $codeRoot $relative
            New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
            Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
            if ((Sha $file.FullName) -ne (Sha $destination)) { throw "Source changed while archiving: $relative" }
            $codeHashes.Add([pscustomobject]@{RelativePath=$relative; SHA256=(Sha $file.FullName); Bytes=$file.Length})
        }
    }
    foreach ($relative in @('app/manage.py','app/requirements.txt','docker/django/Dockerfile',
                            'tools/Create_Continuity_Snapshot.ps1','tools/Create_Continuity_Snapshot.bat')) {
        $file = Join-Path $project $relative
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { continue }
        $destination = Join-Path $codeRoot $relative
        New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $file -Destination $destination -Force
        if ((Sha $file) -ne (Sha $destination)) { throw "Source changed while archiving: $relative" }
        $codeHashes.Add([pscustomobject]@{RelativePath=$relative; SHA256=(Sha $file); Bytes=(Get-Item $file).Length})
    }
    if ($codeHashes.Count -lt 10) { throw 'The source allowlist yielded too few files. Snapshot refused.' }
    $codeHashes | Sort-Object RelativePath | Export-Csv -LiteralPath (Join-Path $stage 'CODE_FILE_HASHES.csv') -NoTypeInformation -Encoding UTF8
    Compress-Archive -Path (Join-Path $codeRoot '*') -DestinationPath (Join-Path $stage 'BASELINE_CODE.zip') -CompressionLevel Optimal
    Remove-Item -LiteralPath $codeRoot -Recurse -Force

    $productLines = @('Calculator Customer | Master rows | Operational | Active | Inactive | Same | Different | Source only | Operational only | Eligible | Blocked | Duplicates | Invalid | Comparison')
    foreach ($item in $state.products_by_calculator_customer) {
        $values = @($item.calculator_customer,$item.product_master_rows,$item.operational_products,
                    $item.active,$item.inactive,$item.same,$item.different,$item.source_only,
                    $item.operational_only,$item.eligible_remaining,$item.blocked,
                    $item.duplicates,$item.invalid_rows,$item.comparison_status) | ForEach-Object { StatusValue $_ }
        $productLines += ($values -join ' | ')
    }
    Save-Utf8 (Join-Path $stage 'PRODUCT_STATE.txt') (($productLines -join "`n") + "`n")
    $sourceLines = @("Latest upload: $($state.latest_upload | ConvertTo-Json -Compress)",
                     "Active validated Product Master: $($state.active_product_master | ConvertTo-Json -Compress)",
                     "Recent active/validated/imported ExternalDataFiles (up to 100 of $($state.active_source_count)):")
    foreach ($source in $state.source_files_recent) {
        $sourceLines += "$($source.id) | $($source.calculator_customer) | $($source.file_type) | $($source.status) | $($source.filename) | SHA256=$($source.sha256) | $($source.uploaded_at)"
    }
    Save-Utf8 (Join-Path $stage 'SOURCE_FILES.txt') (($sourceLines -join "`n") + "`n")

    $backups = Join-Path $project 'update_backups'
    $installed = @()
    if (Test-Path -LiteralPath $backups -PathType Container) {
        $installed = @(Get-ChildItem -LiteralPath $backups -Directory | Where-Object {
            (Test-Path -LiteralPath (Join-Path $_.FullName 'INSTALL_STATE.csv') -PathType Leaf) -and
            -not (Test-Path -LiteralPath (Join-Path $_.FullName 'ROLLBACK_STATE.csv') -PathType Leaf)
        } | ForEach-Object {
            [pscustomobject]@{Name=$_.Name;InstalledAt=(Get-Item (Join-Path $_.FullName 'INSTALL_STATE.csv')).LastWriteTime}
        } | Sort-Object InstalledAt)
    }
    $installedLines = @('Installed package backups with INSTALL_STATE.csv and no ROLLBACK_STATE.csv:')
    foreach ($pkg in $installed) { $installedLines += $pkg.Name }
    $lastPackage = if ($installed.Count) { $installed[-1].Name } else { 'Undetermined (no active install records)' }
    $installedLines += "Last package according to install records: $lastPackage"
    Save-Utf8 (Join-Path $stage 'INSTALLED_PACKAGES.txt') (($installedLines -join "`n") + "`n")

    $rules = Join-Path $project 'tools/CONTINUITY_RULES.md'
    $readme = Join-Path $project 'tools/README_CONTINUE.md'
    if (-not (Test-Path -LiteralPath $rules -PathType Leaf) -or -not (Test-Path -LiteralPath $readme -PathType Leaf)) {
        throw 'Continuity rules or continuation instructions are missing.'
    }
    Copy-Item -LiteralPath $readme -Destination (Join-Path $stage 'README_CONTINUE.md')
    $current = @(
        '# Calculator App current state',
        "Generated from installed code and live database: $($state.generated_at)",
        "Project: $project",
        "Last installed package: $lastPackage",
        "Latest Product Master upload: $($state.latest_upload | ConvertTo-Json -Compress)",
        "Active validated Product Master: $($state.active_product_master | ConvertTo-Json -Compress)",
        '', '## Preserved project decisions',
        (Get-Content -LiteralPath $rules -Raw),
        '## Technical state',
        "Database vendor: $($state.database_vendor)",
        "Products: $($state.counts.products); Calculator Customers: $($state.counts.calculator_customers); Customers: $($state.counts.customers)",
        "Quotations: $($state.counts.quotations); Reconciliation decisions: $($state.counts.product_reconciliation_decisions); Correction Rounds: $($state.counts.correction_rounds); Memory: $($state.counts.reconciliation_memory)",
        "Decision statuses: $($state.decision_statuses | ConvertTo-Json -Compress)",
        "Correction Round statuses: $($state.correction_round_statuses | ConvertTo-Json -Compress)",
        '', '## Migrations applied',
        (($state.migrations_applied | ForEach-Object { '- ' + $_ }) -join "`n"),
        '', '## Product Master and Reconciliation by Calculator Customer',
        ($productLines -join "`n"),
        '', '## Source files and code',
        'See SOURCE_FILES.txt for active source names and hashes, CODE_FILE_HASHES.csv for installed source hashes, and BASELINE_CODE.zip for the allowlisted code snapshot.',
        '', '## Known pending points',
        'No machine-readable issue register is part of the Calculator App. Review the latest full test result and operational differences before inferring any further pending work. A comparison marked Unavailable cannot be treated as zero.'
    )
    Save-Utf8 (Join-Path $stage 'CURRENT_STATE.md') (($current -join "`n") + "`n")
    $hashes = foreach ($name in @('CURRENT_STATE.md','BASELINE_CODE.zip','CODE_FILE_HASHES.csv',
                                'DB_STATE.json','PRODUCT_STATE.txt','SOURCE_FILES.txt',
                                'INSTALLED_PACKAGES.txt','README_CONTINUE.md')) {
        $file = Join-Path $stage $name
        [pscustomobject]@{RelativePath=$name;SHA256=(Sha $file);Bytes=(Get-Item $file).Length}
    }
    $hashes | Export-Csv -LiteralPath (Join-Path $stage 'FILE_HASHES.csv') -NoTypeInformation -Encoding UTF8
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $versioned = Join-Path $continuity ("Calculator_App_Continuity_$stamp.zip")
    $latest = Join-Path $continuity 'Calculator_App_Continuity_LATEST.zip'
    if (Test-Path -LiteralPath $versioned) { throw "Snapshot timestamp collision: $versioned" }
    $temporaryArchive = Join-Path $continuity ('.continuity_' + [guid]::NewGuid().ToString('N') + '.zip')
    $temporaryLatest = Join-Path $continuity ('.latest_' + [guid]::NewGuid().ToString('N') + '.zip')
    try {
        Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $temporaryArchive -CompressionLevel Optimal
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [System.IO.Compression.ZipFile]::OpenRead($temporaryArchive)
        try {
            $names = @($zip.Entries | ForEach-Object { $_.FullName })
            foreach ($required in @('CURRENT_STATE.md','BASELINE_CODE.zip','FILE_HASHES.csv',
                                   'DB_STATE.json','PRODUCT_STATE.txt','SOURCE_FILES.txt',
                                   'INSTALLED_PACKAGES.txt','README_CONTINUE.md')) {
                if ($required -notin $names) { throw "Snapshot archive is incomplete: $required" }
            }
        } finally { $zip.Dispose() }
        Copy-Item -LiteralPath $temporaryArchive -Destination $temporaryLatest -Force
        if ((Sha $temporaryArchive) -ne (Sha $temporaryLatest)) { throw 'LATEST copy hash differs.' }
        Move-Item -LiteralPath $temporaryArchive -Destination $versioned
        Move-Item -LiteralPath $temporaryLatest -Destination $latest -Force
        Write-Host "[OK] Continuity Snapshot: $versioned" -ForegroundColor Green
        Write-Host "[OK] Latest: $latest" -ForegroundColor Green
    } finally {
        foreach ($temporary in @($temporaryArchive,$temporaryLatest)) {
            if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
        }
    }
} catch {
    Write-Host "[FAILED] Continuity Snapshot: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Set-Location -LiteralPath $previousLocation
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}
