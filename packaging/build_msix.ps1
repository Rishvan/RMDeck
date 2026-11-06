# Builds dist\RMDeck-<version>.msix for the Microsoft Store from build\dist\RMDeck
# (run build_installer.bat first). Needs the Windows 10/11 SDK (makeappx, makepri).
#
# The Store re-signs the package, so it is left unsigned. Pass the identity values
# from Partner Center > your app > Product identity:
#   powershell -File packaging\build_msix.ps1 -IdentityName 12345Rishvan.RMDeck `
#     -Publisher "CN=XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX" -PublisherDisplayName Rishvan
# (or set MSIX_IDENTITY_NAME / MSIX_PUBLISHER / MSIX_PUBLISHER_DISPLAY_NAME)
param(
    [string]$IdentityName = $env:MSIX_IDENTITY_NAME,
    [string]$Publisher = $env:MSIX_PUBLISHER,
    [string]$PublisherDisplayName = $env:MSIX_PUBLISHER_DISPLAY_NAME
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# placeholders let the package build (and be checked) before the Store values exist
if (-not $IdentityName) { $IdentityName = "Rishvan.RMDeck" }
if (-not $Publisher) { $Publisher = "CN=Rishvan" }
if (-not $PublisherDisplayName) { $PublisherDisplayName = "Rishvan" }

$version = (Select-String -Path rmdeck.py -Pattern '^APP_VERSION = "([\d.]+)"').Matches[0].Groups[1].Value
$parts = @($version.Split(".") + @("0", "0", "0", "0"))[0..2]
$msixVersion = ($parts -join ".") + ".0"   # the Store needs the 4th number to be 0

$app = Join-Path $root "build\dist\RMDeck"
if (-not (Test-Path (Join-Path $app "RMDeck.exe"))) { throw "Run build_installer.bat first (build\dist\RMDeck missing)." }

$kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
$sdk = Get-ChildItem $kits -Directory -ErrorAction SilentlyContinue |
    Where-Object { Test-Path (Join-Path $_.FullName "x64\makeappx.exe") } |
    Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
if (-not $sdk) { throw "Windows SDK not found (makeappx.exe). Install the Windows 10/11 SDK." }
$makeappx = Join-Path $sdk.FullName "x64\makeappx.exe"
$makepri = Join-Path $sdk.FullName "x64\makepri.exe"

$stage = Join-Path $root "build\msix"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $stage | Out-Null
Copy-Item $app (Join-Path $stage "RMDeck") -Recurse

python packaging\msix\make_assets.py $stage
if ($LASTEXITCODE) { throw "Logo generation failed." }

$manifest = Get-Content packaging\msix\AppxManifest.xml -Raw
$manifest = $manifest.Replace('$IDENTITY_NAME$', $IdentityName).Replace('$PUBLISHER$', $Publisher).
    Replace('$PUBLISHER_DISPLAY_NAME$', $PublisherDisplayName).Replace('$VERSION$', $msixVersion)
[IO.File]::WriteAllText((Join-Path $stage "AppxManifest.xml"), $manifest, (New-Object Text.UTF8Encoding $false))

# resources.pri lets Windows pick the right logo size for each place it is shown
$priConfig = Join-Path $root "build\priconfig.xml"
& $makepri createconfig /cf $priConfig /dq en-US /pv 10.0.0 /o
if ($LASTEXITCODE) { throw "makepri createconfig failed." }
& $makepri new /pr $stage /cf $priConfig /of (Join-Path $stage "resources.pri") /mn (Join-Path $stage "AppxManifest.xml") /o
if ($LASTEXITCODE) { throw "makepri new failed." }

New-Item -ItemType Directory -Force (Join-Path $root "dist") | Out-Null
$out = Join-Path $root "dist\RMDeck-$version.msix"
& $makeappx pack /d $stage /p $out /o
if ($LASTEXITCODE) { throw "makeappx pack failed." }
Write-Host "Done: $out  (identity $IdentityName, version $msixVersion)"
