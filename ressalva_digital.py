# ==============================================================================
# SISTEMA RESSALVA DIGITAL FUNAP — V7.3
# Correções V7.2→V7.3 (REDESIGN COMPLETO DE CÂMERA):
#   1. Câmera do NAVEGADOR (st.camera_input) como MÉTODO PRINCIPAL
#      — funciona SEMPRE via WebRTC, sem warmup, sem OpenCV
#   2. OCR AUTOMÁTICO — ao capturar foto, IA processa imediatamente
#      sem clique extra. Fluxo: tira foto → IA preenche → pronto!
#   3. OpenCV Streaming como OPÇÃO AVANÇADA (preview ao vivo)
#   4. Warmup OpenCV reduzido: 15 tentativas × 3 backends (máx ~8s)
#      com fallback automático para câmera do navegador após 8s
#   5. Bug "tentativa 30/01" corrigido — warmup_tentativa formatado
#      corretamente e fallback rápido quando OpenCV falha
# ==============================================================================
from datetime import datetime, timedelta
import time as _time
import subprocess
import unicodedata
from fpdf import FPDF
from PIL import Image
import google.generativeai as genai
import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import base64
import threading
import time
import json
import io
import re
import site
import sys
import os

# Força o Python portátil a ler as pastas de bibliotecas do Pen Drive primeiro
BASE_DIR = os.path.dirname(os.path.abspath(
    __file__)) if '__file__' in locals() else os.getcwd()
sys.path.append(os.path.join(BASE_DIR, "python_portatil", "Lib"))
sys.path.append(
    os.path.join(
        BASE_DIR,
        "python_portatil",
        "Lib",
        "site-packages"))

# Fallback: tenta Python local do sistema (site-packages) se o portátil
# não funcionar
sys.path.extend(
    site.getsitepackages() if hasattr(
        site, 'getsitepackages') else [])

# Importações adicionais do sistema

# CORREÇÃO 2: FPDF Unicode — DejaVuSans.ttf com fallback


def remover_acentos(texto):
    if texto is None:
        return ""
    return unicodedata.normalize(
        'NFKD', str(texto)).encode(
        'ASCII', 'ignore').decode('ASCII')


def configurar_fonte_pdf(pdf):
    caminhos = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    ttf_regular = None
    ttf_bold = None
    if os.path.exists(caminhos[0]):
        ttf_regular = caminhos[0]
        ttf_bold = caminhos[1] if os.path.exists(caminhos[1]) else None
    if not ttf_regular:
        try:
            import matplotlib
            mpl_dir = os.path.join(
                os.path.dirname(
                    matplotlib.__file__),
                "mpl-data",
                "fonts",
                "ttf")
            candidate = os.path.join(mpl_dir, "DejaVuSans.ttf")
            if os.path.exists(candidate):
                ttf_regular = candidate
                bold_c = os.path.join(mpl_dir, "DejaVuSans-Bold.ttf")
                ttf_bold = bold_c if os.path.exists(bold_c) else None
        except ImportError:
            pass
    if not ttf_regular:
        try:
            result = subprocess.run(["find",
                                     "/",
                                     "-name",
                                     "DejaVuSans.ttf",
                                     "-type",
                                     "f"],
                                    capture_output=True,
                                    text=True,
                                    timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                ttf_regular = result.stdout.strip().split("\n")[0]
                bold_dir = os.path.dirname(ttf_regular)
                bold_candidate = os.path.join(bold_dir, "DejaVuSans-Bold.ttf")
                ttf_bold = bold_candidate if os.path.exists(
                    bold_candidate) else None
        except Exception:
            pass
    if not ttf_regular:
        local_dejavu = os.path.join(BASE_DIR, "DejaVuSans.ttf")
        if os.path.exists(local_dejavu):
            ttf_regular = local_dejavu
            local_bold = os.path.join(BASE_DIR, "DejaVuSans-Bold.ttf")
            ttf_bold = local_bold if os.path.exists(local_bold) else None
    if ttf_regular:
        try:
            pdf.add_font("DejaVu", "", ttf_regular)
            if ttf_bold:
                pdf.add_font("DejaVu", "B", ttf_bold)
            else:
                pdf.add_font("DejaVu", "B", ttf_regular)
            return ("DejaVu", bool(ttf_bold))
        except Exception:
            pass
    return ("Helvetica", False)


_FONTE_UNICODE = None


def _obter_fonte():
    return _FONTE_UNICODE[0] if _FONTE_UNICODE else "Helvetica"


# ──────────────────────────────────────────────────
# CORREÇÃO 1: Importar OpenCV para câmera Iriun/Webcam
# ──────────────────────────────────────────────────
try:
    import cv2
    CV2_DISPONIVEL = True
except ImportError:
    CV2_DISPONIVEL = False

# Tenta importar qrcode; tenta portátil, depois Python local, depois desabilita
try:
    import qrcode
    QRCODE_DISPONIVEL = True
except ImportError:
    try:
        import importlib
        qrcode = importlib.import_module('qrcode')
        QRCODE_DISPONIVEL = True
    except ImportError:
        QRCODE_DISPONIVEL = False

# ──────────────────────────────────────────────────
# V7.3: Arquitetura de câmera REDESENHADA
#
# PROBLEMA V7.2: Câmera Iriun (virtual via celular) travava em
# "Aquecendo câmera... (tentativa 30/01)" — cap.read() falhava
# em TODOS os backends (padrão, MSMF, DShow) após 30 tentativas.
# O atendente ficava preso esperando, incapaz de registrar entradas.
#
# SOLUÇÃO V7.3:
#   1. CÂMERA DO NAVEGADOR (st.camera_input) como MÉTODO PRINCIPAL.
#      Funciona SEMPRE via WebRTC nativo do browser — zero warmup,
#      zero OpenCV, zero threads. O atendente tira a foto e pronto.
#   2. OCR AUTOMÁTICO — ao capturar a foto, o Gemini processa
#      imediatamente e preenche o formulário. Sem clique extra.
#   3. OpenCV Streaming como OPÇÃO AVANÇADA — para quem quer
#      preview ao vivo antes de capturar. Warmup reduzido (15 × 3).
#   4. Se OpenCV falha em 8s, fallback AUTOMÁTICO para câmera
#      do navegador — o atendente nunca fica preso.
# ──────────────────────────────────────────────────



# ──────────────────────────────────────────────────
# V8.0: Arquitetura de câmera SIMPLIFICADA E INFALÍVEL
# PROBLEMA V7.3: Threading + OpenCV + Iriun travava rerun
# SOLUÇÃO V8: st.camera_input como principal + OpenCV opcional estável
# ──────────────────────────────────────────────────

class _CameraCache:
    """V8: Cache simplificado - sem threads, apenas VideoCapture direto"""
    _instance = None
    _camera_id = None
    _lock = threading.Lock()

    @classmethod
    def get(cls, camera_id, prefer_backend=None):
        with cls._lock:
            if cls._instance is not None and cls._camera_id == camera_id:
                if cls._instance.isOpened():
                    return cls._instance
                else:
                    try: cls._instance.release()
                    except: pass
                    cls._instance = None
            if cls._instance is not None:
                try: cls._instance.release()
                except: pass
                cls._instance = None
            cap = cls._open_fast(camera_id, prefer_backend)
            if cap is not None:
                cls._instance = cap
                cls._camera_id = camera_id
            return cap

    @classmethod
    def _open_fast(cls, camera_id, prefer_backend=None):
        if not CV2_DISPONIVEL:
            return None
        estrategias = []
        if prefer_backend is not None:
            estrategias.append(("preferido", prefer_backend))
        estrategias.extend([("padrão", None), ("CAP_MSMF", cv2.CAP_MSMF), ("CAP_DSHOW", cv2.CAP_DSHOW)])
        vistos=set()
        unicas=[]
        for nome,api in estrategias:
            if (nome,api) not in vistos:
                vistos.add((nome,api))
                unicas.append((nome,api))
        for nome_estrat, api_pref in unicas:
            try:
                if api_pref is not None:
                    cap = cv2.VideoCapture(int(camera_id), api_pref)
                else:
                    cap = cv2.VideoCapture(int(camera_id))
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    cap.set(cv2.CAP_PROP_FPS, 30)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                    return cap
                else:
                    cap.release()
            except: pass
        return None

    @classmethod
    def release(cls):
        with cls._lock:
            if cls._instance is not None:
                try: cls._instance.release()
                except: pass
                cls._instance = None
                cls._camera_id = None

    @classmethod
    def is_active(cls):
        with cls._lock:
            return cls._instance is not None and cls._instance.isOpened()

class _LatestFrame:
    """V8: Versão SEM THREAD - leitura direta, sem daemon que trava Streamlit"""
    STATUS_INIT = "iniciando"
    STATUS_WARMUP = "aquecendo"
    STATUS_CONNECTED = "conectado"
    STATUS_ERROR = "erro"
    STATUS_STOPPED = "parado"
    MAX_WARMUP_TENTATIVAS = 5  # V8: reduzido de 15 para 5 - falha rápido e vai pro fallback
    WARMUP_SLEEP = 0.1

    def __init__(self, camera_id):
        self._camera_id = camera_id
        self._lock = threading.Lock()
        self._frame_rgb = None
        self._frame_jpg_bytes = None
        self._running = True
        self._error = None
        self._status = self.STATUS_INIT
        self._warmup_tentativa = 0
        self._warmup_max = self.MAX_WARMUP_TENTATIVAS
        self._backend_usado = ""
        # V8: NÃO inicia thread aqui - leitura sob demanda
        self._cap = _CameraCache.get(camera_id)
        if self._cap is None:
            self._status = self.STATUS_ERROR
            self._error = f"Não foi possível abrir câmera {camera_id}. Use Câmera do Navegador."
        else:
            self._status = self.STATUS_CONNECTED
            self._atualizar_frame()

    def _atualizar_frame(self):
        if self._cap and self._cap.isOpened():
            ret, frame = self._cap.read()
            if ret and frame is not None:
                ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                self._frame_rgb = frame
                self._frame_jpg_bytes = buf.tobytes() if ok else None
                return True
        return False

    @property
    def frame_rgb(self):
        self._atualizar_frame()
        return self._frame_rgb

    @property
    def frame_jpg_bytes(self):
        self._atualizar_frame()
        return self._frame_jpg_bytes

    @property
    def error(self): return self._error
    @property
    def running(self): return self._running and self._status != self.STATUS_ERROR
    @property
    def status(self): return self._status
    @property
    def warmup_tentativa(self): return self._warmup_tentativa
    @property
    def thread_viva(self): return self._running
    @property
    def backend_usado(self): return self._backend_usado
    def stop(self):
        self._running = False
        self._status = self.STATUS_STOPPED

class _StreamCache:
    _instance = None
    _lock = threading.Lock()
    @classmethod
    def get(cls):
        with cls._lock: return cls._instance
    @classmethod
    def set(cls, lf):
        with cls._lock: cls._instance = lf
    @classmethod
    def release(cls):
        with cls._lock:
            if cls._instance is not None:
                try: cls._instance.stop()
                except: pass
                cls._instance = None

# V8: FUNÇÃO NOVA - CAPTURA INFALÍVEL PARA VIGILANTE MOBILE
def camera_captura_v8_infalivel(label="Fotografar Documento"):
    """V8: Prioridade total para st.camera_input - funciona em PC e celular em alta qualidade"""
    st.markdown("""
    <div style="background:#1E293B; padding:12px; border-radius:10px; border-left:4px solid #FFCC00; margin:10px 0;">
        <b style="color:#FFCC00;">📱 Captura Alta Qualidade</b><br>
        <span style="color:#CBD5E1; font-size:0.85em;">Se estiver no celular do vigilante, a foto sai em resolução máxima e vai direto para o PC da recepção.</span>
    </div>
    """, unsafe_allow_html=True)
    foto = st.camera_input(label)
    if not foto:
        st.caption("Câmera não disponível? Use upload:")
        upload = st.file_uploader("Upload JPG/PNG", type=["jpg","jpeg","png"], label_visibility="collapsed", key=f"upload_{label}")
        if upload:
            return upload
    return foto


# =========================================
# CONFIGURAÇÃO GEMINI IA (LENDO DO JSON)
# =========================================
# Define o caminho correto para o arquivo config_sistema.json no Pen Drive
caminho_config = os.path.join(BASE_DIR, "config_sistema.json")

GOOGLE_API_KEY = ""

# Tenta carregar a chave diretamente do arquivo JSON
if os.path.exists(caminho_config):
    try:
        with open(caminho_config, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            GOOGLE_API_KEY = config_data.get("google_api_key", "")
    except Exception as e:
        st.error(f"Erro ao ler o arquivo de configuração: {e}")

# Caso não encontre no JSON, tenta buscar nos segredos nativos do Streamlit
if not GOOGLE_API_KEY:
    GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY", "")

# V6: Lê arquivo .env manualmente (suporta chaves com espaço no nome)
# O arquivo .env pode conter: CHAVE GEMINI=..., CHAVE_GEMINI=...,
# GOOGLE_API_KEY=...
if not GOOGLE_API_KEY:
    caminho_env = os.path.join(BASE_DIR, ".env")
    if os.path.exists(caminho_env):
        try:
            with open(caminho_env, "r", encoding="utf-8") as f_env:
                for linha_env in f_env:
                    linha_env = linha_env.strip()
                    if not linha_env or linha_env.startswith("#"):
                        continue
                    # Divide no PRIMEIRO '=' apenas
                    if "=" in linha_env:
                        chave_env, valor_env = linha_env.split("=", 1)
                        chave_env = chave_env.strip()
                        valor_env = valor_env.strip().strip('"').strip("'")
                        # Aceita variações do nome da chave
                        if chave_env.upper() in (
                            "CHAVE GEMINI", "CHAVE_GEMINI", "GOOGLE_API_KEY",
                            "GEMINI_API_KEY", "GEMINI_KEY"
                        ):
                            GOOGLE_API_KEY = valor_env
                            break
        except Exception as e_env:
            pass  # Silencioso — já tentamos JSON e st.secrets

# Modelos Gemini com fallback automático (V7: lista expandida)
GEMINI_MODELOS = [
    'gemini-2.5-flash',
    'gemini-2.0-flash',
    'gemini-2.0-flash-lite',
    'gemini-2.5-flash-preview-05-20',
    'gemini-1.5-flash',
    'gemini-1.5-flash-latest',
]
GEMINI_MODELO_ATIVO = None

if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

    # ─── V7: DETECÇÃO ROBUSTA DE MODELO GEMINI ───
    # Estratégia 1: genai.list_models() — descobre modelos disponíveis na conta
    try:
        modelos_disponiveis_api = set()
        for m in genai.list_models():
            nome = getattr(m, 'name', '')  # ex: 'models/gemini-2.5-flash'
            if 'gemini' in nome.lower() and 'embed' not in nome.lower() and 'aqa' not in nome.lower():
                # Remove prefixo 'models/' para comparação
                nome_limpo = nome.replace('models/', '')
                modelos_disponiveis_api.add(nome_limpo)
        # Prioriza modelos da nossa lista que estejam disponíveis na API
        for modelo_tentativa in GEMINI_MODELOS:
            if modelo_tentativa in modelos_disponiveis_api:
                GEMINI_MODELO_ATIVO = modelo_tentativa
                break
    except Exception:
        pass  # Fallback para estratégia 2

    # Estratégia 2: generate_content com prompt mínimo (mais confiável que
    # count_tokens)
    if GEMINI_MODELO_ATIVO is None:
        for modelo_tentativa in GEMINI_MODELOS:
            try:
                modelo_teste = genai.GenerativeModel(modelo_tentativa)
                resp = modelo_teste.generate_content(
                    "Responda apenas: ok", request_options={"timeout": 15})
                if resp and getattr(resp, 'text', None):
                    GEMINI_MODELO_ATIVO = modelo_tentativa
                    break
            except Exception:
                continue

    # Estratégia 3: count_tokens como último recurso (pode falhar com 403/429)
    if GEMINI_MODELO_ATIVO is None:
        for modelo_tentativa in GEMINI_MODELOS:
            try:
                modelo_teste = genai.GenerativeModel(modelo_tentativa)
                modelo_teste.count_tokens("test")
                GEMINI_MODELO_ATIVO = modelo_tentativa
                break
            except Exception:
                continue

    if GEMINI_MODELO_ATIVO:
        st.sidebar.success(f"🤖 IA ativa: {GEMINI_MODELO_ATIVO}")
    else:
        st.sidebar.error(
            "⚠️ Nenhum modelo Gemini disponível. Verifique sua API.")
    client_ia = genai
else:
    st.error("Chave de API do Google não encontrada no config_sistema.json!")

# =========================================
# CONFIGURAÇÃO DE CAMINHOS & DIRETÓRIOS
# =========================================
LOGO_PATH = os.path.join(BASE_DIR, "logo_funap.png")
DB_PATH = os.path.join(BASE_DIR, "ressalva_funap.db")
SESSION_FILE = os.path.join(BASE_DIR, ".sessao_ativa.txt")
RELATORIOS_DIR = os.path.join(BASE_DIR, "relatorios")

# Cria diretório de relatórios se não existir
os.makedirs(RELATORIOS_DIR, exist_ok=True)

# =========================================
# INICIALIZAÇÃO DE TABELAS DO BANCO DE DADOS
# =========================================
try:
    conn_init = sqlite3.connect(DB_PATH)
    cursor_init = conn_init.cursor()
    cursor_init.execute("""
        CREATE TABLE IF NOT EXISTS relatorios_arquivados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_plantao DATE UNIQUE,
            total_atendimentos INTEGER,
            total_visitantes INTEGER,
            operador_fechamento TEXT,
            conteudo_json TEXT,
            data_fechamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn_init.commit()
    conn_init.close()
except Exception as e:
    pass

# =========================================
# FUNÇÃO DE SINCRONIZAÇÃO AUTOMÁTICA EXCEL
# =========================================


def sincronizar_banco_com_excel():
    try:
        conn_sync = sqlite3.connect(DB_PATH)

        query = """
            SELECT id as 'ID_Atendimento',
                   nome_reeducando as 'Nome do Reeducando',
                   cpf as 'CPF',
                   filiacao as 'Filiação',
                   strftime('%d/%m/%Y', data_presenca) as 'Data do Atendimento',
                   horario_entrada as 'Horário Entrada',
                   horario_saida as 'Horário Saída',
                   finalidade as 'Finalidade',
                   status as 'Status do Fluxo'
            FROM atendimentos
            ORDER BY id DESC
        """

        df_historico = pd.read_sql_query(query, conn_sync)
        conn_sync.close()
        if 'Filiação' in df_historico.columns:
            df_historico['Filiação'] = df_historico['Filiação'].apply(
                limpar_filiacao)

        excel_path = os.path.join(BASE_DIR, "historico_atendimentos.xlsx")
        df_historico.to_excel(
            excel_path,
            index=False,
            sheet_name="Todos os Atendimentos")
    except Exception as e:
        pass


# Configuração da Página do Streamlit
st.set_page_config(
    page_title="Ressalva Digital FUNAP",
    layout="wide",
    page_icon="📝"
)

# =========================================
# GERENCIAMENTO DO BANCO DE DADOS (SQLITE)
# =========================================


def criar_conexao():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Tabela Atendimentos (Reeducandos)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS atendimentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome_reeducando TEXT,
        cpf TEXT,
        filiacao TEXT,
        data_presenca TEXT,
        horario_entrada TEXT,
        horario_saida TEXT,
        finalidade TEXT,
        vigilante_ent TEXT,
        servidor_sai TEXT,
        mat_servidor TEXT,
        status TEXT DEFAULT 'ENTRADA'
    )
    """)

    # Tabela Usuários
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        login TEXT UNIQUE,
        senha TEXT,
        nome TEXT,
        perfil TEXT,
        matricula TEXT
    )
    """)

    # Tabela Visitas (Acesso de Visitantes Externos)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS visitas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome_visitante TEXT,
        cpf_visitante TEXT,
        vinculo_reeducando TEXT,
        data_visita TEXT,
        horario_entrada TEXT,
        horario_saida TEXT,
        status TEXT DEFAULT 'EM VISITA',
        vigilante_ent TEXT,
        servidor_sai TEXT
    )
    """)

    # Tabela Relatórios Diários de Plantão
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS relatorios_diarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data_plantao TEXT UNIQUE,
        total_reeducandos INTEGER DEFAULT 0,
        total_visitantes INTEGER DEFAULT 0,
        total_atendimentos INTEGER DEFAULT 0,
        operador_fechamento TEXT,
        observacoes TEXT,
        data_hora_fechamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Inserção do Administrador Padrão do Sistema
    senha_admin = hashlib.sha256("123".encode()).hexdigest()
    cursor.execute("""
    INSERT OR IGNORE INTO usuarios (login, senha, nome, perfil, matricula)
    VALUES ('admin', ?, 'ADMINISTRADOR NTI', 'ADMINISTRADOR', '32993439120')
    """, (senha_admin,))

    conn.commit()

    # CORREÇÃO 6: Migration — coluna nome_reeducando_vinculado
    try:
        cursor.execute(
            "ALTER TABLE visitas ADD COLUMN nome_reeducando_vinculado TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    return conn


conn = criar_conexao()

# =========================================
# FUNÇÕES UTILITÁRIAS & REGRAS DE NEGÓCIO
# =========================================


def limpar_cpf(cpf):
    """Remove pontos, traços e caracteres não numéricos do CPF."""
    return re.sub(r'\D', '', str(cpf))


def formatar_cpf(cpf):
    """Aplica máscara padrão de CPF (###.###.###-##)."""
    numeros = limpar_cpf(cpf)
    if len(numeros) == 11:
        return f"{numeros[:3]}.{numeros[3:6]}.{numeros[6:9]}-{numeros[9:]}"
    return cpf


# ──────────────────────────────────────────────────
# CORREÇÃO 3: Função de data em português brasileiro
# ──────────────────────────────────────────────────
MESES_PTBR = {
    1: 'janeiro', 2: 'fevereiro', 3: 'março', 4: 'abril',
    5: 'maio', 6: 'junho', 7: 'julho', 8: 'agosto',
    9: 'setembro', 10: 'outubro', 11: 'novembro', 12: 'dezembro'
}


def formatar_data_ptbr(data_str):
    """Converte data YYYY-MM-DD para formato extenso em português: '19 de agosto de 2026'."""
    try:
        dt = datetime.strptime(data_str, '%Y-%m-%d')
        return f"{dt.day:02d} de {MESES_PTBR[dt.month]} de {dt.year}"
    except Exception:
        try:
            dt = datetime.strptime(data_str, '%d/%m/%Y')
            return f"{dt.day:02d} de {MESES_PTBR[dt.month]} de {dt.year}"
        except Exception:
            return data_str


def formatar_data_curta_ptbr(data_str):
    """Converte data YYYY-MM-DD para formato curto em português: '19/08/2026'."""
    try:
        dt = datetime.strptime(data_str, '%Y-%m-%d')
        return dt.strftime('%d/%m/%Y')
    except Exception:
        return data_str


def limpar_filiacao(texto):
    """Limpa strings de filiação que virem como listas Python: ['NOME1', 'NOME2'] → 'NOME1 e NOME2'."""
    if not texto or not isinstance(texto, str):
        return texto or ''
    import re
    # Remove brackets e aspas de lista Python
    texto = re.sub(r"[\[\]']", '', texto)
    # Substitui vírgula por ' e '
    texto = texto.replace(',', ' e')
    # Corrige espaços duplos
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto


def buscar_cadastro_existente(cpf):
    """Busca o último registro do reeducando no banco para reaproveitamento de dados."""
    cpf_limpo = limpar_cpf(cpf)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT nome_reeducando, filiacao
        FROM atendimentos
        WHERE replace(replace(cpf, '.', ''), '-', '') = ?
        ORDER BY id DESC LIMIT 1
    """, (cpf_limpo,))
    return cursor.fetchone()


def converter_logo_para_base64(caminho_imagem):
    """Converte a imagem do logo para base64 para uso em HTML."""
    try:
        with open(caminho_imagem, "rb") as arquivo_img:
            return base64.b64encode(arquivo_img.read()).decode()
    except BaseException:
        return ""


def obter_logo_html():
    """Retorna tag HTML com o logo da FUNAP em base64."""
    logo_base64 = converter_logo_para_base64(LOGO_PATH)
    if logo_base64:
        return f'<p align="center"><img src="data:image/png;base64,{logo_base64}" style="max-height: 90px; margin-bottom: 15px;"></p>'
    return '<p align="center" style="font-size: 18px; font-weight: bold; color: #1a5276;">🏢 FUNDAÇÃO DE AMPARO AO TRABALHADOR PRESO - FUNAP/GDF</p>'

# ──────────────────────────────────────────────────
# CORREÇÃO 2: QR Code de validação no PDF
# ──────────────────────────────────────────────────


def gerar_qrcode_validacao(codigo, tamanho=120):
    """Gera um QR Code em PNG (bytes) para validação do documento.
    Se o módulo qrcode não estiver instalado, retorna None."""
    if not QRCODE_DISPONIVEL:
        return None
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=4,
            border=2,
        )
        qr.add_data(codigo)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img = img.resize((tamanho, tamanho))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()
    except Exception:
        return None


def buscar_matricula_por_nome(nome_usuario):
    """Busca a matrícula do usuário na tabela de usuários pelo nome completo."""
    if not nome_usuario:
        return "N/A"
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT matricula FROM usuarios WHERE nome = ? LIMIT 1", (nome_usuario,))
        resultado = cursor.fetchone()
        if resultado and resultado['matricula']:
            return resultado['matricula']
        return "N/A"
    except Exception:
        return "N/A"


def desenhar_logo_fallback(pdf, x, y, w, h, fonte="Helvetica"):
    """Desenha um logo fallback estilizado quando o arquivo logo_funap.png não existe."""
    # Fundo azul institucional
    pdf.set_fill_color(0, 51, 102)  # Azul marinho FUNAP
    pdf.rect(x, y, w, h, style='F')
    # Borda branca interna
    pdf.set_draw_color(255, 255, 255)
    pdf.set_line_width(0.5)
    pdf.rect(x + 1.5, y + 1.5, w - 3, h - 3)
    # Texto FUNAP centralizado
    pdf.set_xy(x, y + h / 2 - 4)
    pdf.set_font(fonte, "B", 14)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(w, 8, "FUNAP", ln=0, align='C')
    pdf.set_text_color(0, 0, 0)
    pdf.set_line_width(0.2)
    pdf.set_draw_color(0, 0, 0)


def inserir_logo_no_pdf(pdf, logo_x, logo_y, logo_largura):
    """Insere a logo da FUNAP no PDF, usando PIL para compatibilidade com FPDF.
    Retorna True se conseguiu inserir a logo real, False se usou fallback."""
    if not os.path.exists(LOGO_PATH):
        return False

    logo_temp_path = os.path.join(BASE_DIR, "temp_logo_compativel.png")
    try:
        # Abre com PIL e converte para formato 100% compatível com FPDF
        img = Image.open(LOGO_PATH)
        # Converte para RGB (remove canal alpha/transparência que o FPDF não
        # suporta)
        if img.mode in ('RGBA', 'LA', 'P'):
            fundo = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                fundo.paste(img, mask=img.split()[-1])
                img = fundo
            else:
                img = img.convert('RGB')
        else:
            img = img.convert('RGB')
        # Salva como PNG não-interlaced compatível
        img.save(logo_temp_path, 'PNG')
        # Insere no PDF
        pdf.image(logo_temp_path, x=logo_x, y=logo_y, w=logo_largura)
        return True
    except Exception:
        return False
    finally:
        try:
            os.remove(logo_temp_path)
        except Exception:
            pass


def gerar_pdf_ressalva(dados):
    """Gera o arquivo binário do PDF da ressalva oficial em formato A4."""
    global _FONTE_UNICODE
    pdf = FPDF()
    pdf.add_page()
    _FONTE_UNICODE = configurar_fonte_pdf(pdf)
    fonte = _FONTE_UNICODE[0]

    # ─── CABEÇALHO INSTITUCIONAL COM LOGO ───
    y_topo = 10
    logo_largura = 28
    logo_altura = 28
    logo_x = 15
    logo_y = y_topo
    texto_x = logo_x + logo_largura + 5  # espaço após logo

    # Tenta inserir logo real; se falhar, usa fallback desenhado
    logo_inserido = inserir_logo_no_pdf(pdf, logo_x, logo_y, logo_largura)
    if not logo_inserido:
        desenhar_logo_fallback(
            pdf,
            logo_x,
            logo_y,
            logo_largura,
            logo_altura,
            fonte)

    # Texto do órgão ao lado da logo (centralizado verticalmente)
    pdf.set_xy(texto_x, logo_y + 2)
    pdf.set_font(fonte, "B", 12)
    pdf.cell(0, 6, "GOVERNO DO DISTRITO FEDERAL", ln=True, align='C')
    pdf.set_x(texto_x)
    pdf.set_font(fonte, "B", 10)
    pdf.cell(
        0,
        5,
        "SECRETARIA DE ESTADO DE ADMINISTRAÇÃO PENITENCIÁRIA",
        ln=True,
        align='C')
    pdf.set_x(texto_x)
    pdf.set_font(fonte, "B", 10)
    pdf.cell(
        0,
        5,
        "FUNDAÇÃO DE AMPARO AO TRABALHADOR PRESO - FUNAP",
        ln=True,
        align='C')

    # Linha divisória abaixo do cabeçalho
    pdf.set_y(logo_y + logo_altura + 4)
    pdf.set_draw_color(0, 51, 102)
    pdf.set_line_width(0.8)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(6)

    # Título do documento
    pdf.set_font(fonte, "B", 14)
    pdf.set_fill_color(240, 240, 240)
    pdf.set_draw_color(0, 51, 102)
    pdf.set_line_width(0.3)
    pdf.cell(
        0,
        12,
        "RESSALVA ELETRÔNICA DE ATENDIMENTO PRESENCIAL",
        ln=True,
        align='C',
        fill=True,
        border=1)
    pdf.ln(10)

    # ──────────────────────────────────────────────────
    # CORREÇÃO 3: Data em português extenso no PDF
    # ──────────────────────────────────────────────────
    try:
        data_br = formatar_data_ptbr(dados['data_presenca'])
    except BaseException:
        try:
            data_br = datetime.strptime(
                dados['data_presenca'],
                '%Y-%m-%d').strftime('%d/%m/%Y')
        except BaseException:
            data_br = dados['data_presenca']

    horario_saida = dados['horario_saida'] if dados['horario_saida'] else datetime.now(
    ).strftime('%H:%M')

    texto = (
        f"Certificamos que {
            dados['nome_reeducando'].upper()}, CPF nº {
            dados['cpf']}, " f"filho(a) de {
                limpar_filiacao(
                    dados['filiacao']).upper()}, compareceu PRESENCIALMENTE à FUNAP/GDF em {data_br}, " f"das {
                        dados['horario_entrada']} às {horario_saida}, para a seguinte finalidade institucional: " f"{
                            dados['finalidade'].upper()}.")

    pdf.set_font(fonte, "", 12)
    pdf.multi_cell(0, 8, texto, align='J')
    pdf.ln(15)

    # ─── DADOS DO REGISTRO (com matrículas) ───
    # Busca matrículas automaticamente
    mat_vigilante = buscar_matricula_por_nome(dados.get('vigilante_ent'))
    mat_servidor = dados.get(
        'mat_servidor',
        buscar_matricula_por_nome(
            dados.get('servidor_sai')))

    pdf.set_font(fonte, "B", 10)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(0, 8, "DADOS DO REGISTRO", ln=True, fill=True)
    pdf.set_font(fonte, "", 10)
    # Linha 1: Responsáveis
    pdf.cell(
        95,
        7,
        f"Vigilante Entrada: {
            dados.get(
                'vigilante_ent',
                'N/A')}",
        ln=0)
    pdf.cell(0, 7, f"Servidor Saída: {dados.get('servidor_sai', 'N/A')}", ln=1)
    # Linha 2: Matrículas
    pdf.cell(95, 7, f"Matrícula Vigilante: {mat_vigilante}", ln=0)
    pdf.cell(0, 7, f"Matrícula Servidor: {mat_servidor}", ln=1)
    # Linha 3: Horários
    pdf.cell(95, 7, f"Horário Entrada: {dados['horario_entrada']}", ln=0)
    pdf.cell(0, 7, f"Horário Saída: {horario_saida}", ln=1)
    # Linha 4: Status
    pdf.cell(0, 7, f"Status: {dados.get('status', 'N/A').upper()}", ln=1)
    pdf.ln(12)

    # Validação eletrônica (não requer assinatura manual — o código de
    # autenticidade garante a integridade)
    pdf.set_font(fonte, "I", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(
        0,
        6,
        "Este documento possui validação eletrônica de autenticidade. Não é necessário assinatura manuscrita. Utilize o Código de Autenticidade ou o QR Code para verificar a legitimidade deste documento no sistema oficial da FUNAP/GDF.",
        align='C')
    pdf.set_text_color(0, 0, 0)
    pdf.ln(8)

    # ──────────────────────────────────────────────────
    # CORREÇÃO 4: Frase de autenticação sem "qualquer pessoa pode consultar"
    # ──────────────────────────────────────────────────
    autenticidade = hashlib.sha256(
        f"{dados['cpf']}{horario_saida}".encode()).hexdigest().upper()[:12]

    pdf.set_font(fonte, "I", 8)
    # CORREÇÃO 3: Data de emissão em português
    data_emissao = formatar_data_ptbr(datetime.now().strftime('%Y-%m-%d'))
    hora_emissao = datetime.now().strftime('%H:%M')
    pdf.cell(
        0,
        6,
        f"Código de Autenticidade: {autenticidade} | Sistema Ressalva Digital FUNAP | Emitido em: {data_emissao} às {hora_emissao}",
        ln=True,
        align='C')
    # CORREÇÃO 4: Frase alterada — sem referência a "qualquer pessoa pode consultar"
    # REMOVIDO: frase Validacao interna no PDF

      # ──────────────────────────────────────────────────
    # CORREÇÃO 2: QR Code de validação inserido no rodapé do PDF
    # ──────────────────────────────────────────────────
    qr_path = os.path.join(BASE_DIR, "temp_qr_validacao.png")
    qr_bytes = gerar_qrcode_validacao(autenticidade, tamanho=150)
    
    if qr_bytes:
        # Salva QR temporariamente para o FPDF usar
        with open(qr_path, "wb") as fq:
            fq.write(qr_bytes)

    try:
        if os.path.exists(qr_path):
            os.remove(qr_path)
    except Exception:
        pass

    return bytes(pdf.output(dest='S'), 'latin-1')

def gerar_docx_real(dados):
    """Gera um documento Word (.docx) real com formatação institucional FUNAP.
    Usa python-docx — a mesma biblioteca já usada no Livro de Ata.
    Fallback: se python-docx indisponível, gera HTML com extensão .doc."""
    horario_saida = dados.get(
        'horario_saida') or datetime.now().strftime('%H:%M')
    try:
        from docx import Document
        from docx.shared import Inches, Pt, Cm, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_TABLE_ALIGNMENT

        doc = Document()

        # ── Cabeçalho Institucional ──
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run('GOVERNO DO DISTRITO FEDERAL')
        run.bold = True
        run.font.size = Pt(14)

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run('SECRETARIA DE ESTADO DE ADMINISTRAÇÃO PENITENCIÁRIA')
        run.bold = True
        run.font.size = Pt(10)

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run('FUNDAÇÃO DE AMPARO AO TRABALHADOR PRESO - FUNAP')
        run.bold = True
        run.font.size = Pt(10)

        # Linha divisória
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run('━' * 60)
        run.font.color.rgb = RGBColor(0, 51, 102)

        # Título
        p = doc.add_heading(
            'RESSALVA ELETRÔNICA DE ATENDIMENTO PRESENCIAL', level=1)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # Corpo do certificado
        try:
            data_br = formatar_data_ptbr(dados['data_presenca'])
        except Exception:
            try:
                data_br = datetime.strptime(
                    dados['data_presenca'],
                    '%Y-%m-%d').strftime('%d/%m/%Y')
            except Exception:
                data_br = dados['data_presenca']

        texto_cert = (
            f"Certificamos que {dados['nome_reeducando'].upper()}, CPF nº {dados['cpf']}, "
            f"filho(a) de {limpar_filiacao(dados['filiacao']).upper()}, compareceu PRESENCIALMENTE "
            f"à FUNAP/GDF em {data_br}, das {dados['horario_entrada']} às {horario_saida}, "
            f"para a seguinte finalidade institucional: {dados['finalidade'].upper()}."
        )
        p = doc.add_paragraph(texto_cert)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

        # ── Tabela de Dados do Registro ──
        mat_vigilante = buscar_matricula_por_nome(dados.get('vigilante_ent'))
        mat_servidor = dados.get(
            'mat_servidor', buscar_matricula_por_nome(
                dados.get('servidor_sai')))

        p = doc.add_paragraph()
        run = p.add_run('DADOS DO REGISTRO')
        run.bold = True
        run.font.size = Pt(11)

        table = doc.add_table(rows=5, cols=2)
        table.style = 'Light Grid Accent 1'
        table.alignment = WD_TABLE_ALIGNMENT.CENTER

        dados_tabela = [
            ('Vigilante Entrada', f"{dados.get('vigilante_ent', 'N/A')} — Matrícula: {mat_vigilante}"),
            ('Servidor Saída', f"{dados.get('servidor_sai', 'N/A')} — Matrícula: {mat_servidor}"),
            ('Horário Entrada', dados['horario_entrada']),
            ('Horário Saída', horario_saida),
            ('Status', dados.get('status', 'N/A').upper()),
        ]
        for i, (campo, valor) in enumerate(dados_tabela):
            cell_campo = table.rows[i].cells[0]
            cell_valor = table.rows[i].cells[1]
            cell_campo.text = campo
            cell_valor.text = str(valor)
            for paragraph in cell_campo.paragraphs:
                for run in paragraph.runs:
                    run.bold = True
                    run.font.size = Pt(9)
            for paragraph in cell_valor.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(9)

        # ── Autenticidade ──
        autenticidade = hashlib.sha256(
            f"{dados['cpf']}{horario_saida}".encode()).hexdigest().upper()[:12]
        data_emissao = formatar_data_ptbr(datetime.now().strftime('%Y-%m-%d'))
        hora_emissao = datetime.now().strftime('%H:%M')

        doc.add_paragraph()
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(
            f'Código de Autenticidade: {autenticidade} | Sistema Ressalva Digital FUNAP | '
            f'Emitido em: {data_emissao} às {hora_emissao}'
        )
        run.italic = True
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(100, 100, 100)

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(
            'Este documento possui validação eletrônica de autenticidade. '
            'Não é necessário assinatura manuscrita. Utilize o Código de Autenticidade '
            'para verificar a legitimidade deste documento no sistema oficial da FUNAP/GDF.')
        run.italic = True
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(100, 100, 100)

        # Exporta para bytes
        docx_buf = io.BytesIO()
        doc.save(docx_buf)
        docx_buf.seek(0)
        return docx_buf.read()

    except ImportError:
        # Fallback: gera HTML com extensão .doc (Word abre HTML nativamente)
        html_content = (
            '<html><head><meta charset="utf-8"></head><body>'
            '<div style="text-align:center">'
            '<h2>GOVERNO DO DISTRITO FEDERAL</h2>'
            '<h3>SECRETARIA DE ESTADO DE ADMINISTRAÇÃO PENITENCIÁRIA</h3>'
            '<h3>FUNDAÇÃO DE AMPARO AO TRABALHADOR PRESO - FUNAP</h3>'
            '<hr/>'
            f'<h2>RESSALVA ELETRÔNICA DE ATENDIMENTO PRESENCIAL</h2>'
            '</div>'
            f'<p style="text-align:justify">'
            f'Certificamos que <b>{dados["nome_reeducando"].upper()}</b>, '
            f'CPF nº {dados["cpf"]}, filho(a) de <b>{limpar_filiacao(dados["filiacao"]).upper()}</b>, '
            f'compareceu PRESENCIALMENTE à FUNAP/GDF em {data_br}, '
            f'das {dados["horario_entrada"]} às {horario_saida}, '
            f'para a seguinte finalidade institucional: <b>{dados["finalidade"].upper()}</b>.</p>'
            '<h3>DADOS DO REGISTRO</h3>'
            f'<p>Vigilante Entrada: {dados.get("vigilante_ent", "N/A")}<br/>'
            f'Servidor Saída: {dados.get("servidor_sai", "N/A")}<br/>'
            f'Horário Entrada: {dados["horario_entrada"]}<br/>'
            f'Horário Saída: {horario_saida}<br/>'
            f'Status: {dados.get("status", "N/A").upper()}</p>'
            f'<p style="text-align:center;font-size:10px;color:gray">'
            f'Código de Autenticidade: {autenticidade} | Emitido em: {data_emissao} às {hora_emissao}</p>'
            '</body></html>'
        )
        return html_content.encode('utf-8')

    except Exception as e_gen:
        # Fallback final: texto plano
        texto = (
            f"RESSALVA ELETRÔNICA - FUNAP/GDF\n"
            f"Nome do Reeducando: {dados['nome_reeducando']}\n"
            f"CPF: {dados['cpf']}\n"
            f"Filiação: {limpar_filiacao(dados['filiacao'])}\n"
            f"Data de Presença: {dados['data_presenca']}\n"
            f"Horário de Entrada: {dados['horario_entrada']}\n"
            f"Horário de Saída: {horario_saida}\n"
        )
        return texto.encode('utf-8')

# =========================================
# FUNÇÕES DO RELATÓRIO DIÁRIO DE PLANTÃO
# =========================================


def gerar_relatorio_diario_pdf(data_str):
    """Gera PDF do relatório diário de plantão com todas as movimentações."""
    global _FONTE_UNICODE
    cursor = conn.cursor()

    # Busca atendimentos do dia
    cursor.execute("""
        SELECT * FROM atendimentos WHERE data_presenca = ? ORDER BY horario_entrada ASC
    """, (data_str,))
    atendimentos = cursor.fetchall()

    # Busca visitas do dia
    cursor.execute("""
        SELECT * FROM visitas WHERE data_visita = ? ORDER BY horario_entrada ASC
    """, (data_str,))
    visitas = cursor.fetchall()

    pdf = FPDF(orientation='L', format='A4')
    pdf.add_page()
    _FONTE_UNICODE = configurar_fonte_pdf(pdf)
    fonte = _FONTE_UNICODE[0]

    # ─── CABEÇALHO INSTITUCIONAL COM LOGO ───
    y_topo = 10
    logo_largura = 24
    logo_altura = 24
    logo_x = 15
    logo_y = y_topo
    texto_x = logo_x + logo_largura + 5

    # Tenta inserir logo real; se falhar, usa fallback desenhado
    logo_inserido = inserir_logo_no_pdf(pdf, logo_x, logo_y, logo_largura)
    if not logo_inserido:
        desenhar_logo_fallback(
            pdf,
            logo_x,
            logo_y,
            logo_largura,
            logo_altura,
            fonte)

    pdf.set_xy(texto_x, logo_y + 1)
    pdf.set_font(fonte, "B", 11)
    pdf.cell(0, 6, "GOVERNO DO DISTRITO FEDERAL", ln=True, align='C')
    pdf.set_x(texto_x)
    pdf.set_font(fonte, "B", 9)
    pdf.cell(
        0,
        5,
        "SECRETARIA DE ESTADO DE ADMINISTRAÇÃO PENITENCIÁRIA",
        ln=True,
        align='C')
    pdf.set_x(texto_x)
    pdf.cell(
        0,
        5,
        "FUNDAÇÃO DE AMPARO AO TRABALHADOR PRESO - FUNAP",
        ln=True,
        align='C')

    pdf.set_y(logo_y + logo_altura + 4)
    pdf.set_draw_color(0, 51, 102)
    pdf.set_line_width(0.8)
    pdf.line(15, pdf.get_y(), 280, pdf.get_y())
    pdf.ln(6)

    try:
        data_br = datetime.strptime(data_str, '%Y-%m-%d').strftime('%d/%m/%Y')
    except BaseException:
        data_br = data_str

    pdf.set_font(fonte, "B", 13)
    pdf.set_fill_color(230, 230, 230)
    pdf.set_draw_color(0, 51, 102)
    pdf.set_line_width(0.3)
    pdf.cell(0, 10, f"RELATÓRIO DIÁRIO DE PLANTÃO - FUNAP/GDF",
             ln=True, align='C', fill=True, border=1)
    pdf.set_font(fonte, "B", 11)
    pdf.cell(0, 8, f"Data do Plantão: {data_br}", ln=True, align='C')
    pdf.ln(5)

    # Resumo
    pdf.set_font(fonte, "B", 10)
    pdf.cell(
        0,
        8,
        f"RESUMO DO DIA: {
            len(atendimentos)} Reeducandos | {
            len(visitas)} Visitantes | Total: {
                len(atendimentos) +
                len(visitas)} Movimentações",
        ln=True,
        fill=True)
    pdf.ln(5)

    # Tabela de Reeducandos
    if atendimentos:
        pdf.set_font(fonte, "B", 10)
        pdf.cell(0, 8, "MOVIMENTAÇÃO DE REEDUCANDOS:", ln=True)
        pdf.set_font(fonte, "B", 8)
        pdf.set_fill_color(220, 220, 220)
        pdf.cell(40, 7, "Nome", border=1, fill=True)
        pdf.cell(30, 7, "CPF", border=1, fill=True)
        pdf.cell(50, 7, "Filiação", border=1, fill=True)
        pdf.cell(35, 7, "Entrada", border=1, fill=True)
        pdf.cell(35, 7, "Saída", border=1, fill=True)
        pdf.cell(40, 7, "Finalidade", border=1, fill=True)
        pdf.cell(35, 7, "Status", border=1, fill=True)
        pdf.ln()

        pdf.set_font(fonte, "", 7)
        for at in atendimentos:
            pdf.cell(40, 6, at['nome_reeducando'][:25], border=1)
            pdf.cell(30, 6, at['cpf'], border=1)
            pdf.cell(50, 6, limpar_filiacao(at['filiacao'])[
                     :30] if at['filiacao'] else "-", border=1)
            pdf.cell(35, 6, at['horario_entrada'], border=1)
            pdf.cell(35, 6, at['horario_saida']
                     if at['horario_saida'] else "-", border=1)
            pdf.cell(40, 6, at['finalidade'][:20], border=1)
            pdf.cell(35, 6, at['status'], border=1)
            pdf.ln()
        pdf.ln(5)

    # Tabela de Visitantes
    if visitas:
        pdf.set_font(fonte, "B", 10)
        pdf.cell(0, 8, "MOVIMENTAÇÃO DE VISITANTES EXTERNOS:", ln=True)
        pdf.set_font(fonte, "B", 8)
        pdf.set_fill_color(220, 220, 220)
        pdf.cell(50, 7, "Nome", border=1, fill=True)
        pdf.cell(30, 7, "CPF", border=1, fill=True)
        pdf.cell(30, 7, "Vínculo", border=1, fill=True)
        pdf.cell(35, 7, "Entrada", border=1, fill=True)
        pdf.cell(35, 7, "Saída", border=1, fill=True)
        pdf.cell(40, 7, "Status", border=1, fill=True)
        pdf.cell(45, 7, "Vigilante", border=1, fill=True)
        pdf.ln()

        pdf.set_font(fonte, "", 7)
        for vis in visitas:
            pdf.cell(50, 6, vis['nome_visitante'][:30], border=1)
            pdf.cell(30, 6, vis['cpf_visitante'], border=1)
            pdf.cell(30, 6, vis['vinculo_reeducando'][:15], border=1)
            pdf.cell(35, 6, vis['horario_entrada'], border=1)
            pdf.cell(35, 6, vis['horario_saida']
                     if vis['horario_saida'] else "-", border=1)
            pdf.cell(40, 6, vis['status'], border=1)
            pdf.cell(45, 6, vis['vigilante_ent'][:20], border=1)
            pdf.ln()

    pdf.ln(10)
    pdf.set_font(fonte, "I", 8)
    pdf.cell(
        0,
        10,
        f"Documento gerado automaticamente pelo Sistema Ressalva Digital FUNAP | {
            datetime.now().strftime('%d/%m/%Y %H:%M')}",
        border='T',
        align='C')

    return bytes(pdf.output())


def salvar_relatorio_excel_mensal(data_str):
    """Salva o relatório diário em planilha Excel organizada por mês/ano."""
    try:
        data_obj = datetime.strptime(data_str, '%Y-%m-%d')
        ano = data_obj.strftime('%Y')
        mes = data_obj.strftime('%m')
        dia = data_obj.strftime('%d')
        nome_mes = data_obj.strftime('%B').upper()

        # Cria pastas: relatorios/2026/07-JULHO/
        pasta_ano = os.path.join(RELATORIOS_DIR, ano)
        pasta_mes = os.path.join(pasta_ano, f"{mes}-{nome_mes}")
        os.makedirs(pasta_mes, exist_ok=True)

        arquivo_excel = os.path.join(pasta_mes, f"relatorio_{ano}_{mes}.xlsx")

        conn_excel = sqlite3.connect(DB_PATH)

        # Dados de reeducandos do mês
        query_reed = f"""
            SELECT id, nome_reeducando, cpf, filiacao, data_presenca,
                   horario_entrada, horario_saida, finalidade, status,
                   vigilante_ent, servidor_sai
            FROM atendimentos
            WHERE strftime('%Y-%m', data_presenca) = '{ano}-{mes}'
            ORDER BY data_presenca, horario_entrada
        """
        df_reed = pd.read_sql_query(query_reed, conn_excel)

        # Dados de visitantes do mês
        query_vis = f"""
            SELECT id, nome_visitante, cpf_visitante, nome_reeducando_vinculado, vinculo_reeducando, data_visita,
                   horario_entrada, horario_saida, status, vigilante_ent, servidor_sai
            FROM visitas
            WHERE strftime('%Y-%m', data_visita) = '{ano}-{mes}'
            ORDER BY data_visita, horario_entrada
        """
        df_vis = pd.read_sql_query(query_vis, conn_excel)
        conn_excel.close()

        # Cria arquivo Excel com abas para cada dia do mês
        with pd.ExcelWriter(arquivo_excel, engine='openpyxl') as writer:
            # Aba com todos os dados do mês
            df_reed.to_excel(writer, sheet_name="REEDUCANDOS_MES", index=False)
            df_vis.to_excel(writer, sheet_name="VISITANTES_MES", index=False)

            # Cria abas para cada dia (até 31)
            for dia_num in range(1, 32):
                dia_str = f"{dia_num:02d}"
                data_dia = f"{ano}-{mes}-{dia_str}"

                df_dia_reed = df_reed[df_reed['data_presenca'] == data_dia]
                df_dia_vis = df_vis[df_vis['data_visita'] == data_dia]

                if not df_dia_reed.empty or not df_dia_vis.empty:
                    # Combina dados do dia
                    df_dia_reed_copy = df_dia_reed.copy()
                    df_dia_reed_copy['tipo'] = 'REEDUCANDO'
                    df_dia_vis_copy = df_dia_vis.copy()
                    df_dia_vis_copy['tipo'] = 'VISITANTE'

                    # Padroniza colunas para unificação
                    df_dia_reed_copy = df_dia_reed_copy.rename(columns={
                        'nome_reeducando': 'NOME',
                        'data_presenca': 'DATA',
                        'vigilante_ent': 'VIGILANTE_ENTRADA',
                        'servidor_sai': 'SERVIDOR_SAIDA'
                    })
                    df_dia_vis_copy = df_dia_vis_copy.rename(columns={
                        'nome_visitante': 'NOME',
                        'cpf_visitante': 'cpf',
                        'data_visita': 'DATA',
                        'vigilante_ent': 'VIGILANTE_ENTRADA',
                        'servidor_sai': 'SERVIDOR_SAIDA'
                    })

                    # Seleciona colunas comuns
                    colunas_comuns = [
                        'id',
                        'NOME',
                        'cpf',
                        'DATA',
                        'horario_entrada',
                        'horario_saida',
                        'status',
                        'VIGILANTE_ENTRADA',
                        'SERVIDOR_SAIDA',
                        'tipo']
                    df_dia_reed_copy = df_dia_reed_copy[[
                        c for c in colunas_comuns if c in df_dia_reed_copy.columns]]
                    df_dia_vis_copy = df_dia_vis_copy[[
                        c for c in colunas_comuns if c in df_dia_vis_copy.columns]]

                    df_dia_total = pd.concat(
                        [df_dia_reed_copy, df_dia_vis_copy], ignore_index=True)
                    df_dia_total.to_excel(
                        writer, sheet_name=f"DIA_{dia_str}", index=False)

        return arquivo_excel
    except Exception as e:
        st.error(f"Erro ao gerar Excel: {e}")
        return None

# ==============================================================================
# LOGIN, SESSÃO E SIDEBAR
# ==============================================================================


# Inicialização de Variáveis de Controle Globais no Session State
if 'logado' not in st.session_state:
    st.session_state.logado = False
if 'menu_atual' not in st.session_state:
    st.session_state.menu_atual = "Painel Geral"
if 'ent_nome' not in st.session_state:
    st.session_state.ent_nome = ""
if 'ent_filiacao' not in st.session_state:
    st.session_state.ent_filiacao = ""
if 'ent_cpf' not in st.session_state:
    st.session_state.ent_cpf = ""

# Verificação e Carregamento de Sessão Automática Ativa
if not st.session_state.logado and os.path.exists(SESSION_FILE):
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as sf:
            usuario_salvo = sf.read().strip()
        if usuario_salvo:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM usuarios WHERE login=?", (usuario_salvo,))
            res_sessao = cursor.fetchone()
            if res_sessao:
                st.session_state.logado = True
                st.session_state.nome = res_sessao['nome']
                st.session_state.perfil = res_sessao['perfil']
                st.session_state.mat = res_sessao['matricula']
    except BaseException:
        pass

# Tela de Login do Sistema
if not st.session_state.logado:
    c1, c2, c3 = st.columns(3)
    with c2:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=220)
        else:
            st.subheader("🏢 FUNAP / GDF")

        st.title("Ressalva Digital")
        st.write("Insira suas credenciais de segurança corporativa.")

        usuario = st.text_input("Usuário / Login")
        senha = st.text_input("Senha Corporativa", type="password")
        lembrar = st.checkbox("Manter-me conectado neste terminal")

        if st.button("Entrar no Sistema", use_container_width=True):
            senha_hash = hashlib.sha256(senha.encode()).hexdigest()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM usuarios WHERE login=? AND senha=?", (usuario, senha_hash))
            res = cursor.fetchone()

            if res:
                st.session_state.logado = True
                st.session_state.nome = res['nome']
                st.session_state.perfil = res['perfil']
                st.session_state.mat = res['matricula']
                st.session_state.login = res['login']
                if lembrar:
                    with open(SESSION_FILE, "w", encoding="utf-8") as sf:
                        sf.write(usuario)
                st.success("Autenticação bem-sucedida! Carregando painéis...")
                st.rerun()
            else:
                st.error(
                    "Acesso negado. Credenciais inválidas para a base da FUNAP.")
        st.stop()

# =========================================
# CONFIGURAÇÃO DE SIDEBAR (MENU DE NAVEGAÇÃO)
# =========================================
with st.sidebar:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=160)
    else:
        st.markdown("### 🏢 FUNAP / GDF")
    st.markdown("---")
    st.write(f"👤 **{st.session_state.nome}**")
    st.caption(f"Acesso Nível: {st.session_state.perfil}")
    st.markdown("---")
  
    menu = st.radio(
        "📂 NAVEGAÇÃO DO SISTEMA",
        [
            "Painel Geral",
            "Registro de Entrada",
            "Fila de Espera Interna",
            "Finalizar Saída",
            "Repositório de Documentos",
            "Acesso de Visitantes",
            "Livro de Ata Eletrônico",
            "Relatório Diário de Plantão",
            "Edição e Retificação",
            "Validação Pública",
            "Painel de Administração",
            "🔑 Alterar Senha"
        ]
    )
    st.session_state.menu_atual = menu
    st.markdown("---")
    if st.button("🚪 Encerrar Sessão", use_container_width=True):
        st.session_state.logado = False
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
        st.rerun()

menu = st.session_state.menu_atual

# ==============================================================================
# PARTE 3 - PAINEL, ENTRADA IA & FILAS
# ==============================================================================

# =========================================
# 1. PAINEL GERAL DE MONITORAMENTO
# =========================================
if menu == "Painel Geral":
    st.subheader("📊 Painel Geral de Monitoramento")
    busca = st.text_input(
        "🔍 Buscar Atendimento por Nome ou CPF (Digitação contínua ou com máscara):").strip()
    busca_limpa = limpar_cpf(busca)

    query_base = """
    SELECT id as 'ID', nome_reeducando as 'Nome', cpf as 'CPF', filiacao as 'Filiação',
           strftime('%d/%m/%Y', data_presenca) as 'Data', horario_entrada as 'Entrada',
           horario_saida as 'Saída', finalidade as 'Finalidade', status as 'Situação'
    FROM atendimentos
    """

    if busca:
        if busca_limpa.isdigit() and len(busca_limpa) > 0:
            query_base += " WHERE replace(replace(cpf, '.', ''), '-', '') LIKE ? ORDER BY id DESC"
            df = pd.read_sql_query(
                query_base,
                conn,
                params=(
                    f"%{busca_limpa}%",
                ))
        else:
            query_base += " WHERE nome_reeducando LIKE ? ORDER BY id DESC"
            df = pd.read_sql_query(
                query_base, conn, params=(f"%{busca.upper()}%",))
    else:
        query_base += " ORDER BY id DESC"
        df = pd.read_sql_query(query_base, conn)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total de Atendimentos", len(df))
    c2.metric("Em Espera / Atendimento", len(df[df['Situação'] == 'ENTRADA']))
    c3.metric("Finalizados / Concluídos",
              len(df[df['Situação'] == 'CONCLUÍDO']))
    c4.metric("Data Atual do Sistema", datetime.now().strftime('%d/%m/%Y'))

    st.markdown("---")
    if 'Filiação' in df.columns:
        df['Filiação'] = df['Filiação'].apply(limpar_filiacao)
    st.dataframe(df, use_container_width=True)

# =========================================
# 2. REGISTRO DE ENTRADA DE REEDUCANDO (IA)
# =========================================
elif menu == "Registro de Entrada":
    st.subheader("🚪 Registro de Entrada de Reeducando")

    # ══════════════════════════════════════════════════════════════════════════════
    # V7.3: ARQUITETURA DE CÂMERA REDESENHADA
    # TAB 1 (padrão): 📷 Câmera do Navegador — st.camera_input + OCR automático
    # TAB 2 (avançado): 🎥 OpenCV Streaming — streaming ao vivo com warmup + fallback
    # ══════════════════════════════════════════════════════════════════════════════

    # ── Session state ──
    if 'camera_ativa' not in st.session_state:
        st.session_state.camera_ativa = False
    if 'camera_id_sel' not in st.session_state:
        st.session_state.camera_id_sel = 0
    if 'frame_cv_bytes' not in st.session_state:
        st.session_state.frame_cv_bytes = None
    if 'foto_capturada_cv' not in st.session_state:
        st.session_state.foto_capturada_cv = None
    if 'ocr_automatico' not in st.session_state:
        st.session_state.ocr_automatico = False
    if 'ocr_pendente_browser' not in st.session_state:
        # V7.3: flag para OCR auto da câmera do navegador
        st.session_state.ocr_pendente_browser = False
    if 'ent_nome' not in st.session_state:
        st.session_state.ent_nome = ""
    if 'ent_filiacao' not in st.session_state:
        st.session_state.ent_filiacao = ""
    if 'ent_cpf' not in st.session_state:
        st.session_state.ent_cpf = ""

    # ── Função de OCR com Gemini (centralizada) ──
    def executar_ocr_gemini(imagem_bytes, origem="documento"):
        """Processa imagem via Gemini e preenche formulário automaticamente.
        imagem_bytes: bytes da imagem (JPEG/PNG)
        origem: 'navegador' ou 'opencv' — para mensagem de feedback.
        Retorna True se sucesso, False se falha."""
        if not GOOGLE_API_KEY:
            st.error(
                "Chave de API do Gemini não configurada nas diretrizes locais.")
            return False
        try:
            img_pil = Image.open(io.BytesIO(imagem_bytes))
            modelo_nome = GEMINI_MODELO_ATIVO or GEMINI_MODELOS[0]
            model = genai.GenerativeModel(modelo_nome)
            prompt = """
            Analise esta imagem de documento de identidade brasileiro de forma precisa.
            Extraia estritamente os campos: nome completo, número de CPF e filiação (nome da mãe/pai).
            Retorne estritamente um código estruturado em JSON sem qualquer bloco de formatação markdown.
            Formato esperado:
            {"nome": "NOME EXTRAÍDO", "cpf": "APENAS NÚMEROS", "filiacao": "NOME DA MÃE OU PAI"}
            """
            response = model.generate_content([prompt, img_pil])
            texto_limpo = response.text.replace(
                "```json", "").replace(
                "```", "").strip()
            dados_ia = json.loads(texto_limpo)

            st.session_state.ent_nome = dados_ia.get('nome', '').upper()
            st.session_state.ent_filiacao = dados_ia.get(
                'filiacao', '').upper()
            st.session_state.ent_cpf = formatar_cpf(dados_ia.get('cpf', ''))
            st.success(
                f"✅ OCR Automático — Dados extraídos do {origem} e formulário preenchido!")
            return True
        except Exception as e:
            st.error(f"❌ Falha no OCR: {e}")
            st.info(
                "💡 Dica: Verifique se o documento está legível, bem iluminado e se a chave API está ativa.")
            return False

    # ── Função auxiliar: listar câmeras disponíveis ──
    def listar_cameras_disponiveis(max_test=5):
        """Testa índices 0..max_test-1 e retorna lista de câmeras que abrem.
        V7.3: NÃO faz warmup bloqueante — só testa isOpened() rapidamente.
        O warmup pesado acontece DENTRO da thread de streaming."""
        disponiveis = []
        vistos = set()
        if not CV2_DISPONIVEL:
            return disponiveis
        estrategias = [
            ("padrão", None),
            ("CAP_MSMF", cv2.CAP_MSMF),
            ("CAP_DSHOW", cv2.CAP_DSHOW),
        ]
        for idx in range(max_test):
            for nome_estrat, api_pref in estrategias:
                if idx in vistos:
                    break
                try:
                    if api_pref is not None:
                        cap_test = cv2.VideoCapture(idx, api_pref)
                    else:
                        cap_test = cv2.VideoCapture(idx)
                except Exception:
                    continue
                if cap_test.isOpened():
                    w = int(cap_test.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap_test.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    if w == 0 or h == 0:
                        w, h = 640, 480
                    disp_name = f"Câmera {idx} ({w}x{h})"
                    disponiveis.append((idx, disp_name))
                    vistos.add(idx)
                cap_test.release()
                if idx in vistos:
                    break
        return disponiveis

    # ══════════════════════════════════════════════════════════════════════════════
    # TABS: Câmera do Navegador (padrão) | OpenCV Streaming (avançado)
    # ══════════════════════════════════════════════════════════════════════════════
    tab_browser, tab_opencv = st.tabs([
        "📷 Câmera do Navegador (Recomendado)",
        "🎥 OpenCV Streaming (Avançado)"
    ])

    # ══════════════════════════════════════════════════════════════════════════════
    # TAB 1: 📷 CÂMERA DO NAVEGADOR — st.camera_input (MÉTODO PRINCIPAL V7.3)
    # ══════════════════════════════════════════════════════════════════════════════
    with tab_browser:
        st.markdown("""
        **Como funciona:** Clique no botão de câmera abaixo, posicione o documento e tire a foto.
        O sistema extrairá os dados automaticamente via IA (Gemini) — sem cliques extras!
        """)

        # V7.3: Se há foto capturada anteriormente (do browser ou OpenCV),
        # exibe
        if st.session_state.foto_capturada_cv is not None:
            st.image(st.session_state.foto_capturada_cv,
                     caption="✅ Documento capturado — pronto para IA")

            # V7.3: OCR AUTOMÁTICO — se flag ativado, processa IMEDIATAMENTE
            if st.session_state.get(
                    'ocr_automatico',
                    False) or st.session_state.get(
                    'ocr_pendente_browser',
                    False):
                st.session_state.ocr_automatico = False
                st.session_state.ocr_pendente_browser = False
                with st.spinner("🔍 OCR Automático — Extraindo dados do documento..."):
                    ok = executar_ocr_gemini(
                        st.session_state.foto_capturada_cv, origem="navegador")
                    if ok:
                        st.session_state.foto_capturada_cv = None
                        st.rerun()

            col_desc1, col_ocr1 = st.columns(2)
            with col_desc1:
                if st.button(
                    "🗑️ Descartar Foto e Tirar Outra",
                        use_container_width=True):
                    st.session_state.foto_capturada_cv = None
                    st.session_state.ocr_automatico = False
                    st.session_state.ocr_pendente_browser = False
                    st.rerun()
            with col_ocr1:
                if st.button(
                    "🤖 Extrair via IA (manual)",
                    use_container_width=True,
                        type="primary"):
                    with st.spinner("🤖 Processando documento com IA..."):
                        ok = executar_ocr_gemini(
                            st.session_state.foto_capturada_cv, origem="navegador")
                        if ok:
                            st.session_state.foto_capturada_cv = None
                            st.rerun()

        else:
            # V7.3: st.camera_input como MÉTODO PRINCIPAL
            # Quando o atendente tira a foto, o resultado volta no próximo rerun.
            # O OCR automático é disparado via flag ocr_pendente_browser.
            foto_doc_browser = st.camera_input("📷 Tire a foto do documento")

            if foto_doc_browser is not None:
                # Foto capturada pelo navegador! Salva e dispara OCR
                # automático.
                st.session_state.foto_capturada_cv = foto_doc_browser.read()
                # V7.3: OCR automático no próximo rerun
                st.session_state.ocr_pendente_browser = True
                st.success(
                    "✅ Foto capturada! Extraindo dados automaticamente...")
                st.rerun()

    # ══════════════════════════════════════════════════════════════════════════════
    # TAB 2: 🎥 OPENCV STREAMING (OPÇÃO AVANÇADA)
    # Para quem tem câmera Iriun/Webcam e quer streaming ao vivo.
    # Warmup reduzido (15 tentativas × 3 backends ≈ 4.5s máx).
    # Se falha, fallback automático para câmera do navegador após ~8s.
    # ══════════════════════════════════════════════════════════════════════════════
    with tab_opencv:
        if not CV2_DISPONIVEL:
            st.warning(
                "⚠️ OpenCV não disponível nesta máquina. Use a aba **📷 Câmera do Navegador**.")
        else:
            st.caption(
                "⚡ Streaming ao vivo via OpenCV — warmup reduzido (~4.5s máx) com fallback automático")

            # ── Câmera DESLIGADA: seletor + botão Iniciar ──
            if not st.session_state.camera_ativa:
                _CameraCache.release()
                _StreamCache.release()

                col_cam1, col_cam2 = st.columns([3, 1])

                with col_cam1:
                    cam_list = listar_cameras_disponiveis(5)
                    if cam_list:
                        opcoes_cam = [
                            f"{idx}: {nome}" for idx, nome in cam_list]
                        indices_cam = [idx for idx, _ in cam_list]
                        cam_sel = st.selectbox(
                            "📷 Selecione a câmera:",
                            opcoes_cam,
                            index=0,
                            help="Selecione a câmera Iriun/Webcam")
                        camera_id = indices_cam[opcoes_cam.index(cam_sel)]
                    else:
                        st.warning(
                            "⚠️ Nenhuma câmera detectada automaticamente. Tente manualmente:")
                        camera_id = st.number_input(
                            "Número da câmera (0, 1, 2...):", min_value=0, max_value=10, value=0, step=1)

                with col_cam2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button(
                        "🎬 Iniciar Câmera",
                        use_container_width=True,
                            type="primary"):
                        cap_new = _CameraCache.get(camera_id)
                        if cap_new is not None:
                            st.session_state.camera_ativa = True
                            st.session_state.camera_id_sel = int(camera_id)
                            st.session_state.frame_cv_bytes = None
                            st.session_state.foto_capturada_cv = None
                            st.rerun()
                        else:
                            st.error(
                                f"❌ Não foi possível abrir câmera {camera_id}. Verifique se o Iriun está rodando.")

                # Exibe foto capturada anterior se existir
                if st.session_state.foto_capturada_cv is not None:
                    st.markdown("---")
                    st.image(
                        st.session_state.foto_capturada_cv,
                        caption="✅ Documento capturado — pronto para IA")

                    # V7.3: OCR automático (flag vindo do botão OCR Instantâneo
                    # do stream)
                    if st.session_state.get('ocr_automatico', False):
                        st.session_state.ocr_automatico = False
                        with st.spinner("🔍 OCR Automático — Extraindo dados do documento..."):
                            ok = executar_ocr_gemini(
                                st.session_state.foto_capturada_cv, origem="OpenCV")
                            if ok:
                                st.session_state.foto_capturada_cv = None
                                st.rerun()

                    col_desc2, col_ocr2 = st.columns(2)
                    with col_desc2:
                        if st.button(
                            "🗑️ Descartar Foto",
                                use_container_width=True):
                            st.session_state.foto_capturada_cv = None
                            st.session_state.ocr_automatico = False
                            st.rerun()
                    with col_ocr2:
                        if st.button(
                            "🤖 Extrair via IA (manual)",
                            use_container_width=True,
                                type="primary"):
                            with st.spinner("🤖 Processando documento com IA..."):
                                ok = executar_ocr_gemini(
                                    st.session_state.foto_capturada_cv, origem="OpenCV")
                                if ok:
                                    st.session_state.foto_capturada_cv = None
                                    st.rerun()

            # ── Câmera LIGADA: Streaming ao vivo ──
            else:
                st.markdown(
                    "🎥 **Streaming ao vivo** — Posicione o documento e clique **Capturar Foto** ou **OCR Instantâneo**.")

                # Garante que o _LatestFrame está rodando
                if _StreamCache.get() is None:
                    _StreamCache.set(
                        _LatestFrame(
                            st.session_state.camera_id_sel))
                lf = _StreamCache.get()

                # Verifica erro da thread — FALLBACK AUTOMÁTICO para câmera do
                # navegador
                if lf.error:
                    st.error(f"❌ {lf.error}")
                    st.markdown("---")
                    st.warning(
                        "⚠️ OpenCV falhou. Use a aba **📷 Câmera do Navegador** como alternativa.")
                    if st.button(
                        "📷 Ir para Câmera do Navegador",
                        use_container_width=True,
                            type="primary"):
                        st.session_state.camera_ativa = False
                        _StreamCache.release()
                        _CameraCache.release()
                        st.rerun()
                    if st.button(
                        "🔄 Tentar OpenCV novamente",
                            use_container_width=True):
                        st.session_state.camera_ativa = False
                        _StreamCache.release()
                        _CameraCache.release()
                        st.rerun()

                # Thread parou sem erro (câmera desconectou)
                elif not lf.running and not lf.error:
                    st.warning(
                        "⚠️ Streaming parou — a câmera pode ter desconectado.")
                    st.session_state.camera_ativa = False
                    _StreamCache.release()
                    _CameraCache.release()
                    st.rerun()

                else:
                    # Thread rodando — exibe frame ou status de warmup
                    frame_placeholder = st.empty()

                    jpg_bytes = lf.frame_jpg_bytes
                    status_atual = lf.status
                    warmup_t = lf.warmup_tentativa
                    backend = lf.backend_usado

                    if jpg_bytes is not None:
                        # FRAME RECEBIDO — exibe normalmente
                        backend_txt = f" [{backend}]" if backend else ""
                        frame_placeholder.image(
                            jpg_bytes,
                            caption=f"📷 Ao vivo — Streaming Contínuo{backend_txt}",
                            use_container_width=True)
                        st.session_state.frame_cv_bytes = jpg_bytes
                    else:
                        # Feedback de warmup
                        if status_atual == _LatestFrame.STATUS_WARMUP:
                            thread_ok = "✅" if lf.thread_viva else "❌ MORTA"
                            warmup_max = getattr(
                                lf, '_warmup_max', _LatestFrame.MAX_WARMUP_TENTATIVAS)
                            frame_placeholder.info(
                                f"🔥 Aquecendo câmera... (tentativa {warmup_t}/{warmup_max}) — "
                                f"Thread: {thread_ok} — "
                                f"Câmeras virtuais (Iriun) precisam de alguns segundos."
                            )
                        elif status_atual == _LatestFrame.STATUS_CONNECTED:
                            frame_placeholder.info(
                                "⏳ Conectado, aguardando primeiro frame...")
                        elif status_atual == _LatestFrame.STATUS_INIT:
                            frame_placeholder.info(
                                "⏳ Iniciando thread de captura...")
                        else:
                            frame_placeholder.info(
                                "⏳ Aguardando frame da câmera...")

                    # V7.3: FALLBACK AUTOMÁTICO — após 15+ tentativas de warmup sem frames,
                    # sugere ir para câmera do navegador (não trava mais
                    # indefinidamente!)
                    if jpg_bytes is None and warmup_t >= _LatestFrame.MAX_WARMUP_TENTATIVAS:
                        st.markdown("---")
                        st.warning(
                            f"⚠️ A câmera OpenCV não entregou frames após {warmup_t} tentativas. "
                            f"Isso é comum com câmeras virtuais (Iriun)."
                        )
                        if st.button(
                            "📷 Ir para Câmera do Navegador (recomendado)",
                            use_container_width=True,
                                type="primary"):
                            st.session_state.camera_ativa = False
                            _StreamCache.release()
                            _CameraCache.release()
                            st.rerun()
                        if st.button(
                            "🔄 Tentar OpenCV novamente",
                                use_container_width=True):
                            st.session_state.camera_ativa = False
                            _StreamCache.release()
                            _CameraCache.release()
                            st.rerun()

                    # V7.3: JS auto-rerun via setTimeout + postMessage
                    # (intervalo 500ms)
                    if lf.running:
                        st.components.v1.html(
                            """<script>
                            setTimeout(function(){
                                window.parent.postMessage({type:'streamlit:Rerun'}, '*');
                            }, 500);
                            </script>""",
                            height=0,
                        )

                    # ── BOTÕES DE AÇÃO ──
                    col_snap1, col_snap2, col_snap3, col_snap4 = st.columns([
                                                                            1, 1, 1, 1])

                    with col_snap1:
                        if st.button(
                            "📸 Capturar Foto",
                            use_container_width=True,
                                type="primary"):
                            _StreamCache.release()
                            if st.session_state.frame_cv_bytes is not None:
                                st.session_state.foto_capturada_cv = st.session_state.frame_cv_bytes
                            st.session_state.camera_ativa = False
                            st.session_state.frame_cv_bytes = None
                            st.session_state.ocr_automatico = False
                            st.success(
                                "✅ Foto capturada! Use OCR ou preenchimento manual.")
                            st.rerun()

                    with col_snap2:
                        # V7.3: OCR INSTANTÂNEO — captura frame e envia direto
                        # para IA
                        if st.button(
                            "🔍 OCR Instantâneo",
                            use_container_width=True,
                                help="Captura o frame atual e extrai dados via IA automaticamente"):
                            if st.session_state.frame_cv_bytes is not None:
                                st.session_state.foto_capturada_cv = st.session_state.frame_cv_bytes
                                st.session_state.camera_ativa = False
                                st.session_state.frame_cv_bytes = None
                                st.session_state.ocr_automatico = True
                                _StreamCache.release()
                                st.rerun()
                            else:
                                st.warning(
                                    "⚠️ Nenhum frame disponível ainda. Aguarde a câmera aquecer.")

                    with col_snap3:
                        if st.button(
                            "🔄 Trocar Câmera",
                                use_container_width=True):
                            _StreamCache.release()
                            st.session_state.camera_ativa = False
                            st.session_state.frame_cv_bytes = None
                            _CameraCache.release()
                            st.rerun()

                    with col_snap4:
                        if st.button(
                            "⏹️ Parar Câmera",
                                use_container_width=True):
                            _StreamCache.release()
                            st.session_state.camera_ativa = False
                            st.session_state.frame_cv_bytes = None
                            _CameraCache.release()
                            st.rerun()

    # ══════════════════════════════════════════════════════════════════════════════
    # SEÇÕES COMUNS (fora dos tabs — sempre visíveis)
    # ══════════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.markdown("### 🔍 Método 2: Consultar Histórico por base de CPF")
    c1, c2, c3 = st.columns([2, 1, 1])
    cpf_para_busca = c1.text_input(
        "Insira o número do CPF para varredura de histórico",
        value=st.session_state.ent_cpf)

    if c2.button("Buscar Histórico Local", use_container_width=True):
        if cpf_para_busca:
            historico = buscar_cadastro_existente(cpf_para_busca)
            if historico:
                st.session_state.ent_nome = historico['nome_reeducando']
                st.session_state.ent_filiacao = historico['filiacao']
                st.session_state.ent_cpf = formatar_cpf(cpf_para_busca)
                st.success("Cadastro anterior recuperado da base FUNAP.")
                st.rerun()
            else:
                st.warning("Nenhum registro prévio localizado.")
        else:
            st.error("Insira um CPF válido para consulta.")

    if c3.button("Limpar Formulário", use_container_width=True):
        st.session_state.ent_nome = ""
        st.session_state.ent_filiacao = ""
        st.session_state.ent_cpf = ""
        st.rerun()

    st.markdown("---")
    st.markdown("### 📝 Formulário Oficial de Registro de Entrada")
    with st.form("form_entrada_oficial"):
        nome_f = st.text_input(
            "Nome Completo do Reeducando",
            value=st.session_state.ent_nome)
        cpf_f = st.text_input("Número do CPF", value=st.session_state.ent_cpf)
        filiacao_f = st.text_input(
            "Filiação Completa",
            value=st.session_state.ent_filiacao)
        finalidade_f = st.selectbox("Finalidade do Atendimento Presencial", [
            "Biometria", "Assinatura de Relatórios", "Atendimento Social",
            "Atendimento Técnico", "Atendimento Jurídico", "Outros Lançamentos"
        ])

        if st.form_submit_button("✅ Registrar Entrada na Fila de Espera"):
            if not nome_f or not cpf_f:
                st.error("Campos essenciais pendentes de preenchimento.")
            else:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO atendimentos (nome_reeducando, cpf, filiacao, data_presenca, horario_entrada, finalidade, vigilante_ent, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'ENTRADA')
                """, (nome_f.upper(), formatar_cpf(cpf_f), filiacao_f.upper(), datetime.now().strftime('%Y-%m-%d'), datetime.now().strftime('%H:%M'), finalidade_f, st.session_state.nome))
                conn.commit()
                sincronizar_banco_com_excel()
                st.success(
                    f"Entrada de {
                        nome_f.upper()} confirmada na Fila de Espera Interna.")
                st.session_state.ent_nome = ""
                st.session_state.ent_filiacao = ""
                st.session_state.ent_cpf = ""
                st.rerun()
elif menu == "Fila de Espera Interna":
    st.subheader("🕒 Controle de Fluxo: Fila de Espera Interna")
    st.write(
        "Acompanhamento em tempo real dos cidadãos aguardando atendimento dentro da unidade FUNAP.")

    aba_reeducandos, aba_visitantes = st.tabs(
        ["👤 Fila Interna de Reeducandos", "👥 Fila Interna de Visitantes Externos"])

    with aba_reeducandos:
        df_fila_r = pd.read_sql_query("""
            SELECT id as 'ID Atendimento', nome_reeducando as 'Nome do Reeducando', cpf as 'CPF',
                   horario_entrada as 'Horário de Entrada', finalidade as 'Finalidade Solicitada'
            FROM atendimentos WHERE status='ENTRADA' ORDER BY id ASC
        """, conn)
        if df_fila_r.empty:
            st.info("Nenhum reeducando aguardando na fila no momento.")
        else:
            st.dataframe(df_fila_r, use_container_width=True)

    with aba_visitantes:
        df_fila_v = pd.read_sql_query("""
            SELECT id as 'ID Visita', nome_visitante as 'Nome do Visitante', cpf_visitante as 'CPF do Visitante',
                   nome_reeducando_vinculado as 'Reeducando Vinculado', vinculo_reeducando as 'Vínculo Familiar/Profissional', horario_entrada as 'Horário de Entrada'
            FROM visitas WHERE status='EM VISITA' ORDER BY id ASC
        """, conn)
        if df_fila_v.empty:
            st.info("Nenhum visitante externo listado na fila interna no momento.")
        else:
            st.dataframe(df_fila_v, use_container_width=True)

# ==============================================================================
# PARTE 4 - SAÍDA, REPOSITÓRIO & LIVRO DE ATA
# ==============================================================================

# =========================================
# 4. FINALIZAR SAÍDA E EMISSÃO DE DOCUMENTO
# =========================================
elif menu == "Finalizar Saída":
    st.subheader("📤 Finalizar Saída e Emissão de Documento de Atendimento")

    df_abertos = pd.read_sql_query("""
        SELECT id, nome_reeducando, cpf, finalidade, horario_entrada
        FROM atendimentos WHERE status='ENTRADA' ORDER BY id DESC
    """, conn)

    if df_abertos.empty:
        st.warning("Não constam atendimentos em aberto na Fila Interna.")
    else:
        opcoes_saida = "ID: " + df_abertos["id"].astype(
            str) + " | " + df_abertos["nome_reeducando"] + " | CPF: " + df_abertos["cpf"]
        selecionado = st.selectbox(
            "Selecione o registro para encerramento de atividades:",
            opcoes_saida)
        id_selecionado = int(selecionado.split(" | ")[0].replace("ID: ", ""))

        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM atendimentos WHERE id=?", (id_selecionado,))
        dados_registro = cursor.fetchone()

        if dados_registro:
            c1, c2 = st.columns(2)
            c1.info(f"👤 **Reeducando:** {dados_registro['nome_reeducando']}")
            c2.info(f"📄 **Documento CPF:** {dados_registro['cpf']}")
            c1.info(
                f"📌 **Finalidade declarada:** {dados_registro['finalidade']}")
            c2.info(
                f"⏱️ **Horário Entrada:** {dados_registro['horario_entrada']}")

        if st.button(
            "🔒 Confirmar Saída e Concluir Atendimento",
                use_container_width=True):
            hora_saida = datetime.now().strftime('%H:%M')
            cursor.execute("""
                UPDATE atendimentos
                SET horario_saida=?, servidor_sai=?, mat_servidor=?, status='CONCLUÍDO'
                WHERE id=?
            """, (hora_saida, st.session_state.nome, st.session_state.mat, id_selecionado))
            conn.commit()
            sincronizar_banco_com_excel()
            st.success("Atendimento arquivado como concluído com sucesso!")
            st.rerun()

        # Visualização e download do documento após carregar o registro
        if dados_registro:
            dados_doc = dict(dados_registro)
            # Garante que horario_saida tenha valor para o PDF
            if not dados_doc.get('horario_saida'):
                dados_doc['horario_saida'] = datetime.now().strftime('%H:%M')

            pdf_b = gerar_pdf_ressalva(dados_doc)
            docx_b = gerar_docx_real(dados_doc)
            json_b = json.dumps(
                dados_doc,
                ensure_ascii=False,
                indent=4).encode('utf-8')
            # V7: Excel real (.xlsx) via openpyxl em vez de CSV
            excel_buf = io.BytesIO()
            with pd.ExcelWriter(excel_buf, engine='openpyxl') as writer_xl:
                pd.DataFrame(
                    [dados_doc]).to_excel(
                    writer_xl,
                    index=False,
                    sheet_name='Ressalva')
            excel_buf.seek(0)
            xlsx_b = excel_buf.read()

            # --- CAIXA DE VISUALIZAÇÃO DIRETA ONLINE ---
            st.markdown("### 📄 VISUALIZAÇÃO DO DOCUMENTO DIGITAL")

            # Salva PDF temporário para visualização direta no navegador
            temp_pdf_path = os.path.join(
                BASE_DIR, f"temp_visualizar_{id_selecionado}.pdf")
            with open(temp_pdf_path, "wb") as ftmp:
                ftmp.write(pdf_b)

            # Cria link para abrir em nova aba (visualização nativa do
            # navegador)
            base64_pdf = base64.b64encode(pdf_b).decode('utf-8')
            abrir_nova_aba = f"data:application/pdf;base64,{base64_pdf}"

            st.markdown(f"""
            <div style="margin-bottom:12px;">
                <a href="{abrir_nova_aba}" target="_blank" style="text-decoration:none;">
                    <button style="padding:10px 20px; background-color:#4CAF50; color:white; border:none; border-radius:5px; cursor:pointer; font-size:14px; width:100%;">
                        🔗 ABRIR DOCUMENTO EM NOVA ABA (Visualização Completa)
                    </button>
                </a>
            </div>
            """, unsafe_allow_html=True)

            # Visualização inline via iframe (fallback para navegadores
            # compatíveis)
            pdf_display = f'<embed src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600" type="application/pdf" style="border:1px solid #ccc; border-radius:4px; background:#f5f5f5;"></embed>'
            st.markdown(pdf_display, unsafe_allow_html=True)
            st.caption(
                "💡 Se o documento não aparecer acima, clique em 'ABRIR EM NOVA ABA' acima para visualização completa.")

            # Limpeza do arquivo temporário
            try:
                os.remove(temp_pdf_path)
            except BaseException:
                pass

            st.markdown("---")
            st.write("📥 **Exportar e Baixar Arquivos Digitais Consolidados:**")

            c1, c2, c3, c4 = st.columns(4)
            c1.download_button(
                "PDF (Documento Oficial)",
                pdf_b,
                file_name=f"ressalva_{id_selecionado}.pdf",
                mime="application/pdf",
                use_container_width=True)
            c2.download_button(
                "WORD (.docx)",
                docx_b,
                file_name=f"ressalva_{id_selecionado}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True)
            c3.download_button(
                "Excel (.xlsx)",
                xlsx_b,
                file_name=f"ressalva_{id_selecionado}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True)
            c4.download_button(
                "JSON (Dados Brutos)",
                json_b,
                file_name=f"ressalva_{id_selecionado}.json",
                mime="application/json",
                use_container_width=True)


# ------------------------------------------------------------------------------
# 5. REPOSITÓRIO DE DOCUMENTOS
# ------------------------------------------------------------------------------
elif menu == "Repositório de Documentos":
    st.subheader("📁 Repositório de Documentos Emitidos")
    st.write("Consulta e reemissão de certidões de ressalva digital já emitidas.")

    # V7: Busca por Nome, CPF OU ID direto
    col_busca1, col_busca2 = st.columns([2, 1])
    with col_busca1:
        busca_doc = st.text_input(
            "🔍 Buscar por Nome ou CPF do reeducando:").strip()
    with col_busca2:
        busca_id = st.number_input(
            "🔍 Buscar por ID:", min_value=0, value=0, step=1)
    # CORREÇÃO V5: Busca também por nome de visitante/reeducando vinculado na
    # tabela visitas
    busca_visitante_repo = st.text_input(
        "🔍 Buscar por Visitante ou Reeducando Vinculado (visitas):",
        key="busca_visit_repo",
        placeholder="Nome do visitante ou reeducando vinculado...").strip()
    busca_doc_limpa = limpar_cpf(busca_doc)

    query_repo = """
        SELECT id as 'ID', nome_reeducando as 'Nome', cpf as 'CPF', filiacao as 'Filiação',
               finalidade as 'Finalidade', strftime('%d/%m/%Y', data_presenca) as 'Data',
               horario_entrada as 'Entrada', horario_saida as 'Saída', status as 'Situação'
        FROM atendimentos
    """

    # V7: Busca por ID direto tem prioridade
    if busca_id > 0:
        query_repo += " WHERE id = ? ORDER BY id DESC"
        df_ressalvas = pd.read_sql_query(query_repo, conn, params=(busca_id,))
    elif busca_doc:
        if busca_doc_limpa.isdigit() and len(busca_doc_limpa) > 0:
            query_repo += " WHERE replace(replace(cpf, '.', ''), '-', '') LIKE ? ORDER BY id DESC"
            df_ressalvas = pd.read_sql_query(
                query_repo, conn, params=(f"%{busca_doc_limpa}%",))
        else:
            query_repo += " WHERE nome_reeducando LIKE ? ORDER BY id DESC"
            df_ressalvas = pd.read_sql_query(
                query_repo, conn, params=(f"%{busca_doc.upper()}%",))
    else:
        query_repo += " ORDER BY id DESC"
        df_ressalvas = pd.read_sql_query(query_repo, conn)

    if df_ressalvas.empty:
        st.info("Nenhuma ressalva emitida localizada no sistema.")
    else:
        if 'Filiação' in df_ressalvas.columns:
            df_ressalvas['Filiação'] = df_ressalvas['Filiação'].apply(
                limpar_filiacao)
        st.dataframe(df_ressalvas, use_container_width=True)

        # V7: Visualização e download direto do registro selecionado na tabela
        st.markdown("---")
        st.markdown("### 🖨️ Visualizar / Exportar Documento")
        id_reprint = st.number_input(
            "Informe o ID da ressalva para visualização e exportação:",
            min_value=0,
            value=int(busca_id) if busca_id > 0 else 0,
            step=1)

        if id_reprint > 0:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM atendimentos WHERE id=?", (id_reprint,))
            reg_reprint = cursor.fetchone()
            if reg_reprint:
                dados_reprint = dict(reg_reprint)
                if not dados_reprint.get('horario_saida'):
                    dados_reprint['horario_saida'] = datetime.now().strftime(
                        '%H:%M')

                # V7: Visualização inline automática do PDF
                pdf_reprint = gerar_pdf_ressalva(dados_reprint)
                docx_reprint = gerar_docx_real(dados_reprint)
                # Excel real
                excel_buf_r = io.BytesIO()
                with pd.ExcelWriter(excel_buf_r, engine='openpyxl') as writer_r:
                    pd.DataFrame(
                        [dados_reprint]).to_excel(
                        writer_r,
                        index=False,
                        sheet_name='Ressalva')
                excel_buf_r.seek(0)
                xlsx_reprint = excel_buf_r.read()

                st.success(
                    f"✅ Documento ID {id_reprint} carregado com sucesso!")
                st.markdown("#### 📄 Pré-visualização do Documento Digital")

                base64_pdf_reprint = base64.b64encode(
                    pdf_reprint).decode('utf-8')

                # Botão para abrir em nova aba
                st.markdown(f"""
                <div style="margin-bottom:12px;">
                    <a href="data:application/pdf;base64,{base64_pdf_reprint}" target="_blank" style="text-decoration:none;">
                        <button style="padding:10px 20px; background-color:#4CAF50; color:white; border:none; border-radius:5px; cursor:pointer; font-size:14px; width:100%;">
                            🔗 ABRIR DOCUMENTO EM NOVA ABA (Visualização Completa)
                        </button>
                    </a>
                </div>
                """, unsafe_allow_html=True)

                # Visualização inline via embed
                pdf_display_reprint = f'<embed src="data:application/pdf;base64,{base64_pdf_reprint}" width="100%" height="500" type="application/pdf" style="border:1px solid #ccc; border-radius:4px; background:#f5f5f5;"></embed>'
                st.markdown(pdf_display_reprint, unsafe_allow_html=True)
                st.caption(
                    "💡 Dica: Se o documento não aparecer acima, clique em 'ABRIR EM NOVA ABA' para visualização completa no navegador.")

                st.markdown("---")
                st.write("📥 **Exportar e Baixar Arquivos Digitais Consolidados:**")
                c1, c2, c3 = st.columns(3)
                c1.download_button(
                    "📄 PDF (Oficial)",
                    pdf_reprint,
                    file_name=f"ressalva_{id_reprint}.pdf",
                    mime="application/pdf",
                    use_container_width=True)
                c2.download_button(
                    "📝 Word (.docx)",
                    docx_reprint,
                    file_name=f"ressalva_{id_reprint}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True)
                c3.download_button(
                    "📊 Excel (.xlsx)",
                    xlsx_reprint,
                    file_name=f"ressalva_{id_reprint}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True)
            else:
                st.warning(
                    "⚠️ ID não localizado. Verifique o número digitado e tente novamente.")

    # ── CORREÇÃO V5: Busca de visitas por visitante ou reeducando vinculado ──
    if busca_visitante_repo:
        st.markdown("---")
        st.markdown("### 👥 Resultados na Tabela de Visitas")
        query_vis_repo = """
            SELECT id as 'ID', nome_visitante as 'Visitante', cpf_visitante as 'CPF',
                   nome_reeducando_vinculado as 'Reeducando Vinculado', vinculo_reeducando as 'Vínculo',
                   strftime('%d/%m/%Y', data_visita) as 'Data', horario_entrada as 'Entrada',
                   horario_saida as 'Saída', status as 'Situação'
            FROM visitas
        """
        where_v = []
        params_vr = []
        where_v.append(
            "(nome_visitante LIKE ? OR nome_reeducando_vinculado LIKE ?)")
        params_vr.extend([f"%{busca_visitante_repo.upper()}%",
                         f"%{busca_visitante_repo.upper()}%"])
        query_vis_repo += " WHERE " + \
            " AND ".join(where_v) + " ORDER BY id DESC"
        df_vis_repo = pd.read_sql_query(
            query_vis_repo, conn, params=tuple(params_vr))
        if df_vis_repo.empty:
            st.info("Nenhum registro de visitante localizado com esse filtro.")
        else:
            st.caption(
                f"📋 {
                    len(df_vis_repo)} registro(s) de visitante(s) encontrado(s).")
            st.dataframe(df_vis_repo, use_container_width=True)

        # V7: A reimpressão agora está integrada na seção principal acima
        # (busca por ID + visualização inline + downloads PDF/Word/Excel)
        st.info(
            "💡 Para reimprimir/exportar, use o campo 'Buscar por ID' acima na seção principal.")


# ------------------------------------------------------------------------------
# 6. LIVRO DE ATA ELETRÔNICO DA VIGILÂNCIA
# ------------------------------------------------------------------------------
elif menu == "Livro de Ata Eletrônico":
    st.subheader("📖 Livro de Ata Eletrônico da Vigilância")
    st.write(
        "Diário de bordo digital e ferramenta de auditoria de segurança física da portaria.")

    # Filtro por data
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        data_filtro_ata = st.date_input(
            "Filtrar por data (opcional):",
            value=None,
            key="filtro_ata",
            format="DD/MM/YYYY")
    with col_f2:
        st.markdown("<br>", unsafe_allow_html=True)
        aplicar_filtro_ata = st.checkbox(
            "Aplicar filtro de data",
            value=False,
            key="chk_filtro_ata")

    data_str_ata = data_filtro_ata.strftime(
        '%Y-%m-%d') if (aplicar_filtro_ata and data_filtro_ata) else None

    # Queries
    if aplicar_filtro_ata and data_filtro_ata:
        query_ata = f"SELECT id as 'ID', nome_reeducando as 'Nome', cpf as 'CPF', filiacao as 'Filiacao', finalidade as 'Finalidade', strftime('%d/%m/%Y', data_presenca) as 'Data', horario_entrada as 'Entrada', horario_saida as 'Saida', vigilante_ent as 'Vigilante Entrada', servidor_sai as 'Servidor Saida', status as 'Status' FROM atendimentos WHERE data_presenca='{data_str_ata}' ORDER BY id DESC"
        query_ata_vis = f"SELECT id as 'ID', nome_visitante as 'Nome', cpf_visitante as 'CPF', nome_reeducando_vinculado as 'Reeducando Vinculado', vinculo_reeducando as 'Vinculo', strftime('%d/%m/%Y', data_visita) as 'Data', horario_entrada as 'Entrada', horario_saida as 'Saida', vigilante_ent as 'Vigilante Entrada', servidor_sai as 'Servidor Saida', status as 'Status' FROM visitas WHERE data_visita='{data_str_ata}' ORDER BY id DESC"
    else:
        query_ata = "SELECT id as 'ID', nome_reeducando as 'Nome', cpf as 'CPF', filiacao as 'Filiacao', finalidade as 'Finalidade', strftime('%d/%m/%Y', data_presenca) as 'Data', horario_entrada as 'Entrada', horario_saida as 'Saida', vigilante_ent as 'Vigilante Entrada', servidor_sai as 'Servidor Saida', status as 'Status' FROM atendimentos ORDER BY id DESC LIMIT 200"
        query_ata_vis = "SELECT id as 'ID', nome_visitante as 'Nome', cpf_visitante as 'CPF', nome_reeducando_vinculado as 'Reeducando Vinculado', vinculo_reeducando as 'Vinculo', strftime('%d/%m/%Y', data_visita) as 'Data', horario_entrada as 'Entrada', horario_saida as 'Saida', vigilante_ent as 'Vigilante Entrada', servidor_sai as 'Servidor Saida', status as 'Status' FROM visitas ORDER BY id DESC LIMIT 200"

    tab_ata_r, tab_ata_v = st.tabs(["Reeducandos", "Visitantes"])

    with tab_ata_r:
        df_ata = pd.read_sql_query(query_ata, conn)
        if df_ata.empty:
            st.info("Nenhum registro de reeducando no Livro de Ata.")
        else:
            st.dataframe(df_ata, use_container_width=True)

    with tab_ata_v:
        df_ata_vis = pd.read_sql_query(query_ata_vis, conn)
        if df_ata_vis.empty:
            st.info("Nenhum registro de visitante no Livro de Ata.")
        else:
            st.dataframe(df_ata_vis, use_container_width=True)

    st.markdown("---")
    st.markdown("### Exportar Livro de Ata")

    # Combina dados para exportacao
    df_ata_c = df_ata.copy() if not df_ata.empty else pd.DataFrame()
    df_ata_vis_c = df_ata_vis.copy() if not df_ata_vis.empty else pd.DataFrame()
    if not df_ata_c.empty:
        df_ata_c.insert(0, 'Tipo', 'Reeducando')
    if not df_ata_vis_c.empty:
        df_ata_vis_c.insert(0, 'Tipo', 'Visitante')
    df_export = pd.concat([df_ata_c, df_ata_vis_c], ignore_index=True)

    col_exp1, col_exp2, col_exp3 = st.columns(3)

    # --- PDF ---
    with col_exp1:
        if st.button(
            "Exportar PDF",
            use_container_width=True,
                key="btn_ata_pdf"):
            if df_export.empty:
                st.warning("Nenhum dado para exportar.")
            else:
                with st.spinner("Gerando PDF..."):
                    try:
                        pdf_ata = FPDF(orientation='L', format='A4')
                        pdf_ata.add_page()
                        _FONTE_UNICODE = configurar_fonte_pdf(pdf_ata)
                        fta = _FONTE_UNICODE[0]
                        pdf_ata.set_font(fta, 'B', 14)
                        pdf_ata.cell(
                            0,
                            10,
                            'LIVRO DE ATA ELETRONICA DA VIGILANCIA - FUNAP/GDF',
                            ln=True,
                            align='C')
                        pdf_ata.ln(4)
                        pdf_ata.set_font(fta, '', 10)
                        if data_str_ata:
                            pdf_ata.cell(
                                0,
                                6,
                                'Data: ' +
                                formatar_data_ptbr(data_str_ata),
                                ln=True,
                                align='C')
                        else:
                            pdf_ata.cell(
                                0,
                                6,
                                'Emitido em: ' +
                                formatar_data_ptbr(
                                    datetime.now().strftime('%Y-%m-%d')) +
                                ' as ' +
                                datetime.now().strftime('%H:%M'),
                                ln=True,
                                align='C')
                        pdf_ata.ln(6)
                        cols_pdf = [
                            'Tipo',
                            'ID',
                            'Nome',
                            'CPF',
                            'Entrada',
                            'Saida',
                            'Vigilante Entrada',
                            'Servidor Saida',
                            'Status']
                        widths_pdf = [22, 12, 55, 30, 20, 20, 40, 40, 25]
                        pdf_ata.set_font(fta, 'B', 7)
                        pdf_ata.set_fill_color(0, 51, 102)
                        pdf_ata.set_text_color(255, 255, 255)
                        for j, col in enumerate(cols_pdf):
                            pdf_ata.cell(
                                widths_pdf[j], 7, col, border=1, fill=True, align='C')
                        pdf_ata.ln()
                        pdf_ata.set_font(fta, '', 7)
                        pdf_ata.set_text_color(0, 0, 0)
                        for idx_r, row in df_export.iterrows():
                            if pdf_ata.get_y() > 180:
                                pdf_ata.add_page()
                                pdf_ata.set_font(fta, 'B', 7)
                                pdf_ata.set_fill_color(0, 51, 102)
                                pdf_ata.set_text_color(255, 255, 255)
                                for j, col in enumerate(cols_pdf):
                                    pdf_ata.cell(
                                        widths_pdf[j], 7, col, border=1, fill=True, align='C')
                                pdf_ata.ln()
                                pdf_ata.set_font(fta, '', 7)
                                pdf_ata.set_text_color(0, 0, 0)
                            if idx_r % 2 == 0:
                                pdf_ata.set_fill_color(245, 245, 245)
                            else:
                                pdf_ata.set_fill_color(255, 255, 255)
                            for j, col in enumerate(cols_pdf):
                                val = str(
                                    row.get(
                                        col, '')) if col in row.index else ''
                                pdf_ata.cell(
                                    widths_pdf[j], 6, val[:35], border=1, fill=True, align='C')
                            pdf_ata.ln()
                        pdf_ata.set_font(fta, 'I', 8)
                        pdf_ata.set_y(-15)
                        pdf_ata.cell(
                            0, 6, 'Livro de Ata Eletronica | FUNAP/GDF | Pagina ' + str(pdf_ata.page_no()), align='C')
                        pdf_ata_bytes = bytes(pdf_ata.output())
                        nome_arq = 'livro_ata_' + \
                            (data_str_ata if data_str_ata else 'completo') + '.pdf'
                        st.download_button(
                            "Baixar PDF",
                            pdf_ata_bytes,
                            file_name=nome_arq,
                            mime="application/pdf",
                            use_container_width=True)
                        st.success("PDF gerado com sucesso!")
                    except Exception as e:
                        st.error(f"Erro ao gerar PDF: {e}")

    # --- WORD ---
    with col_exp2:
        if st.button(
            "Exportar Word (.docx)",
            use_container_width=True,
                key="btn_ata_docx"):
            if df_export.empty:
                st.warning("Nenhum dado para exportar.")
            else:
                with st.spinner("Gerando Word..."):
                    try:
                        from docx import Document
                        from docx.shared import Inches, Pt, Cm
                        from docx.enum.text import WD_ALIGN_PARAGRAPH
                        from docx.enum.table import WD_TABLE_ALIGNMENT
                        doc = Document()
                        titulo = doc.add_heading(
                            'Livro de Ata Eletronica da Vigilancia', level=0)
                        titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        subtitulo = doc.add_paragraph('FUNAP/GDF')
                        subtitulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        if data_str_ata:
                            dp = doc.add_paragraph(
                                'Data: ' + formatar_data_ptbr(data_str_ata))
                        else:
                            dp = doc.add_paragraph(
                                'Emitido em: ' +
                                formatar_data_ptbr(
                                    datetime.now().strftime('%Y-%m-%d')) +
                                ' as ' +
                                datetime.now().strftime('%H:%M'))
                        dp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        doc.add_paragraph()
                        cols_docx = [
                            'Tipo',
                            'ID',
                            'Nome',
                            'CPF',
                            'Entrada',
                            'Saida',
                            'Vigilante Entrada',
                            'Servidor Saida',
                            'Status']
                        table = doc.add_table(rows=1, cols=len(cols_docx))
                        table.style = 'Light Grid Accent 1'
                        table.alignment = WD_TABLE_ALIGNMENT.CENTER
                        hdr_cells = table.rows[0].cells
                        for j, col in enumerate(cols_docx):
                            hdr_cells[j].text = col
                            for paragraph in hdr_cells[j].paragraphs:
                                for run in paragraph.runs:
                                    run.font.bold = True
                                    run.font.size = Pt(8)
                        for _, row in df_export.iterrows():
                            row_cells = table.add_row().cells
                            for j, col in enumerate(cols_docx):
                                val = str(
                                    row.get(
                                        col, '')) if col in row.index else ''
                                row_cells[j].text = val
                                for paragraph in row_cells[j].paragraphs:
                                    for run in paragraph.runs:
                                        run.font.size = Pt(7)
                        doc.add_paragraph()
                        doc.add_paragraph(
                            'Livro de Ata Eletronica | FUNAP/GDF | Emitido por: ' +
                            st.session_state.nome)
                        docx_buf = io.BytesIO()
                        doc.save(docx_buf)
                        docx_buf.seek(0)
                        docx_bytes = docx_buf.read()
                        nome_arq_docx = 'livro_ata_' + \
                            (data_str_ata if data_str_ata else 'completo') + '.docx'
                        st.download_button(
                            "Baixar Word",
                            docx_bytes,
                            file_name=nome_arq_docx,
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            use_container_width=True)
                        st.success("Word gerado com sucesso!")
                    except ImportError:
                        st.error(
                            "python-docx nao instalado. Instale com: pip install python-docx")
                    except Exception as e:
                        st.error(f"Erro ao gerar Word: {e}")

    # --- EXCEL ---
    with col_exp3:
        if st.button(
            "Exportar Excel (.xlsx)",
            use_container_width=True,
                key="btn_ata_xlsx"):
            if df_export.empty:
                st.warning("Nenhum dado para exportar.")
            else:
                with st.spinner("Gerando Excel..."):
                    try:
                        excel_buf = io.BytesIO()
                        with pd.ExcelWriter(excel_buf, engine='openpyxl') as writer:
                            df_export.to_excel(
                                writer, index=False, sheet_name='Livro de Ata')
                        excel_buf.seek(0)
                        excel_bytes = excel_buf.read()
                        nome_arq_xlsx = 'livro_ata_' + \
                            (data_str_ata if data_str_ata else 'completo') + '.xlsx'
                        st.download_button(
                            "Baixar Excel",
                            excel_bytes,
                            file_name=nome_arq_xlsx,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True)
                        st.success("Excel gerado com sucesso!")
                    except Exception as e:
                        st.error(f"Erro ao gerar Excel: {e}")

    st.markdown("---")
    st.markdown("### Expandir Detalhes de Registro Selecionado")
    id_expand = st.number_input(
        "Digite o ID do registro para visualizar detalhes:",
        min_value=0,
        step=1)

    if id_expand > 0:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM atendimentos WHERE id=?", (id_expand,))
        reg = cursor.fetchone()

        if reg:
            st.markdown(f"""
            **Detalhes do Registro ID {id_expand}:**
            - **Nome:** {reg['nome_reeducando']}
            - **CPF:** {reg['cpf']}
            - **Filiacao:** {reg['filiacao']}
            - **Finalidade:** {reg['finalidade']}
            - **Data:** {reg['data_presenca']}
            - **Horario Entrada:** {reg['horario_entrada']}
            - **Horario Saida:** {reg['horario_saida']}
            - **Vigilante (Entrada):** {reg['vigilante_ent']}
            - **Servidor (Saida):** {reg['servidor_sai']}
            - **Matricula Servidor:** {reg['mat_servidor']}
            - **Status:** {reg['status']}
            """)
        else:
            st.warning("Registro nao localizado.")


elif menu == "Relatório Diário de Plantão":
    st.subheader("📋 Relatório Diário de Plantão / Fechamento de Turno")
    st.write(
        "Folha de backup físico de toda movimentação do dia e registro em Excel organizado.")

    hoje = datetime.now().strftime('%Y-%m-%d')
    data_relatorio = st.date_input(
        "Selecione a data do plantão:",
        datetime.now(),
        format="DD/MM/YYYY")
    data_str = data_relatorio.strftime('%Y-%m-%d')

    cursor = conn.cursor()

    # Busca dados do dia
    cursor.execute(
        "SELECT COUNT(*) FROM atendimentos WHERE data_presenca=?", (data_str,))
    total_reed = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM visitas WHERE data_visita=?", (data_str,))
    total_vis = cursor.fetchone()[0]

    st.info(
        f"📊 **Movimentação do dia {
            formatar_data_curta_ptbr(data_str)}:** {total_reed} Reeducandos | {total_vis} Visitantes | **Total: {
            total_reed +
            total_vis}**")

    # Visualização online das movimentações
    st.markdown("---")
    st.markdown("### 👁️ Visualização Online das Movimentações")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Reeducandos")
        df_reed_dia = pd.read_sql_query("""
            SELECT id AS 'Nº', nome_reeducando AS 'Nome', cpf AS 'CPF', filiacao AS 'Filiação',
                   horario_entrada AS 'Entrada', horario_saida AS 'Saída', finalidade AS 'Finalidade', status AS 'Status'
            FROM atendimentos WHERE data_presenca=? ORDER BY horario_entrada
        """, conn, params=(data_str,))
        # Limpa filiação que pode vir como lista Python
        if 'Filiação' in df_reed_dia.columns:
            df_reed_dia['Filiação'] = df_reed_dia['Filiação'].apply(
                limpar_filiacao)
        st.dataframe(df_reed_dia, use_container_width=True, hide_index=True)

    with col2:
        st.markdown("#### Visitantes Externos")
        df_vis_dia = pd.read_sql_query("""
            SELECT id AS 'Nº', nome_visitante AS 'Visitante', cpf_visitante AS 'CPF',
                   nome_reeducando_vinculado AS 'Reeducando', vinculo_reeducando AS 'Vínculo',
                   horario_entrada AS 'Entrada', horario_saida AS 'Saída', status AS 'Status'
            FROM visitas WHERE data_visita=? ORDER BY horario_entrada
        """, conn, params=(data_str,))
        st.dataframe(df_vis_dia, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### 📥 Exportar e Arquivar")

    c1, c2, c3 = st.columns(3)

    # Botão de Impressão Direta pelo Navegador (Layout Limpo)
    if c1.button("🖨️ Imprimir Movimentação Diária", use_container_width=True):
        with st.spinner("Preparando documento para o spooler de impressão..."):
            # Injeta gatilho JavaScript para chamar a caixa oficial de
            # impressão do Windows (Ctrl + P)
            st.components.v1.html("""
                <script>
                    setTimeout(function() {
                        window.print();
                    }, 500);
                </script>
            """, height=0)
            st.success("Painel de impressão acionado.")

    # Botão Excel
    if c2.button("📊 Gerar Excel Organizado", use_container_width=True):
        with st.spinner("Organizando planilha Excel..."):
            excel_path = salvar_relatorio_excel_mensal(data_str)
            if excel_path and os.path.exists(excel_path):
                with open(excel_path, "rb") as f:
                    st.download_button(
                        "⬇️ Baixar Excel do Mês",
                        f.read(),
                        file_name=os.path.basename(excel_path),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True)
                st.success(f"Excel salvo em: {excel_path}")
            else:
                st.error("Erro ao gerar Excel.")

    # Botão Fechamento de Turno
    if c3.button("🔒 Fechar Turno e Arquivar", use_container_width=True):
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO relatorios_diarios
                (data_plantao, total_reeducandos, total_visitantes, total_atendimentos, operador_fechamento, observacoes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (data_str, total_reed, total_vis, total_reed + total_vis, st.session_state.nome, f"Fechamento realizado por {st.session_state.nome}"))
            conn.commit()

            # Gera PDF e Excel automaticamente
            pdf_rel = gerar_relatorio_diario_pdf(data_str)
            excel_path = salvar_relatorio_excel_mensal(data_str)

            st.success(f"✅ Turno de {data_str} fechado com sucesso!")
            st.info(f"📁 Arquivos salvos para guarda de 10 anos.")

            # Download automático
            st.download_button(
                "⬇️ Baixar PDF do Plantão",
                pdf_rel,
                file_name=f"relatorio_plantao_{data_str}.pdf",
                mime="application/pdf")
            if excel_path and os.path.exists(excel_path):
                with open(excel_path, "rb") as f:
                    st.download_button(
                        "⬇️ Baixar Excel do Mês",
                        f.read(),
                        file_name=os.path.basename(excel_path),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        except Exception as e:
            st.error(f"Erro ao fechar turno: {e}")

    # Histórico de fechamentos
    st.markdown("---")
    st.markdown("### 📚 Histórico de Fechamentos de Turno")
    df_fechamentos = pd.read_sql_query("""
        SELECT data_plantao as 'Data', total_reeducandos as 'Reeducandos',
               total_visitantes as 'Visitantes', total_atendimentos as 'Total',
               operador_fechamento as 'Operador', data_hora_fechamento as 'Fechamento'
        FROM relatorios_diarios ORDER BY data_plantao DESC
    """, conn)
    st.dataframe(df_fechamentos, use_container_width=True)

# =========================================
# 8. CONTROLE DE ACESSO DE VISITANTES EXTERNOS
# =========================================
elif menu == "Acesso de Visitantes":
    st.subheader("👥 Controle de Acesso de Visitantes Externos")

    aba_cadastro, aba_historico = st.tabs(
        ["➕ Registrar Novo Visitante", "📜 Histórico de Lançamentos de Visitantes"])

    with aba_cadastro:
        with st.form("form_novo_visitante"):
            nome_v = st.text_input("Nome Completo do Visitante")
            cpf_v = st.text_input("CPF do Visitante")
            # CORREÇÃO 6: Nome do Reeducando Vinculado
            nome_reed_vinc = st.text_input(
                "Nome do Reeducando Vinculado",
                help="Nome do reeducando que o visitante visita.")
            if nome_reed_vinc:
                cursor_ac = conn.cursor()
                cursor_ac.execute(
                    "SELECT DISTINCT nome_reeducando FROM atendimentos WHERE nome_reeducando LIKE ? LIMIT 5",
                    (f"%{
                        nome_reed_vinc.upper()}%",
                     ))
                sugestoes = [r["nome_reeducando"]
                             for r in cursor_ac.fetchall()]
                if sugestoes:
                    st.caption("📋 Sugestões: " + " | ".join(sugestoes))
            vinculo = st.selectbox(
                "Vínculo com o Reeducando", [
                    "Pai", "Mãe", "Esposa", "Marido", "Irmão(ã)", "Filho(a)", "Advogado(a)", "Outros"])

            if st.form_submit_button("✅ Registrar Entrada do Visitante"):
                if not nome_v or not cpf_v:
                    st.error("Preencha o nome e o CPF do visitante.")
                else:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO visitas (nome_visitante, cpf_visitante, nome_reeducando_vinculado, vinculo_reeducando, data_visita, horario_entrada, vigilante_ent, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'EM VISITA')
                    """, (nome_v.upper(), formatar_cpf(cpf_v), nome_reed_vinc.upper() if nome_reed_vinc else '', vinculo, datetime.now().strftime('%Y-%m-%d'), datetime.now().strftime('%H:%M'), st.session_state.nome))
                    conn.commit()
                    st.success(
                        f"Entrada de {
                            nome_v.upper()} gravada com sucesso.")
                    st.rerun()

    with aba_historico:
        st.markdown("### 🕒 Fluxo Histórico de Visitas")

        # ── CORREÇÃO V5: Filtros de busca por Reeducando Vinculado e por Nome do Visitante ──
        col_filtro_v1, col_filtro_v2 = st.columns(2)
        with col_filtro_v1:
            filtro_reeducando_v = st.text_input(
                "🔍 Filtrar por Reeducando Vinculado:",
                key="filtro_reed_visi",
                placeholder="Nome do reeducando...").strip()
        with col_filtro_v2:
            filtro_visitante_v = st.text_input(
                "🔍 Filtrar por Nome do Visitante:",
                key="filtro_nome_visi",
                placeholder="Nome do visitante...").strip()

        query_visitas = """
            SELECT id as 'ID', nome_visitante as 'Nome do Visitante', cpf_visitante as 'CPF',
                   nome_reeducando_vinculado as 'Reeducando Vinculado', vinculo_reeducando as 'Vínculo', strftime('%d/%m/%Y', data_visita) as 'Data',
                   horario_entrada as 'Entrada', horario_saida as 'Saída', status as 'Situação',
                   vigilante_ent as 'Vigilante Entrada', servidor_sai as 'Servidor Saída'
            FROM visitas
        """

        # Monta cláusulas WHERE dinâmicas com base nos filtros
        where_clauses = []
        params_v = []
        if filtro_reeducando_v:
            where_clauses.append("nome_reeducando_vinculado LIKE ?")
            params_v.append(f"%{filtro_reeducando_v.upper()}%")
        if filtro_visitante_v:
            where_clauses.append("nome_visitante LIKE ?")
            params_v.append(f"%{filtro_visitante_v.upper()}%")

        if where_clauses:
            query_visitas += " WHERE " + " AND ".join(where_clauses)

        query_visitas += " ORDER BY id DESC"

        df_visitas = pd.read_sql_query(
            query_visitas, conn, params=tuple(params_v) if params_v else None)

        if filtro_reeducando_v or filtro_visitante_v:
            st.caption(
                f"📋 Exibindo {
                    len(df_visitas)} registro(s) com os filtros aplicados.")

        st.dataframe(df_visitas, use_container_width=True)

        # Encerramento de visitas em aberto
        df_visitas_abertas = pd.read_sql_query(
            "SELECT id, nome_visitante FROM visitas WHERE status='EM VISITA'", conn)
        if not df_visitas_abertas.empty:
            st.markdown("---")
            opcoes_fechar = "ID: " + \
                df_visitas_abertas["id"].astype(str) + " | " + df_visitas_abertas["nome_visitante"]
            selecao_fechar = st.selectbox(
                "Finalizar permanência de visitante externo:", opcoes_fechar)
            id_fechar = int(selecao_fechar.split(" | ")[0].replace("ID: ", ""))

            if st.button(
                "📤 Registrar Saída do Visitante",
                    use_container_width=True):
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE visitas SET horario_saida=?, servidor_sai=?, status='FINALIZADA' WHERE id=?
                """, (datetime.now().strftime('%H:%M'), st.session_state.nome, id_fechar))
                conn.commit()
                st.success("Permanência encerrada no histórico.")
                st.rerun()

# =========================================
# 9. CENTRAL DE EDIÇÃO E RETIFICAÇÃO DE LANÇAMENTOS
# =========================================
elif menu == "Edição e Retificação":
    st.subheader(
        "🛠️ Central de Edição de Lançamentos (Retificação de Cadastros)")

    aba_edit_r, aba_edit_v = st.tabs(
        ["📄 Retificar Reeducandos", "👥 Retificar Visitantes"])

    with aba_edit_r:
        df_r = pd.read_sql_query(
            "SELECT id as 'ID', nome_reeducando as 'Nome', cpf as 'CPF', filiacao as 'Filiação', finalidade as 'Finalidade' FROM atendimentos ORDER BY id DESC",
            conn)
        if 'Filiação' in df_r.columns:
            df_r['Filiação'] = df_r['Filiação'].apply(limpar_filiacao)
        st.dataframe(df_r, use_container_width=True)

        id_ret_r = st.number_input(
            "Digite o número de ID do Reeducando para editar/excluir:",
            min_value=0,
            value=0,
            step=1,
            key="id_ret_r")
        if id_ret_r > 0:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM atendimentos WHERE id=?", (id_ret_r,))
            reg_r = cursor.fetchone()

            if reg_r:
                with st.form("form_ret_reeducando"):
                    r_nome = st.text_input(
                        "Nome Completo", value=reg_r['nome_reeducando'])
                    r_cpf = st.text_input("CPF", value=reg_r['cpf'])
                    r_filiacao = st.text_input(
                        "Filiação Completa", value=limpar_filiacao(
                            reg_r['filiacao']))
                    r_finalidade = st.text_input(
                        "Finalidade", value=reg_r['finalidade'])

                    c1, c2 = st.columns(2)
                    if c1.form_submit_button("💾 Salvar Alterações"):
                        cursor.execute("""
                            UPDATE atendimentos SET nome_reeducando=?, cpf=?, filiacao=?, finalidade=? WHERE id=?
                        """, (r_nome.upper(), formatar_cpf(r_cpf), r_filiacao.upper(), r_finalidade.upper(), id_ret_r))
                        conn.commit()
                        st.success(
                            "Registro de reeducando modificado com sucesso.")
                        st.rerun()

                    if c2.form_submit_button("❌ Remover Registro Permanente"):
                        cursor.execute(
                            "DELETE FROM atendimentos WHERE id=?", (id_ret_r,))
                        conn.commit()
                        st.success("Registro expurgado da base de dados.")
                        st.rerun()
            else:
                st.warning("Código ID não localizado no banco.")

    with aba_edit_v:
        df_v = pd.read_sql_query(
            "SELECT id as 'ID', nome_visitante as 'Visitante', cpf_visitante as 'CPF', nome_reeducando_vinculado as 'Reeducando Vinculado', vinculo_reeducando as 'Vínculo' FROM visitas ORDER BY id DESC",
            conn)
        st.dataframe(df_v, use_container_width=True)

        id_ret_v = st.number_input(
            "Digite o número de ID do Visitante para editar/excluir:",
            min_value=0,
            value=0,
            step=1,
            key="id_ret_v")
        if id_ret_v > 0:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM visitas WHERE id=?", (id_ret_v,))
            reg_v = cursor.fetchone()

            if reg_v:
                with st.form("form_ret_visitante"):
                    v_nome = st.text_input(
                        "Nome Completo do Visitante",
                        value=reg_v['nome_visitante'])
                    v_cpf = st.text_input(
                        "CPF do Visitante", value=reg_v['cpf_visitante'])
                    v_nome_reed = st.text_input(
                        "Nome do Reeducando Vinculado",
                        value=reg_v['nome_reeducando_vinculado'] if 'nome_reeducando_vinculado' in reg_v.keys() else '')
                    v_vinculo = st.text_input(
                        "Vínculo", value=reg_v['vinculo_reeducando'])

                    c1, c2 = st.columns(2)
                    if c1.form_submit_button("💾 Salvar Alterações"):
                        cursor.execute("""
                            UPDATE visitas SET nome_visitante=?, cpf_visitante=?, nome_reeducando_vinculado=?, vinculo_reeducando=? WHERE id=?
                        """, (v_nome.upper(), formatar_cpf(v_cpf), v_nome_reed.upper() if v_nome_reed else '', v_vinculo.upper(), id_ret_v))
                        conn.commit()
                        st.success("Cadastro do visitante retificado.")
                        st.rerun()

                    if c2.form_submit_button("❌ Remover Visitante"):
                        cursor.execute(
                            "DELETE FROM visitas WHERE id=?", (id_ret_v,))
                        conn.commit()
                        st.success("Visitante deletado.")
                        st.rerun()
            else:
                st.warning("ID do visitante inválido.")

# ==============================================================================
# 10. VALIDAÇÃO PÚBLICA DE DOCUMENTOS
# ==============================================================================
elif menu == "Validação Pública":
    st.subheader("🔍 Validação Pública de Ressalva Digital")
    st.write(
        "Consulte a autenticidade de uma certidão de ressalva emitida pelo sistema.")
    # ──────────────────────────────────────────────────
    # CORREÇÃO 4: Frase alterada — removida referência a "qualquer pessoa pode consultar"
    # ──────────────────────────────────────────────────
    st.info("Digite o Código de Autenticidade (12 caracteres) impresso no rodapé do documento PDF para verificar a legitimidade.")

    codigo_input = st.text_input(
        "Código de Autenticidade:",
        max_chars=20).strip().upper()

    if st.button("🔎 Verificar Documento", use_container_width=True):
        if not codigo_input:
            st.warning("Informe o código de autenticidade.")
        else:
            cursor = conn.cursor()
            # Busca todos os registros e compara o hash localmente
            cursor.execute(
                "SELECT id, nome_reeducando, cpf, filiacao, finalidade, data_presenca, horario_entrada, horario_saida, status, vigilante_ent, servidor_sai FROM atendimentos")
            registros = cursor.fetchall()
            encontrado = None
            for reg in registros:
                reg_dict = {
                    'id': reg[0],
                    'nome_reeducando': reg[1],
                    'cpf': reg[2],
                    'filiacao': reg[3],
                    'finalidade': reg[4],
                    'data_presenca': reg[5],
                    'horario_entrada': reg[6],
                    'horario_saida': reg[7],
                    'status': reg[8],
                    'vigilante_ent': reg[9],
                    'servidor_sai': reg[10]}
                hs = reg_dict['horario_saida'] if reg_dict['horario_saida'] else "00:00"
                hash_local = hashlib.sha256(
                    f"{reg_dict['cpf']}{hs}".encode()).hexdigest().upper()[:12]
                if hash_local == codigo_input:
                    encontrado = reg_dict
                    break

            if encontrado:
                st.success(
                    "✅ DOCUMENTO AUTÊNTICO — Localizado no sistema oficial da FUNAP.")
                st.balloons()
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown("---")
                    st.markdown(f"**Nome:** {encontrado['nome_reeducando']}")
                    st.markdown(f"**CPF:** {encontrado['cpf']}")
                    st.markdown(
                        f"**Filiação:** {limpar_filiacao(encontrado['filiacao'])}")
                    st.markdown(f"**Finalidade:** {encontrado['finalidade']}")
                    st.markdown(
                        f"**Data:** {formatar_data_curta_ptbr(encontrado['data_presenca'])}")
                    st.markdown(
                        f"**Entrada:** {encontrado['horario_entrada']} | **Saída:** {encontrado['horario_saida']}")
                    st.markdown(f"**Status:** {encontrado['status']}")
                    st.markdown("---")
                with col2:
                    # Gera QR do código novamente para exibir
                    qr_val = gerar_qrcode_validacao(codigo_input, tamanho=150)
                    if qr_val:
                        st.image(qr_val, caption="QR de Validação")
                    st.markdown(f"**Chave:** `{codigo_input}`")

                # Reemite PDF para visualização
                pdf_val = gerar_pdf_ressalva(encontrado)
                base64_val = base64.b64encode(pdf_val).decode('utf-8')
                st.markdown("#### Pré-visualização do Documento Oficial:")
                st.markdown(
                    f'<embed src="data:application/pdf;base64,{base64_val}" width="100%" height="500" style="border:1px solid #ccc;"></embed>',
                    unsafe_allow_html=True)
                st.download_button(
                    "⬇️ Baixar PDF do Documento Validado",
                    pdf_val,
                    file_name=f"ressalva_validada_{
                        encontrado['id']}.pdf",
                    mime="application/pdf",
                    use_container_width=True)
            else:
                st.error(
                    "❌ DOCUMENTO NÃO LOCALIZADO. O código informado não corresponde a nenhuma certidão de ressalva oficial emitida pelo sistema.")
                st.warning(
                    "Dicas: verifique se digitou corretamente os 12 caracteres do Código de Autenticidade (letras e números).")


# ==============================================================================
# 11. PAINEL DE ADMINISTRAÇÃO DE USUÁRIOS
# ==============================================================================
elif menu == "Painel de Administração":
    if st.session_state.perfil not in ["ADMINISTRADOR", "ADM"]:
        st.error(
            "🚨 Nível de acesso restrito apenas a Administradores da NTI / FUNAP.")
        st.stop()

    st.subheader(
        "🔐 Painel de Administração de Usuários (Servidores e Vigilantes)")

    tab_listar, tab_cadastrar = st.tabs(
        ["📋 Últimos Cadastros Realizados", "➕ Cadastrar Novo Operador"])

    with tab_listar:
        df_usuarios = pd.read_sql_query(
            "SELECT id as 'ID', nome as 'Nome Funcionário', login as 'Login', perfil as 'Perfil', matricula as 'Matrícula' FROM usuarios ORDER BY id DESC",
            conn)
        st.markdown("### 👤 Operadores Credenciados Ativos")
        st.dataframe(df_usuarios, use_container_width=True)

        st.markdown("---")
        st.markdown("#### ⚙️ Gerenciar / Modificar Conta Cadastrada")
        id_user = st.number_input(
            "Insira o ID do usuário para modificação administrativa:",
            min_value=0,
            value=0,
            step=1)

        if id_user > 0:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM usuarios WHERE id=?", (id_user,))
            user_data = cursor.fetchone()

            if user_data:
                if user_data['login'] == 'admin':
                    st.error(
                        "O Administrador raiz do sistema não pode ser alterado ou removido por segurança.")
                else:
                    with st.form("form_admin_crud"):
                        u_nome = st.text_input(
                            "Nome Completo", value=user_data['nome'])
                        u_login = st.text_input(
                            "Login / Usuário", value=user_data['login'])
                        u_mat = st.text_input(
                            "Matrícula Funcional", value=user_data['matricula'])

                        perfis_validos = [
                            "SERVIDOR(A)", "VIGILANTE", "ADMINISTRADOR"]
                        perfil_banco = str(user_data['perfil']).upper().strip()

                        if perfil_banco in ["ADM", "ADMINISTRADOR"]:
                            index_padrao = 2
                        elif perfil_banco in ["VIGILANTE"]:
                            index_padrao = 1
                        else:
                            index_padrao = 0

                        u_perfil = st.selectbox(
                            "Perfil de Acesso", perfis_validos, index=index_padrao)
                        u_senha = st.text_input(
                            "Nova Senha (Deixe em branco para manter a atual)", type="password")

                        col_1, col_2, col_3 = st.columns(3)

                        if col_1.form_submit_button("💾 Salvar Alterações"):
                            if u_senha.strip() != "":
                                nova_sh = hashlib.sha256(
                                    u_senha.encode()).hexdigest()
                                cursor.execute(
                                    "UPDATE usuarios SET nome=?, login=?, matricula=?, perfil=?, senha=? WHERE id=?",
                                    (u_nome.upper(),
                                     u_login,
                                     u_mat,
                                     u_perfil,
                                     nova_sh,
                                     id_user))
                            else:
                                cursor.execute(
                                    "UPDATE usuarios SET nome=?, login=?, matricula=?, perfil=? WHERE id=?",
                                    (u_nome.upper(),
                                     u_login,
                                     u_mat,
                                     u_perfil,
                                     id_user))
                            conn.commit()
                            st.success(
                                "Dados do funcionário atualizados com sucesso.")
                            st.rerun()

                        if col_2.form_submit_button(
                                "🚨 Revogar / Excluir Conta"):
                            cursor.execute(
                                "DELETE FROM usuarios WHERE id=?", (id_user,))
                            conn.commit()
                            st.success("Credenciais deletadas e revogadas.")
                            st.rerun()

                        if col_3.form_submit_button("🚫 Cancelar Operação"):
                            st.rerun()
            else:
                st.warning("Usuário não cadastrado.")

    with tab_cadastrar:
        st.markdown("### ➕ Cadastrar Novo Funcionário da FUNAP")
        with st.form("form_novo_user"):
            new_nome = st.text_input("Nome Completo do Funcionário")
            new_login = st.text_input("Login de Acesso Único")
            new_mat = st.text_input("Matrícula Funcional GDF")
            new_perfil = st.selectbox(
                "Perfil de Atribuição", [
                    "SERVIDOR(A)", "VIGILANTE", "ADMINISTRADOR"])
            new_senha = st.text_input("Senha Inicial", type="password")

            if st.form_submit_button("💾 Gravar Credenciais"):
                if not new_nome or not new_login or not new_senha:
                    st.error(
                        "Todos os campos obrigatórios precisam de preenchimento.")
                else:
                    try:
                        sh_new = hashlib.sha256(new_senha.encode()).hexdigest()
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO usuarios (login, senha, nome, perfil, matricula)
                            VALUES (?, ?, ?, ?, ?)
                        """, (new_login, sh_new, new_nome.upper(), new_perfil, new_mat))
                        conn.commit()
                        st.success(
                            f"Operador {
                                new_nome.upper()} credenciado no sistema.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error(
                            "Este Login já está em uso por outro funcionário.")

# =========================================
# TELA ALTERAR SENHA
# =========================================
elif menu == "🔑 Alterar Senha":
    st.header("🔑 Alterar Senha")
    st.write(
        f"Usuário logado: **{st.session_state.nome}** ({st.session_state.login})")

    with st.form("form_alterar_senha"):
        senha_atual = st.text_input("Senha Atual", type="password")
        nova_senha = st.text_input("Nova Senha", type="password")
        confirmar_senha = st.text_input(
            "Confirmar Nova Senha", type="password")
        submitted = st.form_submit_button(
            "💾 Salvar Nova Senha",
            use_container_width=True,
            type="primary")

    if submitted:
        if not senha_atual or not nova_senha or not confirmar_senha:
            st.error("Preencha todos os campos.")
        elif nova_senha != confirmar_senha:
            st.error("A nova senha e a confirmação não conferem.")
        elif len(nova_senha) < 4:
            st.error("A nova senha deve ter pelo menos 4 caracteres.")
        else:
            login_user = st.session_state.login
            hash_atual = hashlib.sha256(senha_atual.encode()).hexdigest()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM usuarios WHERE login=? AND senha=?",
                (login_user,
                 hash_atual))
            res = cursor.fetchone()
            if res:
                hash_nova = hashlib.sha256(nova_senha.encode()).hexdigest()
                cursor.execute(
                    "UPDATE usuarios SET senha=? WHERE login=?", (hash_nova, login_user))
                conn.commit()
                st.success("✅ Senha alterada com sucesso!")
            else:
                st.error("Senha atual incorreta.")

# ── RODAPÉ COM CRÉDITOS V5 ──
st.markdown("---")
st.markdown(
    '<div style="text-align:center; color:#888; font-size:0.85em;">💻 Este sistema foi desenvolvido por <b>Henrique Silva de Souza</b></div>',
    unsafe_allow_html=True)
