import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import easyocr
import numpy as np
from PIL import Image
import re
from fpdf import FPDF
import base64
import hashlib
import io
import os
import requests

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Ressalva Digital - FUNAP/GDF", layout="wide", page_icon="🔐")

# --- DEFINIÇÃO DE DIRETÓRIOS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(BASE_DIR, 'logo_funap.png')
DB_PATH = os.path.join(BASE_DIR, 'ressalva_funap.db')

# --- SEGURANÇA ---
def gerar_hash(texto):
    return hashlib.sha256(texto.encode()).hexdigest()

# --- BANCO DE DADOS ---
def criar_conexao():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS atendimentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, nome_reeducando TEXT, cpf TEXT, rg TEXT, filiacao TEXT,
        data_presenca TEXT, horario_entrada TEXT, horario_saida TEXT, finalidade TEXT, 
        vigilante_ent TEXT, servidor_sai TEXT, mat_servidor TEXT, status TEXT DEFAULT 'Presente')''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT, login TEXT UNIQUE, senha TEXT, nome TEXT, perfil TEXT, matricula TEXT)''')
    
    # Senha padrão: admin123 (Hash seguro)
    senha_adm = gerar_hash("admin123")
    cursor.execute("INSERT OR IGNORE INTO usuarios (login, senha, nome, perfil, matricula) VALUES (?,?,?,?,?)",
                   ('admin', senha_adm, 'ADMINISTRADOR NTI', 'ADM', '000000'))
    conn.commit()
    return conn

# --- FUNÇÃO DO PDF ---
def gerar_pdf_ressalva(nome, cpf, filiacao, data, entrada, saida, finalidade, servidor, matricula, vigilante):
    pdf = FPDF()
    pdf.add_page()
    if os.path.exists(LOGO_PATH):
        try: pdf.image(LOGO_PATH, 10, 8, 35)
        except: pass 
    pdf.set_font("Helvetica", "B", 14); pdf.cell(0, 10, "GOVERNO DO DISTRITO FEDERAL", ln=True, align='C')
    pdf.set_font("Helvetica", "", 10); pdf.cell(0, 7, "FUNDAÇÃO DE AMPARO AO TRABALHADOR PRESO - FUNAP", ln=True, align='C')
    pdf.ln(20); pdf.set_font("Helvetica", "B", 16); pdf.cell(0, 10, "RESSALVA DE COMPARECIMENTO DIGITAL", ln=True, align='C')
    pdf.ln(10); pdf.set_font("Helvetica", "", 12)
    dt_br = datetime.strptime(data, '%Y-%m-%d').strftime('%d/%m/%Y')
    texto = (f"Certificamos que {nome.upper()}, inscrito no CPF sob o nº {cpf}, filho(a) de {filiacao.upper()}, "
             f"compareceu a esta Instituição em {dt_br}. Entrada: {entrada} | Saída: {saida}. Finalidade: {finalidade.upper()}.")
    pdf.multi_cell(0, 10, texto, align='J')
    pdf.ln(20); pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, f"REGISTRO DE ENTRADA (Vigilância): {vigilante}", ln=True)
    pdf.cell(0, 6, f"HOMOLOGAÇÃO DE SAÍDA (Servidor): {servidor} (Mat: {matricula})", ln=True)
    pdf.ln(15); pdf.set_font("Helvetica", "I", 8)
    hash_doc = hashlib.md5(f"{nome}{saida}".encode()).hexdigest().upper()[:12]
    pdf.cell(0, 10, f"Autenticidade: {hash_doc} | Emitido em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", border=1, align='C')
    return bytes(pdf.output())

def exibir_pdf_tela(pdf_bytes):
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    st.markdown(f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600" type="application/pdf"></iframe>', unsafe_allow_html=True)

@st.cache_resource
def iniciar_leitor(): return easyocr.Reader(['pt'])

# --- INICIALIZAÇÃO ---
conn = criar_conexao()
if 'logado' not in st.session_state: st.session_state.logado = False

# --- LOGIN ---
if not st.session_state.logado:
    c1, col_login, c3 = st.columns([1, 2, 1])
    with col_login:
        if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, width=250)
        st.title("🔐 Acesso - FUNAP")
        user = st.text_input("Login")
        pw = st.text_input("Senha", type="password")
        if st.button("Acessar", use_container_width=True):
            pw_h = gerar_hash(pw)
            res = conn.execute("SELECT * FROM usuarios WHERE login=? AND senha=?", (user, pw_h)).fetchone()
            if res:
                st.session_state.logado, st.session_state.nome, st.session_state.perfil, st.session_state.mat = True, res['nome'], res['perfil'], res['matricula']
                st.rerun()
            else: st.error("Acesso Negado!")
    st.stop()

# --- SIDEBAR ---
with st.sidebar:
    if os.path.exists(LOGO_PATH): st.image(LOGO_PATH, use_container_width=True)
    st.write(f"👤 **{st.session_state.nome}**")
    if st.button("Sair"): st.session_state.logado = False; st.rerun()
    st.divider()
    menu = ["📥 Registrar Entrada", "📋 Painel/Ata do Dia", "🏁 Finalizar Saída"]
    escolha = st.selectbox("Menu Principal", menu)

# --- LÓGICA DE REGISTRO ---
if escolha == "📥 Registrar Entrada":
    st.subheader("📥 Novo Registro")
    with st.form("f_ent"):
        nome = st.text_input("Nome Completo")
        cpf = st.text_input("CPF")
        filiacao = st.text_input("Filiação")
        motivo = st.selectbox("Finalidade", ["Biometria", "Financeiro", "Administrativo"])
        if st.form_submit_button("Salvar"):
            conn.execute("INSERT INTO atendimentos (nome_reeducando, cpf, filiacao, data_presenca, horario_entrada, finalidade, vigilante_ent) VALUES (?,?,?,?,?,?,?)",
                         (nome.upper(), cpf, filiacao.upper(), datetime.now().strftime('%Y-%m-%d'), datetime.now().strftime('%H:%M'), motivo, st.session_state.nome))
            conn.commit(); st.success("Registrado!")

elif escolha == "📋 Painel/Ata do Dia":
    st.subheader("📋 Atendimentos de Hoje")
    data_hoje = datetime.now().strftime('%Y-%m-%d')
    df = pd.read_sql("SELECT * FROM atendimentos WHERE data_presenca = ?", conn, params=(data_hoje,))
    st.dataframe(df, use_container_width=True)

elif escolha == "🏁 Finalizar Saída":
    st.subheader("🏁 Homologar Saída")
    pendentes = conn.execute("SELECT id, nome_reeducando FROM atendimentos WHERE status='Presente'").fetchall()
    if pendentes:
        p_dict = {f"{p['nome_reeducando']} (ID: {p['id']})": p['id'] for p in pendentes}
        selecionado = st.selectbox("Selecione o Reeducando", list(p_dict.keys()))
        if st.button("Registrar Saída"):
            id_sel = p_dict[selecionado]
            conn.execute("UPDATE atendimentos SET horario_saida=?, status='Concluído', servidor_sai=?, mat_servidor=? WHERE id=?",
                         (datetime.now().strftime('%H:%M'), st.session_state.nome, st.session_state.mat, id_sel))
            conn.commit(); st.success("Saída registrada com sucesso!")
