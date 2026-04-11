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
    obter_dados_admin, registrar_admin, gerar_dashboard, atualizar_despesa
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
# GERAÇÃO DO PAINEL ADMIN
# ==========================================
def gerar_menu_principal_admin():
    return [
        [{"text": "📅 Gerenciar Agenda", "callback_data": "ADM|CALENDARIO"}],
        [{"text": "💰 Painel Financeiro", "callback_data": "ADM|DASH"}]
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
        icone = "✅"
        if item["estado"] == "bloqueado": icone = "❌"
        elif item["estado"] == "cliente": icone = "🔴"
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

        # FLUXO 1: CLIQUES EM BOTÕES
        if "callback_query" in dados:
            query = dados["callback_query"]
            chat_id = query["message"]["chat"]["id"]
            message_id = query["message"]["message_id"]
            dados_clique = query["data"]
            nome_cliente = query["from"]["first_name"]

            if dados_clique.startswith("ADM|"):
                id_admin_cadastrado = obter_dados_admin()
                if str(id_admin_cadastrado).strip() != str(chat_id).strip():
                    enviar_mensagem_telegram(chat_id, "⛔ Acesso negado. Apenas o dispositivo do dono pode realizar esta ação.")
                    return {"status": "ok"}

            if dados_clique == "ADM|MENU":
                editar_mensagem_com_botoes(chat_id, message_id, "🛠️ **Painel de Controle do Barbeiro**\nO que você deseja fazer?", gerar_menu_principal_admin())

            elif dados_clique == "ADM|CALENDARIO":
                editar_mensagem_com_botoes(chat_id, message_id, "📅 **Calendário da Barbearia**\nSelecione um dia para visualizar os horários:", gerar_botoes_calendario_admin())

            elif dados_clique == "ADM|DASH":
                dash = gerar_dashboard()
                if dash:
                    texto = (
                        "💰 **Painel Financeiro**\n\n"
                        f"🔹 **Faturamento Total:** R$ {dash['faturamento_bruto']:.2f}\n"
                        f"📅 **Faturamento (Esta Semana):** R$ {dash['faturamento_semana']:.2f}\n"
                        "---------------------------\n"
                        f"🏠 **Gastos Fixos (Mês):** R$ {dash['gastos_fixos']:.2f}\n"
                        f"🧴 **Gasto c/ Produtos:** R$ {dash['custo_produtos']:.2f}\n"
                        "---------------------------\n"
                        f"💎 **LUCRO LÍQUIDO:** R$ {dash['lucro_liquido_real']:.2f}\n\n"
                        "💡 _Para alterar seus custos, basta me enviar uma mensagem normal de texto assim:_\n"
                        "`custo fixo 1500`\n"
                        "`custo produto 300`"
                    )
                else:
                    texto = "💰 **Painel Financeiro**\nNão há dados suficientes ainda."
                editar_mensagem_com_botoes(chat_id, message_id, texto, [[{"text": "⬅️ Voltar ao Menu", "callback_data": "ADM|MENU"}]])

            elif dados_clique.startswith("ADM|DIA|"):
                data_iso = dados_clique.split("|")[2]
                data_br = datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
                editar_mensagem_com_botoes(chat_id, message_id, f"🛠️ **Agenda do dia {data_br}**\n✅ Livre | ❌ Bloqueado | 🔴 Cliente", gerar_botoes_horarios_admin(data_iso))

            elif dados_clique.startswith("ADM|CLICK|"):
                _, _, data_iso, hora = dados_clique.split("|")
                detalhe = obter_detalhes_agendamento(data_iso, hora)
                
                if detalhe and detalhe["status"] != "Bloqueado":
                    texto = f"👤 **Cliente:** {detalhe['cliente']}\n✂️ **Serviço:** {detalhe['servico']}\n⏰ **Horário:** {hora}\nℹ️ **Status:** {detalhe['status']}"
                    btns = [
                        [{"text": "✅ Concluir Serviço (Check-in)", "callback_data": f"ADM|DONE|{detalhe['id']}|{data_iso}"}],
                        [{"text": "🗑️ Cancelar Agendamento", "callback_data": f"ADM|CANCEL|{detalhe['id']}|{data_iso}"}],
                        [{"text": "⬅️ Voltar", "callback_data": f"ADM|DIA|{data_iso}"}]
                    ]
                    editar_mensagem_com_botoes(chat_id, message_id, texto, btns)
                else:
                    alternar_bloqueio_horario(data_iso, hora)
                    data_br = datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
                    editar_mensagem_com_botoes(chat_id, message_id, f"🛠️ **Agenda do dia {data_br}**\n✅ Livre | ❌ Bloqueado | 🔴 Cliente", gerar_botoes_horarios_admin(data_iso))

            elif dados_clique.startswith("ADM|DONE|"):
                _, _, id_marcacao, data_iso = dados_clique.split("|")
                atualizar_status_agendamento(int(id_marcacao), "Concluído")
                editar_mensagem_com_botoes(chat_id, message_id, "✅ Serviço finalizado e faturado com sucesso!", [[{"text": "⬅️ Voltar para Agenda", "callback_data": f"ADM|DIA|{data_iso}"}]])

            elif dados_clique.startswith("ADM|CANCEL|"):
                _, _, id_marcacao, data_iso = dados_clique.split("|")
                atualizar_status_agendamento(int(id_marcacao), "Cancelada")
                editar_mensagem_com_botoes(chat_id, message_id, "❌ Agendamento cancelado.", [[{"text": "⬅️ Voltar para Agenda", "callback_data": f"ADM|DIA|{data_iso}"}]])

            # FLUXO DO CLIENTE
            elif dados_clique.startswith("S|"):
                servico = dados_clique.split("|")[1]
                duracao = obter_duracao_servico(servico)
                botoes_dias, hoje = [], datetime.utcnow() - timedelta(hours=3)
                dias_adicionados, deslocamento = 0, 0
                
                while dias_adicionados < 5:
                    data_calc = hoje + timedelta(days=deslocamento)
                    data_iso = data_calc.strftime("%Y-%m-%d")
                    if obter_slots_livres(data_iso, duracao):
                        texto_botao = data_calc.strftime("%d/%m")
                        if data_iso == hoje.strftime("%Y-%m-%d"): texto_botao = f"Hoje ({texto_botao})"
                        elif data_iso == (hoje + timedelta(days=1)).strftime("%Y-%m-%d"): texto_botao = f"Amanhã ({texto_botao})"
                        botoes_dias.append([{"text": texto_botao, "callback_data": f"D|{servico}|{data_iso}"}])
                        dias_adicionados += 1
                    deslocamento += 1
                    if deslocamento > 30: break
                
                if not botoes_dias: enviar_mensagem_telegram(chat_id, "Puxa, a agenda está lotada. Tente novamente outro dia!")
                else: enviar_mensagem_com_botoes(chat_id, f"📅 Para qual dia você quer o {servico}?", botoes_dias)

            elif dados_clique.startswith("D|"):
                _, servico, data_iso = dados_clique.split("|")
                horarios_livres = obter_slots_livres(data_iso, obter_duracao_servico(servico))
                
                if not horarios_livres: enviar_mensagem_telegram(chat_id, "Puxa, os horários esgotaram. Escolha outra data!")
                else:
                    botoes_horas, linha = [], []
                    for h in horarios_livres:
                        linha.append({"text": h, "callback_data": f"H|{servico}|{data_iso}|{h}"})
                        if len(linha) == 3: botoes_horas.append(linha); linha = []
                    if linha: botoes_horas.append(linha)
                    enviar_mensagem_com_botoes(chat_id, "⏰ Selecione um horário livre:", botoes_horas)

            elif dados_clique.startswith("H|"):
                _, servico, data_iso, hora = dados_clique.split("|")
                resposta = agendar_servico(nome_cliente, servico, data_iso, hora, 35.0)
                enviar_mensagem_telegram(chat_id, resposta)

            return {"status": "ok"}

        # FLUXO 2: MENSAGEM DE TEXTO
        if "message" not in dados: return {"status": "ignorado"}
            
        chat_id = dados["message"]["chat"]["id"]
        texto_cru = dados["message"].get("text", "")
        nome_cliente = dados["message"]["chat"].get("first_name", "Cliente")
        texto_limpo = limpar_mensagem(texto_cru)
        
        id_admin_cadastrado = obter_dados_admin()

        # ATUALIZAÇÃO DE GASTOS PELO BARBEIRO
        if texto_limpo.startswith("custo fixo ") or texto_limpo.startswith("custo produto "):
            if str(id_admin_cadastrado).strip() == str(chat_id).strip():
                try:
                    is_fixo = texto_limpo.startswith("custo fixo ")
                    texto_valor = texto_limpo.split("custo fixo ")[1] if is_fixo else texto_limpo.split("custo produto ")[1]
                    valor_float = float(texto_valor.replace(",", ".").strip())
                    
                    if is_fixo:
                        atualizar_despesa("gastos_fixos", valor_float)
                        enviar_mensagem_telegram(chat_id, f"✅ Gasto Fixo Mensal atualizado para R$ {valor_float:.2f}")
                    else:
                        atualizar_despesa("custo_produtos", valor_float)
                        enviar_mensagem_telegram(chat_id, f"✅ Gasto com Produtos atualizado para R$ {valor_float:.2f}")
                except Exception:
                    enviar_mensagem_telegram(chat_id, "❌ Erro ao ler o valor. Use o formato numérico correto. Ex: custo fixo 1500.50")
            return {"status": "ok"}

        if texto_limpo.startswith("admin "):
            chave_digitada = texto_limpo.split("admin ")[1].strip()
            if chave_digitada == CHAVE_MESTRE:
                registrar_admin(chat_id)
                enviar_mensagem_com_botoes(chat_id, "✅ **Aparelho Registrado com Sucesso!**\n\nSua permissão foi salva. Basta digitar **admin** para acessar a agenda e as finanças.\n\n🛠️ **Painel de Controle**", gerar_menu_principal_admin())
            else:
                enviar_mensagem_telegram(chat_id, "❌ Chave mestra incorreta.")
            return {"status": "ok"}
            
        elif texto_limpo in ["admin", "painel", "agenda", "gerenciar"]:
            if str(id_admin_cadastrado).strip() == str(chat_id).strip():
                enviar_mensagem_com_botoes(chat_id, "🛠️ **Painel de Controle do Barbeiro**\nO que você deseja fazer?", gerar_menu_principal_admin())
            else:
                enviar_mensagem_telegram(chat_id, "🔒 Área restrita. Se você é o dono, digite 'admin SUA_CHAVE_MESTRA' para registrar o aparelho.")
            return {"status": "ok"}

        # FLUXO NORMAL DE CLIENTE
        botoes_servicos = [
            [{"text": "✂️ Corte Simples", "callback_data": "S|Corte Simples"}],
            [{"text": "🧔 Barba", "callback_data": "S|Barba"}],
            [{"text": "✂️+🧔 Corte e Barba", "callback_data": "S|Corte e Barba"}]
        ]

        if texto_limpo in ["ola", "olá", "oi", "bom dia", "boa tarde", "boa noite", "menu"]:
            enviar_mensagem_com_botoes(chat_id, f"Olá {nome_cliente}! Qual serviço você deseja?", botoes_servicos)
            return {"status": "ok"}

        hora = None
        data_agendamento = (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d")
        servico = "Corte Simples"
        
        try:
            resultado_ia = processar_texto_com_ia(texto_cru)
            if resultado_ia and isinstance(resultado_ia, dict):
                res_hora = resultado_ia.get("hora")
                res_data = resultado_ia.get("data")
                if res_hora and str(res_hora).lower() != "null":
                    hora = res_hora
                    servico = resultado_ia.get("servico") or "Corte Simples"
                if res_data and str(res_data).lower() != "null":
                    data_agendamento = res_data
        except Exception: pass

        if not hora:
            busca = re.search(r'(\d{1,2})\s*[:hH]\s*(\d{2})?', texto_cru)
            if busca:
                h = busca.group(1).zfill(2)
                m = busca.group(2) if busca.group(2) else "00"
                hora = f"{h}:{m}"

        if not hora:
            enviar_mensagem_com_botoes(chat_id, f"Para agendar, escolha um dos serviços abaixo, {nome_cliente}:", botoes_servicos)
            return {"status": "ok"}
                
        resposta = agendar_servico(nome_cliente, servico, data_agendamento, hora, 35.0)
        enviar_mensagem_telegram(chat_id, resposta)
        return {"status": "ok"}

    except Exception as e:
        print("Erro na Rota:", e)
        return {"status": "erro"}

@router.get("/painel", response_class=HTMLResponse)
def ver_painel_grafico():
    return "<html><body><h1>Sistema Ativo ✂️</h1></body></html>"