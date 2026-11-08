@echo off
rem Optional GPU experiment; the standard run_center.cmd uses center CPU mode.
call "%~dp0run_center.cmd" --semantic-device auto --road-gpu %*
