param([string]$GameDirectory)
$ErrorActionPreference = 'Stop'

if (-not $GameDirectory) {
    $gameProcess = Get-Process CoreKeeper -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($gameProcess) {
        try { $GameDirectory = Split-Path -Parent $gameProcess.Path } catch { }
    }
}
if (-not $GameDirectory) {
    $steamRoots = @()
    try { $steamRoots += (Get-ItemProperty 'HKCU:\Software\Valve\Steam').SteamPath } catch { }
    if (${env:ProgramFiles(x86)}) { $steamRoots += Join-Path ${env:ProgramFiles(x86)} 'Steam' }
    $libraries = @($steamRoots | Where-Object { $_ })
    foreach ($steamRoot in $steamRoots) {
        $libraryFile = Join-Path $steamRoot 'steamapps\libraryfolders.vdf'
        if (Test-Path -LiteralPath $libraryFile) {
            $libraryText = Get-Content -Raw -LiteralPath $libraryFile
            foreach ($match in [regex]::Matches($libraryText, '"path"\s+"([^"]+)"')) {
                $libraries += $match.Groups[1].Value.Replace('\\', '\')
            }
        }
    }
    foreach ($library in ($libraries | Select-Object -Unique)) {
        $candidate = Join-Path $library 'steamapps\common\Core Keeper'
        if (Test-Path -LiteralPath (Join-Path $candidate 'CoreKeeper.exe')) {
            $GameDirectory = $candidate
            break
        }
    }
}
if (-not $GameDirectory) { throw 'Game not found. Run .\build_helper.ps1 -GameDirectory "D:\Games\Core Keeper" with your actual installation folder.' }
$managedDir = Join-Path $GameDirectory 'CoreKeeper_Data\Managed'
$referenceNames = @('mscorlib.dll','System.dll','System.Core.dll','netstandard.dll','0Harmony.dll','Pug.Other.dll','Pug.Base.dll','Pug.ECS.Components.dll','Pug.ECS.Extensions.dll','Pug.ECS.Hybrid.dll','Pug.UnityExtensions.dll','Unity.Entities.dll','Unity.Mathematics.dll','Unity.NetCode.dll','UnityEngine.CoreModule.dll')
$compilerRefs = foreach ($name in $referenceNames) {
    $reference = Join-Path $managedDir $name
    if (-not (Test-Path -LiteralPath $reference)) { throw "Incompatible game installation: missing $name" }
    '/reference:' + $reference
}
$dotnetCommand = Get-Command dotnet -ErrorAction SilentlyContinue
if (-not $dotnetCommand) { throw 'Building requires a .NET SDK (8 or later), not just the .NET runtime.' }
$sdkList = & $dotnetCommand.Source --list-sdks
if ($LASTEXITCODE -ne 0) { throw 'Could not list .NET SDKs.' }
$sdkCandidates = foreach ($line in $sdkList) {
    if ($line -match '^(\S+)\s+\[(.+)\]') {
        $sdkVersion = $Matches[1]
        if ([int]($sdkVersion.Split('.')[0]) -ge 8) {
            $compiler = Join-Path $Matches[2] "$sdkVersion\Roslyn\bincore\csc.dll"
            if (Test-Path -LiteralPath $compiler) { $compiler }
        }
    }
}
$compiler = @($sdkCandidates) | Select-Object -Last 1
if (-not $compiler) { throw 'A .NET SDK version 8 or later is required.' }
$source = Join-Path $PSScriptRoot 'CoreKeeperAutoFishPython.cs'
$output = Join-Path $PSScriptRoot 'CoreKeeperAutoFishPython.dll'
& $dotnetCommand.Source $compiler /nologo /noconfig /target:library /nostdlib "/out:$output" "/pathmap:$PSScriptRoot=." $compilerRefs $source
if ($LASTEXITCODE -ne 0) { throw 'Helper compilation failed. The game API may have changed.' }
Write-Output "Built $output using the installed game assemblies."
