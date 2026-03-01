import streamlit as st
import datetime
import json
import requests
import gspread
import re
import PyPDF2
import os
import pandas as pd
from fpdf import FPDF 
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta

# --- 🔐 CONFIGURAÇÕES VIA SECRETS ---
MINHA_CHAVE = st.secrets["MINHA_CHAVE"]
ID_AGENDA = st.secrets["ID_AGENDA"]
SENHA_ADMIN = "adm123" 

st.set_page_config(page_title="Estúdio de Pilates - Coluna sem Dor", page_icon="🧘‍♀️", layout="wide")

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/calendar']
NOME_PLANILHA_GOOGLE = 'Leads_Pilates'

# --- 🆕 FUNÇÕES DE BANCO DE DATOS (ALUNOS FIXOS) ---
def buscar_aluno_por_cpf(client_sheets, cpf):
    try:
        sh = client_sheets.open(NOME_PLANILHA_GOOGLE)
        try:
            sheet_alunos = sh.worksheet("Alunos")
        except:
            sheet_alunos = sh.add_worksheet(title="Alunos", rows="1000", cols="10")
            sheet_alunos.append_row(["CPF", "Nome", "WhatsApp", "Objetivo", "Restricoes"])
            return None
        
        cell = sheet_alunos.find(cpf)
        if cell:
            dados = sheet_alunos.row_values(cell.row)
            return {"cpf": dados[0], "nome": dados[1], "tel": dados[2], "objetivo": dados[3], "restricoes": dados[4]}
        return None
    except:
        return None

def salvar_ou_atualizar_aluno(client_sheets, dados):
    try:
        sh = client_sheets.open(NOME_PLANILHA_GOOGLE)
        try:
            sheet_alunos = sh.worksheet("Alunos")
        except:
            sheet_alunos = sh.add_worksheet(title="Alunos", rows="1000", cols="10")
            sheet_alunos.append_row(["CPF", "Nome", "WhatsApp", "Objetivo", "Restricoes"])
        
        cell = sheet_alunos.find(dados['cpf'])
        nova_linha = [dados['cpf'], dados['nome'], dados['tel'], dados['objetivo'], dados.get('restricoes', 'N/A')]
        
        if cell:
            sheet_alunos.update(f"A{cell.row}:E{cell.row}", [nova_linha])
        else:
            sheet_alunos.append_row(nova_linha)
    except:
        pass

# --- FUNÇÃO PARA ATUALIZAR STATUS (RESPOSTA DO ALUNO) ---
def atualizar_status_aluno(client_sheets, nome_aluno, novo_status, motivo=""):
    try:
        sh = client_sheets.open(NOME_PLANILHA_GOOGLE); sheet = sh.sheet1
        cell = sheet.find(nome_aluno)
        if cell:
            sheet.update_cell(cell.row, 11, novo_status)
            if motivo:
                sheet.update_cell(cell.row, 12, motivo)
            return True
        return False
    except:
        return False

# --- FUNÇÃO PARA GERAR O PDF ---
def gerar_pdf_paciente(nome, objetivo, horario, analise_ia, tipo_atendimento):
    pdf = FPDF()
    pdf.add_page()
    if os.path.exists("logo.png"):
        pdf.image("logo.png", x=10, y=8, w=33)
        pdf.ln(20)
    pdf.set_font("Arial", "B", 16)
    titulo = "Comprovante de Agendamento"
    pdf.cell(0, 10, titulo.encode('latin-1', 'replace').decode('latin-1'), ln=True, align='C')
    pdf.ln(10)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, f"Paciente: {nome}".encode('latin-1', 'replace').decode('latin-1'), ln=True)
    pdf.cell(0, 10, f"Servico: {tipo_atendimento}".encode('latin-1', 'replace').decode('latin-1'), ln=True)
    pdf.cell(0, 10, f"Objetivo: {objetivo}".encode('latin-1', 'replace').decode('latin-1'), ln=True)
    pdf.set_text_color(0, 102, 204)
    pdf.cell(0, 10, f"Horario: {horario}".encode('latin-1', 'replace').decode('latin-1'), ln=True)
    pdf.set_text_color(0, 0, 0)
    if analise_ia:
        pdf.ln(5)
        pdf.multi_cell(0, 7, f"Analise: {analise_ia}".encode('latin-1', 'replace').decode('latin-1'))
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
    except: return ""

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
        primeira_celula = sheet.acell('A1').value
        if not primeira_celula or primeira_celula == "":
            cabecalho = ["Data Cadastro", "Nome", "WhatsApp", "Objetivo", "Dores/Relato", "Horário Agendado", "Análise IA", "Arquivo PDF", "Status Agenda", "Tipo Atendimento", "Confirmação (Sim/Não)", "Motivo Cancelamento"]
            sheet.insert_row(cabecalho, 1)
        nova_linha = [dados['data_hora'], dados['nome'], dados['tel'], dados['objetivo'], dados.get('restricoes', 'N/A'), dados['melhor_horario'], dados.get('ia_resposta_paciente', 'N/A'), dados.get('nome_arquivo', 'Nenhum'), dados['status_agenda'], dados['tipo'], "Pendente", ""]
        sheet.append_row(nova_linha)
        return True
    except: return False

# --- FLUXO PRINCIPAL ---
def main():
    client_sheets, service_calendar = conectar_google()
    
    # --- LÓGICA DE CAPTURA DE RESPOSTA DO ALUNO ---
    params = st.query_params
    if "confirma" in params and "aluno" in params:
        nome_aluno = params["aluno"]
        acao = params["confirma"]
        col_logo, _ = st.columns([1, 4])
        with col_logo:
            if os.path.exists("logo.png"): st.image("logo.png", width=120)
        st.title(f"Olá, {nome_aluno}! 🧘‍♀️")
        if acao == "sim":
            if atualizar_status_aluno(client_sheets, nome_aluno, "Confirmado"):
                st.success("✨ **Sua presença foi confirmada com sucesso!** Até logo!")
            else: st.error("Registro não encontrado.")
        elif acao == "nao":
            motivo = st.radio("Motivo do cancelamento:", ["Saúde", "Trabalho", "Transporte", "Compromisso", "Outros"])
            if st.button("Confirmar Cancelamento"):
                atualizar_status_aluno(client_sheets, nome_aluno, "Cancelado", motivo)
                st.info("Horário liberado.")
        st.stop()

    if 'show_admin' not in st.session_state: st.session_state.show_admin = False

    # --- TELA DE ADMINISTRADOR ---
    if st.session_state.show_admin:
        st.title("🔐 Área Administrativa")
        senha = st.text_input("Senha de acesso:", type="password")
        if senha == SENHA_ADMIN:
            st.success("Acesso autorizado!")
            sh = client_sheets.open(NOME_PLANILHA_GOOGLE); sheet = sh.sheet1
            dados_planilha = sheet.get_all_records()
            df = pd.DataFrame(dados_planilha)

            # --- 🆕 DASHBOARD DE ANÁLISE ---
            st.divider()
            st.subheader("📊 Dashboard de Performance")
            
            if not df.empty:
                col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                col_m1.metric("Total Agendamentos", len(df))
                col_m2.metric("Confirmados", len(df[df['Confirmação (Sim/Não)'] == 'Confirmado']))
                col_m3.metric("Cancelados", len(df[df['Confirmação (Sim/Não)'] == 'Cancelado']))
                col_m4.metric("Pendentes", len(df[df['Confirmação (Sim/Não)'] == 'Pendente']))

                st.write("#### Distribuição por Tipo de Atendimento")
                # Prepara dados para o gráfico de pizza
                tipo_counts = df['Tipo Atendimento'].value_counts().reset_index()
                tipo_counts.columns = ['Tipo', 'Quantidade']
                
                c1, c2 = st.columns([1, 1])
                with c1:
                    # Gráfico de Pizza Nativo do Streamlit
                    st.write("Proporção de Alunos/Pacientes")
                    st.vega_lite_chart(tipo_counts, {
                        'mark': {'type': 'arc', 'innerRadius': 50, 'tooltip': True},
                        'encoding': {
                            'theta': {'field': 'Quantidade', 'type': 'quantitative'},
                            'color': {'field': 'Tipo', 'type': 'nominal', 'legend': {"orient": "bottom"}}
                        }
                    }, use_container_width=True)
                with c2:
                    st.write("Filtro por Status de Presença")
                    status_counts = df['Confirmação (Sim/Não)'].value_counts().reset_index()
                    st.bar_chart(status_counts.set_index('Confirmação (Sim/Não)'))
            
            st.divider()
            st.subheader("🚀 Lembretes de Amanhã")
            amanha = (datetime.now() + timedelta(days=1)).strftime('%d/%m')
            alunos_amanha = [r for r in dados_planilha if str(r.get('Horário Agendado', '')).startswith(amanha)]
            if alunos_amanha:
                url_app = "https://physiongymatendente.streamlit.app" 
                for aluno in alunos_amanha:
                    col_n, col_b = st.columns([3, 1])
                    nome_url = requests.utils.quote(str(aluno['Nome']))
                    msg = f"Olá {aluno['Nome']}, confirma sua aula amanhã ({aluno['Horário Agendado']})?\n\n👍 SIM: {url_app}?confirma=sim&aluno={nome_url}\n\n❌ NÃO: {url_app}?confirma=nao&aluno={nome_url}"
                    link_wpp = f"https://wa.me/55{re.sub(r'\D', '', str(aluno['WhatsApp']))}?text={requests.utils.quote(msg)}"
                    col_n.write(f"👤 **{aluno['Nome']}** - {aluno['Horário Agendado']} (`{aluno.get('Confirmação (Sim/Não)', 'Pendente')}`)")
                    col_b.markdown(f'''<a href="{link_wpp}" target="_blank"><button style="background-color:#25D366; color:white; border:none; padding:5px 10px; border-radius:5px; cursor:pointer;">Mandar WhatsApp</button></a>''', unsafe_allow_html=True)
            else: st.info("Nenhum agendamento para amanhã.")

            st.divider()
            st.subheader("📋 Lista Geral")
            st.dataframe(df)
            if st.button("⬅️ Sair"): st.session_state.show_admin = False; st.rerun()
        return

    # --- FLUXO DO CLIENTE ---
    if 'fase' not in st.session_state: st.session_state.fase = 0 
    if 'dados_form' not in st.session_state: st.session_state.dados_form = {}

    col1, col2 = st.columns([1, 3])
    with col1:
        if os.path.exists("logo.png"): st.image("logo.png", width=120)
        else: st.markdown("# 🧘‍♀️")
    with col2:
        st.markdown("## Estúdio de pilates")
        st.markdown("#### Coluna sem dor e mais qualidade de vida 🌟")
    st.divider()

    if st.session_state.fase == 0:
        st.subheader("Como podemos ajudar você hoje?")
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("🧘 Já sou Aluno(a)"):
                st.session_state.tipo_atendimento = "Aluno da Casa"; st.session_state.fase = 0.1; st.rerun()
        with c2:
            if st.button("✨ Quero ser Aluno(a)"):
                st.session_state.fase = 0.5; st.rerun()
        with c3:
            if st.button("🏥 Fisioterapia"):
                st.session_state.tipo_atendimento = "Consulta Fisioterapia"; st.session_state.fase = 1; st.rerun()

    if st.session_state.fase == 0.1:
        st.subheader("Identificação")
        cpf_digitado = st.text_input("Digite seu CPF (apenas números):")
        if st.button("Continuar"):
            aluno = buscar_aluno_por_cpf(client_sheets, cpf_digitado)
            if aluno:
                st.session_state.dados_form = aluno
                st.success(f"Bem-vindo de volta, {aluno['nome']}!")
                st.session_state.fase = 4; st.rerun()
            else:
                st.warning("CPF não encontrado. Vamos preencher seu cadastro.")
                st.session_state.dados_form['cpf'] = cpf_digitado
                st.session_state.fase = 1; st.rerun()

    if st.session_state.fase == 1:
        st.subheader(f"Agendamento: {st.session_state.tipo_atendimento}")
        d_pref = st.session_state.dados_form
        nome = st.text_input("Nome Completo", value=d_pref.get('nome', ''))
        tel = st.text_input("WhatsApp", value=d_pref.get('tel', ''))
        cpf = st.text_input("CPF", value=d_pref.get('cpf', ''))
        objetivo = "Manutenção"
        restricoes = "N/A"
        if "Novo" in st.session_state.tipo_atendimento or "Fisioterapia" in st.session_state.tipo_atendimento:
            objetivo = st.selectbox("Objetivo:", ["Dores", "Postura", "Lesão", "Outro"])
            restricoes = st.text_area("Descreva brevemente o que sente:", value=d_pref.get('restricoes', ''))
        if st.button("Próximo"):
            if nome and tel and cpf:
                st.session_state.dados_form = {"nome": nome, "tel": tel, "cpf": cpf, "objetivo": objetivo, "restricoes": restricoes}
                salvar_ou_atualizar_aluno(client_sheets, st.session_state.dados_form)
                st.session_state.fase = 4; st.rerun()
            else: st.warning("Preencha Nome, WhatsApp e CPF.")

    if st.session_state.fase == 4:
        st.subheader("Escolha seu Horário")
        horarios = buscar_horarios_livres(service_calendar)
        horario = st.selectbox("Disponíveis:", horarios)
        if st.button("Confirmar Agendamento"):
            with st.spinner("Reservando..."):
                st.session_state.horario_escolhido = horario
                d = st.session_state.dados_form
                status = criar_evento_agenda(service_calendar, horario, d['nome'], d['tel'], d['objetivo'])
                salvar_na_planilha(client_sheets, {**d, "data_hora": datetime.now().strftime("%d/%m %H:%M"), "melhor_horario": horario, "status_agenda": status, "tipo": st.session_state.tipo_atendimento})
                st.session_state.fase = 5; st.rerun()

    if st.session_state.fase == 5:
        st.balloons()
        st.success(f"✅ Agendamento Realizado!")
        pdf_bytes = gerar_pdf_paciente(st.session_state.dados_form['nome'], st.session_state.dados_form['objetivo'], st.session_state.horario_escolhido, "", st.session_state.tipo_atendimento)
        st.download_button(label="📥 Baixar Comprovante", data=pdf_bytes, file_name=f"Agendamento.pdf", mime="application/pdf")
        st.button("🔄 Novo Atendimento", on_click=lambda: st.session_state.clear())

    st.markdown("<br><br><hr>", unsafe_allow_html=True)
    if st.button("⚙️ Administração"):
        st.session_state.show_admin = True; st.rerun()

if __name__ == "__main__":
    main()
