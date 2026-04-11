import os
import requests
import re
import calendar
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from app.services import (
    limpar_mensagem, agendar_servico, processar_texto_com_ia,
    obter_duracao_servico, obter_slots_livres,
    obter_grade_horarios_admin, alternar_bloqueio_horario,
    obter_detalhes_agendamento, atualizar_status_agendamento,
    obter_dados_admin, registrar_admin, gerar_dashboard, 
    atualizar_despesa, buscar_agendamento_pendente_do_dia, 
    fazer_checkin_por_id, verificar_clientes_para_lembrete
)

# ==========================================
# CONFIGURAÇÕES E SEGURANÇA
# ==========================================
router = APIRouter()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAVE_MESTRE = os.getenv("CHAVE_MESTRE", "12345") 

# ==========================================
# INTEGRAÇÃO EXTERNA (TELEGRAM E BOTÕES)
# ==========================================
def enviar_mensagem_telegram(chat_id: int, texto: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto}
    try: requests.post(url, json=payload, timeout=10)
    except Exception: pass

def enviar_mensagem_com_botoes(chat_id: int, texto: str, botoes: list):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": texto, "reply_markup": {"inline_keyboard": botoes}, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except Exception: pass

def editar_mensagem_com_botoes(chat_id: int, message_id: int, texto: str, botoes: list):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": texto, "reply_markup": {"inline_keyboard": botoes}, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload, timeout=10)
    except Exception: pass

# ==========================================
# GERAÇÃO DO PAINEL ADMIN (MENU E FINANÇAS)
# ==========================================
def gerar_menu_principal_admin():
    return [
        [{"text": "📅 Gerenciar Agenda", "callback_data": "ADM|CALENDARIO"}],
        [{"text": "💰 Painel Financeiro", "callback_data": "ADM|DASH"}],
        [{"text": "📣 Avisar Clientes (20 dias)", "callback_data": "ADM|AVISO"}]
    ]

def gerar_botoes_calendario_admin():
    hoje = datetime.utcnow() - timedelta(hours=3)
    ano, mes = hoje.year, hoje.month
    cal = calendar.monthcalendar(ano, mes)
    botoes = []
    nome_meses = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    botoes.append([{"text": f"📅 Agenda {nome_meses[mes]} {ano}", "callback_data": "IGNORE"}])
    botoes.append([{"text": d, "callback_data": "IGNORE"} for d in ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]])
    for semana in cal:
        linha = []
        for dia in semana:
            if dia == 0: linha.append({"text": " ", "callback_data": "IGNORE"})
            else: linha.append({"text": str(dia), "callback_data": f"ADM|DIA|{ano}-{mes:02d}-{dia:02d}"})
        botoes.append(linha)
    botoes.append([{"text": "⬅️ Voltar ao Menu", "callback_data": "ADM|MENU"}])
    return botoes

def gerar_botoes_horarios_admin(data_iso: str):
    grade = obter_grade_horarios_admin(data_iso)
    botoes, linha = [], []
    for item in grade:
        # DEFINIÇÃO DOS EMOJIS (AZUL PARA CONCLUÍDO)
        icone = "✅"
        if item["estado"] == "bloqueado": icone = "❌"
        elif item["estado"] == "cliente": icone = "🔴"
        elif item["estado"] == "concluido": icone = "🔵"
        
        linha.append({"text": f"{icone} {item['hora']}", "callback_data": f"ADM|CLICK|{data_iso}|{item['hora']}"})
        if len(linha) == 3: botoes.append(linha); linha = []
    if linha: botoes.append(linha)
    botoes.append([{"text": "⬅️ Voltar ao Calendário", "callback_data": "ADM|CALENDARIO"}])
    return botoes

# ==========================================
# WEBHOOK PRINCIPAL (RECEPÇÃO DE MENSAGENS)
# ==========================================
@router.post("/telegram/receber")
async def bot_recebe_mensagem(request: Request):
    try:
        dados = await request.json()

        # --- FLUXO 1: CLIQUES EM BOTÕES (CALLBACKS) ---
        if "callback_query" in dados:
            query = dados["callback_query"]
            chat_id = query["message"]["chat"]["id"]
            msg_id = query["message"]["message_id"]
            clique = query["data"]
            nome_user = query["from"]["first_name"]

            # --- SEGURANÇA ADMIN ---
            if clique.startswith("ADM|"):
                id_admin = obter_dados_admin()
                if str(id_admin).strip() != str(chat_id).strip():
                    enviar_mensagem_telegram(chat_id, "⛔ Acesso negado.")
                    return {"status": "ok"}

                if clique == "ADM|MENU":
                    editar_mensagem_com_botoes(chat_id, msg_id, "🛠️ **Painel Admin**", gerar_menu_principal_admin())
                elif clique == "ADM|CALENDARIO":
                    editar_mensagem_com_botoes(chat_id, msg_id, "📅 **Agenda**", gerar_botoes_calendario_admin())
                elif clique == "ADM|AVISO":
                    clientes = verificar_clientes_para_lembrete()
                    if not clientes: 
                        enviar_mensagem_telegram(chat_id, "✅ Nenhum cliente para avisar hoje.")
                    else:
                        for clie in clientes:
                            msg = f"Olá {clie['cliente']}! 👋 Já faz 20 dias do seu último corte. A agenda está aberta, que tal agendar?"
                            enviar_mensagem_com_botoes(clie['chat_id'], msg, [[{"text": "✂️ Agendar Agora", "callback_data": "MENU"}]])
                        enviar_mensagem_telegram(chat_id, f"📩 {len(clientes)} Lembrete(s) enviado(s)!")
                elif clique == "ADM|DASH":
                    d = gerar_dashboard()
                    txt = f"💰 **Painel Financeiro**\n\n🔹 **Semana:** R$ {d['faturamento_semana']:.2f}\n🔹 **Total:** R$ {d['faturamento_bruto']:.2f}\n---------------------------\n💎 **LUCRO:** R$ {d['lucro_liquido_real']:.2f}"
                    editar_mensagem_com_botoes(chat_id, msg_id, txt, [[{"text": "⬅️ Voltar", "callback_data": "ADM|MENU"}]])
                elif clique.startswith("ADM|DIA|"):
                    dt = clique.split("|")[2]
                    editar_mensagem_com_botoes(chat_id, msg_id, f"📅 Agenda {dt}", gerar_botoes_horarios_admin(dt))
                elif clique.startswith("ADM|CLICK|"):
                    _, _, dt, hr = clique.split("|"); det = obter_detalhes_agendamento(dt, hr)
                    if det and det["status"] != "Bloqueado":
                        emoji = "🔴" if det["status"] == "Pendente" else "🔵"
                        txt = f"👤 **Cliente:** {det['cliente']}\n✂️ **Serviço:** {det['servico']}\n⏰ **Horário:** {hr}\n{emoji} **Status:** {det['status']}"
                        btns = []
                        if det["status"] == "Pendente": 
                            btns.append([{"text": "✅ Concluir (Check-in)", "callback_data": f"ADM|DONE|{det['id']}|{dt}"}])
                        btns.append([{"text": "🗑️ Cancelar Agendamento", "callback_data": f"ADM|CANCEL|{det['id']}|{dt}"}])
                        btns.append([{"text": "⬅️ Voltar", "callback_data": f"ADM|DIA|{dt}"}])
                        editar_mensagem_com_botoes(chat_id, msg_id, txt, btns)
                    else:
                        alternar_bloqueio_horario(dt, hr); editar_mensagem_com_botoes(chat_id, msg_id, f"📅 Agenda {dt}", gerar_botoes_horarios_admin(dt))
                elif clique.startswith("ADM|DONE|"):
                    _, _, id_m, dt = clique.split("|"); atualizar_status_agendamento(int(id_m), "Concluído")
                    editar_mensagem_com_botoes(chat_id, msg_id, "✅ **Concluído!**", [[{"text": "⬅️ Voltar", "callback_data": f"ADM|DIA|{dt}"}]])
                elif clique.startswith("ADM|CANCEL|"):
                    _, _, id_m, dt = clique.split("|"); atualizar_status_agendamento(int(id_m), "Cancelada")
                    editar_mensagem_com_botoes(chat_id, msg_id, "❌ **Cancelado!**", [[{"text": "⬅️ Voltar", "callback_data": f"ADM|DIA|{dt}"}]])

            # --- LÓGICA DO CLIENTE ---
            elif clique == "MENU":
                btns = [[{"text": "✂️ Corte", "callback_data": "S|Corte Simples"}], [{"text": "🧔 Barba", "callback_data": "S|Barba"}]]
                enviar_mensagem_com_botoes(chat_id, "O que deseja agendar?", btns)
            elif clique.startswith("CLIENTE|CHECKIN|"):
                id_agend = clique.split("|")[2]; fazer_checkin_por_id(int(id_agend))
                editar_mensagem_com_botoes(chat_id, msg_id, "✅ **Check-in realizado!** Bom corte!", [])
            elif clique.startswith("S|"):
                serv = clique.split("|")[1]; dur = obter_duracao_servico(serv); b_dias, hj = [], datetime.utcnow() - timedelta(hours=3)
                for i in range(7):
                    dt_iso = (hj + timedelta(days=i)).strftime("%Y-%m-%d")
                    if obter_slots_livres(dt_iso, dur): 
                        b_dias.append([{"text": (hj + timedelta(days=i)).strftime("%d/%m"), "callback_data": f"D|{serv}|{dt_iso}"}])
                enviar_mensagem_com_botoes(chat_id, f"📅 Para quando o {serv}?", b_dias)
            elif clique.startswith("D|"):
                _, s, d = clique.split("|"); slots = obter_slots_livres(d, obter_duracao_servico(s)); b_hrs, lin = [], []
                for h in slots:
                    lin.append({"text": h, "callback_data": f"H|{s}|{d}|{h}"})
                    if len(lin) == 3: b_hrs.append(lin); lin = []
                if lin: b_hrs.append(lin)
                enviar_mensagem_com_botoes(chat_id, "⏰ Escolha o horário:", b_hrs)
            elif clique.startswith("H|"):
                _, s, d, h = clique.split("|"); res = agendar_servico(nome_user, s, d, h, 35.0, chat_id)
                enviar_mensagem_telegram(chat_id, res)
            return {"status": "ok"}

        # --- FLUXO 2: MENSAGENS DE TEXTO ---
        if "message" not in dados: return {"status": "ignorado"}
        chat_id = dados["message"]["chat"]["id"]; texto_limpo = limpar_mensagem(dados["message"].get("text", "")); nome_user = dados["message"]["chat"].get("first_name", "Cliente")
        id_admin = obter_dados_admin()

        if texto_limpo.startswith("admin "):
            if texto_limpo.split("admin ")[1] == CHAVE_MESTRE:
                registrar_admin(chat_id); enviar_mensagem_com_botoes(chat_id, "✅ **Dono Registrado!**", gerar_menu_principal_admin())
            return {"status": "ok"}
        if texto_limpo in ["admin", "painel"] and str(id_admin) == str(chat_id):
            enviar_mensagem_com_botoes(chat_id, "🛠️ **Painel Admin**", gerar_menu_principal_admin()); return {"status": "ok"}
        if (texto_limpo.startswith("custo fixo ") or texto_limpo.startswith("custo produto ")) and str(id_admin) == str(chat_id):
            col = "gastos_fixos" if "fixo" in texto_limpo else "custo_produtos"; val = float(re.findall(r'\d+', texto_limpo)[0])
            atualizar_despesa(col, val); enviar_mensagem_telegram(chat_id, f"✅ {col} atualizado!"); return {"status": "ok"}

        agendamentos_hoje = buscar_agendamento_pendente_do_dia(nome_user)
        if agendamentos_hoje and texto_limpo not in ["admin", "painel"]:
            ag = agendamentos_hoje[0]
            txt_ch = f"Olá! 👋 Vi que você tem horário hoje às {str(ag['hora'])[:5]}. Já chegou?"
            enviar_mensagem_com_botoes(chat_id, txt_ch, [[{"text": "📍 Sim, cheguei!", "callback_data": f"CLIENTE|CHECKIN|{ag['id']}"}], [{"text": "📅 Ver Menu", "callback_data": "MENU"}]])
            return {"status": "ok"}

        btns = [[{"text": "✂️ Corte", "callback_data": "S|Corte Simples"}], [{"text": "🧔 Barba", "callback_data": "S|Barba"}]]
        enviar_mensagem_com_botoes(chat_id, f"Olá {nome_user}! O que deseja agendar?", btns)

    except Exception as e:
        print(f"Erro na Rota: {e}"); return {"status": "erro"}
    return {"status": "ok"}

# ==========================================
# INTERFACE DO PAINEL WEB (DASHBOARD)
# ==========================================
@router.get("/painel", response_class=HTMLResponse)
def ver_painel(): return "<html><body><h1>Sistema Ativo ✂️</h1></body></html>"