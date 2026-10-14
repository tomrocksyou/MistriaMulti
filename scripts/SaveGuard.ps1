# Safety net for solo saves: a rolling copy taken before every launch. The game keeps saves in %LOCALAPPDATA%\FieldsOfMistria\saves
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
