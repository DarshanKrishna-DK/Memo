# Starts the whole Memo stack for local development (Windows PowerShell).
#   Postgres (docker) -> API :8000 -> worker -> Telegram bot (long polling) -> web :5173 -> Cloudflare tunnel.
# The tunnel URL changes on every run; this script writes it into .env.local as PUBLIC_BASE_URL and WEB_BASE_URL
# (Twilio and Agora call it, and Telegram sign-in links point at it) and restarts nothing else for you.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

docker compose up -d | Out-Null

# 1. Tunnel first so the API boots with the right public URL.
$log = Join-Path $root "data\tunnel.log"
Remove-Item $log -ErrorAction SilentlyContinue
Start-Process -WindowStyle Minimized cloudflared -ArgumentList "tunnel","--no-autoupdate","--url","http://localhost:5173" -RedirectStandardError $log
$url = $null
for ($i = 0; $i -lt 40 -and -not $url; $i++) {
  Start-Sleep -Milliseconds 500
  if (Test-Path $log) { $m = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1; if ($m) { $url = $m.Matches[0].Value } }
}
if ($url) {
  $envFile = Join-Path $root ".env.local"
  (Get-Content $envFile) -replace '^PUBLIC_BASE_URL=.*', "PUBLIC_BASE_URL=$url" -replace '^WEB_BASE_URL=.*', "WEB_BASE_URL=$url" | Set-Content -Encoding utf8 $envFile
  Write-Host "Public URL: $url"
  # Keep the GitHub repo's website link pointing at the live tunnel (needs the gh CLI signed in; skipped otherwise).
  if (Get-Command gh -ErrorAction SilentlyContinue) {
    try { gh repo edit DarshanKrishna-DK/Memo --homepage $url 2>$null | Out-Null } catch { }
  }
} else { Write-Warning "Tunnel URL not found; phone calls and Agora live voice will be unavailable." }

$py = Join-Path $root "backend\.venv\Scripts\python.exe"
Start-Process -WorkingDirectory "$root\backend" -WindowStyle Minimized $py -ArgumentList "-m","uvicorn","app.main:app","--port","8000","--proxy-headers","--forwarded-allow-ips=*"
Start-Process -WorkingDirectory "$root\backend" -WindowStyle Minimized $py -ArgumentList "-m","app.worker"
Start-Process -WorkingDirectory "$root\backend" -WindowStyle Minimized $py -ArgumentList "-m","app.telegram.bot"
Start-Process -WorkingDirectory "$root\web" -WindowStyle Minimized "npm.cmd" -ArgumentList "run","dev"
Write-Host "Memo is starting. Open $url (or http://localhost:5173) and send /start to @memo_ajji_bot."
