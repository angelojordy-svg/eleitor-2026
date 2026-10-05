@echo off
cd /d "%~dp0"
echo Gerando resultado-2026.html com os dados mais recentes do TSE...
echo.
".venv\Scripts\eleitor.exe" html --municipio Parauapebas/PA --out resultado-2026.html
echo.
echo Pronto. Abra o arquivo resultado-2026.html no navegador.
pause
