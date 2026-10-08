from flask import Flask, request
import os
import json
import tempfile
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
        timeout=20
    )

    print("TELEGRAM:", resposta.text)


def transcrever_audio(file_id):
    # Descobre o caminho do arquivo dentro do Telegram
    resposta = requests.get(
        f"{TELEGRAM_API}/getFile",
        params={"file_id": file_id},
        timeout=20
    )

    dados = resposta.json()

    if not dados.get("ok"):
        raise Exception("Telegram não conseguiu localizar o áudio.")

    file_path = dados["result"]["file_path"]

    # Baixa o áudio
    url_audio = (
        f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    )

    audio = requests.get(
        url_audio,
        timeout=30
    )

    audio.raise_for_status()

    # Salva temporariamente como OGG
    with tempfile.NamedTemporaryFile(
        suffix=".ogg",
        delete=False
    ) as arquivo:
        arquivo.write(audio.content)
        caminho = arquivo.name

    try:
        with open(caminho, "rb") as arquivo_audio:
            transcricao = openai.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=arquivo_audio,
                language="pt"
            )

        return transcricao.text.strip()

    finally:
        try:
            os.remove(caminho)
        except Exception:
            pass


def buscar_cliente_por_nome(nome):
    if not nome:
        return []

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
Você interpreta mensagens financeiras da empresa JT Metal Serralheria.

Hoje é {hoje}.

A pessoa pode falar de maneira informal, como fala normalmente no WhatsApp.

Identifique UMA ação principal.

Ações possíveis:
- cadastrar_cliente
- criar_obra
- registrar_despesa
- registrar_recebimento
- consultar_obra
- consultar_clientes
- desconhecido

REGRAS:

CADASTRAR CLIENTE
Exemplos:
"cadastre o Augusto"
"cliente novo João"
"coloca o Carlos como cliente"

CRIAR OBRA / VENDA
Exemplos:
"fechei um portão pro Augusto por 12 mil e ele deu 6 mil de entrada"
"peguei um serviço do Carlos de 8 mil"
"vendi um gradil pro João por 20 mil, recebeu 10 mil de entrada"

Extraia:
cliente
servico
valor_total
valor_entrada
prazo_entrega

REGISTRAR DESPESA
Exemplos:
"gastei mil reais de ferro pro Augusto"
"paguei 350 de tinta na obra do João"
"comprei 2200 de material pro Carlos"

Extraia:
cliente
descricao
categoria
valor

REGISTRAR RECEBIMENTO
Exemplos:
"Augusto me pagou 5000"
"entrou mais 3 mil do João"
"recebi 1200 do Carlos"

CONSULTAR OBRA
Exemplos:
"quanto já gastei no Augusto"
"quanto o Carlos ainda me deve"
"como está a obra do João"

CONSULTAR CLIENTES
Exemplos:
"quais clientes eu tenho"
"me mostra os clientes"

Valores falados como:
"mil" = 1000
"mil e quinhentos" = 1500
"12 mil" = 12000
"vinte e um mil" = 21000

Nunca invente informações.
Se não existir informação, use null.

Responda SOMENTE JSON válido, sem markdown:

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
        model="gpt-4.1-mini",
        input=prompt
    )

    texto_resposta = resposta.output_text.strip()

    if texto_resposta.startswith("```"):
        texto_resposta = (
            texto_resposta
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )

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
            "🛠 Nova obra / serviço\n\n"
            f"Cliente: {dados.get('cliente')}\n"
            f"Serviço: {dados.get('servico') or 'Não informado'}\n"
            f"Valor total: R$ {float(dados.get('valor_total') or 0):,.2f}\n"
            f"Entrada: R$ {float(dados.get('valor_entrada') or 0):,.2f}\n"
            f"Prazo: {dados.get('prazo_entrega') or 'Não informado'}\n\n"
            "Confirmar?"
        )

    elif acao == "registrar_despesa":
        mensagem = (
            "💸 Nova despesa\n\n"
            f"Cliente: {dados.get('cliente')}\n"
            f"Descrição: {dados.get('descricao') or 'Despesa'}\n"
            f"Categoria: {dados.get('categoria') or 'Não informada'}\n"
            f"Valor: R$ {float(dados.get('valor') or 0):,.2f}\n\n"
            "Confirmar lançamento?"
        )

    elif acao == "registrar_recebimento":
        mensagem = (
            "💰 Novo recebimento\n\n"
            f"Cliente: {dados.get('cliente')}\n"
            f"Valor: R$ {float(dados.get('valor') or 0):,.2f}\n\n"
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
            "Não existe lançamento aguardando confirmação."
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

        entrada = float(dados.get("valor_entrada") or 0)

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

        valor_total = float(dados.get("valor_total") or 0)
        saldo = valor_total - entrada

        enviar_mensagem(
            chat_id,
            "✅ Obra cadastrada!\n\n"
            f"Cliente: {nome_cliente}\n"
            f"Valor total: R$ {valor_total:,.2f}\n"
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
                "❌ Encontrei o cliente, mas ele não possui obra aberta."
            )

        else:
            valor = float(dados.get("valor") or 0)

            supabase.table("movimentacoes").insert({
                "obra_id": obra["id"],
                "tipo": "despesa",
                "descricao": dados.get("descricao") or "Despesa",
                "categoria": dados.get("categoria"),
                "valor": valor,
                "pago": True,
                "criado_por": str(chat_id)
            }).execute()

            enviar_mensagem(
                chat_id,
                "✅ Despesa registrada.\n\n"
                f"Cliente: {cliente['nome']}\n"
                f"Valor: R$ {valor:,.2f}"
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
                "❌ Esse cliente não possui obra aberta."
            )

        else:
            valor = float(dados.get("valor") or 0)

            supabase.table("movimentacoes").insert({
                "obra_id": obra["id"],
                "tipo": "entrada",
                "descricao": dados.get("descricao") or "Recebimento",
                "categoria": "Recebimento",
                "valor": valor,
                "pago": True,
                "criado_por": str(chat_id)
            }).execute()

            enviar_mensagem(
                chat_id,
                "✅ Recebimento registrado.\n\n"
                f"Cliente: {cliente['nome']}\n"
                f"Valor: R$ {valor:,.2f}"
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


def processar_texto(chat_id, texto):
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
                "Não consegui entender.\n\n"
                "Tente falar de outra forma."
            )

    except Exception as erro:
        print("ERRO PROCESSAMENTO:", erro)

        enviar_mensagem(
            chat_id,
            "❌ Tive um erro ao interpretar essa mensagem."
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

    # BOTÕES DE CONFIRMAÇÃO
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

    # TEXTO
    texto = mensagem.get("text", "").strip()

    if texto == "/start":
        enviar_mensagem(
            chat_id,
            "🤖 JT Financeiro\n\n"
            "Pode escrever ou mandar áudio normalmente.\n\n"
            "Exemplos:\n"
            "• Cadastre o cliente Augusto\n"
            "• Fechei um portão pro Augusto por 21 mil e recebi 10.500 de entrada\n"
            "• Gastei 3200 de gradil pro Augusto\n"
            "• Augusto me pagou 5000\n"
            "• Quanto já gastei no Augusto?"
        )

        return "ok", 200

    # ÁUDIO DE VOZ
    voz = mensagem.get("voice")

    if voz:
        try:
            enviar_mensagem(
                chat_id,
                "🎙️ Recebi seu áudio. Estou transcrevendo..."
            )

            transcricao = transcrever_audio(
                voz["file_id"]
            )

            print("TRANSCRIÇÃO:", transcricao)

            enviar_mensagem(
                chat_id,
                f"📝 Entendi:\n\n{transcricao}"
            )

            processar_texto(
                chat_id,
                transcricao
            )

        except Exception as erro:
            print("ERRO AUDIO:", erro)

            enviar_mensagem(
                chat_id,
                "❌ Não consegui processar esse áudio."
            )

        return "ok", 200

    # ARQUIVO DE ÁUDIO
    audio = mensagem.get("audio")

    if audio:
        try:
            enviar_mensagem(
                chat_id,
                "🎙️ Recebi seu áudio. Estou transcrevendo..."
            )

            transcricao = transcrever_audio(
                audio["file_id"]
            )

            enviar_mensagem(
                chat_id,
                f"📝 Entendi:\n\n{transcricao}"
            )

            processar_texto(
                chat_id,
                transcricao
            )

        except Exception as erro:
            print("ERRO AUDIO:", erro)

            enviar_mensagem(
                chat_id,
                "❌ Não consegui processar esse áudio."
            )

        return "ok", 200

    # MENSAGEM NORMAL
    if texto:
        processar_texto(
            chat_id,
            texto
        )

    return "ok", 200
