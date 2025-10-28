# Windows Setup Guide for Swarm

This guide helps Windows developers set up the Swarm project without common issues.

## Prerequisites

1. Python 3.11–3.13 (3.13 recommended)
2. Git for Windows with Unix line ending support
3. Poetry for dependency management

## Common Issues and Solutions

### 1. Line Ending Issues (yamllint errors)

Problem: YAML files have CRLF line endings; yamllint expects LF.

Solution:
- The project includes `.gitattributes` to enforce LF
- After cloning, run: `git add --renormalize .`
- Or convert via PowerShell:
  ```powershell
  Get-ChildItem -Path . -Include *.yml,*.yaml -Recurse | ForEach-Object {
    (Get-Content $_.FullName -Raw) -replace "`r`n","`n" | Set-Content -NoNewline $_.FullName
  }
  ```

### 2. msgpack Build Errors

Problem: msgpack may require MSVC 14+.

Solution:
- mitmproxy (which required msgpack) was removed
- If needed: `poetry update msgpack` (Windows wheels available)

### 3. Logging Configuration Errors

Problem: "Unable to configure handler 'file'".

Solution:
- File handler only created when `LOG_TO_FILE` is set
- No action needed for normal development

### 4. Pytest Permission Errors

Problem: Temp directories become locked.

Solution:
```powershell
Remove-Item -Path "$env:TEMP\pytest-of-$env:USERNAME" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path ".pytest_cache" -Recurse -Force -ErrorAction SilentlyContinue
```
Run `make clean` (project‑scoped wipe and rebuild). For a complete Docker reset on your machine, use `make clean-all` (dangerous: removes all containers/images/volumes/networks).

### 5. Docker Compose Path Issues

Solution:
- Environment variables for paths (e.g., `${PERSONAS_CONFIG_PATH:-./config/personas.yaml}`)
- Persona mounts optional (commented out by default)

## Quick Start

```powershell
# Clone the repository
git clone <repository-url>
cd swarm

# Fix line endings
git add --renormalize .

# Install dependencies
poetry install --with dev

# Run checks
make check
```

## Makefile on Windows

- Automatically detects and uses Git Bash if available
- Falls back to `sh` if Git Bash is not found
- Clean targets:
  - `make clean` — project‑scoped: compose down with volumes/images, then rebuild
  - `make clean-all` — DANGEROUS: wipes all Docker data on the machine, then rebuild

If you still have issues:
- Use Poetry commands directly: `poetry run pytest`
- Ensure Git Bash is installed in standard locations:
  - `C:\\Program Files\\Git\\bin\\bash.exe`
  - `C:\\Program Files\\Git\\usr\\bin\\bash.exe`
  - `C:\\Program Files (x86)\\Git\\bin\\bash.exe`
