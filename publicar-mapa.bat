@echo off
setlocal
cd /d "%~dp0"
title Publicar mapa eleitoral (GitHub Pages)

set "XLSX=In Put\boletim_urna_parauapebas_2026_z75_z106_com_locais.xlsx"
set "HTML=In Put\mapa_eleitoral_parauapebas_2026.html"
set "WORK=%TEMP%\eleitor-gh-pages"
set "URL=https://angelojordy-svg.github.io/eleitor-2026/mapa/parauapebas/"

echo ============================================
echo  Gerar mapa (fundo offline + HTML + Google)
echo ============================================
".venv\Scripts\eleitor.exe" mapa-urnas --xlsx "%XLSX%"
if errorlevel 1 goto fim

echo.
echo ============================================
echo  Preparar worktree da gh-pages
echo ============================================
if exist "%WORK%" rmdir /s /q "%WORK%"
git worktree prune
git fetch origin gh-pages
git worktree add --detach "%WORK%" origin/gh-pages
if errorlevel 1 goto fim

if not exist "%WORK%\mapa\parauapebas" mkdir "%WORK%\mapa\parauapebas"
copy /Y "%HTML%" "%WORK%\mapa\parauapebas\index.html" >nul
if errorlevel 1 goto limpar

if exist "%WORK%\mapa\parauapebas\google" rmdir /s /q "%WORK%\mapa\parauapebas\google"
xcopy /E /I /Y "In Put\google" "%WORK%\mapa\parauapebas\google" >nul
if errorlevel 1 goto limpar
copy /Y "mapa-index.html" "%WORK%\mapa\index.html" >nul
if errorlevel 1 goto limpar

echo.
echo ============================================
echo  Commit e push (gh-pages)
echo ============================================
cd /d "%WORK%"
git add mapa
git -c user.name="Wally" -c user.email="wally@local" commit -m "Publica mapa eleitoral de Parauapebas (OSM offline + Google)"
if errorlevel 1 (
    echo Nada mudou no mapa publicado.
    goto limpar
)
git push origin HEAD:gh-pages
if errorlevel 1 goto limpar

echo.
echo Mapa publicado:
echo   %URL%
echo (o GitHub Pages pode levar ~1 min para atualizar)

:limpar
cd /d "%~dp0"
git worktree remove "%WORK%" --force >nul 2>&1

:fim
echo.
pause
