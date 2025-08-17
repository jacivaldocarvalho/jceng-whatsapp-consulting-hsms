
# JC Eng — WhatsApp + Azure OpenAI + HSM + Lembretes

Assistente completo para o **Eng. Jacivaldo Carvalho** com:
- Catálogo de serviços
- Extração inteligente (Azure OpenAI)
- **Agendamento** + **Confirmação (HSM)**
- **Lembretes automáticos** (24h e 1h antes) via Timer Trigger
- **Handoff para humano**
- Persistência em **Azure Table Storage**

## Estrutura
```
jceng-whatsapp-consulting-hsms/
├── host.json
├── local.settings.json
├── requirements.txt
├── service_catalog.json
├── hsm_templates/
│   ├── confirmacao_agendamento_jceng.json
│   ├── lembrete_24h_jceng.json
│   └── lembrete_1h_jceng.json
├── whatsapp_webhook/
│   ├── __init__.py
│   └── function.json
└── reminders/
    ├── __init__.py
    └── function.json
```

## Como funciona
- Ao detectar agendamento completo, o sistema:
  1) Salva na **Table** com os horários dos lembretes (`reminder24AtUtc`, `reminder1hAtUtc`).
  2) Envia **HSM de confirmação** (caso aprovado no Meta).
  3) **Notifica** você no WhatsApp (`OWNER_WHATSAPP`).

- A função `reminders` roda a cada 5 minutos, procura lembretes *pendentes* cujo horário passou e envia:
  - Template **lembrete_24h_jceng** com parâmetros `[nome, serviço, hora]`.
  - Template **lembrete_1h_jceng** com `[nome, serviço]`.

> Importante: Cadastre os **templates HSM** no **Meta Business Manager** com os arquivos em `hsm_templates/`. Use exatamente os nomes.

## Variáveis necessárias
- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`
- `WHATSAPP_TOKEN`, `VERIFY_TOKEN`
- `OWNER_WHATSAPP`, `OWNER_NAME`
- `AzureWebJobsStorage` (obrigatório para lembretes)
- `LOCAL_UTC_OFFSET` (ex.: `-03:00` para America/Belem)

## Rodar local
```bash
pip install -r requirements.txt
func start
```
Para expor localmente: `ngrok http 7071` e cadastre como Callback.

## Deploy
Crie a Function App (Python) e publique. Configure as App Settings acima. No **Meta**, verifique o webhook e publique os templates HSM.
