from flask import Flask, request
import os
import json
import requests
from datetime import date

from supabase import create_client, Client
from openai import OpenAI

app = Flask(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
SECRET_TOKEN = os.environ.get("TELEGRAM_SECRET_TOKEN", "")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)

openai = OpenAI(api_key=OPENAI_API_KEY)


def enviar_mensagem(chat_id, texto, botoes=None):
    payload = {
        "chat_id": chat_id,
        "text": texto
    }

    if botoes:
        payload["reply_markup"] = {
            "inline_keyboard": botoes
        }

    resposta = requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json=payload,
        timeout=15
    )

    print("RESPOSTA TELEGRAM:", resposta.text)


def buscar_cliente_por_nome(nome):
    resultado = (
        supabase
        .table("clientes")
        .select("*")
        .ilike("nome", f"%{nome}%")
        .limit(5)
        .execute()
    )

    return resultado.data or []


def buscar_obra_por_cliente(nome_cliente):
    clientes = buscar_cliente_por_nome(nome_cliente)

    if not clientes:
        return None, None

    cliente = clientes[0]

    resultado = (
        supabase
        .table("obras")
        .select("*")
        .eq("cliente_id", cliente["id"])
        .eq("status", "aberta")
        .order("criado_em", desc=True)
        .limit(1)
        .execute()
    )

    obras = resultado.data or []

    if not obras:
        return cliente, None

    return cliente, obras[0]


def salvar_pendencia(chat_id, acao, dados):
    supabase.table("pendencias").delete().eq(
        "chat_id",
        str(chat_id)
    ).execute()

    supabase.table("pendencias").insert({
        "chat_id": str(chat_id),
        "acao": acao,
        "dados": dados
    }).execute()


def pegar_pendencia(chat_id):
    resultado = (
        supabase
        .table("pendencias")
        .select("*")
        .eq("chat_id", str(chat_id))
        .order("criado_em", desc=True)
        .limit(1)
        .execute()
    )

    dados = resultado.data or []

    if not dados:
        return None

    return dados[0]


def excluir_pendencia(chat_id):
    supabase.table("pendencias").delete().eq(
        "chat_id",
        str(chat_id)
    ).execute()


def interpretar_texto(texto):
    hoje = date.today().isoformat()

    prompt = f"""
Você é o interpretador financeiro da empresa JT Metal Serralheria.

Hoje é {hoje}.

Leia a mensagem do usuário e identifique UMA ação.

Ações permitidas:
- cadastrar_cliente
- criar_obra
- registrar_despesa
- registrar_recebimento
- consultar_obra
- consultar_clientes
- desconhecido

Regras:

1. cadastrar_cliente:
Quando a pessoa disser algo como:
"cadastre o cliente Augusto"
"novo cliente João"

2. criar_obra:
Quando houver um serviço/venda fechado com cliente.
Extraia:
cliente
servico
valor_total
valor_entrada
prazo_entrega

Exemplo:
"Fechei um portão com Augusto por 21000, ele deu 10500 de entrada e entrego dia 30"

3. registrar_despesa:
Extraia:
cliente
descricao
categoria
valor

Exemplo:
"gastei 3200 de gradil pro Augusto"

4. registrar_recebimento:
Extraia:
cliente
descricao
valor

Exemplo:
"Augusto me pagou mais 5000"

5. consultar_obra:
Quando perguntarem quanto gastou, recebeu, falta receber ou situação de um cliente.

Nunca invente valores.
Se alguma informação não existir, use null.

Responda SOMENTE JSON válido neste formato:

{{
  "acao": "",
  "cliente": null,
  "servico": null,
  "descricao": null,
  "categoria": null,
  "valor": null,
  "valor_total": null,
  "valor_entrada": null,
  "prazo_entrega": null
}}

Mensagem:
{texto}
"""

    resposta = openai.responses.create(
        model="gpt-6-luna",
        input=prompt
    )

    texto_resposta = resposta.output_text.strip()

    if texto_resposta.startswith("```"):
        texto_resposta = texto_resposta.replace("```json", "")
        texto_resposta = texto_resposta.replace("```", "")
        texto_resposta = texto_resposta.strip()

    return json.loads(texto_resposta)


def mostrar_confirmacao(chat_id, dados):
    acao = dados.get("acao")

    if acao == "cadastrar_cliente":
        mensagem = (
            "👤 Novo cliente\n\n"
            f"Nome: {dados.get('cliente')}\n\n"
            "Deseja cadastrar?"
        )

    elif acao == "criar_obra":
        mensagem = (
            "🛠 Nova obra/serviço\n\n"
            f"Cliente: {dados.get('cliente')}\n"
            f"Serviço: {dados.get('servico')}\n"
            f"Valor total: R$ {dados.get('valor_total') or 0:,.2f}\n"
            f"Entrada: R$ {dados.get('valor_entrada') or 0:,.2f}\n"
            f"Prazo: {dados.get('prazo_entrega') or 'não informado'}\n\n"
            "Confirmar?"
        )

    elif acao == "registrar_despesa":
        mensagem = (
            "💸 Nova despesa\n\n"
            f"Cliente: {dados.get('cliente')}\n"
            f"Descrição: {dados.get('descricao')}\n"
            f"Categoria: {dados.get('categoria') or 'não informada'}\n"
            f"Valor: R$ {dados.get('valor') or 0:,.2f}\n\n"
            "Confirmar lançamento?"
        )

    elif acao == "registrar_recebimento":
        mensagem = (
            "💰 Novo recebimento\n\n"
            f"Cliente: {dados.get('cliente')}\n"
            f"Descrição: {dados.get('descricao') or 'Recebimento'}\n"
            f"Valor: R$ {dados.get('valor') or 0:,.2f}\n\n"
            "Confirmar recebimento?"
        )

    else:
        return

    botoes = [
        [
            {
                "text": "✅ Confirmar",
                "callback_data": "confirmar"
            },
            {
                "text": "❌ Cancelar",
                "callback_data": "cancelar"
            }
        ]
    ]

    enviar_mensagem(chat_id, mensagem, botoes)


def executar_pendencia(chat_id):
    pendencia = pegar_pendencia(chat_id)

    if not pendencia:
        enviar_mensagem(
            chat_id,
            "Não existe nenhum lançamento aguardando confirmação."
        )
        return

    acao = pendencia["acao"]
    dados = pendencia["dados"]

    if acao == "cadastrar_cliente":

        nome = dados.get("cliente")

        supabase.table("clientes").insert({
            "nome": nome,
            "criado_por": str(chat_id)
        }).execute()

        enviar_mensagem(
            chat_id,
            f"✅ Cliente {nome} cadastrado."
        )

    elif acao == "criar_obra":

        nome_cliente = dados.get("cliente")

        clientes = buscar_cliente_por_nome(nome_cliente)

        if clientes:
            cliente = clientes[0]

        else:
            resultado = supabase.table("clientes").insert({
                "nome": nome_cliente,
                "criado_por": str(chat_id)
            }).execute()

            cliente = resultado.data[0]

        resultado_obra = supabase.table("obras").insert({
            "cliente_id": cliente["id"],
            "nome": dados.get("servico") or f"Serviço - {nome_cliente}",
            "descricao": dados.get("servico"),
            "valor_total": dados.get("valor_total") or 0,
            "prazo_entrega": dados.get("prazo_entrega"),
            "status": "aberta"
        }).execute()

        obra = resultado_obra.data[0]

        entrada = dados.get("valor_entrada") or 0

        if entrada > 0:
            supabase.table("movimentacoes").insert({
                "obra_id": obra["id"],
                "tipo": "entrada",
                "descricao": "Entrada inicial",
                "categoria": "Recebimento",
                "valor": entrada,
                "pago": True,
                "criado_por": str(chat_id)
            }).execute()

        saldo = (dados.get("valor_total") or 0) - entrada

        enviar_mensagem(
            chat_id,
            "✅ Obra cadastrada!\n\n"
            f"Cliente: {nome_cliente}\n"
            f"Valor total: R$ {(dados.get('valor_total') or 0):,.2f}\n"
            f"Recebido: R$ {entrada:,.2f}\n"
            f"A receber: R$ {saldo:,.2f}"
        )

    elif acao == "registrar_despesa":

        cliente, obra = buscar_obra_por_cliente(
            dados.get("cliente")
        )

        if not cliente:
            enviar_mensagem(
                chat_id,
                "❌ Não encontrei esse cliente."
            )

        elif not obra:
            enviar_mensagem(
                chat_id,
                "❌ Encontrei o cliente, mas ele não possui uma obra aberta."
            )

        else:
            supabase.table("movimentacoes").insert({
                "obra_id": obra["id"],
                "tipo": "despesa",
                "descricao": dados.get("descricao") or "Despesa",
                "categoria": dados.get("categoria"),
                "valor": dados.get("valor"),
                "pago": True,
                "criado_por": str(chat_id)
            }).execute()

            enviar_mensagem(
                chat_id,
                "✅ Despesa registrada.\n\n"
                f"Cliente: {cliente['nome']}\n"
                f"Valor: R$ {dados.get('valor'):,.2f}"
            )

    elif acao == "registrar_recebimento":

        cliente, obra = buscar_obra_por_cliente(
            dados.get("cliente")
        )

        if not cliente:
            enviar_mensagem(
                chat_id,
                "❌ Não encontrei esse cliente."
            )

        elif not obra:
            enviar_mensagem(
                chat_id,
                "❌ Esse cliente não possui uma obra aberta."
            )

        else:
            supabase.table("movimentacoes").insert({
                "obra_id": obra["id"],
                "tipo": "entrada",
                "descricao": dados.get("descricao") or "Recebimento",
                "categoria": "Recebimento",
                "valor": dados.get("valor"),
                "pago": True,
                "criado_por": str(chat_id)
            }).execute()

            enviar_mensagem(
                chat_id,
                "✅ Recebimento registrado.\n\n"
                f"Cliente: {cliente['nome']}\n"
                f"Valor: R$ {dados.get('valor'):,.2f}"
            )

    excluir_pendencia(chat_id)


def consultar_obra(chat_id, nome_cliente):

    cliente, obra = buscar_obra_por_cliente(nome_cliente)

    if not cliente:
        enviar_mensagem(
            chat_id,
            "❌ Não encontrei esse cliente."
        )
        return

    if not obra:
        enviar_mensagem(
            chat_id,
            "Esse cliente não possui obra aberta."
        )
        return

    movimentos = (
        supabase
        .table("movimentacoes")
        .select("*")
        .eq("obra_id", obra["id"])
        .execute()
    ).data or []

    entradas = sum(
        float(m["valor"])
        for m in movimentos
        if m["tipo"] == "entrada"
    )

    despesas = sum(
        float(m["valor"])
        for m in movimentos
        if m["tipo"] == "despesa"
    )

    valor_total = float(obra["valor_total"] or 0)

    falta_receber = valor_total - entradas

    resultado_atual = entradas - despesas

    enviar_mensagem(
        chat_id,
        "📊 Resumo da obra\n\n"
        f"Cliente: {cliente['nome']}\n"
        f"Serviço: {obra['nome']}\n\n"
        f"💵 Valor contratado: R$ {valor_total:,.2f}\n"
        f"✅ Recebido: R$ {entradas:,.2f}\n"
        f"🕐 Falta receber: R$ {falta_receber:,.2f}\n"
        f"💸 Gastos: R$ {despesas:,.2f}\n"
        f"📈 Caixa atual da obra: R$ {resultado_atual:,.2f}"
    )


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


@app.post("/webhook")
def webhook():

    if SECRET_TOKEN:
        recebido = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token"
        )

        if recebido != SECRET_TOKEN:
            return "Não autorizado", 403

    dados = request.get_json(silent=True) or {}

    callback = dados.get("callback_query")

    if callback:
        chat_id = callback["message"]["chat"]["id"]
        escolha = callback["data"]

        if escolha == "confirmar":
            executar_pendencia(chat_id)

        elif escolha == "cancelar":
            excluir_pendencia(chat_id)

            enviar_mensagem(
                chat_id,
                "❌ Lançamento cancelado."
            )

        requests.post(
            f"{TELEGRAM_API}/answerCallbackQuery",
            json={
                "callback_query_id": callback["id"]
            },
            timeout=10
        )

        return "ok", 200

    mensagem = dados.get("message")

    if not mensagem:
        return "ok", 200

    chat_id = mensagem["chat"]["id"]
    texto = mensagem.get("text", "").strip()

    if texto == "/start":
        enviar_mensagem(
            chat_id,
            "🤖 JT Financeiro\n\n"
            "Pode falar comigo normalmente.\n\n"
            "Exemplos:\n"
            "• Cadastre o cliente Augusto\n"
            "• Fechei um portão com Augusto por 21 mil e recebi 10.500 de entrada\n"
            "• Gastei 3200 de gradil pro Augusto\n"
            "• Augusto me pagou 5000\n"
            "• Quanto já gastei no Augusto?"
        )

        return "ok", 200

    try:
        interpretacao = interpretar_texto(texto)

        acao = interpretacao.get("acao")

        if acao in [
            "cadastrar_cliente",
            "criar_obra",
            "registrar_despesa",
            "registrar_recebimento"
        ]:
            salvar_pendencia(
                chat_id,
                acao,
                interpretacao
            )

            mostrar_confirmacao(
                chat_id,
                interpretacao
            )

        elif acao == "consultar_obra":
            consultar_obra(
                chat_id,
                interpretacao.get("cliente")
            )

        elif acao == "consultar_clientes":
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
                    "Nenhum cliente cadastrado."
                )

            else:
                lista = "\n".join(
                    f"• {c['nome']}"
                    for c in clientes
                )

                enviar_mensagem(
                    chat_id,
                    f"👥 Clientes:\n\n{lista}"
                )

        else:
            enviar_mensagem(
                chat_id,
                "Não consegui entender esse lançamento.\n\n"
                "Pode escrever de outra forma?"
            )

    except Exception as erro:
        print("ERRO:", erro)

        enviar_mensagem(
            chat_id,
            "❌ Tive um erro ao interpretar essa mensagem."
        )

    return "ok", 200
