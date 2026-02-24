$ErrorActionPreference = "Stop"

Write-Host "Instalando dependencias..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Write-Host "Gerando executavel..."
pyinstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name TelegramSenderMVP `
  app.py

Write-Host "Build concluido em dist\\TelegramSenderMVP.exe"
