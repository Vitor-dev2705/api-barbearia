import os
import json
from google import genai
from dotenv import load_dotenv
from datetime import datetime, timedelta
from supabase import create_client, Client

# ==========================================
# CONFIGURAÇÕES INICIAIS
# ==========================================
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

dicionario_nlp = {
    "dps": "depois",
    "hj": "hoje",
    "amanha": "amanhã",
    "vc": "você",
    "p/": "para"
}

# ==========================================
# PROCESSAMENTO DE LINGUAGEM NATURAL (IA)
# ==========================================
def processar_texto_com_ia(texto_cliente: str):
    hoje = datetime.now()
    data_hoje_str = hoje.strftime("%Y-%m-%d")
    dia_semana_hoje = hoje.strftime("%A")

    try:
        prompt = f"""
        Você é um assistente de barbearia profissional. 
        O cliente disse: "{texto_cliente}".
        
        INFORMAÇÕES DE CONTEXTO:
        Hoje é {dia_semana_hoje}, data: {data_hoje_str}.
        
        Sua tarefa é extrair a DATA, o HORÁRIO e o SERVIÇO.
        
        REGRAS DE DATA:
        - "hoje": retorne {data_hoje_str}
        - "amanhã": adicione 1 dia à data de hoje.
        - "depois de amanhã": adicione 2 dias.
        - Se for um dia da semana (ex: "quinta"), retorne a data da próxima quinta-feira.
        - Se não achar data, retorne null.
        
        REGRAS DE HORÁRIO:
        - Converta "13 h", "13h", "às 13" ou "uma da tarde" para "13:00".
        - Se não achar horário, retorne null.
        
        Responda APENAS um JSON plano: {{"data": "YYYY-MM-DD", "hora": "HH:MM", "servico": "nome"}}
        """
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        
        texto_limpo = response.text.strip()
        if "```json" in texto_limpo:
            texto_limpo = texto_limpo.split("```json")[1].split("```")[0].strip()
        elif "```" in texto_limpo:
            texto_limpo = texto_limpo.split("```")[1].split("```")[0].strip()
            
        return json.loads(texto_limpo)
    except Exception as e:
        print("ERRO DETALHADO DA IA:", e)
        return {"data": None, "hora": None, "servico": None}

def limpar_mensagem(mensagem: str):
    palavras = mensagem.lower().split()
    mensagem_limpa = [dicionario_nlp.get(p, p) for p in palavras]
    return " ".join(mensagem_limpa)

# ==========================================
# GERENCIAMENTO DE DADOS DA BARBEARIA
# ==========================================
def obter_duracao_servico(nome_servico: str):
    try:
        resposta = supabase.table("servicos").select("duracao_minutos").ilike("nome", f"%{nome_servico}%").execute()
        if resposta.data:
            return resposta.data[0]["duracao_minutos"]
    except Exception:
        pass
    return 30

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
    try:
        supabase.table("configuracoes").update({
            "custo_aluguel": novo_aluguel, "custo_produtos": novos_produtos, "gastos_fixos": novo_total
        }).eq("id", 1).execute()
        return novo_total
    except Exception: 
        return 0

def atualizar_preco_servico_db(nome_servico: str, novo_valor: float):
    try:
        resposta = supabase.table("servicos").update({"preco": novo_valor}).ilike("nome", nome_servico).execute()
        return len(resposta.data) > 0
    except Exception: 
        return False

# ==========================================
# LÓGICA DE AGENDAMENTO E EXPEDIENTE
# ==========================================
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

def agendar_servico(cliente: str, servico: str, data_iso: str, hora: str, valor: float):
    duracao = obter_duracao_servico(servico)
    formato_hora = "%H:%M"
    
    try:
        hora_inicio = datetime.strptime(hora, formato_hora)
        hora_fim = hora_inicio + timedelta(minutes=duracao)
    except Exception:
        return "Horário com formato inválido."

    try:
        if "/" in data_iso:
            try:
                data_obj = datetime.strptime(data_iso, "%d/%m/%Y")
            except Exception:
                data_obj = datetime.strptime(data_iso, "%Y/%m/%d")
        else:
            data_obj = datetime.strptime(data_iso, "%Y-%m-%d")
            
        dia_semana = data_obj.weekday()
        
        expediente = supabase.table("expediente").select("*").eq("dia_semana", dia_semana).execute()
        
        if not expediente.data or not expediente.data[0].get('aberto', False):
            return "Desculpe, a barbearia está fechada neste dia."
            
        str_abertura = str(expediente.data[0].get('hora_abertura', '09:00'))[:5]
        str_fechamento = str(expediente.data[0].get('hora_fechamento', '18:00'))[:5]
        
        hr_abertura = datetime.strptime(str_abertura, "%H:%M").time()
        hr_fechamento = datetime.strptime(str_fechamento, "%H:%M").time()
        
        if hora_inicio.time() < hr_abertura or hora_fim.time() > hr_fechamento:
            return f"Nosso horário neste dia é das {str_abertura} às {str_fechamento}. Lembrando que o serviço leva {duracao} minutos!"
            
    except Exception as e:
        print(f"Erro detalhado no expediente: {e}")
        return "Tive um problema ao verificar os horários. Tente novamente."

    disponivel, horario_final = verificar_vaga_e_sugerir(data_iso, hora)
    
    if disponivel:
        novo_dado = {
            "cliente": cliente, "servico": servico, "data": data_iso,
            "hora": hora, "valor": valor, "status": "Pendente"
        }
        try:
            supabase.table("marcacoes").insert(novo_dado).execute()
            data_formatada_br = data_obj.strftime("%d/%m/%Y")
            return f"Maravilha! Seu {servico} ({duracao} min) foi marcado para {data_formatada_br} às {hora}."
        except Exception:
            return "Erro ao salvar no banco."
    else:
        if horario_final:
            return f"Puxa, às {hora} já estou ocupado. Que tal às {horario_final}?"
        return "Horário indisponível."

# ==========================================
# OPERAÇÕES DE CAIXA E DASHBOARD
# ==========================================
def realizar_checkin(nome_cliente: str):
    try:
        resposta = supabase.table("marcacoes").select("id").ilike("cliente", nome_cliente).eq("status", "Pendente").order("id", desc=True).execute()
        
        if resposta.data:
            id_marcacao = resposta.data[0]["id"]
            supabase.table("marcacoes").update({"status": "Concluído"}).eq("id", id_marcacao).execute()
            return True
    except Exception: 
        pass
    return False

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