# Starts the Memo Telegram bot once Telegram accepts the token (new bots on this account were rate-limited
# with HTTP 429 for hours). Checks every 15 minutes, then runs the long-polling bot and restarts it if it exits.
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
$log = Join-Path $root "data\bot.log"
while ($true) {
  $token = ((Get-Content (Join-Path $root ".env.local")) | Where-Object { $_ -like 'TELEGRAM_BOT_TOKEN=*' }) -replace '^TELEGRAM_BOT_TOKEN=', ''
  try {
    $r = Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/getMe" -TimeoutSec 20
    if ($r.ok) {
      Add-Content $log "$(Get-Date -Format s) Telegram accepted @$($r.result.username); starting bot"
      Start-Process -Wait -NoNewWindow -WorkingDirectory (Join-Path $root "backend") $py -ArgumentList "-m","app.telegram.bot" -RedirectStandardError (Join-Path $root "data\bot.err.log")
      Add-Content $log "$(Get-Date -Format s) bot exited; retrying in 60 s"
      Start-Sleep 60
      continue
    }
  } catch {
    Add-Content $log "$(Get-Date -Format s) Telegram not ready: $($_.Exception.Message)"
  }
  Start-Sleep 900
}
