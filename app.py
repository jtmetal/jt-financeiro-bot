from flask import Flask, request
import os
import requests

app = Flask(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
SECRET_TOKEN = os.environ.get("TELEGRAM_SECRET_TOKEN", "")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


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
        recebido = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if recebido != SECRET_TOKEN:
            return "Não autorizado", 403

    dados = request.get_json(silent=True) or {}

    mensagem = dados.get("message")

    if not mensagem:
        return "ok", 200

    chat_id = mensagem["chat"]["id"]
    texto = mensagem.get("text", "")

    if texto == "/start":
        enviar_mensagem(
            chat_id,
            "🤖 JT Financeiro iniciado!\n\n"
            "Estou online e pronto para começar a organizar a JT Metal."
        )

    else:
        enviar_mensagem(
            chat_id,
            f"✅ Recebi sua mensagem:\n\n{texto}"
        )

    return "ok", 200
