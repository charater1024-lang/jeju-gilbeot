$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'runtime\python.exe')) {
    & (Join-Path $PSScriptRoot 'runtime\python.exe') (Join-Path $PSScriptRoot 'center_app.py')
    exit $LASTEXITCODE
}
$centerPython = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $centerPython -or $centerPython -like '*WindowsApps*') {
    $bundledCenterPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundledCenterPython) { $centerPython = $bundledCenterPython }
    else { throw 'Python 3.10 이상을 설치한 뒤 python -m jeju_agent serve --open-browser 명령을 실행하세요.' }
}
& $centerPython -m jeju_agent serve --open-browser
if ($LASTEXITCODE -ne 0) { throw '실행 실패. 센터 운영 매뉴얼을 확인하세요.' }
