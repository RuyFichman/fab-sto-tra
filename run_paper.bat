@echo off
rem Avanca o paper trading (agendado para dias uteis, apos o fechamento da B3).
cd /d "%~dp0"
if not exist paper mkdir paper
echo ==== %date% %time% ==== >> paper\paper.log
".venv\Scripts\python.exe" -m quantlab paper >> paper\paper.log 2>&1
