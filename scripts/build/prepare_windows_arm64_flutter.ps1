$ErrorActionPreference = 'Stop'

# flutter-action's CACHE-PATH is a cache container; FLUTTER_ROOT is the SDK.
if ([string]::IsNullOrWhiteSpace($env:FLUTTER_ROOT)) {
    throw 'FLUTTER_ROOT is missing; Flutter setup must run first'
}
$sdk = (Resolve-Path -LiteralPath $env:FLUTTER_ROOT).Path
foreach ($relative in @('bin/internal/update_dart_sdk.ps1', 'bin/dart.bat', 'bin/flutter.bat')) {
    if (!(Test-Path -LiteralPath (Join-Path $sdk $relative) -PathType Leaf)) {
        throw "Flutter SDK entry point missing under FLUTTER_ROOT: $relative"
    }
}

Remove-Item -Force "$sdk/bin/cache/engine-dart-sdk.stamp" -ErrorAction SilentlyContinue
& "$sdk/bin/internal/update_dart_sdk.ps1"
if ($LASTEXITCODE -ne 0) { throw 'Native Dart installation failed' }

$dart = & "$sdk/bin/dart.bat" --version 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { throw 'Native Dart version check failed' }
if ($dart -notmatch 'windows_arm64') { throw 'Dart is not native ARM64' }

& "$sdk/bin/flutter.bat" precache --windows
if ($LASTEXITCODE -ne 0) { throw 'Native engine precache failed' }
$engine = "$sdk/bin/cache/artifacts/engine/windows-arm64-release/flutter_windows.dll"
if (!(Test-Path -LiteralPath $engine -PathType Leaf)) { throw 'Native ARM64 engine missing' }
$hash = (Get-FileHash $engine -Algorithm SHA256).Hash.ToLowerInvariant()
"ENGINE_LIBRARY_SHA256=$hash" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
