# app/routes.py
from fastapi import APIRouter
from fastapi.responses import HTMLResponse # <- Adicionei isto para podermos mostrar uma página web
from pydantic import BaseModel
from app.services import limpar_mensagem, agendar_servico, realizar_checkin, gerar_dashboard

router = APIRouter()

class RequisicaoWhatsApp(BaseModel):
    cliente: str
    texto_cru: str
    servico: str
    data: str
    hora_desejada: str
    valor: float

@router.post("/whatsapp/receber")
def bot_recebe_mensagem(dados: RequisicaoWhatsApp):
    mensagem_processada = limpar_mensagem(dados.texto_cru)
    print(f"Log interno -> Traduzido para: '{mensagem_processada}'")
    
    resposta = agendar_servico(dados.cliente, dados.servico, dados.data, dados.hora_desejada, dados.valor)
    return {"resposta_para_enviar": resposta}

@router.put("/checkin/{cliente}")
def fazer_checkin_cliente(cliente: str):
    sucesso = realizar_checkin(cliente)
    if sucesso:
        return {"mensagem": f"Check-in do {cliente} efetuado!"}
    return {"erro": f"Não encontrei marcação pendente para {cliente}."}

@router.get("/dashboard")
def consultar_dashboard():
    return gerar_dashboard()

# --- NOVO CÓDIGO: O VISUAL DO DASHBOARD ---

@router.get("/painel", response_class=HTMLResponse)
def ver_painel_grafico():
    """Esta rota cria uma página HTML completa com um gráfico de pizza que o barbeiro pode aceder."""
    
    # Eu criei esta página HTML com Javascript (Chart.js) embutido.
    # Ela vai ligar-se sozinha à nossa rota '/dashboard', pegar nos números e desenhar a pizza!
    codigo_html = """
    <!DOCTYPE html>
    <html lang="pt">
    <head>
        <meta charset="UTF-8">
        <title>Painel do Barbeiro</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; background-color: #f4f4f9; }
            .container { width: 50%; margin: auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0px 0px 10px rgba(0,0,0,0.1); mt-5}
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
            // Aqui eu faço o navegador ir buscar os dados à nossa própria API
            fetch('http://127.0.0.1:8000/dashboard')
                .then(resposta => resposta.json())
                .then(dados => {
                    // Preencho o conselho na tela
                    document.getElementById('textoConselho').innerText = "Conselho da IA: " + dados.o_que_fazer;

                    // Preparo os dados para o gráfico
                    const valores = [dados.faturamento_bruto, dados.gastos_fixos_da_loja, dados.lucro_liquido_real];
                    
                    // Desenho o gráfico de pizza
                    const ctx = document.getElementById('graficoPizza').getContext('2d');
                    new Chart(ctx, {
                        type: 'pie',
                        data: {
                            labels: ['Faturamento Bruto', 'Gastos Fixos', 'Lucro Líquido'],
                            datasets: [{
                                data: valores,
                                backgroundColor: ['#4caf50', '#f44336', '#2196f3'], // Cores: Verde, Vermelho, Azul
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