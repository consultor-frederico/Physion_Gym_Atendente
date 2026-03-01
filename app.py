import streamlit as st
import datetime
import json
import requests
import gspread
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta

# --- 🔐 CONFIGURAÇÕES VIA SECRETS ---
MINHA_CHAVE = st.secrets["MINHA_CHAVE"]
ID_AGENDA = st.secrets["ID_AGENDA"]

st.set_page_config(page_title="Studio Pilates - Recepção", page_icon="🧘‍♀️")

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/calendar']
NOME_PLANILHA_GOOGLE = 'Leads_Pilates' # Nome da planilha que você vai criar para o cliente

# --- CSS PARA ESCONDER ÍCONES DO STREAMLIT ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stAppDeployButton {display:none;}
    [data-testid="stStatusWidget"] {visibility: hidden;}
    .viewerBadge_container__1QSob {display:none !important;}
    </style>
    """, unsafe_allow_html=True)

# --- CALLBACKS DE FORMATAÇÃO ---
def formatar_tel_callback():
    val = st.session_state.tel_input
    limpo = re.sub(r'\D', '', str(val))
    if len(limpo) == 11:
        st.session_state.tel_input = f"({limpo[:2]}) {limpo[2:7]}-{limpo[7:]}"
    elif len(limpo) == 10:
        st.session_state.tel_input = f"({limpo[:2]}) {limpo[2:6]}-{limpo[6:]}"

# --- FUNÇÕES DE SISTEMA ---
def conectar_google():
    try:
        info_chaves = json.loads(st.secrets["google_credentials"]["json_data"])
        creds = Credentials.from_service_account_info(info_chaves, scopes=SCOPES)
        return gspread.authorize(creds), build('calendar', 'v3', credentials=creds)
    except Exception as e:
        return None, None

def consultar_ia(mensagem, sistema):
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {MINHA_CHAVE}", "Content-Type": "application/json"}
        # Modelo rápido e estável
        dados = {"model": "llama-3.1-8b-instant", "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": mensagem}], "temperature": 0.4}
        resp = requests.post(url, headers=headers, json=dados).json()
        return resp['choices'][0]['message']['content']
    except: 
        return "Olá! Ficamos muito felizes com seu interesse. Por favor, avance para escolher o melhor horário para sua aula."

def buscar_horarios_livres(service_calendar):
    sugestoes = []
    dia_foco = datetime.now() + timedelta(days=1)
    while len(sugestoes) < 15:
        if dia_foco.weekday() >= 6: # Pula Domingo
            dia_foco += timedelta(days=1); continue
        inicio_iso = dia_foco.replace(hour=7, minute=0, second=0).isoformat() + 'Z'
        fim_iso = dia_foco.replace(hour=20, minute=0, second=0).isoformat() + 'Z'
        try:
            events_result = service_calendar.events().list(calendarId=ID_AGENDA, timeMin=inicio_iso, timeMax=fim_iso, singleEvents=True, orderBy='startTime').execute()
            events = events_result.get('items', [])
            horas_ocupadas = [datetime.fromisoformat(e['start'].get('dateTime').replace('Z', '')).hour for e in events if 'dateTime' in e['start']]
        except: horas_ocupadas = []
        
        dia_txt = f"{dia_foco.strftime('%d/%m')} ({['Seg','Ter','Qua','Qui','Sex','Sáb'][dia_foco.weekday()]})"
        # Horários típicos de Pilates (Manhã e Fim de Tarde)
        horarios_pilates = [7, 8, 9, 10, 17, 18, 19] if dia_foco.weekday() < 5 else [8, 9, 10, 11]
        
        for h in horarios_pilates:
            if h not in horas_ocupadas:
                sugestoes.append(f"{dia_txt} às {h}:00")
        dia_foco += timedelta(days=1)
    return sugestoes[:15]

def criar_evento_agenda(service_calendar, horario_texto, nome, tel, objetivo):
    try:
        partes = horario_texto.split(" às ")
        data_pt, hora_pt = partes[0].split(" ")[0], partes[1]
        data_c = datetime.strptime(f"{data_pt}/{datetime.now().year} {hora_pt}", "%d/%m/%Y %H:%M")
        evento = {
            'summary': f'Aula Exp: {nome}', 
            'description': f'WhatsApp: {tel}\nObjetivo: {objetivo}', 
            'start': {'dateTime': data_c.isoformat(), 'timeZone': 'America/Sao_Paulo'}, 
            'end': {'dateTime': (data_c + timedelta(hours=1)).isoformat(), 'timeZone': 'America/Sao_Paulo'}
        }
        service_calendar.events().insert(calendarId=ID_AGENDA, body=evento).execute()
        return "Agendado"
    except: return "Erro Agenda"

def salvar_na_planilha(client_sheets, dados):
    try:
        sh = client_sheets.open(NOME_PLANILHA_GOOGLE); sheet = sh.sheet1
        if not sheet.get_all_values():
            sheet.append_row(["Data da Triagem", "Nome", "WhatsApp", "Objetivo", "Restrições/Dores", "Horário Agendado", "Parecer da IA para Instrutor", "Status"])
        linha = [
            dados['data_hora'], dados['nome'], dados['tel'], dados['objetivo'], 
            dados['restricoes'], dados['melhor_horario'], dados['parecer_instrutor'], dados['status_agenda']
        ]
        sheet.append_row(linha)
        return True
    except: return False

# --- FLUXO PRINCIPAL ---
def main():
    if 'fase' not in st.session_state: st.session_state.fase = 1
    if 'dados_form' not in st.session_state: st.session_state.dados_form = {}
    if 'ia_inicial' not in st.session_state: st.session_state.ia_inicial = ""

    client_sheets, service_calendar = conectar_google()

    col_logo, col_text = st.columns([1, 4])
    with col_logo: st.markdown("<h1 style='text-align: center; margin-top: 5px;'>🧘‍♀️</h1>", unsafe_allow_html=True)
    with col_text:
        st.markdown("<h2 style='margin-bottom: -15px;'>Studio Pilates - Recepção</h2>", unsafe_allow_html=True)
        st.markdown("<h4 style='color: gray;'>Triagem e Agendamento</h4>", unsafe_allow_html=True)
    st.divider()

    if st.session_state.fase == 1:
        st.subheader("1. Conhecendo Você")
        d = st.session_state.dados_form
        
        nome = st.text_input("Seu Nome Completo", value=d.get("nome", ""))
        tel = st.text_input("Seu WhatsApp", key="tel_input", on_change=formatar_tel_callback, placeholder="(11) 99999-9999", value=d.get("tel", ""))
        
        objetivos = ["Alívio de Dores", "Ganho de Flexibilidade", "Fortalecimento Muscular", "Correção Postural", "Gestante", "Outro"]
        objetivo = st.selectbox("Qual o seu principal objetivo com o Pilates?", objetivos, index=objetivos.index(d.get("objetivo")) if d.get("objetivo") in objetivos else 0)
        
        restricoes = st.text_area("Você possui alguma dor crônica, cirurgia recente ou restrição médica? (Descreva brevemente)", value=d.get("restricoes", ""))

        if st.button("💬 Continuar Atendimento"):
            if not nome or not tel: st.warning("Por favor, preencha Nome e WhatsApp para continuarmos.")
            else:
                st.session_state.dados_form.update({"nome": nome, "tel": tel, "objetivo": objetivo, "restricoes": restricoes})
                with st.spinner("Nossa equipe virtual está analisando seu perfil..."):
                    p = f"Aja como uma recepcionista muito acolhedora de um Studio de Pilates de alto padrão. O(a) futuro(a) aluno(a) {nome} busca o Pilates para {objetivo}. Condição física relatada: {restricoes}. Dê as boas-vindas, valide que o Pilates é excelente para o caso dele(a) (sem dar diagnósticos médicos) e convide calorosamente para agendar uma Aula Experimental."
                    st.session_state.ia_inicial = consultar_ia(p, "Recepcionista de Studio de Pilates.")
                    st.session_state.fase = 2; st.rerun()

    if st.session_state.fase == 2:
        st.subheader("2. Avaliação Preliminar")
        st.success(st.session_state.ia_inicial)
        
        c1, c2 = st.columns(2)
        if c1.button("✅ Ver Horários Disponíveis"): st.session_state.fase = 4; st.rerun()
        if c2.button("❌ Corrigir Meus Dados"): st.session_state.fase = 1; st.rerun()

    if st.session_state.fase == 4:
        st.subheader("🗓️ Aula Experimental")
        st.write("Escolha um horário para vir conhecer nosso espaço e metodologia.")
        horarios = buscar_horarios_livres(service_calendar)
        horario = st.selectbox("Horários disponíveis:", horarios)
        
        if st.button("✅ Confirmar Aula"):
            with st.spinner("Reservando seu horário..."):
                d = st.session_state.dados_form
                
                # IA gera um resumo técnico para o professor do Studio ler antes da aula
                p_instrutor = f"Faça um resumo de 3 linhas para o instrutor de Pilates se preparar para a aula. Aluno: {d['nome']}. Objetivo: {d['objetivo']}. Restrição/Dor: {d['restricoes']}."
                parecer = consultar_ia(p_instrutor, "Fisioterapeuta Especialista em Pilates")
                
                status = criar_evento_agenda(service_calendar, horario, d['nome'], d['tel'], d['objetivo'])
                salvar_na_planilha(client_sheets, {**d, "data_hora": datetime.now().strftime("%d/%m %H:%M"), "melhor_horario": horario, "parecer_instrutor": parecer, "status_agenda": status})
                
                st.session_state.fase = 5; st.rerun()

    if st.session_state.fase == 5:
        st.balloons()
        st.success("✅ Aula Experimental Agendada com Sucesso!")
        st.info("Nossa equipe enviará uma mensagem no seu WhatsApp para confirmar os detalhes. Venha com roupas leves e confortáveis!")
        st.button("🔄 Novo Atendimento", on_click=lambda: st.session_state.clear())

if __name__ == "__main__":
    main()
