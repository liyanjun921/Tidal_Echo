# Compatible with Windows PowerShell 5.1. Save this source as ASCII.
param([ValidateSet('Start', 'Stop', 'Phone', 'Access', 'Status')][string]$Action = 'Start',
      [switch]$KeepOpenOnError)
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))

function Read-LuneEnvironment([string]$Root, [switch]$Create) {
    $path = Join-Path $Root '.env'
    if (-not (Test-Path -LiteralPath $path)) {
        if (-not $Create) { throw 'Start Lune first using Lune-Start.cmd.' }
        [IO.File]::WriteAllText($path, "RELAY_SECRET=`nLUNE_PORT=8080`n", [Text.UTF8Encoding]::new($false))
    }
    $text = [IO.File]::ReadAllText($path)
    $secrets = [regex]::Matches($text, '(?m)^RELAY_SECRET=([^\r\n]*)\r?$')
    if ($secrets.Count -ne 1) { throw 'The private .env needs exactly one RELAY_SECRET line; existing data was preserved.' }
    $secret = $secrets[0].Groups[1].Value
    if (-not $secret -and $Create) {
        $bytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $secret = ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
        $text = [regex]::Replace($text, '(?m)^RELAY_SECRET=\r?$', ('RELAY_SECRET=' + $secret))
        [IO.File]::WriteAllText($path, $text, [Text.UTF8Encoding]::new($false))
    }
    if ($secret -notmatch '^[A-Za-z0-9_+/=-]{24,}$') {
        throw 'RELAY_SECRET is empty or uses an unsupported format. Existing credentials were not replaced.'
    }
    $ports = [regex]::Matches($text, '(?m)^LUNE_PORT=([^\r\n]*)\r?$')
    if ($ports.Count -gt 1) { throw 'Duplicate LUNE_PORT values in .env.' }
    $portText = '8080'
    if ($ports.Count -eq 1) { $portText = $ports[0].Groups[1].Value }
    if ($portText -notmatch '^\d{1,5}$' -or [int]$portText -lt 1024 -or [int]$portText -gt 65535) {
        throw 'LUNE_PORT must be a number from 1024 to 65535.'
    }
    return @{ Secret = $secret; Port = [int]$portText }
}

function Find-LuneTool([string]$Name, [string[]]$Candidates) {
    $tool = Get-Command $Name -ErrorAction SilentlyContinue
    if ($tool) { return $tool.Source }
    foreach ($candidate in $Candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw "$Name was not found. Follow docs/LUNE_WINDOWS.md to install the prerequisite."
}

function Invoke-LuneNative([string]$Tool, [string[]]$Arguments) {
    # Native stderr is diagnostic output, not a PowerShell terminating error.
    $before = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = & $Tool @Arguments 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $before }
    return @{ Text = $output.Trim(); Code = $code }
}

function Get-LuneComposeArguments([string]$Root) {
    # Fixed project name keeps the same named data volume across folder renames.
    return @('compose', '--project-name', 'lune-local', '--project-directory', $Root,
             '--env-file', (Join-Path $Root '.env'),
             '-f', (Join-Path $Root 'compose.lune.yaml'),
             '-f', (Join-Path $Root 'compose.lune.local.yaml'))
}

function Write-LuneAccess([string]$Root, $Environment, [string]$PhoneUrl = '') {
    $directory = Join-Path $Root '.lune-local'
    [void][IO.Directory]::CreateDirectory($directory)
    $urlPath = Join-Path $directory 'phone-url.txt'
    if ($PhoneUrl) { [IO.File]::WriteAllText($urlPath, $PhoneUrl) }
    elseif (Test-Path -LiteralPath $urlPath) { $PhoneUrl = [IO.File]::ReadAllText($urlPath) }
    $accessPath = Join-Path $directory 'access.txt'
    $text = "PRIVATE - do not upload or share this file.`r`n`r`nComputer: http://127.0.0.1:$($Environment.Port)/`r`n"
    if ($PhoneUrl) { $text += "iPhone (Tailscale connected): $PhoneUrl`r`n" }
    $text += "API path: /relay`r`nConnection password: $($Environment.Secret)`r`n"
    [IO.File]::WriteAllText($accessPath, $text, [Text.UTF8Encoding]::new($false))
    return $accessPath
}

function Assert-LuneServeConfig($Config, [string]$HostPort, [string]$Target) {
    # A previous Funnel on this machine must never expose this private backend.
    if ($Config.AllowFunnel) {
        foreach ($entry in $Config.AllowFunnel.PSObject.Properties) {
            if ($entry.Value -ne $false) { throw 'An existing public Funnel is configured. Private phone setup stopped without changing it.' }
        }
    }
    $tcp = @($Config.TCP.PSObject.Properties | Where-Object { $_.MemberType -eq 'NoteProperty' })
    $web = @($Config.Web.PSObject.Properties | Where-Object { $_.MemberType -eq 'NoteProperty' })
    if ($Config.Services -or $Config.Foreground -or $Config.Tun) {
        throw 'Other Tailscale services exist. Setup stopped without replacing them.'
    }
    if ($tcp.Count -eq 0 -and $web.Count -eq 0) { return }
    if ($tcp.Count -ne 1 -or $tcp[0].Name -ne '443' -or $tcp[0].Value.HTTPS -ne $true -or
        $tcp[0].Value.TCPForward -or $web.Count -ne 1 -or $web[0].Name -ne $HostPort) {
        throw 'An existing Tailscale Serve configuration uses this machine. Setup stopped without replacing it.'
    }
    $handlers = @($web[0].Value.Handlers.PSObject.Properties | Where-Object { $_.MemberType -eq 'NoteProperty' })
    if ($handlers.Count -ne 1 -or $handlers[0].Name -ne '/' -or $handlers[0].Value.Proxy -ne $Target -or
        $handlers[0].Value.Path -or $handlers[0].Value.Text) {
        throw 'An existing Tailscale web route was preserved; automatic setup stopped.'
    }
}

function Start-LunePhone([string]$Root, $Environment) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host 'Approve the Windows prompt to configure private HTTPS access.'
        $quoted = '"' + $PSCommandPath + '"'
        $elevated = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $quoted, '-Action', 'Phone', '-KeepOpenOnError')
        if ($elevated.ExitCode -ne 0) { throw 'Private phone setup did not finish; rerun Lune-Phone.cmd to read its message.' }
        return
    }
    $tailscale = Find-LuneTool 'tailscale.exe' @((Join-Path $env:ProgramFiles 'Tailscale/tailscale.exe'))
    $status = Invoke-LuneNative $tailscale @('status', '--json')
    if ($status.Code -ne 0) { throw 'Open Tailscale and sign in on this computer first.' }
    $node = $status.Text | ConvertFrom-Json
    if ($node.BackendState -ne 'Running' -or -not $node.Self.DNSName) { throw 'Connect Tailscale on this computer before continuing.' }
    $hostName = $node.Self.DNSName.TrimEnd('.')
    if ($hostName -notmatch '^[a-zA-Z0-9-]+\.[a-zA-Z0-9.-]+\.ts\.net$') { throw 'No valid Tailscale HTTPS hostname was returned.' }
    $target = "http://127.0.0.1:$($Environment.Port)"
    $before = Invoke-LuneNative $tailscale @('serve', 'status', '--json')
    if ($before.Code -ne 0) { throw 'Cannot inspect existing Tailscale Serve settings. Nothing was changed.' }
    $configuration = $before.Text | ConvertFrom-Json
    Assert-LuneServeConfig $configuration ($hostName + ':443') $target
    # HTTPS may require the owner's confirmation in the browser shown by Tailscale.
    & $tailscale serve --bg --https=443 $target
    if ($LASTEXITCODE -ne 0) { throw 'HTTPS setup is incomplete. Follow the Tailscale link, then rerun Lune-Phone.cmd.' }
    $after = Invoke-LuneNative $tailscale @('serve', 'status', '--json')
    if ($after.Code -ne 0) { throw 'Unable to verify private HTTPS after setup.' }
    $verified = $after.Text | ConvertFrom-Json
    Assert-LuneServeConfig $verified ($hostName + ':443') $target
    if (-not $verified.Web) { throw 'No HTTPS route was saved.' }
    $url = 'https://' + $hostName + '/'
    $access = Write-LuneAccess $Root $Environment $url
    Write-Host "On iPhone: connect Tailscale with the same personal account, then open $url"
    Start-Process notepad.exe -ArgumentList ('"' + $access + '"')
}

function Invoke-LuneAction {
    if ($env:OS -ne 'Windows_NT') { throw 'This launcher runs on Windows. Use the Compose instructions on Linux.' }
    Set-Location -LiteralPath $ProjectRoot
    $settings = Read-LuneEnvironment $ProjectRoot -Create:($Action -eq 'Start')
    # Compose gives inherited variables priority over .env; use the same values
    # as the phone credentials and readiness URL, only in this launcher process.
    $env:RELAY_SECRET = $settings.Secret
    $env:LUNE_PORT = [string]$settings.Port
    if ($Action -eq 'Access') {
        $access = Write-LuneAccess $ProjectRoot $settings
        Start-Process notepad.exe -ArgumentList ('"' + $access + '"')
        return
    }
    if ($Action -eq 'Phone') { Start-LunePhone $ProjectRoot $settings; return }
    $docker = Find-LuneTool 'docker.exe' @(
        (Join-Path $env:ProgramFiles 'Docker/Docker/resources/bin/docker.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'))
    $engine = Invoke-LuneNative $docker @('info', '--format', '{{.OSType}}')
    if ($engine.Code -ne 0 -or $engine.Text -ne 'linux') {
        throw 'Open Docker Desktop, enable its WSL 2 Linux engine and wait for Engine running, then retry.'
    }
    $arguments = Get-LuneComposeArguments $ProjectRoot
    if ($Action -eq 'Stop') {
        & $docker @arguments stop
        if ($LASTEXITCODE -ne 0) { throw 'Docker could not stop the service.' }
        Write-Host 'Lune stopped. Its persistent data volume was kept.'
        return
    }
    if ($Action -eq 'Status') {
        & $docker @arguments ps
        if ($LASTEXITCODE -ne 0) { throw 'Docker status failed.' }
        return
    }
    Write-Host 'Building and starting Lune. First installation downloads dependencies and public model assets.'
    & $docker @arguments up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'Build/start failed. Read the error above; no data volume was removed.' }
    $ready = $false
    for ($attempt = 0; $attempt -lt 180; $attempt++) {
        try {
            $check = Invoke-RestMethod -Uri "http://127.0.0.1:$($settings.Port)/readyz" -TimeoutSec 4
            if ($check.ok -eq $true) { $ready = $true; break }
        } catch { }
        if ($attempt % 6 -eq 0) { Write-Host 'Waiting for the backend and native Latent resources...' }
        Start-Sleep -Seconds 5
    }
    if (-not $ready) { throw 'Backend did not become ready. Open the lune-local container logs in Docker Desktop.' }
    $access = Write-LuneAccess $ProjectRoot $settings
    Write-Host 'Backend ready. The private password opens in Notepad. Use Lune-Phone.cmd for iPhone HTTPS.'
    Start-Process notepad.exe -ArgumentList ('"' + $access + '"')
    Start-Process "http://127.0.0.1:$($settings.Port)/"
}

if ($MyInvocation.InvocationName -ne '.') {
    try { Invoke-LuneAction }
    catch {
        Write-Host ('Lune: ' + $_.Exception.Message) -ForegroundColor Red
        if ($KeepOpenOnError) { [void](Read-Host 'Press Enter to close') }
        exit 1
    }
}
