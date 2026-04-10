import os
import requests
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from app.services import limpar_mensagem, agendar_servico, realizar_checkin, gerar_dashboard, atualizar_custos_da_loja

router = APIRouter()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

class NovosCustos(BaseModel):
    aluguel: float
    produtos: float

def enviar_mensagem_telegram(chat_id: int, texto: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto}
    requests.post(url, json=payload)

@router.post("/telegram/receber")
async def bot_recebe_mensagem(request: Request):
    try:
        dados = await request.json()
        
        if "message" not in dados:
            return {"status": "ignorado"}
            
        chat_id = dados["message"]["chat"]["id"]
        texto_cru = dados["message"].get("text", "")
        nome_cliente = dados["message"]["chat"].get("first_name", "Cliente")
        
        mensagem_processada = limpar_mensagem(texto_cru)
        
        if mensagem_processada in ["ola", "olá", "oi", "bom dia", "boa tarde"]:
            enviar_mensagem_telegram(chat_id, f"Olá {nome_cliente}! Eu sou o assistente da Barbearia. Para agendar, mande a hora desejada (ex: 14:00).")
            return {"status": "ok"}

        hora_detectada = None
        palavras = mensagem_processada.split()
        for p in palavras:
            if ":" in p and len(p) >= 4:
                hora_detectada = p
                break
        
        if not hora_detectada:
            enviar_mensagem_telegram(chat_id, "Ainda não consegui entender a hora. Pode enviar no formato HH:MM? Exemplo: 15:30")
            return {"status": "ok"}
                
        resposta_do_sistema = agendar_servico(
            cliente=nome_cliente, 
            servico="Corte Simples",
            data="hoje", 
            hora=hora_detectada, 
            valor=35.00
        )
        
        enviar_mensagem_telegram(chat_id, resposta_do_sistema)
        return {"status": "ok"}
    
    except Exception as e:
        return {"status": "erro"}

@router.put("/checkin/{cliente}")
def fazer_checkin_cliente(cliente: str):
    sucesso = realizar_checkin(cliente)
    if sucesso:
        return {"mensagem": f"Check-in do {cliente} efetuado!"}
    return {"erro": f"Não encontrei marcação pendente para {cliente}."}

@router.put("/configuracoes")
def mudar_custos_da_barbearia(dados: NovosCustos):
    novo_total = atualizar_custos_da_loja(dados.aluguel, dados.produtos)
    return {"mensagem": f"Sucesso! Os novos gastos fixos agora são R$ {novo_total}"}

@router.get("/dashboard")
def consultar_dashboard():
    return gerar_dashboard()

@router.get("/painel", response_class=HTMLResponse)
def ver_painel_grafico():
    codigo_html = """
    <!DOCTYPE html>
    <html lang="pt">
    <head>
        <meta charset="UTF-8">
        <title>Painel do Barbeiro</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; background-color: #f4f4f9; }
            .container { width: 50%; margin: auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0px 0px 10px rgba(0,0,0,0.1); margin-top: 50px;}
            h1 { color: #333; }
            .conselho { background-color: #e3f2fd; padding: 15px; border-radius: 5px; color: #0d47a1; font-weight: bold; margin-top: 20px;}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Dashboard Financeiro ✂️</h1>
            <canvas id="graficoPizza"></canvas>
            <div class="conselho" id="textoConselho">A carregar conselho financeiro...</div>
        </div>
        <script>
            fetch('/dashboard')
                .then(resposta => resposta.json())
                .then(dados => {
                    document.getElementById('textoConselho').innerText = "Conselho da IA: " + dados.o_que_fazer;
                    const valores = [dados.faturamento_bruto, dados.gastos_fixos_da_loja, dados.lucro_liquido_real];
                    const ctx = document.getElementById('graficoPizza').getContext('2d');
                    new Chart(ctx, {
                        type: 'pie',
                        data: {
                            labels: ['Faturamento Bruto', 'Gastos Fixos', 'Lucro Líquido'],
                            datasets: [{
                                data: valores,
                                backgroundColor: ['#4caf50', '#f44336', '#2196f3'],
                                hoverOffset: 4
                            }]
                        }
                    });
                })
                .catch(erro => console.error("Erro ao carregar dados:", erro));
        </script>
    </body>
    </html>
    """
    return codigo_html