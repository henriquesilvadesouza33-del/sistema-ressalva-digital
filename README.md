# sistema-ressalva-digital
Sistema para informatização de ressalvas digitais (FUNAP/GDF), utilizando OCR para leitura de documentos e geração de certificados em PDF.

# 🔐 Sistema de Ressalva Digital - FUNAP/GDF

Este sistema foi desenvolvido para modernizar e informatizar o controle de comparecimento e a emissão de ressalvas na **Fundação de Amparo ao Trabalhador Preso (FUNAP)**. O objetivo principal é substituir processos manuais por uma solução digital rápida, segura e eficiente.

## 🚀 Principais Funcionalidades
*   **Scanner Inteligente (OCR):** Integração com Inteligência Artificial (`EasyOCR`) para leitura automática de dados de documentos (RG/CPF) via webcam ou câmera IP.
*   **Emissão de Ressalvas:** Geração instantânea de certificados de comparecimento em formato PDF.
*   **Segurança e Autenticidade:** Cada documento gerado possui um **código de autenticidade (Hash)** único para verificação.
*   **Banco de Dados Integrado:** Armazenamento organizado de atendimentos com consulta rápida por CPF.
*   **Gestão de Acesso:** Sistema de login seguro para vigilantes e servidores.

## 🛠️ Tecnologias Utilizadas
*   **Python 3.x**
*   **Streamlit:** Interface web moderna e responsiva.
*   **SQLite:** Banco de dados local leve e eficiente.
*   **FPDF:** Biblioteca para geração dinâmica de documentos PDF.
*   **EasyOCR:** IA para reconhecimento óptico de caracteres.

## 📦 Como rodar o projeto
1. Clone este repositório ou baixe os arquivos.
2. Certifique-se de ter o Python instalado.
3. Instale as bibliotecas necessárias:
   ```bash
   pip install -r requirements.txt
   ```
4. Execute o comando para iniciar o sistema:
   ```bash
   streamlit run ressalva_digital.py
   ```

---
*Desenvolvido para otimizar os serviços da FUNAP/GDF.*
