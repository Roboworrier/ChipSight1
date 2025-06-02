@echo off
cd /d "C:\Users\Diwakar Singh\Downloads\ChipSight deepskv7"
waitress-serve --host=0.0.0.0 --port=5000 app:app