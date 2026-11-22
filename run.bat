@echo off
rem Windows PC で実行するときは、このファイルをダブルクリックします
chcp 65001 > nul
cd /d %~dp0
py -m pip install -q -r requirements.txt
py main.py
start "" docs\index.html
pause
