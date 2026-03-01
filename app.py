import streamlit as st
import datetime
import json
import requests
import gspread
import re
import PyPDF2
import os
from fpdf import FPDF 
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta

# --- 🔐 CONFIGURAÇÕES VIA SECRETS ---
MINHA_CHAVE = st.secrets["MINHA_CHAVE"]
ID_AGENDA = st.secrets["ID_AGENDA"]

st.set_page_config(page_title="Estúdio de Pilates - Coluna sem Dor", page_icon="🧘‍♀️")

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/calendar']
NOME_PLANILHA_GOOGLE = 'Leads_Pilates'

# --- FUNÇÃO PARA GERAR O PDF DO PACIENTE COM DATA E HORA ---
def gerar_pdf_paciente(nome, objetivo, horario, analise_ia, tipo_atendimento):
    pdf = FPDF()
    pdf.add_page()
    
    if os.path.exists("logo.png"):
        pdf.image("logo.png", x=10, y=8, w=33)
        pdf.ln(20)
    
    pdf.set_font("Arial", "B", 16)
    titulo = "Comprovante de Agendamento" if "Aluno" in tipo_atendimento else "Relatorio de Acolhimento"
    pdf.cell(0, 10, titulo.encode('latin-1', 'replace').decode('latin-1'), ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, f"Paciente: {nome}".encode('latin-1', 'replace').decode('latin-1'), ln=True)
    pdf.cell(0, 10, f"Servico: {tipo_atendimento}".encode('latin-1', 'replace').decode('latin-1'), ln=True)
    pdf.cell(0, 10, f"Objetivo: {objetivo}".encode('latin-1', 'replace').decode('latin-1'), ln=True)
    
    pdf.set_text_color(0, 102, 204)
    pdf.cell(0, 10, f"Horario: {horario}".encode('latin-1', 'replace').decode('latin-1'), ln=True)
    pdf.set_text_color(0, 0, 0)
    
    if "Avaliação" in tipo_atendimento or "Fisioterapia" in tipo_atendimento:
        pdf.ln(5)
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, "Analise Inicial:".encode('latin-1', 'replace').decode('latin-1'), ln=True)
        pdf.set_font("Arial", "", 11)
        pdf.multi_cell(0, 7, analise_ia.encode('latin-1', 'replace').decode('latin-1'))
    
    pdf.ln(20)
    pdf.set_font("Arial", "I", 8)
    pdf.set_text_color(100, 100, 100)
    aviso = ("AVISO: Este documento confirma seu agendamento. Esta analise nao substitui "
             "a avaliacao presencial clinica.").encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 5, aviso, align='C')
    
    return bytes(pdf.output())

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
        return resp.json()['choices'][0]['message']['content']
    except: return "Olá! Entendido. Vamos prosseguir."

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
        evento = {'summary': f'{objetivo}: {nome}', 'description': f'WhatsApp: {tel}', 'start': {'dateTime': data_c.isoformat(), 'timeZone': 'America/Sao_Paulo'}, 'end': {'dateTime': (data_c + timedelta(hours=1)).isoformat(), 'timeZone': 'America/Sao_Paulo'}}
        service_calendar.events().insert(calendarId=ID_AGENDA, body=evento).execute()
        return "Agendado"
    except: return "Erro Agenda"

def salvar_na_planilha(client_sheets, dados):
    try:
        sh = client_sheets.open(NOME_PLANILHA_GOOGLE); sheet = sh.sheet1
        if not sheet.get_all_values():
            sheet.append_row(["Data", "Nome", "WhatsApp", "Objetivo", "Dores", "Horário", "Análise Paciente", "Arquivo", "Análise Professor", "Status", "Tipo"])
        sheet.append_row([dados['data_hora'], dados['nome'], dados['tel'], dados['objetivo'], dados.get('restricoes', 'N/A'), dados['melhor_horario'], dados.get('ia_resposta_paciente', 'N/A'), dados.get('nome_arquivo', 'Nenhum'), dados.get('parecer_instrutor', 'N/A'), dados['status_agenda'], dados['tipo']])
        return True
    except: return False

# --- FLUXO PRINCIPAL ---
def main():
    # --- METADADOS PARA PREVIEW NO WHATSAPP ---
    st.markdown(f"""
        <head>
            <meta property="og:title" content="Estúdio de Pilates - Coluna sem Dor" />
            <meta property="og:description" content="Agendamento Inteligente e Avaliação Especializada 🧘‍♀️" />
            <meta property="og:image" content="https://raw.githubusercontent.com/consultor-frederico/Physion_Gym_Atendente/main/logo.png" />
            <meta property="og:type" content="website" />
        </head>
    """, unsafe_allow_html=True)

    if 'fase' not in st.session_state: st.session_state.fase = 0 
    if 'tipo_atendimento' not in st.session_state: st.session_state.tipo_atendimento = ""
    if 'dados_form' not in st.session_state: st.session_state.dados_form = {}
    if 'ia_inicial' not in st.session_state: st.session_state.ia_inicial = ""
    if 'ia_resposta_paciente' not in st.session_state: st.session_state.ia_resposta_paciente = ""
    if 'conteudo_arquivo' not in st.session_state: st.session_state.conteudo_arquivo = ""
    if 'nome_arquivo' not in st.session_state: st.session_state.nome_arquivo = "Nenhum"
    if 'horario_escolhido' not in st.session_state: st.session_state.horario_escolhido = ""

    client_sheets, service_calendar = conectar_google()

    col1, col2 = st.columns([1, 3])
    with col1:
        if os.path.exists("logo.png"): st.image("logo.png", width=120)
        else: st.markdown("# 🧘‍♀️")
    with col2:
        st.markdown("## Estúdio de pilates")
        st.markdown("#### Coluna sem dor e mais qualidade de vida 🌟")
    
    st.caption("Pilates | Fisioterapia | RPG | Acupuntura | DTM")
    st.divider()

    # --- FASE 0: ESCOLHA DO SERVIÇO ---
    if st.session_state.fase == 0:
        st.subheader("Como podemos ajudar você hoje?")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.info("🧘 **Já sou Aluno(a)**")
            if st.button("Marcar minha Aula"):
                st.session_state.tipo_atendimento = "Aluno da Casa"
                st.session_state.fase = 1; st.rerun()
        with c2:
            st.success("✨ **Quero ser Aluno(a)**")
            if st.button("Agendar Aula Exp."):
                st.session_state.fase = 0.5; st.rerun()
        with c3:
            st.warning("🏥 **Fisioterapia**")
            if st.button("Agendar Consulta"):
                st.session_state.tipo_atendimento = "Consulta Fisioterapia"
                st.session_state.fase = 1; st.rerun()

    if st.session_state.fase == 0.5:
        st.subheader("Bem-vindo! Escolha o tipo de aula:")
        if st.button("Apenas agendar (Rápido)"):
            st.session_state.tipo_atendimento = "Novo Aluno - Direto"
            st.session_state.fase = 1; st.rerun()
        if st.button("Agendar com Avaliação Técnica"):
            st.session_state.tipo_atendimento = "Novo Aluno - Avaliação"
            st.session_state.fase = 1; st.rerun()
        if st.button("⬅️ Voltar"): st.session_state.fase = 0; st.rerun()

    if st.session_state.fase == 1:
        st.subheader(f"Agendamento: {st.session_state.tipo_atendimento}")
        nome = st.text_input("Nome Completo")
        tel = st.text_input("WhatsApp", placeholder="(11) 99999-9999")
        
        objetivo = "Manutenção"
        restricoes = "N/A"
        
        if "Novo" in st.session_state.tipo_atendimento or "Fisioterapia" in st.session_state.tipo_atendimento:
            objetivo = st.selectbox("Seu objetivo principal:", ["Alívio de Dores", "Postura", "Recuperação de Lesão", "Flexibilidade", "Outro"])
            restricoes = st.text_area("Descreva brevemente o que sente:")

        if st.button("Próximo Passo"):
            if nome and tel:
                st.session_state.dados_form = {"nome": nome, "tel": tel, "objetivo": objetivo, "restricoes": restricoes}
                if "Avaliação" in st.session_state.tipo_atendimento or "Fisioterapia" in st.session_state.tipo_atendimento:
                    with st.spinner("Analisando seu perfil..."):
                        p = f"Aja como recepcionista clínica. Chame {nome} pelo nome. Diga que entendeu o caso de {objetivo} e acolha o relato '{restricoes}'. Seja sucinta (2 linhas)."
                        st.session_state.ia_inicial = consultar_ia(p, "Recepcionista Clínica.")
                    st.session_state.fase = 2
                else: st.session_state.fase = 4
                st.rerun()
            else: st.warning("Preencha os campos obrigatórios.")

    if st.session_state.fase == 2:
        st.subheader("Triagem Técnica")
        st.success(st.session_state.ia_inicial)
        arquivo = st.file_uploader("Possui exames em PDF?", type=["pdf"])
        if arquivo:
            st.session_state.nome_arquivo = arquivo.name
            st.session_state.conteudo_arquivo = ler_conteudo_arquivo(arquivo)
            if st.button("Analisar Exame"):
                with st.spinner("Lendo laudo..."):
                    p_ex = f"Paciente {st.session_state.dados_form['nome']}. Conteúdo: {st.session_state.conteudo_arquivo}. Resuma em 3 linhas o diagnóstico de forma humana."
                    st.session_state.ia_resposta_paciente = consultar_ia(p_ex, "Fisioterapeuta Analista.")
                st.info(st.session_state.ia_resposta_paciente)
        
        if st.button("✅ Ver Horários"): st.session_state.fase = 4; st.rerun()

    if st.session_state.fase == 4:
        st.subheader("🗓️ Escolha o Horário")
        horarios = buscar_horarios_livres(service_calendar)
        horario = st.selectbox("Disponíveis:", horarios)
        
        if st.button("Confirmar Agendamento"):
            with st.spinner("Reservando..."):
                st.session_state.horario_escolhido = horario
                d = st.session_state.dados_form
                
                if "Avaliação" in st.session_state.tipo_atendimento or "Fisioterapia" in st.session_state.tipo_atendimento:
                    p_final = f"Paciente {d['nome']}. Relato: {d['restricoes']}. Objetivo: {d['objetivo']}. Exame: {st.session_state.conteudo_arquivo}. Resuma o acolhimento para o PDF."
                    st.session_state.ia_resposta_paciente = consultar_ia(p_final, "Analista de Acolhimento.")
                
                status = criar_evento_agenda(service_calendar, horario, d['nome'], d['tel'], d['objetivo'])
                salvar_na_planilha(client_sheets, {**d, "data_hora": datetime.now().strftime("%d/%m %H:%M"), "melhor_horario": horario, "ia_resposta_paciente": st.session_state.ia_resposta_paciente, "nome_arquivo": st.session_state.nome_arquivo, "status_agenda": status, "tipo": st.session_state.tipo_atendimento})
                st.session_state.fase = 5; st.rerun()

    if st.session_state.fase == 5:
        st.balloons()
        st.success(f"✅ Agendamento Realizado com Sucesso!")
        st.markdown(f"### Aula/Consulta confirmada: **{st.session_state.horario_escolhido}**")
        
        pdf_bytes = gerar_pdf_paciente(st.session_state.dados_form['nome'], st.session_state.dados_form['objetivo'], st.session_state.horario_escolhido, st.session_state.ia_resposta_paciente, st.session_state.tipo_atendimento)
        st.download_button(label="📥 Baixar Comprovante (PDF)", data=pdf_bytes, file_name=f"Agendamento_{st.session_state.dados_form['nome']}.pdf", mime="application/pdf")
        
        st.button("🔄 Novo Atendimento", on_click=lambda: st.session_state.clear())

if __name__ == "__main__":
    main()
