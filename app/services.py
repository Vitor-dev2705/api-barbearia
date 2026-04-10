import os
import json
from google import genai
from dotenv import load_dotenv
from datetime import datetime, timedelta
from supabase import create_client, Client

# Carrega as variáveis de ambiente
load_dotenv()

# Configuração Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configuração Gemini (NOVA BIBLIOTECA)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

dicionario_nlp = {
    "dps": "depois",
    "hj": "hoje",
    "amanha": "amanhã",
    "vc": "você",
    "p/": "para"
}

# --- FUNÇÕES DE INTELIGÊNCIA ARTIFICIAL ---

def processar_texto_com_ia(texto_cliente: str):
    try:
        prompt = f"""
        Você é um assistente de barbearia profissional. 
        O cliente disse: "{texto_cliente}".
        
        Sua tarefa é extrair o HORÁRIO e o SERVIÇO.
        
        REGRAS DE HORÁRIO:
        - Se o cliente disser "13 h", "13h", "às 13" ou "13 horas", converta para "13:00".
        - Se disser "meio dia", converta para "12:00".
        - Se disser "uma da tarde", converta para "13:00".
        - Sempre responda no formato de 24 horas HH:MM.
        
        REGRAS DE SERVIÇO:
        - Se não mencionado, assuma 'Corte Simples'.
        
        Responda APENAS um JSON plano: {{"hora": "HH:MM", "servico": "nome"}}
        Se não encontrar horário de jeito nenhum, responda: {{"hora": null, "servico": null}}
        """
        
        # NOVA FORMA DE CHAMAR A API DO GEMINI
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        
        # Limpeza de Markdown
        texto_limpo = response.text.strip()
        if "```json" in texto_limpo:
            texto_limpo = texto_limpo.split("```json")[1].split("```")[0].strip()
        elif "```" in texto_limpo:
            texto_limpo = texto_limpo.split("```")[1].split("```")[0].strip()
            
        return json.loads(texto_limpo)
    except Exception as e:
        print(f"Erro IA: {e}")
        return {"hora": None, "servico": None}

# --- FUNÇÕES DE CONFIGURAÇÃO E CUSTOS ---

def obter_configuracoes():
    try:
        resposta = supabase.table("configuracoes").select("*").eq("id", 1).execute()
        if resposta.data:
            return resposta.data[0]
    except Exception as e:
        print(f"Erro configurações: {e}")
    return {"gastos_fixos": 1500.0, "custo_aluguel": 800.0, "custo_produtos": 700.0}

def atualizar_custos_da_loja(novo_aluguel: float, novos_produtos: float):
    novo_total = novo_aluguel + novos_produtos
    try:
        supabase.table("configuracoes").update({
            "custo_aluguel": novo_aluguel,
            "custo_produtos": novos_produtos,
            "gastos_fixos": novo_total
        }).eq("id", 1).execute()
        return novo_total
    except Exception as e:
        print(f"Erro atualizar custos: {e}")
        return 0

def atualizar_preco_servico_db(nome_servico: str, novo_valor: float):
    try:
        resposta = supabase.table("servicos").update({"preco": novo_valor}).ilike("nome", nome_servico).execute()
        return len(resposta.data) > 0
    except Exception:
        return False

# --- FUNÇÕES DE TRATAMENTO DE TEXTO ---

def limpar_mensagem(mensagem: str):
    palavras = mensagem.lower().split()
    mensagem_limpa = [dicionario_nlp.get(p, p) for p in palavras]
    return " ".join(mensagem_limpa)

# --- FUNÇÕES DE AGENDAMENTO ---

def verificar_vaga_e_sugerir(data: str, hora_desejada: str):
    try:
        resposta = supabase.table("marcacoes").select("hora").eq("data", data).neq("status", "Cancelada").execute()
        horarios_ocupados = [item["hora"] for item in resposta.data]
        
        if hora_desejada not in horarios_ocupados:
            return True, hora_desejada
        
        formato = "%H:%M"
        hora_obj = datetime.strptime(hora_desejada, formato)
        nova_hora_obj = hora_obj + timedelta(hours=1)
        nova_hora = nova_hora_obj.strftime(formato)
        
        while nova_hora in horarios_ocupados:
            nova_hora_obj += timedelta(hours=1)
            nova_hora = nova_hora_obj.strftime(formato)
            
        return False, nova_hora
    except Exception:
        return False, None

def agendar_servico(cliente: str, servico: str, data: str, hora: str, valor: float):
    disponivel, horario_final = verificar_vaga_e_sugerir(data, hora)
    
    if disponivel:
        novo_dado = {
            "cliente": cliente, "servico": servico, "data": data,
            "hora": hora, "valor": valor, "status": "Pendente"
        }
        try:
            supabase.table("marcacoes").insert(novo_dado).execute()
            return f"Maravilha! O serviço de {servico} para {cliente} foi marcado para {data} às {hora}."
        except Exception as e:
            return f"Erro ao salvar no banco: {e}"
    else:
        if horario_final:
            return f"Puxa, às {hora} já estou ocupado. Que tal às {horario_final}?"
        return "Horário inválido. Por favor, tente algo como 14:30."

# --- FUNÇÕES DE OPERAÇÃO ---

def realizar_checkin(nome_cliente: str):
    try:
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
    except Exception:
        pass
    return False

# --- DASHBOARD FINANCEIRO ---

def gerar_dashboard():
    config = obter_configuracoes()
    gastos_fixos = config.get("gastos_fixos", 0)
    
    try:
        resposta = supabase.table("marcacoes").select("valor").eq("status", "Concluído").execute()
        total_ganho = sum(item["valor"] for item in resposta.data)
        lucro = total_ganho - gastos_fixos
        
        if lucro > 500:
            dica = "Excelente mês! Considere investir em novos equipamentos."
        elif lucro >= 0:
            dica = "Contas pagas, mas a margem está apertada."
        else:
            dica = "Atenção: O lucro está negativo."
        
        return {
            "cortes_concluidos": len(resposta.data),
            "faturamento_bruto": total_ganho,
            "gastos_fixos_da_loja": gastos_fixos,
            "lucro_liquido_real": lucro,
            "o_que_fazer": dica
        }
    except Exception:
        return {"erro": "Não foi possível carregar os dados"}