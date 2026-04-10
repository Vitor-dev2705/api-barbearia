import os
import requests
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from app.services import (
    limpar_mensagem, 
    agendar_servico, 
    realizar_checkin, 
    gerar_dashboard, 
    atualizar_custos_da_loja,
    atualizar_preco_servico_db
)

router = APIRouter()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# --- MODELOS DE DADOS (PYDANTIC) ---

class NovosCustos(BaseModel):
    aluguel: float
    produtos: float

class AlterarPreco(BaseModel):
    servico: str
    novo_valor: float

# --- UTILITÁRIOS ---

def enviar_mensagem_telegram(chat_id: int, texto: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Erro ao enviar para Telegram: {e}")

# --- ROTAS DO TELEGRAM ---

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
            enviar_mensagem_telegram(chat_id, f"Olá {nome_cliente}! Sou o assistente da Barbearia. Para agendar, envie o horário desejado (ex: 14:00).")
            return {"status": "ok"}

        hora_detectada = None
        palavras = mensagem_processada.split()
        for p in palavras:
            if ":" in p and len(p) >= 4:
                hora_detectada = p
                break
        
        if not hora_detectada:
            enviar_mensagem_telegram(chat_id, "Não entendi o horário. Por favor, envie no formato HH:MM (exemplo: 15:30).")
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
        print(f"Erro no webhook: {e}")
        return {"status": "erro"}

# --- ROTAS ADMINISTRATIVAS (BARBEIRO) ---

@router.put("/checkin/{cliente}")
def fazer_checkin_cliente(cliente: str):
    sucesso = realizar_checkin(cliente)
    if sucesso:
        return {"mensagem": f"Check-in do cliente '{cliente}' efetuado!"}
    raise HTTPException(status_code=404, detail=f"Agendamento pendente para '{cliente}' não encontrado.")

@router.put("/servicos/preco")
def mudar_preco_servico(dados: AlterarPreco):
    sucesso = atualizar_preco_servico_db(dados.servico, dados.novo_valor)
    if sucesso:
        return {"mensagem": f"Preço de '{dados.servico}' atualizado para R$ {dados.novo_valor}"}
    raise HTTPException(status_code=400, detail="Erro ao atualizar preço. Verifique o nome do serviço.")

@router.put("/configuracoes")
def mudar_custos_da_barbearia(dados: NovosCustos):
    """Atualiza os gastos fixos da loja."""
    novo_total = atualizar_custos_da_loja(dados.aluguel, dados.produtos)
    return {"mensagem": f"Gastos fixos atualizados para R$ {novo_total}"}

# --- DASHBOARD E INTERFACE ---

@router.get("/dashboard")
def consultar_dashboard():
    """Retorna dados financeiros para o gráfico."""
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
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; text-align: center; background-color: #f4f4f9; padding: 20px; }
            .container { max-width: 600px; margin: auto; background: white; padding: 30px; border-radius: 15px; box-shadow: 0px 4px 15px rgba(0,0,0,0.1); }
            h1 { color: #2c3e50; margin-bottom: 25px; }
            .conselho { background-color: #d1ecf1; padding: 15px; border-radius: 8px; color: #0c5460; font-weight: bold; margin-top: 25px; border-left: 5px solid #0c5460; }
            canvas { margin-top: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Dashboard da Barbearia ✂️</h1>
            <canvas id="graficoPizza"></canvas>
            <div class="conselho" id="textoConselho">Carregando análise financeira...</div>
        </div>
        <script>
            fetch('/dashboard')
                .then(res => res.json())
                .then(dados => {
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
                })
                .catch(err => console.error("Erro ao carregar Dashboard:", err));
        </script>
    </body>
    </html>
    """
    return codigo_html