@echo off
title Login GitHub (gh)
echo ============================================
echo  Login no GitHub para publicar o site
echo ============================================
echo.
echo Vai abrir o navegador (ou mostrar um codigo + link https://github.com/login/device).
echo Autorize o acesso e volte aqui.
echo.
"C:\Users\user\AppData\Local\gh\bin\gh.exe" auth login --hostname github.com --git-protocol https --web
echo.
echo Se apareceu "Logged in as ..." deu certo.
echo Volte ao chat e diga: pronto
pause
