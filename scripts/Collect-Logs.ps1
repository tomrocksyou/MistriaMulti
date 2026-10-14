# Gathers every mod log (mod_data\<mod>\logs\*.log) plus the game log into one zip on the Desktop.
$root = Join-Path $env:LOCALAPPDATA 'FieldsOfMistria'
$stage = Join-Path ([IO.Path]::GetTempPath()) ('mistri-logs-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
$count = 0
foreach ($log in Get-ChildItem -Path (Join-Path $root 'mod_data') -Recurse -Filter '*.log' -ErrorAction SilentlyContinue) {
    $mod = $log.Directory.Parent.Name
    Copy-Item -LiteralPath $log.FullName -Destination (Join-Path $stage ("$mod`__" + $log.Name)); $count++
}
$game = Join-Path $root 'log.txt'
if (Test-Path -LiteralPath $game) { Copy-Item -LiteralPath $game -Destination (Join-Path $stage 'game_log.txt'); $count++ }
$zip = Join-Path ([Environment]::GetFolderPath('Desktop')) 'mistri-logs.zip'
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip }
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip
Remove-Item -LiteralPath $stage -Recurse -Force
Write-Host "Collected $count log file(s) into $zip"
