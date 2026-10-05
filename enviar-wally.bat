@echo off
title Enviar link pelo Wally (Telegram)
echo Enviando o link do site pelo bot Wally...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$cfg = Get-Content 'C:\Users\user\.opencode_tg\tgbot.json' -Raw | ConvertFrom-Json; $t = $cfg.token; $texto = 'Resultados Eleicoes 2026 - site: https://angelojordy-svg.github.io/eleitor-2026/'; foreach ($c in @('1330186321','8372820947')) { try { $r = Invoke-RestMethod -Method Post ('https://api.telegram.org/bot' + $t + '/sendMessage') -Body @{ chat_id = $c; text = $texto } -TimeoutSec 30; Write-Output ('  enviado para ' + $c + ' (ok=' + $r.ok + ')') } catch { Write-Output ('  ERRO no chat ' + $c + ': ' + $_.Exception.Message) } }"
echo.
pause
