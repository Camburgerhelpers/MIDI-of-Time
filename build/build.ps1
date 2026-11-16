# Builds the portable Windows app into dist\MIDI of Time\ and the release zip into release\.
# Run from anywhere in PowerShell 7. Uses its own virtual environment (.venv-build) - nothing is installed system-wide.
param([string]$Python = 'python', [string]$PyInstallerVersion = '6.22.3')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent; Set-Location $root
$ver = (Select-String -Path 'src\midi_of_time\__init__.py' -Pattern "__version__ = '(.+)'").Matches[0].Groups[1].Value
$venv = Join-Path $root '.venv-build'
if (-not (Test-Path "$venv\Scripts\python.exe")) { & $Python -m venv $venv }
& "$venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check "pyinstaller==$PyInstallerVersion"
& "$venv\Scripts\python.exe" tests\test_offline.py
if ($LASTEXITCODE) { throw 'offline tests failed' }
& "$venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name 'MIDI of Time' `
    --icon "$root\src\midi_of_time\assets\ocarina-midi.ico" --add-data "$root\src\midi_of_time\assets;assets" `
    --paths "$root\src" --distpath "$root\dist" --workpath "$root\build\work" --specpath "$root\build\work" `
    "$root\build\launcher.py"
$app = Join-Path $root 'dist\MIDI of Time'
Copy-Item README.md, LICENSE, CHANGELOG.md, TROUBLESHOOTING.md, COMPATIBILITY.md, CREDITS.md, THIRD_PARTY_NOTICES.md $app
Copy-Item docs $app -Recurse -Force
Remove-Item "$app\docs\research" -Recurse -Force -ErrorAction SilentlyContinue   # research lives in the repo, not the app package
# exact inventory of everything that ships
$inv = Get-ChildItem $app -Recurse -File | Sort-Object FullName | ForEach-Object {
    '{0}  {1,10}  {2}' -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.Length, $_.FullName.Substring($app.Length + 1) }
(@("MIDI of Time $ver - file inventory (SHA-256, bytes, path)", '') + $inv) | Set-Content "$app\INVENTORY.txt"
New-Item -ItemType Directory "$root\release" -Force | Out-Null
$zip = "$root\release\MIDI-of-Time-$ver-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $app -DestinationPath $zip
$h = (Get-FileHash $zip -Algorithm SHA256).Hash
"$h  $(Split-Path $zip -Leaf)" | Set-Content "$zip.sha256"
"Built $zip`nSHA256 $h"
