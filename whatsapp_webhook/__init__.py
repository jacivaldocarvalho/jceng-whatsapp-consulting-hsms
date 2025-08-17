
import os, json, logging, requests, azure.functions as func, uuid, re
from datetime import datetime, timedelta

# Table Storage
USE_TABLE = False
try:
    from azure.data.tables import TableClient
    USE_TABLE = True
except Exception:
    USE_TABLE = False

# ENV
AOAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AOAI_KEY = os.environ.get("AZURE_OPENAI_API_KEY")
AOAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "verificacao-jceng-123")
OWNER_WHATSAPP = os.environ.get("OWNER_WHATSAPP", "")
OWNER_NAME = os.environ.get("OWNER_NAME", "Eng. Jacivaldo Carvalho")
AZURE_STORAGE = os.environ.get("AzureWebJobsStorage", "")
LOCAL_UTC_OFFSET = os.environ.get("LOCAL_UTC_OFFSET", "-03:00")
TABLE_NAME = "bookings"

# OpenAI
from openai import AzureOpenAI
aoai = AzureOpenAI(api_key=AOAI_KEY, azure_endpoint=AOAI_ENDPOINT, api_version="2024-08-01-preview")

PROMPT_EXTRACT = """
Você é a assistente do Engenheiro Jacivaldo Carvalho (consultoria).
Interprete a mensagem do cliente e identifique se é AGENDAMENTO.
Se for, extraia:
- nome, servico, categoria (uma das: Web & Aplicações, Soluções em IA, Nuvem & DevOps, Telecom – Redes & Fibra, Documentação & Melhoria, Consultoria em TI)
- data (ex: 20/08/2025 ou 20/08), horario (ex: 14:00 ou 14h)
- contato (telefone ou e-mail), observacoes
- intent (schedule|info|handoff|unknown)
Regra de handoff: se a pessoa pedir para falar com humano/atendente/telefone, classifique intent=handoff.
Responda SOMENTE JSON:
{"intent":"...", "nome":"...", "servico":"...", "categoria":"...", "data":"...", "horario":"...", "contato":"", "observacoes":""}
"""

def call_extract(user_text: str):
    try:
        r = aoai.chat.completions.create(
            model=AOAI_DEPLOYMENT,
            messages=[{"role":"system","content":PROMPT_EXTRACT},{"role":"user","content":user_text}],
            temperature=0.2, max_tokens=400
        )
        content = r.choices[0].message.content.strip()
        start, end = content.find("{"), content.rfind("}")
        content = content[start:end+1]
        return json.loads(content)
    except Exception as e:
        logging.error("extract error: %s", e)
        return {"intent":"unknown","nome":"","servico":"","categoria":"","data":"","horario":"","contato":"","observacoes":""}

def missing_fields(d):
    return [k for k in ["nome","servico","categoria","data","horario","contato"] if not d.get(k)]

def send_whatsapp_text(phone_number_id: str, to: str, text: str):
    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "text": {"body": text}}
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    if r.status_code >= 300:
        logging.error("send text fail: %s - %s", r.status_code, r.text)

def send_whatsapp_template(phone_number_id: str, to: str, name: str, language="pt_BR", parameters=None):
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
            "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in parameters]}] if parameters else []
        }
    }
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    if r.status_code >= 300:
        logging.error("send template fail: %s - %s", r.status_code, r.text)

def parse_datetime_local(date_str: str, time_str: str, utc_offset: str):
    # Simplified: accepts DD/MM or DD/MM/YYYY and HH(:MM)? or HHh
    import re
    try:
        now = datetime.utcnow()
        parts = re.findall(r"\d+", date_str)
        if len(parts) >= 2:
            d, m = int(parts[0]), int(parts[1])
            y = int(parts[2]) if len(parts) >= 3 else now.year
            dt_base = datetime(y, m, d)
            if dt_base < now and (now - dt_base).days > 30:
                dt_base = datetime(y+1, m, d)
        else:
            return None
        tnums = re.findall(r"\d+", time_str)
        if not tnums:
            return None
        h = int(tnums[0])
        mi = int(tnums[1]) if len(tnums) > 1 else 0
        local_dt = datetime(dt_base.year, dt_base.month, dt_base.day, h, mi, 0)
        sign = -1 if utc_offset.startswith("-") else 1
        hh, mm = utc_offset[1:].split(":")
        delta = timedelta(hours=int(hh), minutes=int(mm)) * sign
        utc_dt = local_dt - delta
        return utc_dt
    except Exception:
        return None

def save_booking(wan: str, booking: dict, phone_number_id: str):
    if not (USE_TABLE and AZURE_STORAGE):
        return False
    try:
        client = TableClient.from_connection_string(AZURE_STORAGE, table_name="bookings")
        try: client.create_table()
        except Exception: pass
        utc_dt = parse_datetime_local(booking.get("data",""), booking.get("horario",""), os.environ.get("LOCAL_UTC_OFFSET","-03:00"))
        if utc_dt:
            booking["appointmentUtc"] = utc_dt.isoformat()+"Z"
            booking["reminder24AtUtc"] = (utc_dt - timedelta(hours=24)).isoformat()+"Z"
            booking["reminder1hAtUtc"] = (utc_dt - timedelta(hours=1)).isoformat()+"Z"
            booking["reminder24Status"] = "pending"
            booking["reminder1hStatus"] = "pending"
        entity = {**booking,
            "PartitionKey": wan,
            "RowKey": booking.get("id") or str(uuid.uuid4()),
            "createdAt": datetime.utcnow().isoformat()+"Z",
            "phoneNumberId": phone_number_id
        }
        client.upsert_entity(entity=entity, mode="merge")
        return True
    except Exception as e:
        logging.error("save booking fail: %s", e)
        return False

def notify_owner(phone_number_id: str, booking: dict):
    if OWNER_WHATSAPP:
        txt = (f"🔔 Novo agendamento\n"
               f"Cliente: {booking.get('nome')}\n"
               f"Serviço: {booking.get('servico')} ({booking.get('categoria')})\n"
               f"Quando: {booking.get('data')} {booking.get('horario')}\n"
               f"Contato: {booking.get('contato')}\n"
               f"Obs: {booking.get('observacoes','-')}")
        send_whatsapp_text(phone_number_id, OWNER_WHATSAPP, txt)

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Webhook JC Eng + HSM acionado.")
    if req.method == "GET":
        mode = req.params.get("hub.mode")
        token = req.params.get("hub.verify_token")
        challenge = req.params.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
            return func.HttpResponse(challenge, status_code=200)
        return func.HttpResponse("Verificação inválida", status_code=403)

    if req.method == "POST":
        try:
            data = req.get_json()
        except ValueError:
            return func.HttpResponse("JSON inválido", status_code=400)

        try:
            changes = data.get("entry", [])[0].get("changes", [])[0]
            value = changes.get("value", {})
            phone_number_id = value.get("metadata", {}).get("phone_number_id")
            messages = value.get("messages", [])
            if not messages:
                return func.HttpResponse("OK", status_code=200)
            msg = messages[0]
            from_ = msg.get("from")

            if msg.get("type") == "text":
                user_text = msg["text"]["body"]
            else:
                user_text = "Olá! Sou a assistente do Eng. Jacivaldo. Pode enviar sua mensagem em texto? 🙂"

            extracted = call_extract(user_text)
            intent = extracted.get("intent","unknown")

            if intent == "handoff":
                notify_owner(phone_number_id, {"nome": extracted.get("nome","(sem nome)"),
                                               "servico": extracted.get("servico","(sem serviço)"),
                                               "categoria": extracted.get("categoria",""),
                                               "data": extracted.get("data",""), "horario": extracted.get("horario",""),
                                               "contato": extracted.get("contato",""), "observacoes": extracted.get("observacoes","Pedido de humano")})
                send_whatsapp_text(phone_number_id, from_, "Claro! Vou te conectar com o Eng. Jacivaldo. Ele já foi notificado e falará com você por aqui 💬.")
                return func.HttpResponse("EVENT_RECEIVED", status_code=200)

            if intent == "schedule" and not missing_fields(extracted):
                save_booking(from_, {**extracted, "id": msg.get("id")}, phone_number_id)
                send_whatsapp_text(phone_number_id, from_, "✅ Agendamento registrado! Você receberá lembretes automáticos antes do horário. Qualquer ajuste é só avisar por aqui.")
                send_whatsapp_template(phone_number_id, from_, "confirmacao_agendamento_jceng",
                                       parameters=[extracted.get("nome",""), extracted.get("servico",""),
                                                   extracted.get("data",""), extracted.get("horario","")])
                notify_owner(phone_number_id, extracted)
            else:
                need = missing_fields(extracted)
                if need:
                    labels = {
                        "nome":"seu nome completo",
                        "servico":"o serviço desejado",
                        "categoria":"a categoria (Web & Aplicações, Soluções em IA, Nuvem & DevOps, Telecom – Redes & Fibra, Documentação & Melhoria, Consultoria em TI)",
                        "data":"a data",
                        "horario":"o horário",
                        "contato":"um telefone ou e-mail"
                    }
                    itens = ", ".join(labels[n] for n in need)
                    send_whatsapp_text(phone_number_id, from_, f"✨ Perfeito! Para concluir seu agendamento, me informe: {itens}.")
                else:
                    send_whatsapp_text(phone_number_id, from_, "Posso te ajudar a escolher um serviço? Também posso verificar disponibilidade para uma data/horário específicos 🙂.")

        except Exception as e:
            logging.exception("Erro webhook: %s", e)
            return func.HttpResponse("Erro", status_code=500)

        return func.HttpResponse("EVENT_RECEIVED", status_code=200)

    return func.HttpResponse("Método não suportado", status_code=405)
