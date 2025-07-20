# Windows Setup Guide for Swarm

This guide helps Windows developers set up the Swarm project without common issues.

## Prerequisites

1. **Python 3.11-3.13** (3.13 recommended)
2. **Git for Windows** with Unix line ending support
3. **Poetry** for dependency management

## Common Issues and Solutions

### 1. Line Ending Issues (yamllint errors)

**Problem**: YAML files have Windows CRLF line endings but yamllint expects Unix LF.

**Solution**: 
- The project includes `.gitattributes` to enforce LF line endings
- After cloning, run: `git add --renormalize .` 
- Then either commit or use PowerShell to convert files:
  ```powershell
  Get-ChildItem -Path . -Include *.yml,*.yaml -Recurse | ForEach-Object { 
    (Get-Content $_.FullName -Raw) -replace "`r`n","`n" | Set-Content -NoNewline $_.FullName 
  }
  ```

### 2. msgpack Build Errors

**Problem**: msgpack fails to install because it needs Microsoft Visual C++ 14.0 or greater.

**Solution**: 
- The project no longer depends on mitmproxy (which required msgpack)
- If you still get this error, run: `poetry update msgpack`
- This will install a version with pre-built Windows wheels

### 3. Logging Configuration Errors

**Problem**: Tests fail with "Unable to configure handler 'file'" error.

**Solution**: 
- This has been fixed in the codebase
- The file handler is now only created when LOG_TO_FILE environment variable is set
- No action needed for normal development

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
make check  # or poetry run pytest
```

## Environment Variables (Optional)

- `LOG_FORMAT=pretty` - Use colored console output instead of JSON
- `LOG_TO_FILE=1` - Enable file logging (creates logs/ directory)
- `LOG_FILE_PATH=custom/path.log` - Custom log file location

## Makefile on Windows

The Makefile is configured to work with Git Bash. If you have issues:
- Use Poetry commands directly: `poetry run pytest` instead of `make test`
- Or ensure Git Bash is in your PATH