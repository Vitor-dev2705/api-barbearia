# app/services.py
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from supabase import create_client, Client

# [NOVO: Mando o Python procurar e abrir o nosso "cofre" (ficheiro .env)]
load_dotenv()

# [1. CONFIGURAÇÃO DA NUVEM: Aqui eu ligo o nosso código ao banco de dados de forma SEGURA]
# Em vez de escrever a chave aqui, o Python vai buscá-la ao cofre!
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") 

# [Aqui o Python cria a "ponte" oficial de comunicação com o Supabase]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# [2. VARIÁVEIS FINANCEIRAS: Estes são os custos fixos da barbearia que descontamos do faturamento]
GASTOS_FIXOS = 1500.00
CUSTO_ALUGUEL = 800.00
CUSTO_PRODUTOS = 700.00 # Somando dá os 1500

# [3. INTELIGÊNCIA ARTIFICIAL BÁSICA: Dicionário para limpar as gírias dos clientes no Telegram]
dicionario_nlp = {
    "dps": "depois",
    "hj": "hoje",
    "amanha": "amanhã",
    "vc": "você",
    "p/": "para"
}

def limpar_mensagem(mensagem: str):
    """[Pega a frase do cliente e troca as gírias pelas palavras corretas]"""
    palavras = mensagem.lower().split()
    mensagem_limpa = []
    for palavra in palavras:
        palavra_corrigida = dicionario_nlp.get(palavra, palavra)
        mensagem_limpa.append(palavra_corrigida)
    return " ".join(mensagem_limpa)

def verificar_vaga_e_sugerir(data: str, hora_desejada: str):
    """[Vai à nuvem e verifica se a cadeira do barbeiro está livre nessa hora]"""
    
    # [Pergunto ao Supabase: "Traz-me todas as horas ocupadas neste dia"]
    resposta = supabase.table("marcacoes").select("hora").eq("data", data).neq("status", "Cancelada").execute()
    horarios_ocupados = [item["hora"] for item in resposta.data]
    
    if hora_desejada not in horarios_ocupados:
        return True, hora_desejada # [Se a hora não estiver na lista da nuvem, está livre!]
    
    # [Se estiver ocupada, o código soma +1 hora matematicamente para sugerir um novo horário]
    formato = "%H:%M"
    try:
        hora_obj = datetime.strptime(hora_desejada, formato)
        nova_hora_obj = hora_obj + timedelta(hours=1)
        nova_hora = nova_hora_obj.strftime(formato)
        
        while nova_hora in horarios_ocupados:
            nova_hora_obj += timedelta(hours=1)
            nova_hora = nova_hora_obj.strftime(formato)
            
        return False, nova_hora
    except ValueError:
        return False, None

def agendar_servico(cliente: str, servico: str, data: str, hora: str, valor: float):
    """[Cria o agendamento e GRAVA DEFINITIVAMENTE no banco de dados na nuvem]"""
    disponivel, horario_final = verificar_vaga_e_sugerir(data, hora)
    
    if disponivel:
        # [Preparo o pacote de dados exatamente como o Supabase exige]
        novo_dado = {
            "cliente": cliente,
            "servico": servico,
            "data": data,
            "hora": hora,
            "valor": valor,
            "status": "Pendente"
        }
        # [Dou a ordem de INSERIR (Insert) na tabela marcacoes]
        supabase.table("marcacoes").insert(novo_dado).execute()
        return f"Maravilha! O serviço de {servico} para {cliente} foi marcado para {data} às {hora}."
    else:
        if horario_final:
            return f"Puxa, às {hora} eu já tenho a agenda cheia. Que tal marcarmos para as {horario_final}?"
        return "Desculpe, não entendi a hora. Use o formato HH:MM (ex: 10:00)."

def realizar_checkin(nome_cliente: str):
    """[Quando o cliente chega na loja, muda o status dele de 'Pendente' para 'Concluído' na nuvem]"""
    
    # [Procuro na nuvem se o cliente tem marcações pendentes]
    resposta = supabase.table("marcacoes").select("id").ilike("cliente", nome_cliente).eq("status", "Pendente").execute()
    
    if resposta.data:
        # [Pego no ID (número da linha) dele e dou a ordem de ATUALIZAR (Update) o status]
        id_marcacao = resposta.data[0]["id"]
        supabase.table("marcacoes").update({"status": "Concluído"}).eq("id", id_marcacao).execute()
        return True
    return False

def gerar_dashboard():
    """[O cérebro financeiro: Puxa o dinheiro da nuvem e faz as contas de lucro e gastos]"""
    
    # [Peço à nuvem: "Dá-me apenas os valores dos serviços que já foram Concluídos"]
    resposta = supabase.table("marcacoes").select("valor").eq("status", "Concluído").execute()
    
    # [A matemática: somo todos os valores recebidos da nuvem]
    total_ganho = sum(item["valor"] for item in resposta.data)
    cortes_realizados = len(resposta.data)
            
    lucro_liquido = total_ganho - GASTOS_FIXOS
    
    # [A IA do barbeiro dando conselhos com base no lucro real]
    if lucro_liquido > 500:
        dica = "Excelente mês! Considere investir em novos equipamentos."
    elif lucro_liquido >= 0:
        dica = "Contas pagas, mas a margem está apertada. Tente vender produtos extras."
    else:
        dica = "Atenção: O lucro está negativo. Precisamos focar em atrair clientes."
    
    # [Devolvo tudo formatado para a nossa página web consumir e montar a tela]
    return {
        "cortes_concluidos": cortes_realizados,
        "faturamento_bruto": total_ganho,
        "gastos_fixos_da_loja": GASTOS_FIXOS,
        "lucro_liquido_real": lucro_liquido,
        "o_que_fazer": dica
    }
    
def gerar_dados_pizza():
    """[Esta função prepara as fatias exatas para o nosso Gráfico de Pizza no painel do barbeiro]"""
    
    # [Busco o dinheiro total na nuvem mais uma vez]
    resposta = supabase.table("marcacoes").select("valor").eq("status", "Concluído").execute()
    total_recebido = sum(item["valor"] for item in resposta.data)
    
    # [A matemática para o gráfico: não posso ter lucro negativo numa fatia de pizza]
    lucro = max(0, total_recebido - GASTOS_FIXOS)
    
    # [Monto a estrutura que a biblioteca Chart.js adora ler]
    dados_grafico = [
        {"categoria": "Aluguel", "valor": CUSTO_ALUGUEL},
        {"categoria": "Produtos/Fixos", "valor": CUSTO_PRODUTOS},
        {"categoria": "Lucro Líquido", "valor": lucro}
    ]
    
    if lucro > GASTOS_FIXOS:
        conselho = "O lucro superou os custos! Sugestão: Reserve 20% para fundo de reserva e invista em marketing."
    else:
        conselho = "Margem apertada. Tente oferecer serviços casados (Cabelo + Barba) para aumentar o ticket médio."
        
    return {"dados": dados_grafico, "conselho": conselho}