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
    obter_grade_horarios_admin, alternar_bloqueio_horario
)

# ==========================================
# CONFIGURAÇÕES E MODELOS DE DADOS
# ==========================================
router = APIRouter()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

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
    payload = {"chat_id": chat_id, "text": texto, "reply_markup": {"inline_keyboard": botoes}}
    try: requests.post(url, json=payload, timeout=10)
    except Exception: pass

def editar_mensagem_com_botoes(chat_id: int, message_id: int, texto: str, botoes: list):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": texto, "reply_markup": {"inline_keyboard": botoes}}
    try: requests.post(url, json=payload, timeout=10)
    except Exception: pass

# ==========================================
# GERAÇÃO DO PAINEL ADMIN (CALENDÁRIO)
# ==========================================
def gerar_botoes_calendario_admin():
    hoje = datetime.utcnow() - timedelta(hours=3)
    ano = hoje.year
    mes = hoje.month
    cal = calendar.monthcalendar(ano, mes)
    
    botoes = []
    # Cabeçalho do Mês
    nome_meses = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    botoes.append([{"text": f"📅 {nome_meses[mes]} {ano}", "callback_data": "IGNORE"}])
    
    # Dias da Semana
    dias_semana = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    botoes.append([{"text": d, "callback_data": "IGNORE"} for d in dias_semana])
    
    # Grade de Dias
    for semana in cal:
        linha = []
        for dia in semana:
            if dia == 0:
                linha.append({"text": " ", "callback_data": "IGNORE"})
            else:
                data_iso = f"{ano}-{mes:02d}-{dia:02d}"
                linha.append({"text": str(dia), "callback_data": f"ADM|DIA|{data_iso}"})
        botoes.append(linha)
    return botoes

def gerar_botoes_horarios_admin(data_iso: str):
    grade = obter_grade_horarios_admin(data_iso)
    botoes = []
    linha = []
    for item in grade:
        icone = "✅"
        if item["estado"] == "bloqueado": icone = "❌"
        elif item["estado"] == "cliente": icone = "🔴"
        
        texto_botao = f"{icone} {item['hora']}"
        linha.append({"text": texto_botao, "callback_data": f"ADM|TOG|{data_iso}|{item['hora']}"})
        
        if len(linha) == 3:
            botoes.append(linha)
            linha = []
    if linha: 
        botoes.append(linha)
        
    data_br = datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    botoes.append([{"text": "⬅️ Voltar ao Calendário", "callback_data": "ADM|VOLTAR"}])
    return botoes, data_br

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

            # ADMIN: Clique no Botão "Voltar ao Calendário"
            if dados_clique == "ADM|VOLTAR":
                botoes = gerar_botoes_calendario_admin()
                editar_mensagem_com_botoes(chat_id, message_id, "🛠️ **Painel Admin: Calendário**\nSelecione um dia para configurar os horários:", botoes)

            # ADMIN: Clique em um Dia do Calendário
            elif dados_clique.startswith("ADM|DIA|"):
                data_iso = dados_clique.split("|")[2]
                botoes, data_br = gerar_botoes_horarios_admin(data_iso)
                editar_mensagem_com_botoes(chat_id, message_id, f"🛠️ **Agenda do dia {data_br}**\n✅ Livre | ❌ Bloqueado | 🔴 Cliente", botoes)

            # ADMIN: Clique para Bloquear/Desbloquear Horário
            elif dados_clique.startswith("ADM|TOG|"):
                _, _, data_iso, hora = dados_clique.split("|")
                resultado = alternar_bloqueio_horario(data_iso, hora)
                
                # Se for de cliente, avisa em vez de bloquear
                if resultado == "Ocupado_Cliente":
                    enviar_mensagem_telegram(chat_id, "⚠️ Este horário já tem um agendamento real de cliente!")
                else:
                    botoes, data_br = gerar_botoes_horarios_admin(data_iso)
                    editar_mensagem_com_botoes(chat_id, message_id, f"🛠️ **Agenda do dia {data_br}**\n✅ Livre | ❌ Bloqueado | 🔴 Cliente", botoes)

            # CLIENTE: Clique no Serviço
            elif dados_clique.startswith("S|"):
                servico = dados_clique.split("|")[1]
                duracao = obter_duracao_servico(servico)
                
                botoes_dias = []
                hoje = datetime.utcnow() - timedelta(hours=3)
                
                dias_adicionados = 0
                deslocamento = 0
                
                while dias_adicionados < 5:
                    data_calc = hoje + timedelta(days=deslocamento)
                    data_iso = data_calc.strftime("%Y-%m-%d")
                    slots = obter_slots_livres(data_iso, duracao)
                    
                    if slots:
                        texto_botao = data_calc.strftime("%d/%m")
                        if data_iso == hoje.strftime("%Y-%m-%d"): 
                            texto_botao = f"Hoje ({texto_botao})"
                        elif data_iso == (hoje + timedelta(days=1)).strftime("%Y-%m-%d"): 
                            texto_botao = f"Amanhã ({texto_botao})"
                            
                        botoes_dias.append([{"text": texto_botao, "callback_data": f"D|{servico}|{data_iso}"}])
                        dias_adicionados += 1
                    
                    deslocamento += 1
                    if deslocamento > 30: break
                
                if not botoes_dias:
                    enviar_mensagem_telegram(chat_id, "Puxa, a agenda está lotada ou fechada. Tente novamente outro dia!")
                else:
                    enviar_mensagem_com_botoes(chat_id, f"📅 Para qual dia você quer o {servico}?", botoes_dias)

            # CLIENTE: Clique no Dia
            elif dados_clique.startswith("D|"):
                _, servico, data_iso = dados_clique.split("|")
                duracao = obter_duracao_servico(servico)
                horarios_livres = obter_slots_livres(data_iso, duracao)
                
                if not horarios_livres:
                    enviar_mensagem_telegram(chat_id, "Puxa, os horários esgotaram. Escolha outra data!")
                else:
                    botoes_horas = []
                    linha = []
                    for h in horarios_livres:
                        linha.append({"text": h, "callback_data": f"H|{servico}|{data_iso}|{h}"})
                        if len(linha) == 3:
                            botoes_horas.append(linha)
                            linha = []
                    if linha: 
                        botoes_horas.append(linha)
                    enviar_mensagem_com_botoes(chat_id, "⏰ Selecione um horário livre:", botoes_horas)

            # CLIENTE: Clique na Hora
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
        
        # MODO ADMINISTRADOR - CALENDÁRIO COMPLETO
        if texto_limpo in ["admin", "painel", "agenda", "gerenciar"]:
            botoes = gerar_botoes_calendario_admin()
            enviar_mensagem_com_botoes(chat_id, "🛠️ **Painel Admin: Calendário**\nSelecione um dia para configurar os horários:", botoes)
            return {"status": "ok"}

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

    except Exception:
        return {"status": "erro"}