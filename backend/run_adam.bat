@echo off
setlocal enabledelayedexpansion

:: ==========================================
:: CONFIGURATION (Synced with ModelConfig)
:: ==========================================
set "SERVER_HOST=127.0.0.1"
set "SERVER_PORT=8080"
set "SERVER_TIMEOUT=60"

:: Target GGUF models matching ModelConfig repo and filenames
set "MAIN_MODEL_FILE=Qwen3.5-4B-Q4_K_M.gguf"
set "MMPROJ_MODEL_FILE=mmproj-Qwen3.5-4B-BF16.gguf"
set "DRAFT_MODEL_FILE=Qwen3.5-0.8B-Q4_K_M.gguf"

set "LLAMA_SERVER_BIN=llama-server.exe"
set "PYTHON_ENV=env\Scripts\python.exe"

set "LLAMA_PID="

:: ==========================================
:: LLAMA.CPP VERBOSITY CONFIGURATION
:: ==========================================
:: Set internal llama.cpp logger level to debug
set "LLAMA_LOG_LEVEL=debug"
set "VERBOSITY_FLAGS=--verbose --log-colors auto"

:: ==========================================
:: RESOLVE MODEL PATHS (Local or HF Cache)
:: ==========================================
set "MAIN_MODEL_PATH=models\%MAIN_MODEL_FILE%"
set "MMPROJ_PATH=models\mmproj\%MMPROJ_MODEL_FILE%"
set "DRAFT_MODEL_PATH=models\drafters\%DRAFT_MODEL_FILE%"

:: ==========================================
:: 1. CHECK IF LLAMA-SERVER IS ONLINE
:: ==========================================
call :check_server_online
if "%SERVER_ONLINE%"=="1" (
    echo [1/3] llama-server is already running on %SERVER_HOST%:%SERVER_PORT%. Reusing active instance.
) else (
    echo [1/3] llama-server is offline. Initializing local instance with verbose logging...
    
    if not exist "%MAIN_MODEL_PATH%" (
        echo [ERROR] Main model file not found in ./models or HF Cache: %MAIN_MODEL_FILE%
        exit /b 1
    )

    if exist "%DRAFT_MODEL_PATH%" (
        echo [SYSTEM] Launching llama-server with draft model: %DRAFT_MODEL_FILE%
        start "" /B "%LLAMA_SERVER_BIN%" -m "%MAIN_MODEL_PATH%" --mmproj "%MMPROJ_PATH%" -md "%DRAFT_MODEL_PATH%" --cache-type-k q4_0 --cache-type-v q4_0 --spec-draft-n-max 16 --host %SERVER_HOST% --port %SERVER_PORT% -c 50000 -ngl -1 --flash-attn on %VERBOSITY_FLAGS% > llama_server.log 2>&1
    ) else (
        echo [WARNING] Draft model not found. Running standalone main model...
        start "" /B "%LLAMA_SERVER_BIN%" -m "%MAIN_MODEL_PATH%" --mmproj "%MMPROJ_PATH%" --cache-type-k q4_0 --cache-type-v q4_0 --host %SERVER_HOST% --port %SERVER_PORT% -c 50000 -ngl -1 --flash-attn on %VERBOSITY_FLAGS% > llama_server.log 2>&1
    )

    echo [SYSTEM] Waiting for model weights to load into VRAM...
    set "RETRY_COUNT=0"
    
    :WAIT_LOOP
    timeout /t 2 /nobreak > nul
    call :check_server_online
    if "%SERVER_ONLINE%"=="1" (
        echo [SYSTEM] llama-server is online and ready!
        goto :RUN_PYTHON
    )
    
    set /a RETRY_COUNT+=2
    if !RETRY_COUNT! geq %SERVER_TIMEOUT% (
        echo [ERROR] Timed out after %SERVER_TIMEOUT%s waiting for llama-server. Check llama_server.log.
        goto :CLEANUP
    )
    goto :WAIT_LOOP
)

:RUN_PYTHON
echo [2/3] Launching Adam pipeline (src.main)...
echo --------------------------------------------------------

:: Check and fix pyvenv.cfg if virtualenv home path is invalid
if exist "env\pyvenv.cfg" (
    powershell -NoProfile -Command "$cfg = 'env\pyvenv.cfg'; $content = Get-Content $cfg; $homeLine = $content | Where-Object { $_ -match 'home\s*=\s*(.*)' }; if ($homeLine -match 'home\s*=\s*(.*)') { $homePath = $Matches[1].Trim(); $isValid = (Test-Path $homePath) -and (-not ($homePath -like '*WindowsApps*')) -and (Test-Path (Join-Path $homePath 'python.exe')); if (-not $isValid) { Write-Host '[SYSTEM] Virtualenv home path is invalid or missing python.exe. Patching pyvenv.cfg...'; $pyPath = @(Get-Command python.exe -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*WindowsApps*' })[0].Source; if ($pyPath) { $pyHome = Split-Path $pyPath; $newContent = $content | ForEach-Object { if ($_ -match '^home\s*=') { 'home = ' + $pyHome } elseif ($_ -match '^executable\s*=') { 'executable = ' + $pyPath } elseif ($_ -match '^command\s*=') { 'command = ' + $pyPath + ' -m venv env' } else { $_ } }; $newContent | Set-Content $cfg; Write-Host '[SYSTEM] Successfully patched pyvenv.cfg.'; } else { Write-Host '[WARNING] System python.exe not found to patch virtualenv.'; } } }"
)

:: Execute as a module to fix 'No module named config' error
set "PYTHONPATH=.;env\Lib\site-packages"
"%PYTHON_ENV%" -m src.main

echo --------------------------------------------------------
echo [3/3] Python execution finished.

:: ==========================================
:: 3. CLEANUP & SHUTDOWN
:: ==========================================
:CLEANUP
echo [SYSTEM] Shutting down Adam ecosystem...
if defined LLAMA_PID (
    echo [SYSTEM] Stopping spawned llama-server process ^(PID: %LLAMA_PID%^)...
    taskkill /F /PID %LLAMA_PID% > nul 2>&1
) else (
    echo [SYSTEM] Ensuring background llama-server processes are closed...
    taskkill /F /IM %LLAMA_SERVER_BIN% > nul 2>&1
)
echo [SYSTEM] Cleanup complete.
exit /b 0

:: ==========================================
:: HELPER: HEALTH CHECK VIA POWERSHELL
:: ==========================================
:check_server_online
set "SERVER_ONLINE=0"
for /f "usebackq tokens=*" %%A in (`powershell -NoProfile -Command "try { $res = Invoke-WebRequest -Uri 'http://%SERVER_HOST%:%SERVER_PORT%/health' -TimeoutSec 2 -UseBasicParsing; if ($res.StatusCode -eq 200) { 'ONLINE' } } catch { 'OFFLINE' }"`) do (
    if "%%A"=="ONLINE" set "SERVER_ONLINE=1"
)

if "%SERVER_ONLINE%"=="1" (
    for /f "tokens=2 delims=," %%P in ('wmic process where "name='%LLAMA_SERVER_BIN%'" get ProcessId /format:csv 2^>nul ^| findstr /r "[0-9]"') do (
        set "LLAMA_PID=%%P"
    )
)
exit /b