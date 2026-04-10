import os
import requests
import re
import json
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from app.services import (
    limpar_mensagem, 
    agendar_servico, 
    realizar_checkin, 
    gerar_dashboard, 
    atualizar_custos_da_loja,
    atualizar_preco_servico_db,
    processar_texto_com_ia
)

router = APIRouter()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# --- MODELOS DE DADOS ---

class NovosCustos(BaseModel):
    aluguel: float
    produtos: float

class AlterarPreco(BaseModel):
    servico: str
    novo_valor: float

# --- UTILITÁRIOS ---

def enviar_mensagem_telegram(chat_id: int, texto: str):
    url = f"[https://api.telegram.org/bot](https://api.telegram.org/bot){TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")

# --- WEBHOOK DO TELEGRAM ---

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
        
        # Resposta amigável para saudações
        if texto_limpo in ["ola", "olá", "oi", "bom dia", "boa tarde", "boa noite"]:
            enviar_mensagem_telegram(chat_id, f"Olá {nome_cliente}! ✂️ Sou o assistente da Barbearia. O que deseja agendar e para qual horário? (Ex: Corte às 15:00)")
            return {"status": "ok"}

        # --- PASSO 1: TENTATIVA COM INTELIGÊNCIA ARTIFICIAL ---
        hora = None
        servico = "Corte Simples"
        
        try:
            resultado_ia = processar_texto_com_ia(texto_cru)
            # Garante que resultado_ia seja um dicionário
            if isinstance(resultado_ia, dict):
                hora = resultado_ia.get("hora")
                servico = resultado_ia.get("servico") or "Corte Simples"
        except Exception as e:
            print(f"Falha na IA: {e}")

        # --- PASSO 2: PLANO B (REGEX MANUAL) ---
        # Caso a IA falhe ou não retorne hora, buscamos padrões como 14:30 ou 14h30
        if not hora:
            busca_hora = re.search(r'(\d{1,2}[:hH]\d{2})', texto_cru)
            if busca_hora:
                hora = busca_hora.group(1).replace('h', ':').replace('H', ':')

        # --- PASSO 3: VALIDAÇÃO FINAL ---
        if not hora:
            enviar_mensagem_telegram(chat_id, f"Poxa {nome_cliente}, não consegui entender o horário. Pode enviar no formato 14:30?")
            return {"status": "ok"}
                
        # Realiza o agendamento no Supabase
        resposta_sistema = agendar_servico(
            cliente=nome_cliente, 
            servico=servico,
            data="hoje", 
            hora=hora, 
            valor=35.00 
        )
        
        enviar_mensagem_telegram(chat_id, resposta_sistema)
        return {"status": "ok"}

    except Exception as e:
        print(f"Erro crítico no webhook: {e}")
        return {"status": "erro"}

# --- ROTAS ADMINISTRATIVAS ---

@router.put("/checkin/{cliente}")
def fazer_checkin_cliente(cliente: str):
    sucesso = realizar_checkin(cliente)
    if sucesso:
        return {"mensagem": f"Check-in do cliente '{cliente}' efetuado!"}
    raise HTTPException(status_code=404, detail="Agendamento não encontrado.")

@router.put("/servicos/preco")
def mudar_preco_servico(dados: AlterarPreco):
    sucesso = atualizar_preco_servico_db(dados.servico, dados.novo_valor)
    if sucesso:
        return {"mensagem": f"Preço de '{dados.servico}' atualizado para R$ {dados.novo_valor}"}
    raise HTTPException(status_code=400, detail="Erro ao atualizar preço.")

@router.put("/configuracoes")
def mudar_custos_da_barbearia(dados: NovosCustos):
    novo_total = atualizar_custos_da_loja(dados.aluguel, dados.produtos)
    return {"mensagem": f"Gastos fixos atualizados para R$ {novo_total}"}

# --- DASHBOARD ---

@router.get("/dashboard")
def consultar_dashboard():
    return gerar_dashboard()

@router.get("/painel", response_class=HTMLResponse)
def ver_painel_grafico():
    return """
    <!DOCTYPE html>
    <html lang="pt">
    <head>
        <meta charset="UTF-8">
        <title>Painel do Barbeiro</title>
        <script src="[https://cdn.jsdelivr.net/npm/chart.js](https://cdn.jsdelivr.net/npm/chart.js)"></script>
        <style>
            body { font-family: 'Segoe UI', Tahoma, sans-serif; text-align: center; background-color: #f4f4f9; padding: 20px; }
            .container { max-width: 600px; margin: auto; background: white; padding: 30px; border-radius: 15px; box-shadow: 0px 4px 15px rgba(0,0,0,0.1); }
            h1 { color: #333; }
            .conselho { background-color: #d1ecf1; padding: 15px; border-radius: 8px; color: #0c5460; font-weight: bold; margin-top: 25px; border-left: 5px solid #0c5460; }
            canvas { margin-top: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Dashboard Barbearia ✂️</h1>
            <canvas id="graficoPizza"></canvas>
            <div class="conselho" id="textoConselho">Analisando dados financeiros...</div>
        </div>
        <script>
            async def carregarDashboard() {
                try {
                    const res = await fetch('/dashboard');
                    const dados = await res.json();
                    
                    document.getElementById('textoConselho').innerText = "IA: " + dados.o_que_fazer;
                    
                    const ctx = document.getElementById('graficoPizza').getContext('2d');
                    new Chart(ctx, {
                        type: 'pie',
                        data: {
                            labels: ['Faturamento', 'Gastos Fixos', 'Lucro Real'],
                            datasets: [{
                                data: [dados.faturamento_bruto, dados.gastos_fixos_da_loja, dados.lucro_liquido_real],
                                backgroundColor: ['#2ecc71', '#e74c3c', '#3498db']
                            }]
                        },
                        options: { responsive: true }
                    });
                } catch (err) {
                    console.error("Erro ao carregar dashboard:", err);
                }
            }
            carregarDashboard();
        </script>
    </body>
    </html>
    """