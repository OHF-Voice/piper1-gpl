param(
    [Parameter(Mandatory = $true)]
    [string]$InstallPrefix
)

$ErrorActionPreference = 'Stop'
$installedPath = (Resolve-Path -LiteralPath $InstallPrefix).Path
$checkRoot = Join-Path $env:RUNNER_TEMP ('piper-install-check-' + [Guid]::NewGuid().ToString('N'))
$relocatedPath = Join-Path $checkRoot 'installed'
$outsidePath = Join-Path $checkRoot 'outside'
New-Item -ItemType Directory -Path $checkRoot, $outsidePath | Out-Null
Copy-Item -LiteralPath $installedPath -Destination $relocatedPath -Recurse

Add-Type -Namespace PiperInstallCheck -Name NativeErrorMode -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern uint SetErrorMode(uint mode);
'@

$previousPath = $env:PATH
$previousErrorMode = [PiperInstallCheck.NativeErrorMode]::SetErrorMode(0x8003)
Push-Location -LiteralPath $outsidePath
try {
    $env:PATH = (Join-Path $env:SystemRoot 'System32') + ';' + $env:SystemRoot
    $executablePath = Join-Path $relocatedPath 'bin/piper_exe.exe'
    $version = (& $executablePath --version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Installed CLI failed with exit code $LASTEXITCODE"
    }
    if ($version -notmatch '^\d+\.\d+\.\d+') {
        throw "Unexpected installed CLI version: $version"
    }
    foreach ($relativePath in @('bin/piper.dll', 'bin/onnxruntime.dll', 'bin/espeak-ng-data/phontab')) {
        if (-not (Test-Path -LiteralPath (Join-Path $relocatedPath $relativePath) -PathType Leaf)) {
            throw "Installed CLI is missing $relativePath"
        }
    }
    Write-Output "Installed Windows CLI $version loads outside the build tree"
} finally {
    Pop-Location
    $env:PATH = $previousPath
    [void][PiperInstallCheck.NativeErrorMode]::SetErrorMode($previousErrorMode)
}
