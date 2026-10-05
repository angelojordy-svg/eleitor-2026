@echo off
cd /d "%~dp0"
echo ============================================
echo  Atualizar o site publicado (GitHub Pages)
echo ============================================
echo.
echo Gerando o site com os dados mais recentes do TSE...
".venv\Scripts\eleitor.exe" html --municipio Parauapebas/PA --out resultado-2026.html
if errorlevel 1 goto fim

echo.
echo Publicando na branch gh-pages...
git checkout gh-pages
copy /Y resultado-2026.html index.html >nul
git add index.html
git -c user.name="Wally" -c user.email="wally@local" commit -m "Atualiza o site" >nul
git push
git checkout main

echo.
echo Pronto. Site: https://angelojordy-svg.github.io/eleitor-2026/
echo (o GitHub pode levar ~1 min para reconstruir a pagina)
:fim
echo.
pause
