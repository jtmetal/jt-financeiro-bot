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
    resposta = requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": texto
        },
        timeout=15
    )

    print("RESPOSTA TELEGRAM:", resposta.text)
    return resposta


@app.get("/")
def inicio():
    return "JT Financeiro está online!"


@app.get("/configurar-webhook")
def configurar_webhook():
    webhook_url = "https://jt-financeiro-bot.onrender.com/webhook"

    resposta = requests.post(
        f"{TELEGRAM_API}/setWebhook",
        json={
            "url": webhook_url,
            "secret_token": SECRET_TOKEN,
            "drop_pending_updates": True
        },
        timeout=15
    )

    return resposta.json()


@app.get("/diagnostico-webhook")
def diagnostico_webhook():
    resposta = requests.get(
        f"{TELEGRAM_API}/getWebhookInfo",
        timeout=15
    )

    return resposta.json()


@app.get("/teste-telegram")
def teste_telegram():
    resposta = requests.get(
        f"{TELEGRAM_API}/getMe",
        timeout=15
    )

    return resposta.json()


@app.post("/webhook")
def webhook():
    print("WEBHOOK RECEBIDO")

    if SECRET_TOKEN:
        token_recebido = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token"
        )

        if token_recebido != SECRET_TOKEN:
            print("SECRET TOKEN INVÁLIDO")
            return "Não autorizado", 403

    dados = request.get_json(silent=True) or {}

    print("DADOS:", dados)

    mensagem = dados.get("message")

    if not mensagem:
        print("SEM MENSAGEM")
        return "ok", 200

    chat_id = mensagem.get("chat", {}).get("id")
    texto = mensagem.get("text", "").strip()

    if not chat_id:
        return "ok", 200

    if texto == "/start":
        enviar_mensagem(
            chat_id,
            "🤖 JT Financeiro iniciado!\n\n"
            "Estou online e conectado ao sistema da JT Metal."
        )

    elif texto.startswith("/cliente "):
        nome_cliente = texto.replace("/cliente ", "", 1).strip()

        if not nome_cliente:
            enviar_mensagem(
                chat_id,
                "Digite o nome do cliente depois de /cliente."
            )
            return "ok", 200

        try:
            supabase.table("clientes").insert({
                "nome": nome_cliente,
                "criado_por": str(chat_id)
            }).execute()

            enviar_mensagem(
                chat_id,
                f"✅ Cliente cadastrado com sucesso:\n{nome_cliente}"
            )

        except Exception as erro:
            print("ERRO SUPABASE:", erro)

            enviar_mensagem(
                chat_id,
                "❌ Não consegui cadastrar o cliente.\n"
                "Vou precisar verificar a conexão com o banco."
            )

    elif texto == "/clientes":
        try:
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
                    "Ainda não existem clientes cadastrados."
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

        except Exception as erro:
            print("ERRO AO LISTAR CLIENTES:", erro)

            enviar_mensagem(
                chat_id,
                "❌ Não consegui consultar os clientes agora."
            )

    else:
        enviar_mensagem(
            chat_id,
            "✅ Recebi sua mensagem.\n\n"
            "Comandos disponíveis agora:\n"
            "/start\n"
            "/cliente Nome do Cliente\n"
            "/clientes"
        )

    return "ok", 200
