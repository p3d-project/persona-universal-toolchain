@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
taskkill /f /im RmdToGlb.exe >nul 2>&1

set ASSIMP_SRC=tools\assimp-5.4.3
set ASSIMP_BUILD=%ASSIMP_SRC%\build\x64
set ASSIMP_DLL_SRC=%ASSIMP_BUILD%\bin\Release\assimp-vc143-mt.dll
set ASSIMP_DLL_SRC2=%ASSIMP_BUILD%\bin\Release\assimp-vc142-mt.dll
set ASSIMP_OUT=bin\Debug\net472\assimp.dll

goto check_cmake

:: ── CMake ─────────────────────────────────────────────────────────────────────

:check_cmake
cmake --version >nul 2>&1
if errorlevel 1 goto install_cmake
goto check_vs

:install_cmake
echo CMake not found, installing via winget...
winget install Kitware.CMake --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo winget failed, trying choco...
    choco install cmake --installargs "ADD_CMAKE_TO_PATH=System" -y
    if errorlevel 1 (
        echo Failed to install CMake. Install manually from https://cmake.org/download/
        pause
        exit /b 1
    )
)
refreshenv >nul 2>&1
cmake --version >nul 2>&1
if errorlevel 1 (
    echo CMake installed but not on PATH. Restart after opening a new terminal.
    pause
    exit /b 1
)

:: ── Visual Studio ─────────────────────────────────────────────────────────────

:check_vs
set VS_GENERATOR=
set VSWHERE="%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"

if not exist %VSWHERE% goto vs_not_found

for /f "usebackq tokens=*" %%i in (`%VSWHERE% -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationVersion`) do set VS_VER=%%i
if "%VS_VER%"=="" goto vs_not_found

for /f "usebackq tokens=1 delims=." %%i in (`echo %VS_VER%`) do set VS_MAJOR=%%i

if "%VS_MAJOR%"=="17" set VS_GENERATOR=Visual Studio 17 2022
if "%VS_MAJOR%"=="16" set VS_GENERATOR=Visual Studio 16 2019
if "%VS_MAJOR%"=="15" set VS_GENERATOR=Visual Studio 15 2017

if "%VS_GENERATOR%"=="" (
    echo Unsupported Visual Studio version: %VS_VER%
    pause
    exit /b 1
)
goto build_assimp

:vs_not_found
echo Visual Studio with C++ tools not found, installing VS 2022 Build Tools...
winget install Microsoft.VisualStudio.2022.BuildTools --silent --accept-package-agreements --accept-source-agreements --override "--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --quiet --wait"
if errorlevel 1 (
    echo winget failed. Install manually from https://visualstudio.microsoft.com/visual-cpp-build-tools/
    pause
    exit /b 1
)
set VS_GENERATOR=Visual Studio 17 2022

:: ── Assimp build ──────────────────────────────────────────────────────────────

:build_assimp
if not exist "%ASSIMP_SRC%\CMakeLists.txt" (
    echo Assimp source not found at %ASSIMP_SRC%
    pause
    exit /b 1
)

echo.
echo Wiping stale CMake cache...
if exist "%ASSIMP_BUILD%" rmdir /s /q "%ASSIMP_BUILD%"

echo Building Assimp 5.4.3 with FBX exporter...
echo Generator: %VS_GENERATOR%
echo.

cmake -S "%ASSIMP_SRC%" -B "%ASSIMP_BUILD%" ^
    -G "%VS_GENERATOR%" -A x64 ^
    -DASSIMP_BUILD_FBX_EXPORTER:BOOL=ON ^
    -DASSIMP_BUILD_ASSIMP_TOOLS:BOOL=OFF ^
    -DASSIMP_BUILD_TESTS:BOOL=OFF ^
    -DASSIMP_BUILD_SAMPLES:BOOL=OFF ^
    -DASSIMP_INSTALL:BOOL=OFF ^
    -DBUILD_SHARED_LIBS:BOOL=ON
if errorlevel 1 (
    echo CMake configure failed.
    pause
    exit /b 1
)

cmake --build "%ASSIMP_BUILD%" --config Release --parallel
if errorlevel 1 (
    echo Assimp build failed.
    pause
    exit /b 1
)

:copy_assimp
if not exist "%ASSIMP_DLL_SRC%" (
    if not exist "%ASSIMP_DLL_SRC2%" (
        echo Assimp built but DLL not found at expected path.
        echo Expected: %ASSIMP_DLL_SRC%
        pause
        exit /b 1
    )
    set ASSIMP_DLL_SRC=%ASSIMP_DLL_SRC2%
)

if not exist "bin\Debug\net472" mkdir "bin\Debug\net472"
copy /y "%ASSIMP_DLL_SRC%" "%ASSIMP_OUT%"
if errorlevel 1 (
    echo Failed to copy assimp DLL.
    pause
    exit /b 1
)
echo Copied %ASSIMP_DLL_SRC% -> %ASSIMP_OUT%

:: ── dotnet build ──────────────────────────────────────────────────────────────

:build_dotnet
echo.
echo Building RmdToGlb...
dotnet build RmdToGlb.csproj -c Debug --nologo
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Build succeeded.
pause
