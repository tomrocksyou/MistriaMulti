function Find-MistriMultiGame([string]$Directory) {
    if ($Directory) { return $Directory }
    $taskSteamRoots = @()
    foreach ($taskKey in @('HKCU:\Software\Valve\Steam', 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam')) {
        $taskRegistry = Get-ItemProperty -LiteralPath $taskKey -ErrorAction SilentlyContinue
        if ($taskRegistry.SteamPath) { $taskSteamRoots += $taskRegistry.SteamPath }
        if ($taskRegistry.InstallPath) { $taskSteamRoots += $taskRegistry.InstallPath }
    }
    $taskSteamRoots += Join-Path ${env:ProgramFiles(x86)} 'Steam'
    $taskLibraries = @($taskSteamRoots)
    foreach ($taskSteamRoot in ($taskSteamRoots | Select-Object -Unique)) {
        $taskVdf = Join-Path $taskSteamRoot 'steamapps\libraryfolders.vdf'
        if (Test-Path -LiteralPath $taskVdf) {
            $taskText = Get-Content -LiteralPath $taskVdf -Raw
            foreach ($taskMatch in [regex]::Matches($taskText, '"path"\s+"([^"]+)"')) {
                $taskLibraries += $taskMatch.Groups[1].Value.Replace('\\','\')
            }
        }
    }
    foreach ($taskLibrary in ($taskLibraries | Select-Object -Unique)) {
        $taskCandidate = Join-Path $taskLibrary 'steamapps\common\Fields of Mistria'
        if (Test-Path -LiteralPath (Join-Path $taskCandidate 'Maybe.toml')) { return $taskCandidate }
    }
    throw 'Game not found in Steam libraries. Set -GameDirectory to its installation folder.'
}
