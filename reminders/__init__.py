
import os, logging, requests
from datetime import datetime, timedelta

USE_TABLE = False
try:
    from azure.data.tables import TableClient
    USE_TABLE = True
except Exception:
    USE_TABLE = False

WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
AZURE_STORAGE = os.environ.get("AzureWebJobsStorage", "")

def send_whatsapp_template(phone_number_id: str, to: str, name: str, parameters=None, language="pt_BR"):
    parameters = parameters or []
    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": language},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in parameters]}]
        }
    }
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    if r.status_code >= 300:
        logging.error("template send fail: %s - %s", r.status_code, r.text)

def send_whatsapp_text(phone_number_id: str, to: str, text: str):
    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "text": {"body": text}}
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    if r.status_code >= 300:
        logging.error("text send fail: %s - %s", r.status_code, r.text)

def run(mytimer) -> None:
    if not (USE_TABLE and AZURE_STORAGE):
        logging.info("Reminders: Table Storage não configurado.")
        return

    client = TableClient.from_connection_string(AZURE_STORAGE, table_name="bookings")
    try:
        client.create_table()
    except Exception:
        pass

    now = datetime.utcnow()
    window = now - timedelta(minutes=7)

    entities = client.list_entities()
    for e in entities:
        try:
            phone_number_id = e.get("phoneNumberId")
            to = e.get("PartitionKey")
            nome = e.get("nome","")
            servico = e.get("servico","")
            data = e.get("data","")
            horario = e.get("horario","")
            r24_at = e.get("reminder24AtUtc")
            r24_status = e.get("reminder24Status","")
            if r24_at and r24_status == "pending":
                t = datetime.fromisoformat(r24_at.replace("Z",""))
                if t <= now and t > window:
                    if phone_number_id:
                        send_whatsapp_template(phone_number_id, to, "lembrete_24h_jceng", [nome, servico, horario])
                        client.update_entity({"PartitionKey": e["PartitionKey"], "RowKey": e["RowKey"], "reminder24Status":"sent"}, mode="merge")
            r1h_at = e.get("reminder1hAtUtc")
            r1h_status = e.get("reminder1hStatus","")
            if r1h_at and r1h_status == "pending":
                t = datetime.fromisoformat(r1h_at.replace("Z",""))
                if t <= now and t > window:
                    if phone_number_id:
                        send_whatsapp_template(phone_number_id, to, "lembrete_1h_jceng", [nome, servico])
                        client.update_entity({"PartitionKey": e["PartitionKey"], "RowKey": e["RowKey"], "reminder1hStatus":"sent"}, mode="merge")
        except Exception as ex:
            logging.error("Erro ao processar lembrete: %s", ex)
