@echo off
setlocal

set "PYTHON=%~dp0tools\python\python.exe"

if not exist "%PYTHON%" (
  echo Portable Python was not found at "%PYTHON%"
  exit /b 1
)

"%PYTHON%" -m unittest discover -s tests
