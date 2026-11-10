<#
.SYNOPSIS
    Allow (or remove) the inbound LAN rule for the media controller.

.DESCRIPTION
    Adds an inbound TCP rule for the requested port, scoped to LocalSubnet so
    devices outside the local network cannot reach it.

    The app has no authentication, so keep this on trusted networks. The
    Ethernet/Wi-Fi adapter must either be on the Private profile, or you can
    deliberately use -Profile Any to allow the port on the current profile
    (for example when Windows marks a home network as Public).

    Run from an elevated PowerShell (Run as administrator).

.EXAMPLE
    .\allow_firewall.ps1
    .\allow_firewall.ps1 -Profile Any
    .\allow_firewall.ps1 -Remove
#>
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8722,

    [ValidateSet("Private", "Public", "Domain", "Any")]
    [string]$Profile = "Private",

    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$ruleName = "ESP32 Media Controller ($Port)"

$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "This script must run from an elevated PowerShell." -ForegroundColor Red
    Write-Host "Right-click PowerShell and choose 'Run as administrator', then:"
    Write-Host "  cd `"$PSScriptRoot\..`""
    Write-Host "  .\scripts\allow_firewall.ps1 -Profile Any"
    exit 1
}

if ($Remove) {
    $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if ($existing) {
        Remove-NetFirewallRule -DisplayName $ruleName
        Write-Host "Removed firewall rule: $ruleName"
    } else {
        Write-Host "No firewall rule named '$ruleName' found."
    }
    exit 0
}

$activeProfiles = @(
    Get-NetConnectionProfile -ErrorAction SilentlyContinue |
        ForEach-Object { $_.NetworkCategory.ToString() } |
        Sort-Object -Unique
)
if ($activeProfiles.Count -gt 0) {
    Write-Host "Active network profile(s): $($activeProfiles -join ', ')"
}
if ($Profile -ne "Any" -and $activeProfiles -notcontains $Profile) {
    Write-Warning "The rule will apply to '$Profile' only, but the active profile is '$($activeProfiles -join ', ')'."
    Write-Warning "Either mark the network Private or run: .\allow_firewall.ps1 -Profile Any"
}

# Recreate the rule so profile/scope changes always take effect.
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Remove-NetFirewallRule -DisplayName $ruleName
}

New-NetFirewallRule `
    -DisplayName $ruleName `
    -Description "Phone/LAN access to the ESP32 media controller (local subnet only)" `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $Port `
    -RemoteAddress LocalSubnet `
    -Profile $Profile | Out-Null

Write-Host "Created firewall rule: $ruleName"
Write-Host "  TCP $Port, profile: $Profile, remote: LocalSubnet"
Write-Host ""
Write-Host "If the phone still cannot connect:"
Write-Host "  1. Make sure the PC and phone are on the same Wi-Fi/LAN (no guest isolation)."
Write-Host "  2. Use the LAN URL printed by the app, not 127.0.0.1."
Write-Host "  3. Check that the app is running (tray icon / listening on port $Port)."
