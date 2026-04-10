import os
import requests
import re
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from app.services import (
    limpar_mensagem, agendar_servico, realizar_checkin, 
    gerar_dashboard, atualizar_custos_da_loja,
    atualizar_preco_servico_db, processar_texto_com_ia,
    obter_duracao_servico, obter_slots_livres
)

# ==========================================
# CONFIGURAÇÕES E MODELOS DE DADOS
# ==========================================
router = APIRouter()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

class NovosCustos(BaseModel):
    aluguel: float
    produtos: float

class AlterarPreco(BaseModel):
    servico: str
    novo_valor: float

# ==========================================
# INTEGRAÇÃO EXTERNA (TELEGRAM E BOTÕES)
# ==========================================
def enviar_mensagem_telegram(chat_id: int, texto: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass

def enviar_mensagem_com_botoes(chat_id: int, texto: str, botoes: list):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "reply_markup": {"inline_keyboard": botoes}
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass

# ==========================================
# WEBHOOK PRINCIPAL (RECEPÇÃO DE MENSAGENS)
# ==========================================
@router.post("/telegram/receber")
async def bot_recebe_mensagem(request: Request):
    try:
        dados = await request.json()

        # FLUXO 1: INTERAÇÃO COM BOTÕES (CALLBACK QUERY)
        if "callback_query" in dados:
            query = dados["callback_query"]
            chat_id = query["message"]["chat"]["id"]
            dados_clique = query["data"]
            nome_cliente = query["from"]["first_name"]

            if dados_clique.startswith("S|"):
                servico = dados_clique.split("|")[1]
                botoes_dias = []
                hoje = datetime.now()
                for i in range(5):
                    data_calc = hoje + timedelta(days=i)
                    data_iso = data_calc.strftime("%Y-%m-%d")
                    texto_botao = data_calc.strftime("%d/%m")
                    if i == 0: texto_botao = f"Hoje ({texto_botao})"
                    elif i == 1: texto_botao = f"Amanhã ({texto_botao})"
                    botoes_dias.append([{"text": texto_botao, "callback_data": f"D|{servico}|{data_iso}"}])
                
                enviar_mensagem_com_botoes(chat_id, f"📅 Para qual dia você quer o {servico}?", botoes_dias)

            elif dados_clique.startswith("D|"):
                _, servico, data_iso = dados_clique.split("|")
                duracao = obter_duracao_servico(servico)
                horarios_livres = obter_slots_livres(data_iso, duracao)
                
                if not horarios_livres:
                    enviar_mensagem_telegram(chat_id, "Puxa, estamos lotados ou fechados neste dia. Escolha outra data!")
                else:
                    botoes_horas = []
                    linha = []
                    for h in horarios_livres:
                        linha.append({"text": h, "callback_data": f"H|{servico}|{data_iso}|{h}"})
                        if len(linha) == 3:
                            botoes_horas.append(linha)
                            linha = []
                    if linha: 
                        botoes_horas.append(linha)
                    
                    enviar_mensagem_com_botoes(chat_id, "⏰ Selecione um horário livre:", botoes_horas)

            elif dados_clique.startswith("H|"):
                _, servico, data_iso, hora = dados_clique.split("|")
                resposta = agendar_servico(nome_cliente, servico, data_iso, hora, 35.0)
                enviar_mensagem_telegram(chat_id, resposta)

            return {"status": "ok"}

        # FLUXO 2: MENSAGEM DE TEXTO COMUM
        if "message" not in dados:
            return {"status": "ignorado"}
            
        chat_id = dados["message"]["chat"]["id"]
        texto_cru = dados["message"].get("text", "")
        nome_cliente = dados["message"]["chat"].get("first_name", "Cliente")
        texto_limpo = limpar_mensagem(texto_cru)
        
        if texto_limpo in ["ola", "olá", "oi", "bom dia", "boa tarde", "boa noite", "menu"]:
            botoes_servicos = [
                [{"text": "✂️ Corte Simples", "callback_data": "S|Corte Simples"}],
                [{"text": "🧔 Barba", "callback_data": "S|Barba"}],
                [{"text": "✂️+🧔 Corte e Barba", "callback_data": "S|Corte e Barba"}]
            ]
            enviar_mensagem_com_botoes(chat_id, f"Olá {nome_cliente}! Qual serviço você deseja?", botoes_servicos)
            return {"status": "ok"}

        hora = None
        data_agendamento = datetime.now().strftime("%Y-%m-%d")
        servico = "Corte Simples"
        
        try:
            resultado_ia = processar_texto_com_ia(texto_cru)
            if resultado_ia and isinstance(resultado_ia, dict):
                res_hora = resultado_ia.get("hora")
                res_data = resultado_ia.get("data")
                
                if res_hora and str(res_hora).lower() != "null":
                    hora = res_hora
                    servico = resultado_ia.get("servico") or "Corte Simples"
                
                if res_data and str(res_data).lower() != "null":
                    data_agendamento = res_data
        except Exception:
            pass

        if not hora:
            busca = re.search(r'(\d{1,2})\s*[:hH]\s*(\d{2})?', texto_cru)
            if busca:
                h = busca.group(1).zfill(2)
                m = busca.group(2) if busca.group(2) else "00"
                hora = f"{h}:{m}"

        if not hora:
            enviar_mensagem_telegram(chat_id, f"Não entendi, {nome_cliente}. Digite 'Oi' para ver o menu de botões ou mande o horário desejado (ex: 14:30).")
            return {"status": "ok"}
                
        resposta = agendar_servico(nome_cliente, servico, data_agendamento, hora, 35.0)
        enviar_mensagem_telegram(chat_id, resposta)
        return {"status": "ok"}

    except Exception:
        return {"status": "erro"}

# ==========================================
# INTERFACE DO PAINEL WEB
# ==========================================
@router.get("/painel", response_class=HTMLResponse)
def ver_painel_grafico():
    return """
    <html>
        <head>
            <meta charset="UTF-8">
            <title>Painel Barbearia</title>
            <style>
                body { font-family: sans-serif; text-align: center; padding: 50px; background: #f4f4f9; }
                .card { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); display: inline-block; }
                h1 { color: #333; }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Painel do Barbeiro Ativo ✂️</h1>
                <p>O sistema está monitorando o Telegram e o Banco de Dados.</p>
                <hr>
                <p>Consulte os logs no Render para detalhes técnicos.</p>
            </div>
        </body>
    </html>
    """