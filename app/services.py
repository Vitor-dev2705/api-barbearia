import os
import json
from google import genai
from dotenv import load_dotenv
from datetime import datetime, timedelta
from supabase import create_client, Client

# ==========================================
# CONFIGURAÇÕES INICIAIS E SEGURANÇA
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

def obter_dados_admin():
    try:
        if os.path.exists("admin_id.txt"):
            with open("admin_id.txt", "r") as f:
                conteudo = f.read().strip()
                if conteudo:
                    return conteudo
    except Exception: pass

    try:
        resposta = supabase.table("configuracoes").select("admin_chat_id").eq("id", 1).execute()
        if resposta.data and len(resposta.data) > 0 and resposta.data[0].get("admin_chat_id"):
            return str(resposta.data[0]["admin_chat_id"]).strip()
    except Exception: pass
    
    return None

def registrar_admin(chat_id: int):
    try:
        with open("admin_id.txt", "w") as f:
            f.write(str(chat_id))
    except Exception as e: 
        print("Erro Arquivo:", e)

    try:
        supabase.table("configuracoes").upsert({"id": 1, "admin_chat_id": chat_id}).execute()
        return True
    except Exception as e: 
        print("Erro BD:", e)
        return False

# ==========================================
# PROCESSAMENTO DE LINGUAGEM NATURAL (IA)
# ==========================================
def processar_texto_com_ia(texto_cliente: str):
    hoje = datetime.utcnow() - timedelta(hours=3)
    data_hoje_str = hoje.strftime("%d-%m-%Y")
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
        
        Responda APENAS um JSON plano: {{"data": "DD-MM-YYYY", "hora": "HH:MM", "servico": "nome"}}
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
    except Exception:
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
            return int(resposta.data[0]["duracao_minutos"])
    except Exception: pass
    return 30

def obter_configuracoes():
    try:
        resposta = supabase.table("configuracoes").select("*").eq("id", 1).execute()
        if resposta.data:
            return resposta.data[0]
    except Exception: pass
    return {"gastos_fixos": 1500.0, "custo_aluguel": 800.0, "custo_produtos": 700.0}

def atualizar_despesa(coluna: str, valor: float):
    try:
        supabase.table("configuracoes").update({coluna: valor}).eq("id", 1).execute()
        return True
    except Exception: return False

def atualizar_preco_servico_db(nome_servico: str, novo_valor: float):
    try:
        resposta = supabase.table("servicos").update({"preco": novo_valor}).ilike("nome", nome_servico).execute()
        return len(resposta.data) > 0
    except Exception: return False

# ==========================================
# LÓGICA DE AGENDAMENTO E EXPEDIENTE
# ==========================================
def obter_slots_livres(data_iso: str, duracao: int):
    try:
        duracao = int(duracao) if duracao else 30
        data_obj = datetime.strptime(data_iso, "%Y-%m-%d")
        dia_semana = data_obj.weekday()
        
        try:
            expediente = supabase.table("expediente").select("*").eq("dia_semana", dia_semana).execute()
            dados_exp = expediente.data[0] if expediente.data else None
        except Exception:
            dados_exp = None

        if not dados_exp:
            if dia_semana == 6: return []
            str_ab, str_fe = "09:00", "18:00"
        else:
            if not dados_exp.get('aberto', False): return []
            str_ab = str(dados_exp.get('hora_abertura', '09:00'))[:5]
            str_fe = str(dados_exp.get('hora_fechamento', '18:00'))[:5]

        hr_abertura = datetime.strptime(str_ab, "%H:%M")
        hr_fechamento = datetime.strptime(str_fe, "%H:%M")

        try:
            marcacoes = supabase.table("marcacoes").select("hora", "servico").eq("data", data_iso).neq("status", "Cancelada").execute()
            lista_marcacoes = marcacoes.data or []
        except Exception:
            lista_marcacoes = []

        ocupados = []
        for m in lista_marcacoes:
            try:
                inicio = datetime.strptime(str(m.get('hora', '00:00'))[:5].strip(), "%H:%M")
                d_serv = int(obter_duracao_servico(m.get('servico', '')))
                fim = inicio + timedelta(minutes=d_serv)
                ocupados.append((inicio, fim))
            except Exception: continue

        slots = []
        atual = hr_abertura
        fuso_br = datetime.utcnow() - timedelta(hours=3)
        is_hoje = data_iso == fuso_br.strftime("%Y-%m-%d")

        while atual + timedelta(minutes=duracao) <= hr_fechamento:
            fim_slot = atual + timedelta(minutes=duracao)
            if is_hoje and atual.time() <= fuso_br.time():
                atual += timedelta(minutes=30)
                continue
            conflito = False
            for (o_ini, o_fim) in ocupados:
                if atual < o_fim and fim_slot > o_ini:
                    conflito = True
                    break
            if not conflito: slots.append(atual.strftime("%H:%M"))
            atual += timedelta(minutes=30)
        return slots
    except Exception: return []

def verificar_vaga_e_sugerir(data: str, hora_desejada: str):
    try:
        resposta = supabase.table("marcacoes").select("hora").eq("data", data).neq("status", "Cancelada").execute()
        horarios_ocupados = [item["hora"] for item in resposta.data]
        if hora_desejada not in horarios_ocupados: return True, hora_desejada
        formato = "%H:%M"
        hora_obj = datetime.strptime(hora_desejada, formato)
        nova_hora_obj = hora_obj + timedelta(hours=1)
        nova_hora = nova_hora_obj.strftime(formato)
        while nova_hora in horarios_ocupados:
            nova_hora_obj += timedelta(hours=1)
            nova_hora = nova_hora_obj.strftime(formato)
        return False, nova_hora
    except Exception: return False, None

def agendar_servico(cliente: str, servico: str, data_iso: str, hora: str, valor: float):
    duracao = obter_duracao_servico(servico)
    formato_hora = "%H:%M"
    try:
        hora_inicio = datetime.strptime(hora, formato_hora)
        hora_fim = hora_inicio + timedelta(minutes=duracao)
    except Exception: return "Horário com formato inválido."

    try:
        if "/" in data_iso:
            try: data_obj = datetime.strptime(data_iso, "%d/%m/%Y")
            except Exception: data_obj = datetime.strptime(data_iso, "%Y/%m/%d")
        else: data_obj = datetime.strptime(data_iso, "%Y-%m-%d")
            
        dia_semana = data_obj.weekday()
        fuso_br = datetime.utcnow() - timedelta(hours=3)
        is_hoje = data_obj.strftime("%Y-%m-%d") == fuso_br.strftime("%Y-%m-%d")

        if is_hoje and hora_inicio.time() <= fuso_br.time():
            return "Esse horário já passou. Por favor, escolha um horário futuro!"
        
        try:
            expediente = supabase.table("expediente").select("*").eq("dia_semana", dia_semana).execute()
            dados_exp = expediente.data[0] if expediente.data else None
        except Exception: dados_exp = None
        
        if dados_exp:
            if not dados_exp.get('aberto', False): return "Desculpe, a barbearia está fechada neste dia."
            str_abertura = str(dados_exp.get('hora_abertura', '09:00'))[:5]
            str_fechamento = str(dados_exp.get('hora_fechamento', '18:00'))[:5]
        else:
            if dia_semana == 6: return "Desculpe, a barbearia está fechada neste dia."
            str_abertura, str_fechamento = "09:00", "18:00"
        
        hr_abertura = datetime.strptime(str_abertura, "%H:%M").time()
        hr_fechamento = datetime.strptime(str_fechamento, "%H:%M").time()
        
        if hora_inicio.time() < hr_abertura or hora_fim.time() > hr_fechamento:
            return f"Nosso horário neste dia é das {str_abertura} às {str_fechamento}. Lembrando que o serviço leva {duracao} minutos!"
            
    except Exception: return "Tive um problema ao verificar os horários. Tente novamente."

    disponivel, horario_final = verificar_vaga_e_sugerir(data_iso, hora)
    
    if disponivel:
        novo_dado = {"cliente": cliente, "servico": servico, "data": data_iso, "hora": hora, "valor": valor, "status": "Pendente"}
        try:
            supabase.table("marcacoes").insert(novo_dado).execute()
            data_formatada_br = data_obj.strftime("%d/%m/%Y")
            return f"Maravilha! Seu {servico} ({duracao} min) foi marcado para {data_formatada_br} às {hora}."
        except Exception: return "Erro ao salvar no banco."
    else:
        if horario_final: return f"Puxa, às {hora} já estou ocupado. Que tal às {horario_final}?"
        return "Horário indisponível."

# ==========================================
# PAINEL DO BARBEIRO E CHECK-IN
# ==========================================
def obter_grade_horarios_admin(data_iso: str):
    try:
        # Define o horário padrão de atendimento
        hr_ab, hr_fe = datetime.strptime("09:00", "%H:%M"), datetime.strptime("18:00", "%H:%M")
        
        # Busca todas as marcações do dia (exceto canceladas)
        marcacoes = supabase.table("marcacoes").select("*").eq("data", data_iso).neq("status", "Cancelada").execute()
        
        # MAPEAMENTO VISUAL: Aqui garantimos que o emoji mude conforme o status
        mapa_ocupados = {}
        for m in marcacoes.data:
            hora_str = str(m['hora'])[:5]
            if m['status'] == "Bloqueado":
                mapa_ocupados[hora_str] = "bloqueado"
            elif m['status'] == "Concluído":
                mapa_ocupados[hora_str] = "concluido"
            else:
                mapa_ocupados[hora_str] = "cliente"
                
        grade, atual = [], hr_ab
        while atual < hr_fe:
            h_str = atual.strftime("%H:%M")
            grade.append({"hora": h_str, "estado": mapa_ocupados.get(h_str, "livre")})
            atual += timedelta(minutes=30)
        return grade
    except Exception as e:
        print(f"Erro na grade: {e}")
        return []
def alternar_bloqueio_horario(data_iso: str, hora: str):
    try:
        resposta = supabase.table("marcacoes").select("*").eq("data", data_iso).eq("hora", hora).neq("status", "Cancelada").execute()
        if not resposta.data:
            novo_dado = {"cliente": "ADMIN", "servico": "Bloqueio", "data": data_iso, "hora": hora, "valor": 0.0, "status": "Bloqueado"}
            supabase.table("marcacoes").insert(novo_dado).execute()
            return "Bloqueado"
        else:
            marcacao = resposta.data[0]
            if marcacao.get("status") == "Bloqueado":
                supabase.table("marcacoes").delete().eq("id", marcacao["id"]).execute()
                return "Desbloqueado"
            else: return "Ocupado_Cliente"
    except Exception: return "Erro"

def obter_detalhes_agendamento(data_iso: str, hora: str):
    try:
        res = supabase.table("marcacoes").select("*").eq("data", data_iso).eq("hora", hora).neq("status", "Cancelada").execute()
        return res.data[0] if res.data else None
    except Exception: return None

def atualizar_status_agendamento(id_marcacao: int, novo_status: str):
    try:
        supabase.table("marcacoes").update({"status": novo_status}).eq("id", id_marcacao).execute()
        return True
    except Exception: return False

def gerar_dashboard():
    config = obter_configuracoes()
    gastos_fixos = config.get("gastos_fixos", 0)
    custo_produtos = config.get("custo_produtos", 0)
    despesas_totais = gastos_fixos + custo_produtos

    try:
        resposta = supabase.table("marcacoes").select("data, valor").eq("status", "Concluído").execute()
        marcacoes = resposta.data or []
        
        total_ganho = sum(item["valor"] for item in marcacoes)
        lucro = total_ganho - despesas_totais

        hoje = datetime.utcnow() - timedelta(hours=3)
        inicio_semana = hoje - timedelta(days=hoje.weekday())
        str_inicio_semana = inicio_semana.strftime("%Y-%m-%d")

        faturamento_semana = sum(item["valor"] for item in marcacoes if item["data"] >= str_inicio_semana)

        return {
            "faturamento_bruto": total_ganho,
            "faturamento_semana": faturamento_semana,
            "gastos_fixos": gastos_fixos,
            "custo_produtos": custo_produtos,
            "lucro_liquido_real": lucro
        }
    except Exception: return None
def buscar_agendamento_pendente_do_dia(chat_id_cliente: int):
    try:
        hoje = (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d")
        resposta = supabase.table("marcacoes").select("*").eq("data", hoje).eq("status", "Pendente").execute()
        return resposta.data if resposta.data else []
    except Exception:
        return []

def fazer_checkin_por_id(id_agendamento: int):
    try:
        supabase.table("marcacoes").update({"status": "Concluído"}).eq("id", id_agendamento).execute()
        return True
    except Exception:
        return False