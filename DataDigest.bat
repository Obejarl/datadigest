@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
TITLE DataDigest  -  Launcher

:: ============================================================================
::  DataDigest launcher: installs the Python environment, starts the app and
::  opens the dashboard. Double-click for the menu, or run a command directly:
::
::    DataDigest.bat                 menu
::    DataDigest.bat start           install if needed, start, open the panel
::    DataDigest.bat start --no-browser
::    DataDigest.bat docker          full stack with Docker Compose
::    DataDigest.bat monitoring      Docker stack + Prometheus + Grafana
::    DataDigest.bat demo            load sample datasets and optimization examples
::    DataDigest.bat health          pre-flight checks
::    DataDigest.bat test            run the test suite
::    DataDigest.bat stop            stop the local server and the Docker stack
:: ============================================================================

:: ── ESC character for ANSI colours ──
for /F "tokens=1,2 delims=#" %%a in ('"prompt #$H#$E# & echo on & for %%b in (1) do rem"') do set "ESC=%%b"

:: ── Palette (same as the web dashboard) ──
set "R=%ESC%[0m"
set "B=%ESC%[1m"
set "D=%ESC%[2m"
set "WH=%ESC%[38;2;230;237;243m"
set "GR=%ESC%[38;2;147;161;180m"
set "CY=%ESC%[38;2;34;211;238m"
set "VI=%ESC%[38;2;167;139;250m"
set "GN=%ESC%[38;2;16;227;154m"
set "YL=%ESC%[38;2;255;200;87m"
set "RD=%ESC%[38;2;255;77;109m"
set "G1=%ESC%[38;2;34;211;238m"
set "G2=%ESC%[38;2;70;196;240m"
set "G3=%ESC%[38;2;105;180;243m"
set "G4=%ESC%[38;2;135;163;246m"
set "G5=%ESC%[38;2;157;148;249m"
set "G6=%ESC%[38;2;167;139;250m"
set "BG_C=%ESC%[48;2;8;110;130m%WH%%B%"
set "BG_V=%ESC%[48;2;88;64;170m%WH%%B%"
set "BG_G=%ESC%[48;2;6;120;80m%WH%%B%"
set "BG_Y=%ESC%[48;2;150;105;0m%WH%%B%"
set "BG_R=%ESC%[48;2;150;25;50m%WH%%B%"

:: ── Paths and settings ──
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "VPY=%VENV_DIR%\Scripts\python.exe"
set "REQ_FILE=%PROJECT_DIR%\requirements.txt"
set "LOG_DIR=%PROJECT_DIR%\logs"
set "LOG_FILE=%LOG_DIR%\api.log"
set "PORT=8000"
set "API_URL=http://localhost:%PORT%"
:: Checks use 127.0.0.1: Windows resolves "localhost" to IPv6 first, the local server listens on
:: IPv4 only, and PowerShell 5.1 burns its whole timeout on the IPv6 attempt instead of falling back.
set "CHECK_URL=http://127.0.0.1:%PORT%"
set "GRAFANA_URL=http://localhost:3000/d/datadigest"
set "OPEN_BROWSER=1"
cd /d "%PROJECT_DIR%"

:: ── Command-line mode (no menu) ──
if /i "%~2"=="--no-browser" set "OPEN_BROWSER=0"
if /i "%~1"=="start"      ( call :DO_START      & exit /b !ERRORLEVEL! )
if /i "%~1"=="docker"     ( call :DO_DOCKER     & exit /b !ERRORLEVEL! )
if /i "%~1"=="monitoring" ( call :DO_MONITORING & exit /b !ERRORLEVEL! )
if /i "%~1"=="demo"       ( call :DO_DEMO       & exit /b !ERRORLEVEL! )
if /i "%~1"=="health"     ( call :DO_HEALTH     & exit /b !ERRORLEVEL! )
if /i "%~1"=="test"       ( call :DO_TEST       & exit /b !ERRORLEVEL! )
if /i "%~1"=="stop"       ( call :DO_STOP       & exit /b !ERRORLEVEL! )
if not "%~1"=="" (
    echo  %RD%Bilinmeyen komut:%R% %~1
    echo  %GR%Kullanim: DataDigest.bat [start^|docker^|monitoring^|demo^|health^|test^|stop] [--no-browser]%R%
    exit /b 2
)
mode con: cols=110 lines=46 >nul 2>&1
goto :BOOT

::==========================================================================
:BOOT
::==========================================================================
cls
echo.
echo.
echo %G1%    ██████╗  █████╗ ████████╗ █████╗ ██████╗ ██╗ ██████╗ ███████╗███████╗████████╗%R%
echo %G2%    ██╔══██╗██╔══██╗╚══██╔══╝██╔══██╗██╔══██╗██║██╔════╝ ██╔════╝██╔════╝╚══██╔══╝%R%
echo %G3%    ██║  ██║███████║   ██║   ███████║██║  ██║██║██║  ███╗█████╗  ███████╗   ██║   %R%
echo %G4%    ██║  ██║██╔══██║   ██║   ██╔══██║██║  ██║██║██║   ██║██╔══╝  ╚════██║   ██║   %R%
echo %G5%    ██████╔╝██║  ██║   ██║   ██║  ██║██████╔╝██║╚██████╔╝███████╗███████║   ██║   %R%
echo %G6%    ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═════╝ ╚═╝ ╚═════╝ ╚══════╝╚══════╝   ╚═╝   %R%
echo.
echo                   %GR%Data quality  ·  Operations research  ·  Queueing theory%R%
echo.
<nul set /p "_=    "
for /L %%A in (1,1,40) do (
    <nul set /p "_=%CY%▰%R%"
    ping -n 1 127.0.0.1 >nul
)
echo  %GN%hazir%R%
ping -n 2 127.0.0.1 >nul
goto :MAIN_MENU

::==========================================================================
:MAIN_MENU
::==========================================================================
cls
TITLE DataDigest  -  Launcher
call :GET_STATUS
for /f "usebackq delims=" %%d in (`powershell -NoProfile -InputFormat None -Command "Get-Date -Format 'dd.MM.yyyy HH:mm'"`) do set "NOW=%%d"
echo.
echo %CY%  ╔════════════════════════════════════════════════════════════════════════════╗%R%
echo %CY%  ║ %WH%%B%DataDigest%R%  %D%%GR%//%R%  %VI%CSV profilleme · Optimizasyon · Kapasite planlama%R%          %CY%║%R%
echo %CY%  ╠════════════════════════════════════════════════════════════════════════════╣%R%
echo %CY%  ║ %GR%PANEL  :%R% %CY%%API_URL%%R%          %GR%TARIH :%R% %WH%%NOW%%R%           %CY%║%R%
echo %CY%  ╚════════════════════════════════════════════════════════════════════════════╝%R%
echo    %D%%GR%Klasor: %PROJECT_DIR%%R%
echo.
if "%APP_ONLINE%"=="1" (
    echo    %BG_G% CALISIYOR %R%  %CY%%STATUS_LINE%%R%
) else (
    echo    %BG_R% KAPALI %R%  %GR%Sunucu calismiyor. Baslatmak icin [1].%R%
)
echo.
echo      %BG_C% [ 1 ] %R%  %CY%%B%KUR VE BASLAT%R%        %GR%Python ortamini kurar, sunucuyu baslatir, paneli acar%R%
echo      %BG_C% [ 2 ] %R%  %CY%DOCKER: TAM SISTEM%R%   %GR%PostgreSQL + Redis + 2 worker  (Docker Desktop gerekir)%R%
echo      %BG_C% [ 3 ] %R%  %CY%DOCKER + IZLEME%R%      %GR%Ayrica Prometheus ve Grafana panosu%R%
echo.
echo      %BG_V% [ 4 ] %R%  %VI%PANELI AC%R%            %GR%%API_URL% tarayicida%R%
echo      %BG_V% [ 5 ] %R%  %VI%ORNEK VERI%R%           %GR%2 ornek veri seti + 4 optimizasyon ornegi yukler%R%
echo.
echo      %BG_Y% [ 6 ] %R%  %YL%SAGLIK KONTROLU%R%      %GR%Python, ortam, port, Docker, WSL%R%
echo      %BG_Y% [ 7 ] %R%  %YL%TESTLER%R%              %GR%pytest ile tum testleri calistirir%R%
echo      %BG_Y% [ 8 ] %R%  %YL%CANLI LOG%R%            %GR%Yerel sunucunun logunu izler (CTRL+C ile cik)%R%
echo.
echo      %BG_R% [ 9 ] %R%  %RD%DURDUR%R%               %GR%Yerel sunucuyu ve Docker sistemini kapatir%R%
echo      %BG_R% [ 0 ] %R%  %RD%CIKIS%R%
echo.
set "choice="
set /p "choice=  %CY%>>> %R% "
if "%choice%"=="1" ( call :DO_START      & goto :AFTER_ACTION )
if "%choice%"=="2" ( call :DO_DOCKER     & goto :AFTER_ACTION )
if "%choice%"=="3" ( call :DO_MONITORING & goto :AFTER_ACTION )
if "%choice%"=="4" ( call :OPEN_PANEL    & goto :AFTER_ACTION )
if "%choice%"=="5" ( call :DO_DEMO       & goto :AFTER_ACTION )
if "%choice%"=="6" ( call :DO_HEALTH     & goto :AFTER_ACTION )
if "%choice%"=="7" ( call :DO_TEST       & goto :AFTER_ACTION )
if "%choice%"=="8" ( call :DO_LOGS       & goto :MAIN_MENU )
if "%choice%"=="9" ( call :DO_STOP       & goto :AFTER_ACTION )
if "%choice%"=="0" goto :EXIT_APP
goto :MAIN_MENU

:AFTER_ACTION
echo.
echo  %D%%GR%Menuye donmek icin bir tusa basin...%R%
pause >nul
goto :MAIN_MENU

::==========================================================================
:GET_STATUS
::==========================================================================
:: APP_ONLINE=1 and a one-line summary when DataDigest answers on the port.
set "APP_ONLINE=0"
set "STATUS_LINE="
for /f "usebackq delims=" %%s in (`powershell -NoProfile -InputFormat None -Command "try { $s = Invoke-RestMethod -Uri '%CHECK_URL%/api/stats' -TimeoutSec 3 -ErrorAction Stop; $q = if ($null -eq $s.avg_quality) { '-' } else { [math]::Round($s.avg_quality) }; Write-Output ('Veri seti: ' + $s.datasets + '   Ortalama kalite: ' + $q + '   Mod: ' + $s.mode) } catch { try { $a = Invoke-RestMethod -Uri '%CHECK_URL%/api/auth/status' -TimeoutSec 3 -ErrorAction Stop; if ($a.required) { Write-Output 'Calisiyor (giris anahtari gerekli: ACCESS_TOKEN)' } } catch {} }" 2^>nul`) do (
    set "STATUS_LINE=%%s"
    set "APP_ONLINE=1"
)
goto :EOF

::==========================================================================
:STEP
::==========================================================================
:: call :STEP "message"  -> prints an aligned step line
echo  %CY%[ .. ]%R% %WH%%~1%R%
goto :EOF

::==========================================================================
:FIND_PYTHON
::==========================================================================
:: SYS_PY = a Python 3.13+ interpreter, or empty.
set "SYS_PY="
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 13) else 1)" >nul 2>&1 && set "SYS_PY=python"
if not defined SYS_PY (
    py -3.13 -c "import sys" >nul 2>&1 && set "SYS_PY=py -3.13"
)
goto :EOF

::==========================================================================
:INSTALL
::==========================================================================
:: Creates .venv, installs requirements only when they changed, migrates the database.
call :FIND_PYTHON
if not defined SYS_PY (
    echo  %RD%[ X  ]%R% %WH%Python 3.13 veya ustu bulunamadi.%R%
    echo         %GR%https://www.python.org/downloads/ adresinden kurup "Add to PATH" secin.%R%
    exit /b 1
)
for /f "usebackq delims=" %%v in (`%SYS_PY% --version 2^>^&1`) do set "PYVER=%%v"
echo  %GN%[ OK ]%R% %WH%%PYVER%%R% %D%%GR%(%SYS_PY%)%R%

if not exist "%VPY%" (
    call :STEP "Sanal ortam olusturuluyor (.venv)..."
    %SYS_PY% -m venv "%VENV_DIR%"
    if errorlevel 1 ( echo  %RD%[ X  ]%R% Sanal ortam olusturulamadi. & exit /b 1 )
)
echo  %GN%[ OK ]%R% %WH%Sanal ortam hazir%R%

set "REQ_HASH="
for /f "usebackq delims=" %%h in (`powershell -NoProfile -InputFormat None -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath '%REQ_FILE%').Hash"`) do set "REQ_HASH=%%h"
set "OLD_HASH="
if exist "%VENV_DIR%\.req-hash" set /p OLD_HASH=<"%VENV_DIR%\.req-hash"
if /i "%REQ_HASH%"=="%OLD_HASH%" (
    echo  %GN%[ OK ]%R% %WH%Bagimliliklar guncel%R% %D%%GR%^(requirements.txt degismedi^)%R%
) else (
    call :STEP "Bagimliliklar kuruluyor (ilk seferde birkac dakika surebilir)..."
    "%VPY%" -m pip install --disable-pip-version-check -q -r "%REQ_FILE%"
    if errorlevel 1 ( echo  %RD%[ X  ]%R% pip install basarisiz. Internet baglantisini kontrol edin. & exit /b 1 )
    >"%VENV_DIR%\.req-hash" echo %REQ_HASH%
    echo  %GN%[ OK ]%R% %WH%Bagimliliklar kuruldu%R%
)

call :STEP "Veritabani guncelleniyor (alembic upgrade head)..."
"%VPY%" -m alembic upgrade head >"%TEMP%\dd_migrate.log" 2>&1
if errorlevel 1 (
    echo  %RD%[ X  ]%R% Migration basarisiz:
    type "%TEMP%\dd_migrate.log"
    exit /b 1
)
echo  %GN%[ OK ]%R% %WH%Veritabani guncel%R%
exit /b 0

::==========================================================================
:WAIT_READY
::==========================================================================
:: call :WAIT_READY seconds  -> errorlevel 0 when /readyz answers 200
powershell -NoProfile -InputFormat None -Command "for ($i = 0; $i -lt %~1; $i++) { try { $r = Invoke-WebRequest -UseBasicParsing -Uri '%CHECK_URL%/readyz' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Seconds 1 }; exit 1"
exit /b %ERRORLEVEL%

::==========================================================================
:PORT_STATE
::==========================================================================
:: PORT_STATE = FREE / DATADIGEST / OTHER
set "PORT_STATE=FREE"
powershell -NoProfile -InputFormat None -Command "if (Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if errorlevel 1 (
    set "PORT_STATE=OTHER"
    call :GET_STATUS
    if "!APP_ONLINE!"=="1" set "PORT_STATE=DATADIGEST"
)
goto :EOF

::==========================================================================
:DO_START
::==========================================================================
echo.
echo %CY%  ╔════════════════════════════════════════════════════════════════════════════╗%R%
echo %CY%  ║ %WH%%B%KUR VE BASLAT%R%  %GR%yerel mod: SQLite, Redis gerekmez%R%                           %CY%║%R%
echo %CY%  ╚════════════════════════════════════════════════════════════════════════════╝%R%
echo.
call :PORT_STATE
if "%PORT_STATE%"=="DATADIGEST" (
    echo  %GN%[ OK ]%R% %WH%DataDigest zaten calisiyor%R% %D%%GR%^(%API_URL%^)%R%
    call :OPEN_PANEL
    exit /b 0
)
if "%PORT_STATE%"=="OTHER" (
    echo  %RD%[ X  ]%R% %WH%Port %PORT% baska bir uygulama tarafindan kullaniliyor.%R%
    echo         %GR%O uygulamayi kapatin ya da [6] Saglik kontrolu ile hangisi oldugunu gorun.%R%
    exit /b 1
)
call :INSTALL
if errorlevel 1 exit /b 1

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
call :STEP "Sunucu baslatiliyor (arka planda, log: logs\api.log)..."
:: Win32_Process.Create starts the server fully detached: no inherited handles, hidden window,
:: and it keeps running after this window closes ([9] stops it). Quotes and the greater-than sign are built with
:: [char] so cmd.exe does not interpret them while reading this line.
powershell -NoProfile -InputFormat None -Command "$q = [char]34; $gt = [char]62; $cl = 'cmd /c ' + $q + $q + '%VPY%' + $q + ' -m uvicorn datadigest.api.main:app --host 127.0.0.1 --port %PORT% ' + $gt + $q + '%LOG_FILE%' + $q + ' 2' + $gt + '&1' + $q; $si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }; $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cl; CurrentDirectory = '%PROJECT_DIR%'; ProcessStartupInformation = $si }; exit $r.ReturnValue"
<nul set /p "=  %CY%[ .. ]%R% %GR%Sunucunun hazir olmasi bekleniyor%R% "
call :WAIT_READY 45
if errorlevel 1 (
    echo.
    echo  %RD%[ X  ]%R% %WH%Sunucu 45 saniyede hazir olmadi. Son log satirlari:%R%
    powershell -NoProfile -InputFormat None -Command "Get-Content -LiteralPath '%LOG_FILE%' -Tail 15 -ErrorAction SilentlyContinue"
    exit /b 1
)
echo %GN%hazir%R%
echo  %GN%[ OK ]%R% %WH%DataDigest calisiyor:%R% %CY%%API_URL%%R%
call :OPEN_PANEL
exit /b 0

::==========================================================================
:OPEN_PANEL
::==========================================================================
if "%OPEN_BROWSER%"=="0" (
    echo  %D%%GR%[ -- ] Tarayici acilmadi ^(--no-browser^)%R%
    goto :EOF
)
echo  %CY%[ ^>^> ]%R% %WH%Panel aciliyor:%R% %CY%%API_URL%%R%
start "" "%API_URL%"
goto :EOF

::==========================================================================
:DOCKER_READY
::==========================================================================
:: errorlevel 0 when the Docker engine answers; tries to start Docker Desktop once.
docker info >nul 2>&1
if not errorlevel 1 exit /b 0
where docker >nul 2>&1
if errorlevel 1 (
    echo  %RD%[ X  ]%R% %WH%Docker bulunamadi.%R% %GR%Docker Desktop'i kurun: winget install -e --id Docker.DockerDesktop%R%
    exit /b 1
)
powershell -NoProfile -InputFormat None -Command "$o = (wsl.exe --status 2>&1 | Out-String) -replace [char]0, ''; if ($o -match 'not enabled') { exit 1 } else { exit 0 }"
if errorlevel 1 (
    echo  %RD%[ X  ]%R% %WH%WSL2 calisamiyor: sanallastirma etkin degil.%R%
    echo         %GR%WSL kurulumundan sonra bilgisayar henuz yeniden baslatilmadi. Yeniden baslatip tekrar deneyin.%R%
    echo         %GR%O zamana kadar [1] ile yerel modda calisabilirsiniz.%R%
    exit /b 1
)
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
    call :STEP "Docker Desktop baslatiliyor..."
    start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
)
<nul set /p "=  %CY%[ .. ]%R% %GR%Docker motoru bekleniyor (en fazla 2 dakika)%R% "
for /L %%i in (1,1,60) do (
    docker info >nul 2>&1
    if not errorlevel 1 ( echo %GN%hazir%R% & exit /b 0 )
    <nul set /p "=."
    ping -n 3 127.0.0.1 >nul
)
echo.
echo  %RD%[ X  ]%R% %WH%Docker motoru baslamadi. Docker Desktop penceresini kontrol edin.%R%
exit /b 1

::==========================================================================
:DO_DOCKER
::==========================================================================
set "_PROFILE="
set "_TITLE=DOCKER: TAM SISTEM"
goto :_DOCKER_UP

:DO_MONITORING
set "_PROFILE=--profile monitoring"
set "_TITLE=DOCKER + IZLEME   "

:_DOCKER_UP
echo.
echo %CY%  ╔════════════════════════════════════════════════════════════════════════════╗%R%
echo %CY%  ║ %WH%%B%%_TITLE%%R%  %GR%PostgreSQL, Redis, migration, API, 2 worker%R%            %CY%║%R%
echo %CY%  ╚════════════════════════════════════════════════════════════════════════════╝%R%
echo.
call :DOCKER_READY
if errorlevel 1 exit /b 1
call :PORT_STATE
if "%PORT_STATE%"=="DATADIGEST" (
    echo  %YL%[WARN]%R% %WH%Yerel sunucu port %PORT%'u kullaniyor; Docker icin once o durduruluyor.%R%
    call :STOP_LOCAL
)
call :STEP "Imaj derleniyor ve servisler baslatiliyor (ilk seferde birkac dakika)..."
docker compose %_PROFILE% up -d --build
if errorlevel 1 ( echo  %RD%[ X  ]%R% docker compose basarisiz. & exit /b 1 )
<nul set /p "=  %CY%[ .. ]%R% %GR%API bekleniyor%R% "
call :WAIT_READY 120
if errorlevel 1 (
    echo.
    echo  %RD%[ X  ]%R% %WH%API hazir olmadi.%R% %GR%Loglar: docker compose logs api%R%
    exit /b 1
)
echo %GN%hazir%R%
docker compose %_PROFILE% ps
call :OPEN_PANEL
if defined _PROFILE if "%OPEN_BROWSER%"=="1" (
    echo  %CY%[ ^>^> ]%R% %WH%Grafana aciliyor:%R% %CY%%GRAFANA_URL%%R% %D%%GR%^(kullanici: admin / sifre: admin^)%R%
    start "" "%GRAFANA_URL%"
)
exit /b 0

::==========================================================================
:DO_DEMO
::==========================================================================
echo.
echo %VI%  ╔════════════════════════════════════════════════════════════════════════════╗%R%
echo %VI%  ║ %WH%%B%ORNEK VERI%R%  %GR%profil ornekleri ve dort optimizasyon ornegi%R%                   %VI%║%R%
echo %VI%  ╚════════════════════════════════════════════════════════════════════════════╝%R%
echo.
call :GET_STATUS
if not "%APP_ONLINE%"=="1" (
    echo  %RD%[ X  ]%R% %WH%Sunucu calismiyor. Once [1] Kur ve baslat.%R%
    exit /b 1
)
powershell -NoProfile -InputFormat None -Command "$u = '%CHECK_URL%'; $ok = $true; $h = @{}; if ($env:ACCESS_TOKEN) { $h['Authorization'] = 'Bearer ' + $env:ACCESS_TOKEN }; foreach ($s in 'sales.csv', 'tr_survey.csv') { try { $d = Invoke-RestMethod -Method Post -Headers $h -Uri ($u + '/api/samples/' + $s) -TimeoutSec 15; Write-Host ('  [ OK ] Veri seti yuklendi: ' + $s) -ForegroundColor Green } catch { Write-Host ('  [ X  ] ' + $s + ': ' + $_.Exception.Message) -ForegroundColor Red; $ok = $false } }; foreach ($k in 'production', 'transport', 'assignment', 'knapsack') { try { $o = Invoke-RestMethod -Method Post -Headers $h -Uri ($u + '/api/optimize/examples/' + $k) -TimeoutSec 15; for ($i = 0; $i -lt 30; $i++) { $r = Invoke-RestMethod -Headers $h -Uri ($u + '/api/optimizations/' + $o.id) -TimeoutSec 10; if ($r.status -eq 'done' -or $r.status -eq 'failed') { break }; Start-Sleep -Milliseconds 500 }; $b = $r.result.baseline; $lift = if ($b -and $null -ne $b.uplift_pct) { (' (+{0:N1}%% vs basit kural)' -f $b.uplift_pct) } else { '' }; $names = @{ production = 'Uretim plani'; transport = 'Ulastirma'; assignment = 'Atama'; knapsack = 'Butce secimi' }; Write-Host ('  [ OK ] ' + $names[$k] + ': ' + $r.result_status + ', ' + $r.result.objective_label + ' = ' + ('{0:N2}' -f $r.objective) + $lift) -ForegroundColor Green } catch { Write-Host ('  [ X  ] ' + $k + ': ' + $_.Exception.Message) -ForegroundColor Red; $ok = $false } }; if ($ok) { exit 0 } else { exit 1 }"
set "_DEMO_EXIT=%ERRORLEVEL%"
if "%OPEN_BROWSER%"=="1" if "%_DEMO_EXIT%"=="0" start "" "%API_URL%/optimize"
exit /b %_DEMO_EXIT%

::==========================================================================
:DO_HEALTH
::==========================================================================
echo.
echo %YL%  ╔════════════════════════════════════════════════════════════════════════════╗%R%
echo %YL%  ║ %WH%%B%SAGLIK KONTROLU%R%  %GR%kurulum oncesi ve sonrasi tanilama%R%                        %YL%║%R%
echo %YL%  ╚════════════════════════════════════════════════════════════════════════════╝%R%
echo.
set "_FAIL=0"
call :FIND_PYTHON
if defined SYS_PY (
    for /f "usebackq delims=" %%v in (`%SYS_PY% --version 2^>^&1`) do echo  %GN%[ OK ]%R% %WH%Python:%R% %CY%%%v%R%
) else (
    echo  %RD%[ X  ]%R% %WH%Python 3.13+ bulunamadi%R%
    set "_FAIL=1"
)
if exist "%VPY%" (
    echo  %GN%[ OK ]%R% %WH%Sanal ortam:%R% %CY%.venv%R%
) else (
    echo  %YL%[WARN]%R% %WH%Sanal ortam yok%R% %D%%GR%- [1] olusturur%R%
)
call :PORT_STATE
if "%PORT_STATE%"=="FREE"       echo  %GN%[ OK ]%R% %WH%Port %PORT% bos%R%
if "%PORT_STATE%"=="DATADIGEST" echo  %GN%[ OK ]%R% %WH%DataDigest calisiyor:%R% %CY%%STATUS_LINE%%R%
if "%PORT_STATE%"=="OTHER" (
    echo  %RD%[ X  ]%R% %WH%Port %PORT% baska bir uygulamada%R%
    set "_FAIL=1"
)
where docker >nul 2>&1
if errorlevel 1 (
    echo  %YL%[WARN]%R% %WH%Docker kurulu degil%R% %D%%GR%- yerel mod icin gerekmez%R%
) else (
    docker info >nul 2>&1
    if errorlevel 1 (
        echo  %YL%[WARN]%R% %WH%Docker kurulu ama motor calismiyor%R% %D%%GR%- [2]/[3] baslatmayi dener%R%
    ) else (
        echo  %GN%[ OK ]%R% %WH%Docker motoru calisiyor%R%
    )
)
powershell -NoProfile -InputFormat None -Command "$o = (wsl.exe --status 2>&1 | Out-String) -replace [char]0, ''; if ($o -match 'not enabled') { exit 2 } elseif ($o -match 'Default Version') { exit 0 } else { exit 1 }"
if errorlevel 2 (
    echo  %YL%[WARN]%R% %WH%WSL2 sanallastirma bekliyor%R% %D%%GR%- bilgisayari yeniden baslatin ^(Docker icin gerekli^)%R%
) else if errorlevel 1 (
    echo  %YL%[WARN]%R% %WH%WSL kurulu degil%R% %D%%GR%- sadece Docker modu icin gerekli%R%
) else (
    echo  %GN%[ OK ]%R% %WH%WSL2 hazir%R%
)
where kubectl >nul 2>&1
if errorlevel 1 (
    echo  %D%%GR%[ -- ] kubectl yok ^(Kubernetes istege bagli^)%R%
) else (
    echo  %GN%[ OK ]%R% %WH%kubectl kurulu%R%
)
for /f "usebackq delims=" %%d in (`powershell -NoProfile -InputFormat None -Command "'{0:N1}' -f ((Get-PSDrive C).Free / 1GB)"`) do echo  %GN%[ OK ]%R% %WH%Bos disk:%R% %CY%%%d GB%R%
echo.
if "%_FAIL%"=="1" (
    echo  %RD%%B%Sorun var:%R% %GR%yukaridaki [ X ] satirlarini cozun.%R%
    exit /b 1
)
echo  %GN%%B%Hazir.%R% %GR%[1] ile baslatabilirsiniz.%R%
exit /b 0

::==========================================================================
:DO_TEST
::==========================================================================
echo.
echo %YL%  ╔════════════════════════════════════════════════════════════════════════════╗%R%
echo %YL%  ║ %WH%%B%TESTLER%R%  %GR%pytest (birim testleri; entegrasyon testleri CI'da kosar)%R%         %YL%║%R%
echo %YL%  ╚════════════════════════════════════════════════════════════════════════════╝%R%
echo.
call :INSTALL
if errorlevel 1 exit /b 1
call :STEP "Test bagimliliklari kontrol ediliyor..."
"%VPY%" -m pip install --disable-pip-version-check -q -r "%PROJECT_DIR%\requirements-dev.txt"
"%VPY%" -m pytest -q
exit /b %ERRORLEVEL%

::==========================================================================
:DO_LOGS
::==========================================================================
cls
echo.
echo %CY%  CANLI LOG  --  logs\api.log  (CTRL+C ile cikin)%R%
echo.
if exist "%LOG_FILE%" (
    powershell -NoProfile -InputFormat None -Command "Get-Content -LiteralPath '%LOG_FILE%' -Wait -Tail 40"
) else (
    echo  %YL%[WARN]%R% %GR%Henuz log yok. Sunucuyu [1] ile baslatin.%R%
    pause
)
goto :EOF

::==========================================================================
:STOP_LOCAL
::==========================================================================
:: Stops whatever listens on the port (the local uvicorn started by [1]).
powershell -NoProfile -InputFormat None -Command "$c = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue; if ($c) { $c.OwningProcess | Sort-Object -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }; exit 0 } else { exit 1 }"
if errorlevel 1 (
    echo  %D%%GR%[ -- ] Yerel sunucu zaten kapali%R%
) else (
    echo  %GN%[ OK ]%R% %WH%Yerel sunucu durduruldu%R%
)
goto :EOF

::==========================================================================
:DO_STOP
::==========================================================================
echo.
call :STOP_LOCAL
docker info >nul 2>&1
if not errorlevel 1 (
    docker compose --profile monitoring ps -q 2>nul | findstr . >nul
    if not errorlevel 1 (
        call :STEP "Docker sistemi kapatiliyor (veriler korunur)..."
        docker compose --profile monitoring down
        echo  %GN%[ OK ]%R% %WH%Docker sistemi durduruldu%R%
    )
)
exit /b 0

::==========================================================================
:EXIT_APP
::==========================================================================
cls
echo.
echo  %GR%DataDigest launcher kapandi. Calisan sunucu arka planda devam eder; durdurmak icin [9].%R%
echo.
ping -n 2 127.0.0.1 >nul
exit /b 0
