from flask import Flask, request
import os
import requests
from supabase import create_client, Client

app = Flask(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
SECRET_TOKEN = os.environ.get("TELEGRAM_SECRET_TOKEN", "")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)


def enviar_mensagem(chat_id, texto):
    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": texto
        },
        timeout=10
    )


@app.get("/")
def inicio():
    return "JT Financeiro está online!"


@app.get("/configurar-webhook")
def configurar_webhook():
    url_webhook = "https://jt-financeiro-bot.onrender.com/webhook"

    resposta = requests.post(
        f"{TELEGRAM_API}/setWebhook",
        json={
            "url": url_webhook,
            "secret_token": SECRET_TOKEN
        },
        timeout=10
    )

    return resposta.json()


@app.post("/webhook")
def webhook():
    if SECRET_TOKEN:
        recebido = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token"
        )

        if recebido != SECRET_TOKEN:
            return "Não autorizado", 403

    dados = request.get_json(silent=True) or {}

    mensagem = dados.get("message")

    if not mensagem:
        return "ok", 200

    chat_id = mensagem["chat"]["id"]
    texto = mensagem.get("text", "").strip()

    if texto == "/start":
        enviar_mensagem(
            chat_id,
            "🤖 JT Financeiro iniciado!\n\n"
            "Agora já estou conectado ao banco de dados da JT Metal."
        )

    elif texto.startswith("/cliente "):
        nome_cliente = texto.replace("/cliente ", "", 1).strip()

        if not nome_cliente:
            enviar_mensagem(
                chat_id,
                "Informe o nome do cliente."
            )
            return "ok", 200

        supabase.table("clientes").insert({
            "nome": nome_cliente,
            "criado_por": str(chat_id)
        }).execute()

        enviar_mensagem(
            chat_id,
            f"✅ Cliente cadastrado:\n{nome_cliente}"
        )

    elif texto == "/clientes":
        resultado = (
            supabase
            .table("clientes")
            .select("nome")
            .order("nome")
            .execute()
        )

        clientes = resultado.data or []

        if not clientes:
            enviar_mensagem(
                chat_id,
                "Nenhum cliente cadastrado ainda."
            )
        else:
            lista = "\n".join(
                f"• {cliente['nome']}"
                for cliente in clientes
            )

            enviar_mensagem(
                chat_id,
                f"👥 Clientes cadastrados:\n\n{lista}"
            )

    else:
        enviar_mensagem(
            chat_id,
            "Por enquanto eu entendo:\n\n"
            "/cliente Nome do Cliente\n"
            "/clientes"
        )

    return "ok", 200
