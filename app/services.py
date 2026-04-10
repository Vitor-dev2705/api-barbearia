import os
import json
import google.generativeai as genai
from dotenv import load_dotenv
from datetime import datetime, timedelta
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model_ia = genai.GenerativeModel('gemini-1.5-flash')

dicionario_nlp = {
    "dps": "depois",
    "hj": "hoje",
    "amanha": "amanhã",
    "vc": "você",
    "p/": "para"
}

def processar_texto_com_ia(texto_cliente: str):
    try:
        prompt = f"""
        Você é um assistente de barbearia profissional. 
        O cliente disse: "{texto_cliente}".
        Extraia o HORÁRIO (no formato HH:MM) e o SERVIÇO.
        Se o serviço não for mencionado, assuma 'Corte Simples'.
        Responda APENAS um JSON plano assim: {{"hora": "HH:MM", "servico": "nome"}}
        Se não encontrar horário, responda: {{"hora": null, "servico": null}}
        """
        response = model_ia.generate_content(prompt)
        resultado = json.loads(response.text.replace("```json", "").replace("```", "").strip())
        return resultado
    except Exception:
        return {"hora": None, "servico": None}

def obter_configuracoes():
    try:
        resposta = supabase.table("configuracoes").select("*").eq("id", 1).execute()
        if resposta.data:
            return resposta.data[0]
    except Exception:
        pass
    return {"gastos_fixos": 1500.0, "custo_aluguel": 800.0, "custo_produtos": 700.0}

def atualizar_custos_da_loja(novo_aluguel: float, novos_produtos: float):
    novo_total = novo_aluguel + novos_produtos
    supabase.table("configuracoes").update({
        "custo_aluguel": novo_aluguel,
        "custo_produtos": novos_produtos,
        "gastos_fixos": novo_total
    }).eq("id", 1).execute()
    return novo_total

def atualizar_preco_servico_db(nome_servico: str, novo_valor: float):
    try:
        resposta = supabase.table("servicos").update({"preco": novo_valor}).ilike("nome", nome_servico).execute()
        return len(resposta.data) > 0
    except Exception:
        return False

def limpar_mensagem(mensagem: str):
    palavras = mensagem.lower().split()
    mensagem_limpa = []
    for palavra in palavras:
        palavra_corrigida = dicionario_nlp.get(palavra, palavra)
        mensagem_limpa.append(palavra_corrigida)
    return " ".join(mensagem_limpa)

def verificar_vaga_e_sugerir(data: str, hora_desejada: str):
    resposta = supabase.table("marcacoes").select("hora").eq("data", data).neq("status", "Cancelada").execute()
    horarios_ocupados = [item["hora"] for item in resposta.data]
    
    if hora_desejada not in horarios_ocupados:
        return True, hora_desejada
    
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
    disponivel, horario_final = verificar_vaga_e_sugerir(data, hora)
    
    if disponivel:
        novo_dado = {
            "cliente": cliente,
            "servico": servico,
            "data": data,
            "hora": hora,
            "valor": valor,
            "status": "Pendente"
        }
        supabase.table("marcacoes").insert(novo_dado).execute()
        return f"Maravilha! O serviço de {servico} para {cliente} foi marcado para {data} às {hora}."
    else:
        if horario_final:
            return f"Puxa, às {hora} eu já tenho a agenda cheia. Que tal marcarmos para as {horario_final}?"
        return "Desculpe, não entendi a hora. Use o formato HH:MM (ex: 10:00)."

def realizar_checkin(nome_cliente: str):
    resposta = supabase.table("marcacoes")\
        .select("id")\
        .ilike("cliente", nome_cliente)\
        .eq("status", "Pendente")\
        .order("id", desc=True)\
        .execute()
    
    if resposta.data:
        id_marcacao = resposta.data[0]["id"]
        supabase.table("marcacoes").update({"status": "Concluído"}).eq("id", id_marcacao).execute()
        return True
    return False

def gerar_dashboard():
    config = obter_configuracoes()
    gastos_fixos = config.get("gastos_fixos", 0)
    
    resposta = supabase.table("marcacoes").select("valor").eq("status", "Concluído").execute()
    
    total_ganho = sum(item["valor"] for item in resposta.data)
    cortes_realizados = len(resposta.data)
    lucro_liquido = total_ganho - gastos_fixos
    
    if lucro_liquido > 500:
        dica = "Excelente mês! Considere investir em novos equipamentos."
    elif lucro_liquido >= 0:
        dica = "Contas pagas, mas a margem está apertada. Tente vender produtos extras."
    else:
        dica = "Atenção: O lucro está negativo. Precisamos focar em atrair clientes."
    
    return {
        "cortes_concluidos": cortes_realizados,
        "faturamento_bruto": total_ganho,
        "gastos_fixos_da_loja": gastos_fixos,
        "lucro_liquido_real": lucro_liquido,
        "o_que_fazer": dica
    }