$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot '../scripts/windows/emoi.ps1'
$tokens = $null
$errors = $null
[void][Management.Automation.Language.Parser]::ParseFile($script, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
. $script

function Expect-Blocked([scriptblock]$Call) {
    $blocked = $false
    try { & $Call } catch { $blocked = $true }
    if (-not $blocked) { throw 'Expected unsafe/conflicting state to be rejected.' }
}

$temporary = Join-Path ([IO.Path]::GetTempPath()) ('emoi-launcher-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($temporary)
try {
    $first = Read-EmoiEnvironment $temporary -Create
    if ($first.Secret -notmatch '^[a-f0-9]{64}$' -or $first.Port -ne 8080) { throw 'Invalid first-run credentials.' }
    $second = Read-EmoiEnvironment $temporary -Create
    if ($first.Secret -ne $second.Secret) { throw 'Restart rotated existing credentials.' }
    $envPath = Join-Path $temporary '.env'
    $saved = [IO.File]::ReadAllText($envPath)
    $access = Write-EmoiAccess $temporary $second 'https://test.tail123.ts.net/'
    if (-not [IO.File]::ReadAllText($access).Contains($first.Secret)) { throw 'Private access file omitted the password.' }
    $access = Write-EmoiAccess $temporary $second
    if (-not [IO.File]::ReadAllText($access).Contains('https://test.tail123.ts.net/')) { throw 'Restart forgot the phone URL.' }
    [IO.File]::WriteAllText($envPath, $saved + "RELAY_SECRET=conflict`n")
    Expect-Blocked { Read-EmoiEnvironment $temporary -Create }
    if (-not [IO.File]::ReadAllText($envPath).Contains('RELAY_SECRET=conflict')) { throw 'Conflicting configuration was overwritten.' }
    [IO.File]::WriteAllText($envPath, $saved.Replace('EMOI_PORT=8080', 'EMOI_PORT=80'))
    Expect-Blocked { Read-EmoiEnvironment $temporary }
    [IO.File]::WriteAllText($envPath, $saved.Replace('EMOI_PORT=8080', 'EMOI_PORT=8080;whoami'))
    Expect-Blocked { Read-EmoiEnvironment $temporary }
    [IO.File]::WriteAllText($envPath, "RELAY_SECRET=short`nEMOI_PORT=8080`n")
    Expect-Blocked { Read-EmoiEnvironment $temporary -Create }
    if ([IO.File]::ReadAllText($envPath) -notmatch 'RELAY_SECRET=short') { throw 'Existing invalid secret was silently replaced.' }
    $arguments = @(Get-EmoiComposeArguments (Join-Path $temporary 'folder with spaces'))
    if ($arguments[2] -ne 'emoi-local' -or $arguments -contains 'down' -or $arguments -contains '-v') { throw 'Unstable/destructive Compose arguments.' }
    $target = 'http://127.0.0.1:8080'
    $hostPort = 'test.tail123.ts.net:443'
    Assert-EmoiServeConfig ('{}' | ConvertFrom-Json) $hostPort $target
    $ours = '{"TCP":{"443":{"HTTPS":true}},"Web":{"test.tail123.ts.net:443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:8080"}}}}}'
    Assert-EmoiServeConfig ($ours | ConvertFrom-Json) $hostPort $target
    $privateOnly = $ours | ConvertFrom-Json
    $privateOnly | Add-Member -NotePropertyName 'AllowFunnel' -NotePropertyValue ([pscustomobject]@{ 'test.tail123.ts.net:443' = $false })
    Assert-EmoiServeConfig $privateOnly $hostPort $target
    Expect-Blocked { Assert-EmoiServeConfig ('{"AllowFunnel":{"test.tail123.ts.net:443":true}}' | ConvertFrom-Json) $hostPort $target }
    Expect-Blocked { Assert-EmoiServeConfig (($ours.Replace('http://127.0.0.1:8080', 'http://127.0.0.1:9000')) | ConvertFrom-Json) $hostPort $target }
    Expect-Blocked { Assert-EmoiServeConfig (($ours.Replace('"/":', '"/other":')) | ConvertFrom-Json) $hostPort $target }
    Expect-Blocked { Assert-EmoiServeConfig ('{"Services":{"svc:foreign":{"TCP":{"443":{"HTTPS":true}}}}}' | ConvertFrom-Json) $hostPort $target }
    Expect-Blocked { Assert-EmoiServeConfig ('{"TCP":{"443":{"TCPForward":"127.0.0.1:9000"}}}' | ConvertFrom-Json) $hostPort $target }
    $fixture = Join-Path $temporary 'native-fixture.cmd'
    [IO.File]::WriteAllText($fixture, "@echo off`r
echo fixture diagnostic 1>&2`r
exit /b 7`r
", [Text.Encoding]::ASCII)
    $cmd = Join-Path $env:WINDIR 'System32/cmd.exe'
    $native = Invoke-EmoiNative $cmd @('/d', '/c', ('"' + $fixture + '"'))
    if ($native.Code -ne 7 -or -not $native.Text.Contains('fixture diagnostic')) {
        throw ('Native failure was hidden or lost its exit status. Code=' + $native.Code + '; Output=' + $native.Text)
    }
    # The GitHub PowerShell runner propagates LASTEXITCODE after dot-sourcing this test.
    $global:LASTEXITCODE = 0
    Write-Host 'PASS: syntax; persistent random credentials; private access file; port validation; stable volume project; private HTTPS guards.'
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
