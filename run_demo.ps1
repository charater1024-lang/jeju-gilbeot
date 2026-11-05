$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py -or $py -like '*WindowsApps*') {
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundledPython) { $py = $bundledPython }
    else { throw 'Python 3.10 이상을 설치한 뒤 python -m jeju_agent serve 명령을 실행하세요.' }
}
& $py -m jeju_agent serve
if ($LASTEXITCODE -ne 0) { throw '실행 실패. README와 오류 안내를 확인하세요.' }
