# Telegram Sender MVP

Aplicativo desktop Windows para disparo de mensagem em grupo do Telegram com alta precisao de horario.

## Avisos importantes

- Use apenas com autorizacao explicita do titular da conta.
- O app trabalha em melhor esforco de precisao; nao garante posicao no ranking de chegada.
- O Telegram pode impor rate limits dependendo do comportamento de envio.

## Requisitos

- Windows 10/11
- Python 3.13+
- Credenciais Telegram API (`api_id` e `api_hash`) obtidas em `https://my.telegram.org/apps`

## Instalar dependencias

```powershell
python -m pip install -r requirements.txt
```

## Executar em desenvolvimento

```powershell
python app.py
```

## Fluxo de uso

1. Abrir app e informar senha mestra local.
2. Informar `API ID` e `API Hash`.
3. Clicar em `Novo login via QR` para autenticar a conta.
4. Selecionar perfil carregado.
5. Clicar em `Carregar grupos` e escolher o grupo alvo.
6. Informar mensagem e horario (`HH:MM:SS`).
7. Opcionalmente clicar em `Validar relogio`.
8. Clicar em `Iniciar rodada`.

## Arquivos locais

- `data/profiles.json`: metadados de perfis.
- `data/sessions.enc`: sessoes criptografadas.
- `data/runs.jsonl`: historico resumido de execucoes.
- `data/app_config.json`: credenciais API locais.

## Build do executavel

```powershell
.\build_exe.ps1
```

Saida esperada: `dist\TelegramSenderMVP.exe`

