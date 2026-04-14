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
                if conteudo: return conteudo
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
    except Exception: pass

    try:
        supabase.table("configuracoes").upsert({"id": 1, "admin_chat_id": chat_id}).execute()
        return True
    except Exception: return False

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
        Hoje é {dia_semana_hoje}, data: {data_hoje_str}.
        Sua tarefa é extrair a DATA, o HORÁRIO e o SERVIÇO.
        Responda APENAS um JSON plano: {{"data": "DD-MM-YYYY", "hora": "HH:MM", "servico": "nome"}}
        """
        
        response = client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
        texto_limpo = response.text.strip()
        if "```json" in texto_limpo:
            texto_limpo = texto_limpo.split("```json")[1].split("```")[0].strip()
        elif "```" in texto_limpo:
            texto_limpo = texto_limpo.split("```")[1].split("```")[0].strip()
            
        return json.loads(texto_limpo)
    except Exception:
        return {"data": None, "hora": None, "servico": None}

def limpar_mensagem(mensagem: str):
    if not mensagem: return ""
    palavras = mensagem.lower().split()
    mensagem_limpa = [dicionario_nlp.get(p, p) for p in palavras]
    return " ".join(mensagem_limpa)

# ==========================================
# GESTÃO DE SERVIÇOS (BARBEIRO)
# ==========================================
def obter_servicos_db():
    try:
        res = supabase.table("servicos").select("*").order("nome").execute()
        return res.data or []
    except Exception: return []

def salvar_servico_db(nome: str, preco: float, duracao: int = 30):
    try:
        supabase.table("servicos").upsert({
            "nome": nome.strip().title(),
            "preco": preco,
            "duracao_minutos": duracao
        }, on_conflict="nome").execute()
        return True
    except Exception: return False

def deletar_servico_db(id_servico: int):
    try:
        supabase.table("servicos").delete().eq("id", id_servico).execute()
        return True
    except Exception: return False

def obter_dados_servico_por_nome(nome_servico: str):
    try:
        res = supabase.table("servicos").select("*").ilike("nome", nome_servico).execute()
        return res.data[0] if res.data else None
    except Exception: return None

# ==========================================
# LÓGICA DE AGENDAMENTO (CÁLCULO DINÂMICO DE DURAÇÃO)
# ==========================================
def obter_duracao_servico(nome_servico: str):
    servico = obter_dados_servico_por_nome(nome_servico)
    return int(servico["duracao_minutos"]) if servico else 30

def obter_slots_livres(data_iso: str, duracao_novo: int):
    try:
        duracao_novo = int(duracao_novo)
        data_obj = datetime.strptime(data_iso, "%Y-%m-%d")
        expediente = supabase.table("expediente").select("*").eq("dia_semana", data_obj.weekday()).execute()
        dados_exp = expediente.data[0] if expediente.data else None

        if not dados_exp or not dados_exp.get('aberto', False): return []
        
        hr_abertura = datetime.strptime(str(dados_exp.get('hora_abertura', '09:00'))[:5], "%H:%M")
        hr_fechamento = datetime.strptime(str(dados_exp.get('hora_fechamento', '18:00'))[:5], "%H:%M")

        # Busca marcações ordenadas para calcular o fim de cada uma
        marcacoes = supabase.table("marcacoes").select("hora, servico").eq("data", data_iso).neq("status", "Cancelada").order("hora").execute()
        
        ocupados = []
        for m in (marcacoes.data or []):
            try:
                inicio = datetime.strptime(str(m['hora'])[:5].strip(), "%H:%M")
                dur_m = obter_duracao_servico(m['servico'])
                fim = inicio + timedelta(minutes=dur_m)
                ocupados.append({"inicio": inicio, "fim": fim})
            except Exception: continue

        fuso_br = datetime.utcnow() - timedelta(hours=3)
        
        # --- LÓGICA ANTI-BURACO COM CÁLCULO DE TÉRMINO ---
        if not ocupados:
            # Dia Vazio: Libera o início do expediente (ajustado se for hoje)
            if data_iso == fuso_br.strftime("%Y-%m-%d") and hr_abertura.time() <= fuso_br.time():
                min_atual = fuso_br.minute
                proximo_redondo = fuso_br + timedelta(minutes=(30 - min_atual % 30))
                return [proximo_redondo.strftime("%H:%M")]
            return [hr_abertura.strftime("%H:%M")]

        # Próximo horário disponível é EXATAMENTE onde o último terminou
        ultimo_fim = ocupados[-1]["fim"]
        
        # Verifica se cabe o novo serviço antes de fechar a barbearia
        if ultimo_fim + timedelta(minutes=duracao_novo) <= hr_fechamento:
            if not (data_iso == fuso_br.strftime("%Y-%m-%d") and ultimo_fim.time() <= fuso_br.time()):
                return [ultimo_fim.strftime("%H:%M")]
        
        return [] # Agenda lotada para esta duração

    except Exception: return []

def agendar_servico(cliente: str, servico_nome: str, data_iso: str, hora: str, chat_id: int):
    try:
        check = supabase.table("marcacoes").select("id").eq("data", data_iso).eq("chat_id", chat_id).neq("status", "Cancelada").execute()
        if check.data:
            data_br = datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m")
            return f"⚠️ Você já possui um agendamento para o dia {data_br}! Fale com o barbeiro para alterar."

        servico = obter_dados_servico_por_nome(servico_nome)
        if not servico: return "❌ Erro: Serviço não encontrado."

        novo_agendamento = {
            "cliente": cliente.strip().title(), "servico": servico['nome'], "data": data_iso,
            "hora": hora, "valor": servico['preco'], "status": "Pendente", "chat_id": chat_id
        }
        supabase.table("marcacoes").insert(novo_agendamento).execute()
        data_br = datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
        return f"✅ **Confirmado!**\n\n👤 {cliente.title()}\n✂️ {servico['nome']}\n💰 R$ {servico['preco']:.2f}\n📅 {data_br} às {hora}"
    except Exception: return "❌ Erro ao salvar agendamento."

# ==========================================
# PAINEL DO BARBEIRO E CHECK-IN
# ==========================================
def obter_grade_horarios_admin(data_iso: str):
    try:
        hr_ab, hr_fe = datetime.strptime("09:00", "%H:%M"), datetime.strptime("18:00", "%H:%M")
        marcacoes = supabase.table("marcacoes").select("*").eq("data", data_iso).neq("status", "Cancelada").execute()
        mapa_ocupados = {}
        for m in marcacoes.data:
            hora_str = str(m['hora'])[:5]
            if m['status'] == "Bloqueado": mapa_ocupados[hora_str] = "bloqueado"
            elif m['status'] == "Concluído": mapa_ocupados[hora_str] = "concluido"
            else: mapa_ocupados[hora_str] = "cliente"
                
        grade, atual = [], hr_ab
        while atual < hr_fe:
            h_str = atual.strftime("%H:%M")
            grade.append({"hora": h_str, "estado": mapa_ocupados.get(h_str, "livre")})
            atual += timedelta(minutes=30)
        return grade
    except Exception: return []

def alternar_bloqueio_horario(data_iso: str, hora: str):
    try:
        resposta = supabase.table("marcacoes").select("*").eq("data", data_iso).eq("hora", hora).neq("status", "Cancelada").execute()
        if not resposta.data:
            supabase.table("marcacoes").insert({"cliente": "ADMIN", "servico": "Bloqueio", "data": data_iso, "hora": hora, "valor": 0.0, "status": "Bloqueado"}).execute()
            return "Bloqueado"
        else:
            if resposta.data[0].get("status") == "Bloqueado":
                supabase.table("marcacoes").delete().eq("id", resposta.data[0]["id"]).execute()
                return "Desbloqueado"
            return "Ocupado_Cliente"
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

def buscar_agendamento_pendente_do_dia(nome_cliente: str):
    try:
        hoje = (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d")
        res = supabase.table("marcacoes").select("*").eq("data", hoje).ilike("cliente", f"%{nome_cliente}%").eq("status", "Pendente").execute()
        return res.data if res.data else []
    except Exception: return []

def fazer_checkin_por_id(id_agendamento: int):
    try:
        supabase.table("marcacoes").update({"status": "Concluído"}).eq("id", id_agendamento).execute()
        return True
    except Exception: return False

# ==========================================
# OPERAÇÕES DE CAIXA E DASHBOARD
# ==========================================
def obter_configuracoes():
    try:
        resposta = supabase.table("configuracoes").select("*").eq("id", 1).execute()
        return resposta.data[0] if resposta.data else {}
    except Exception: return {}

def atualizar_despesa(coluna: str, valor: float):
    try:
        supabase.table("configuracoes").update({coluna: valor}).eq("id", 1).execute()
        return True
    except Exception: return False

def gerar_dashboard():
    try:
        config = obter_configuracoes()
        res = supabase.table("marcacoes").select("data, valor").eq("status", "Concluído").execute()
        marcacoes = res.data or []
        
        total_ganho = sum(item["valor"] for item in marcacoes)
        hoje = datetime.utcnow() - timedelta(hours=3)
        segunda = (hoje - timedelta(days=hoje.weekday())).strftime("%Y-%m-%d")
        faturamento_semana = sum(item["valor"] for item in marcacoes if item["data"] >= segunda)
        
        gastos_fixos = float(config.get("gastos_fixos", 0))
        custo_produtos = float(config.get("custo_produtos", 0))
        
        return {
            "faturamento_bruto": total_ganho,
            "faturamento_semana": faturamento_semana,
            "gastos_fixos": gastos_fixos,
            "custo_produtos": custo_produtos,
            "lucro_liquido_real": total_ganho - (gastos_fixos + custo_produtos)
        }
    except Exception:
        return {
            "faturamento_bruto": 0.0, "faturamento_semana": 0.0,
            "gastos_fixos": 0.0, "custo_produtos": 0.0, "lucro_liquido_real": 0.0
        }

def verificar_clientes_para_lembrete():
    try:
        data_alvo = (datetime.utcnow() - timedelta(hours=3) - timedelta(days=20)).strftime("%Y-%m-%d")
        res = supabase.table("marcacoes").select("cliente, chat_id").eq("data", data_alvo).eq("status", "Concluído").execute()
        return res.data if res.data else []
    except Exception: return []