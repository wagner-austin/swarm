# Update Fly.io BOT_SECRET_PERSONAS secret from local personas.yaml (Windows PowerShell)
# 1. Copies the operator personas file into the project root for convenience
# 2. Reads its contents into a string
# 3. Uploads the contents to Fly as the BOT_SECRET_PERSONAS secret

# Stop on first error
$ErrorActionPreference = 'Stop'

Write-Host "🚀  Updating personas secret on Fly.io (PowerShell)…"

# Path to the operator-maintained personas file
$source = Join-Path $Env:USERPROFILE ".config\discord-bot\secrets\personas.yaml"
$dest   = "personas.yaml"

if (!(Test-Path $source)) {
    Write-Error "❌ Personas file not found: $source"
    exit 1
}

Copy-Item -Path $source -Destination $dest -Force

# Read entire YAML file as a single string
$yaml = Get-Content -Raw $dest

if ([string]::IsNullOrWhiteSpace($yaml)) {
    Write-Error "❌ Personas file is empty: $dest"
    exit 1
}

# Unset previous secret (ignore errors) then set new value
fly secrets unset BOT_SECRET_PERSONAS 2>$null | Out-Null
fly secrets set BOT_SECRET_PERSONAS="$yaml"

# Clean up local copy – we don't want to keep the file in the repo
Remove-Item -Path $dest -ErrorAction SilentlyContinue

Write-Host "✅  Personas secret updated successfully (temporary file removed)."
