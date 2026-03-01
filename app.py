import streamlit as st
import datetime
import json
import requests
import gspread
import re
import PyPDF2
import os
from fpdf import FPDF # <-- Necessário adicionar fpdf2 no requirements.txt
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta

# --- 🔐 CONFIGURAÇÕES VIA SECRETS ---
MINHA_CHAVE = st.secrets["MINHA_CHAVE"]
ID_AGENDA = st.secrets["ID_AGENDA"]

st.set_page_config(page_title="Estúdio de Pilates - Coluna sem Dor", page_icon="🧘‍♀️")

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/calendar']
NOME_PLANILHA_GOOGLE = 'Leads_Pilates'

# --- FUNÇÃO PARA GERAR O PDF DO PACIENTE ---
def gerar_pdf_paciente(nome, objetivo, analise_ia):
    pdf = FPDF()
    pdf.add_page()
    
    # Logotipo no PDF
    if os.path.exists("logo.png"):
        pdf.image("logo.png", x=10, y=8, w=33)
        pdf.ln(20)
    
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "Relatório de Acolhimento", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, f"Paciente: {nome}", ln=True)
    pdf.cell(0, 10, f"Objetivo principal: {objetivo}", ln=True)
    pdf.ln(5)
    
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Entendimento inicial do seu caso:", ln=True)
    pdf.set_font("Arial", "", 11)
    pdf.multi_cell(0, 7, analise_ia)
    
    pdf.ln(20)
    pdf.set_font("Arial", "I", 8)
    pdf.set_text_color(100, 100, 100)
    # AVISO LEGAL OBRIGATÓRIO
    aviso = ("AVISO: Este documento foi gerado por Inteligência Artificial para fins informativos de acolhimento. "
             "Esta análise NÃO substitui uma avaliação física presencial. A conduta e o diagnóstico definitivo "
             "serão realizados pelo profissional responsável durante a sua consulta no estúdio.")
    pdf.multi_cell(0, 5, aviso, align='C')
    
    return pdf.output(dest='S')

# --- FUNÇÕES DE SISTEMA ---
def ler_conteudo_arquivo(uploaded_file):
    if uploaded_file is None: return ""
    try:
        if uploaded_file.type == "application/pdf":
            leitor = PyPDF2.PdfReader(uploaded_file)
            texto = "\n".join([p.extract_text() for p in leitor.pages if p.extract_text()])
            return texto
        return str(uploaded_file.read(), "utf-8")
    except: return "[Erro na leitura técnica]"

def conectar_google():
    try:
        info_chaves = json.loads(st.secrets["google_credentials"]["json_data"])
        creds = Credentials.from_service_account_info(info_chaves, scopes=SCOPES)
        return gspread.authorize(creds), build('calendar', 'v3', credentials=creds)
    except: return None, None

def consultar_ia(mensagem, sistema):
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {MINHA_CHAVE}", "Content-Type": "application/json"}
        dados = {"model": "llama-3.1-8b-instant", "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": mensagem}], "temperature": 0.4}
        resp = requests.post(url, headers=headers, json=dados)
        if resp.status_code != 200: return "Olá! Por favor, avance para o agendamento."
        return resp.json()['choices'][0]['message']['content']
    except: return "Olá! Por favor, avance para o agendamento."

def buscar_horarios_livres(service_calendar):
    sugestoes = []
    dia_foco = datetime.now() + timedelta(days=1)
    while len(sugestoes) < 15:
        if dia_foco.weekday() >= 6: dia_foco += timedelta(days=1); continue
        inicio_iso = dia_foco.replace(hour=7, minute=0, second=0).isoformat() + 'Z'
        fim_iso = dia_foco.replace(hour=20, minute=0, second=0).isoformat() + 'Z'
        try:
            events_result = service_calendar.events().list(calendarId=ID_AGENDA, timeMin=inicio_iso, timeMax=fim_iso, singleEvents=True, orderBy='startTime').execute()
            events = events_result.get('items', [])
            horas_ocupadas = [datetime.fromisoformat(e['start'].get('dateTime').replace('Z', '')).hour for e in events if 'dateTime' in e['start']]
        except: horas_ocupadas = []
        dia_txt = f"{dia_foco.strftime('%d/%m')} ({['Seg','Ter','Qua','Qui','Sex','Sáb'][dia_foco.weekday()]})"
        horarios = [7, 8, 9, 10, 17, 18, 19] if dia_foco.weekday() < 5 else [8, 9, 10, 11]
        for h in horarios:
            if h not in horas_ocupadas: sugestoes.append(f"{dia_txt} às {h}:00")
        dia_foco += timedelta(days=1)
    return sugestoes[:15]

def criar_evento_agenda(service_calendar, horario_texto, nome, tel, objetivo):
    try:
        partes = horario_texto.split(" às ")
        data_pt, hora_pt = partes[0].split(" ")[0], partes[1]
        data_c = datetime.strptime(f"{data_pt}/{datetime.now().year} {hora_pt}", "%d/%m/%Y %H:%M")
        evento = {'summary': f'Aula Exp: {nome}', 'description': f'WhatsApp: {tel}\nObjetivo: {objetivo}', 'start': {'dateTime': data_c.isoformat(), 'timeZone': 'America/Sao_Paulo'}, 'end': {'dateTime': (data_c + timedelta(hours=1)).isoformat(), 'timeZone': 'America/Sao_Paulo'}}
        service_calendar.events().insert(calendarId=ID_AGENDA, body=evento).execute()
        return "Agendado"
    except: return "Erro Agenda"

def salvar_na_planilha(client_sheets, dados):
    try:
        sh = client_sheets.open(NOME_PLANILHA_GOOGLE); sheet = sh.sheet1
        if not sheet.get_all_values():
            sheet.append_row(["Data", "Nome", "WhatsApp", "Objetivo", "Dores", "Horário", "Análise Paciente", "Arquivo", "Análise Professor", "Status"])
        sheet.append_row([dados['data_hora'], dados['nome'], dados['tel'], dados['objetivo'], dados['restricoes'], dados['melhor_horario'], dados['ia_resposta_paciente'], dados['nome_arquivo'], dados['parecer_instrutor'], dados['status_agenda']])
        return True
    except: return False

# --- FLUXO PRINCIPAL ---
def main():
    if 'fase' not in st.session_state: st.session_state.fase = 1
    if 'dados_form' not in st.session_state: st.session_state.dados_form = {}
    if 'ia_inicial' not in st.session_state: st.session_state.ia_inicial = ""
    if 'ia_resposta_paciente' not in st.session_state: st.session_state.ia_resposta_paciente = "Aguardando análise de perfil..."
    if 'conteudo_arquivo' not in st.session_state: st.session_state.conteudo_arquivo = "Sem PDF"
    if 'nome_arquivo' not in st.session_state: st.session_state.nome_arquivo = "Nenhum"

    client_sheets, service_calendar = conectar_google()

    # --- CABEÇALHO COM LOGO E TEXTO ---
    col1, col2 = st.columns([1, 3])
    with col1:
        if os.path.exists("logo.png"):
            st.image("logo.png", width=120)
        else:
            st.markdown("# 🧘‍♀️")
    with col2:
        st.markdown("## Estúdio de pilates")
        st.markdown("#### Coluna sem dor e mais qualidade de vida 🌟")
    
    st.caption("Especialistas em Pilates | Fisioterapia | RPG | Acupuntura | DTM | Palmilhas personalizadas")
    st.divider()

    if st.session_state.fase == 1:
        st.subheader("1. Conhecendo Você")
        d = st.session_state.dados_form
        nome = st.text_input("Seu Nome Completo", value=d.get("nome", ""))
        tel = st.text_input("Seu WhatsApp", placeholder="(11) 99999-9999", value=d.get("tel", ""))
        objetivo = st.selectbox("Seu objetivo principal:", ["Alívio de Dores", "Postura", "Flexibilidade", "Fortalecimento Muscular", "Gestante", "Outro"], index=0)
        restricoes = st.text_area("Descreva brevemente suas dores ou restrições médicas:", value=d.get("restricoes", ""))

        if st.button("💬 Continuar Atendimento"):
            if not nome or not tel:
                st.warning("Por favor, preencha nome e telefone.")
            else:
                st.session_state.dados_form.update({"nome": nome, "tel": tel, "objetivo": objetivo, "restricoes": restricoes})
                with st.spinner("Analisando seu perfil..."):
                    p = f"Seja uma recepcionista acolhedora para {nome} que busca {objetivo}. Valide que o Pilates ajudará e convide para a próxima fase."
                    st.session_state.ia_inicial = consultar_ia(p, "Recepcionista de Estúdio de Pilates.")
                    st.session_state.fase = 2; st.rerun()

    if st.session_state.fase == 2:
        st.subheader("2. Avaliação Preliminar")
        st.success(st.session_state.ia_inicial)
        
        st.write("---")
        st.markdown("**Você possui algum exame (Ressonância, Raio-X) em PDF?**")
        arquivo = st.file_uploader("Anexar Exame (Opcional)", type=["pdf"])
        
        if arquivo:
            st.session_state.nome_arquivo = arquivo.name
            st.session_state.conteudo_arquivo = ler_conteudo_arquivo(arquivo)
            if st.button("Analisar meu Exame"):
                with st.spinner("Lendo seu laudo..."):
                    # PROMPT SIMPLIFICADO PARA O PACIENTE
                    p_ex = f"Paciente {st.session_state.dados_form['nome']}. Exame: {st.session_state.conteudo_arquivo}. Explique em 3 linhas de forma muito simples e acolhedora o que você viu no exame e como o Pilates vai proteger a coluna dele(a)."
                    st.session_state.ia_resposta_paciente = consultar_ia(p_ex, "Fisioterapeuta que explica de forma simples e humana.")
                st.info(st.session_state.ia_resposta_paciente)
        
        st.write("---")
        c1, c2 = st.columns(2)
        if c1.button("✅ Ver Horários Disponíveis"): st.session_state.fase = 4; st.rerun()
        if c2.button("❌ Corrigir Dados"): st.session_state.fase = 1; st.rerun()

    if st.session_state.fase == 4:
        st.subheader("🗓️ Escolha seu Horário")
        horarios = buscar_horarios_livres(service_calendar)
        horario = st.selectbox("Horários sugeridos:", horarios)
        
        if st.button("✅ Confirmar Agendamento"):
            with st.spinner("Finalizando..."):
                d = st.session_state.dados_form
                # PARECER TÉCNICO PARA O PROFESSOR
                p_prof = f"Aluno: {d['nome']}. Dores: {d['restricoes']}. Exame: {st.session_state.conteudo_arquivo}. Forneça diagnóstico técnico e restrições de movimento."
                parecer = consultar_ia(p_prof, "Fisioterapeuta Sênior Analista.")
                
                status = criar_evento_agenda(service_calendar, horario, d['nome'], d['tel'], d['objetivo'])
                salvar_na_planilha(client_sheets, {**d, "data_hora": datetime.now().strftime("%d/%m %H:%M"), "melhor_horario": horario, "ia_resposta_paciente": st.session_state.ia_resposta_paciente, "nome_arquivo": st.session_state.nome_arquivo, "parecer_instrutor": parecer, "status_agenda": status})
                st.session_state.fase = 5; st.rerun()

    if st.session_state.fase == 5:
        st.balloons()
        st.success("✅ Agendamento Realizado com Sucesso!")
        st.write("Aguardamos você para sua aula experimental!")
        
        # BOTÃO DE DOWNLOAD DO PDF
        pdf_bytes = gerar_pdf_paciente(st.session_state.dados_form['nome'], st.session_state.dados_form['objetivo'], st.session_state.ia_resposta_paciente)
        st.download_button(label="📥 Baixar meu Relatório de Acolhimento (PDF)", data=pdf_bytes, file_name=f"Boas_Vindas_{st.session_state.dados_form['nome']}.pdf", mime="application/pdf")
        
        st.divider()
        st.button("🔄 Novo Atendimento", on_click=lambda: st.session_state.clear())

if __name__ == "__main__":
    main()
