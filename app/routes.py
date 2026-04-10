import os
import requests
import re
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from app.services import (
    limpar_mensagem, agendar_servico, realizar_checkin, 
    gerar_dashboard, atualizar_custos_da_loja,
    atualizar_preco_servico_db, processar_texto_com_ia
)

router = APIRouter()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

class NovosCustos(BaseModel):
    aluguel: float
    produtos: float

class AlterarPreco(BaseModel):
    servico: str
    novo_valor: float

def enviar_mensagem_telegram(chat_id: int, texto: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erro Telegram: {e}")

@router.post("/telegram/receber")
async def bot_recebe_mensagem(request: Request):
    try:
        dados = await request.json()
        if "message" not in dados:
            return {"status": "ignorado"}
            
        chat_id = dados["message"]["chat"]["id"]
        texto_cru = dados["message"].get("text", "")
        nome_cliente = dados["message"]["chat"].get("first_name", "Cliente")
        
        texto_limpo = limpar_mensagem(texto_cru)
        
        # Saudações
        if texto_limpo in ["ola", "olá", "oi", "bom dia", "boa tarde", "boa noite"]:
            enviar_mensagem_telegram(chat_id, f"Olá {nome_cliente}! ✂️ Sou o assistente da Barbearia. O que deseja agendar e para qual horário?")
            return {"status": "ok"}

        hora = None
        servico = "Corte Simples"
        
        # --- 1. TENTATIVA COM IA (GEMINI) ---
        try:
            resultado_ia = processar_texto_com_ia(texto_cru)
            if resultado_ia and isinstance(resultado_ia, dict):
                res_hora = resultado_ia.get("hora")
                if res_hora and str(res_hora).lower() != "null":
                    hora = res_hora
                    servico = resultado_ia.get("servico") or "Corte Simples"
        except Exception as e:
            print(f"Erro na IA: {e}")

        # --- 2. PLANO B: REGEX REFORÇADO (Se a IA falhar ou não achar hora) ---
        if not hora:
            busca = re.search(r'(\d{1,2}:\d{2})', texto_cru)
            if busca:
                hora = busca.group(1)

        # --- 3. RESPOSTA DE ERRO ---
        if not hora:
            enviar_mensagem_telegram(chat_id, f"Não entendi o horário, {nome_cliente}. Use o formato 14:30 (exemplo: 'corte as 14:30')")
            return {"status": "ok"}
                
        # --- 4. AGENDAMENTO NO BANCO ---
        resposta = agendar_servico(nome_cliente, servico, "hoje", hora, 35.0)
        enviar_mensagem_telegram(chat_id, resposta)
        return {"status": "ok"}

    except Exception as e:
        print(f"Erro Crítico no Webhook: {e}")
        return {"status": "erro"}

@router.get("/painel", response_class=HTMLResponse)
def ver_painel_grafico():
    return """
    <html>
        <head><title>Painel Barbearia</title></head>
        <body>
            <h1>Painel do Barbeiro Ativo</h1>
            <p>Consulte o console para logs de agendamento.</p>
        </body>
    </html>
    """