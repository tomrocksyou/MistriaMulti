# Safety net for solo saves. The game keeps saves in %LOCALAPPDATA%\FieldsOfMistria\saves
# (game-<id>-<id>.sav plus steam_autocloud.vdf). This never deletes a save: anything it
# replaces or removes is moved to a quarantine folder first.
$script:SaveGuardIgnore = @('steam_autocloud.vdf')

function Get-MistriMultiSavesDir { Join-Path $env:LOCALAPPDATA 'FieldsOfMistria\saves' }

function New-SoloBackup {
    param([string]$SavesDir, [string]$BackupRoot, [int]$Keep = 10)
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $dest = Join-Path $BackupRoot $stamp
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    $hashes = @{}
    if (Test-Path -LiteralPath $SavesDir) {
        foreach ($f in Get-ChildItem -LiteralPath $SavesDir -File) {
            if ($script:SaveGuardIgnore -contains $f.Name) { continue }
            Copy-Item -LiteralPath $f.FullName -Destination (Join-Path $dest $f.Name)
            $hashes[$f.Name] = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
        }
    }
    [IO.File]::WriteAllText((Join-Path $dest 'manifest.json'), ($hashes | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
    # Keep only the newest backups; backup folders are named by timestamp.
    Get-ChildItem -LiteralPath $BackupRoot -Directory | Sort-Object Name -Descending | Select-Object -Skip $Keep |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
    return [pscustomobject]@{ Path = $dest; Hashes = $hashes }
}

# Compares the saves folder with a backup. With -Restore, solo saves are put back and
# anything new or changed is moved to $QuarantineRoot. Returns the list of differences.
function Test-SoloSaves {
    param($Backup, [string]$SavesDir, [string]$QuarantineRoot, [switch]$Restore)
    $quarantine = Join-Path $QuarantineRoot (Split-Path $Backup.Path -Leaf)
    $changes = @()
    $seen = @{}
    if (Test-Path -LiteralPath $SavesDir) {
        foreach ($f in Get-ChildItem -LiteralPath $SavesDir -File) {
            if ($script:SaveGuardIgnore -contains $f.Name) { continue }
            $seen[$f.Name] = $true
            $hash = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
            if (-not $Backup.Hashes.ContainsKey($f.Name)) { $kind = 'new' }
            elseif ($Backup.Hashes[$f.Name] -ne $hash) { $kind = 'changed' }
            else { continue }
            $changes += "$kind $($f.Name)"
            if ($Restore) {
                New-Item -ItemType Directory -Path $quarantine -Force | Out-Null
                Move-Item -LiteralPath $f.FullName -Destination (Join-Path $quarantine $f.Name) -Force
                if ($kind -eq 'changed') { Copy-Item -LiteralPath (Join-Path $Backup.Path $f.Name) -Destination $f.FullName }
            }
        }
    }
    foreach ($name in $Backup.Hashes.Keys) {
        if ($seen.ContainsKey($name)) { continue }
        $changes += "missing $name"
        if ($Restore) { Copy-Item -LiteralPath (Join-Path $Backup.Path $name) -Destination (Join-Path $SavesDir $name) }
    }
    return $changes
}
