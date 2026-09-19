@echo off
title Agendar videos prontos
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python agendar.py
pause
