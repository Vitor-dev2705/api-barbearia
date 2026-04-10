import os
import requests
import re
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from app.services import (
    limpar_mensagem, agendar_servico, realizar_checkin, 
    gerar_dashboard, atualizar_custos_da_loja,
    atualizar_preco_servico_db, processar_texto_com_ia
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
# INTEGRAÇÃO EXTERNA (TELEGRAM)
# ==========================================
def enviar_mensagem_telegram(chat_id: int, texto: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto}
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
        # 1. Extração de Dados Iniciais
        dados = await request.json()
        if "message" not in dados:
            return {"status": "ignorado"}
            
        chat_id = dados["message"]["chat"]["id"]
        texto_cru = dados["message"].get("text", "")
        nome_cliente = dados["message"]["chat"].get("first_name", "Cliente")
        
        texto_limpo = limpar_mensagem(texto_cru)
        
        if texto_limpo in ["ola", "olá", "oi", "bom dia", "boa tarde", "boa noite"]:
            enviar_mensagem_telegram(chat_id, f"Olá {nome_cliente}! ✂️ Sou o assistente da Barbearia. O que deseja agendar e para qual horário?")
            return {"status": "ok"}

        # Valores padrão caso as extrações falhem
        hora = None
        data_agendamento = datetime.now().strftime("%Y-%m-%d")
        servico = "Corte Simples"
        
        # 2. Processamento com Inteligência Artificial
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

        # 3. Fallback (Plano B via Regex)
        if not hora:
            busca = re.search(r'(\d{1,2})\s*[:hH]\s*(\d{2})?', texto_cru)
            if busca:
                h = busca.group(1).zfill(2)
                m = busca.group(2) if busca.group(2) else "00"
                hora = f"{h}:{m}"

        if not hora:
            enviar_mensagem_telegram(chat_id, f"Poxa {nome_cliente}, não consegui entender o horário. Pode enviar no formato 14:30 ou 14h?")
            return {"status": "ok"}
                
        # 4. Efetivação do Agendamento no Banco
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