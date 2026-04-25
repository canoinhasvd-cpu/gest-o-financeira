import streamlit as st
import psycopg2
import xml.etree.ElementTree as ET
import pandas as pd
import re
from datetime import date
import time

st.set_page_config(page_title="Financeiro Pro", layout="wide")

LOJAS = {
    "79503280000100": "Matriz", "14995048000191": "VD", "79503280000291": "Papanduva", 
    "79503280000372": "Via", "79503280000453": "Queluz", "79503280000615": "Bruda"
}

def conectar_banco():
    # Conexão segura lendo do Streamlit Secrets
    return psycopg2.connect(st.secrets["postgres_url"])

# --- MENU LATERAL ---
with st.sidebar:
    st.title("Gestão Financeiro")
    st.markdown("---")
    opcao = st.radio("MENU", ["Gestão de NFs", "Relatórios", "Importar XML"])
    st.markdown("---")

# --- LÓGICA DE DADOS ---
if opcao in ["Gestão de NFs", "Relatórios"]:
    try:
        conn = conectar_banco()
        query = "SELECT c.id, n.loja_destino, n.numero_nota, n.fornecedor_nome, c.data_vencimento, c.valor_parcela, c.pago FROM contas_a_pagar c JOIN notas_fiscais n ON c.nota_fiscal_id = n.id ORDER BY c.data_vencimento ASC"
        df = pd.read_sql(query, conn)
        conn.close()
        if not df.empty:
            hoje = date.today()
            df['Categoria'] = df.apply(lambda r: "Pago" if r['pago'] else ("Vencido" if r['data_vencimento'] < hoje else "A pagar"), axis=1)
    except: df = pd.DataFrame()

if opcao == "Gestão de NFs":
    st.title("Gestão de pagamentos")
    if not df.empty:
        df['Status'] = df.apply(lambda r: "Pago ✅" if r['pago'] else ("Vencido 🚨" if r['data_vencimento'] < hoje else "A pagar ⏳"), axis=1)
        
        # Métrica de Total Geral da Rede
        total_geral = df['valor_parcela'].sum()
        st.metric("Total Geral da Rede (Todos os Status)", f"R$ {total_geral:,.2f}")
        st.divider()
        
        m1, m2, m3 = st.columns(3)
        m1.metric("A Pagar", f"R$ {df[df['Categoria'] == 'A pagar']['valor_parcela'].sum():,.2f}")
        m2.metric("Vencido", f"R$ {df[df['Categoria'] == 'Vencido']['valor_parcela'].sum():,.2f}")
        m3.metric("Pago", f"R$ {df[df['Categoria'] == 'Pago']['valor_parcela'].sum():,.2f}")
        st.divider()
        
        f1, f2 = st.columns(2)
        with f1: l_f = st.multiselect("Loja", df['loja_destino'].unique(), default=df['loja_destino'].unique())
        with f2: s_f = st.multiselect("Status", ["A pagar ⏳", "Vencido 🚨", "Pago ✅"], default=["A pagar ⏳", "Vencido 🚨"])
        df_f = df[(df['loja_destino'].isin(l_f)) & (df['Status'].isin(s_f))]
        
        cap1, cap2, cap3, cap4, cap5 = st.columns([1, 3, 1.5, 1.5, 1.2])
        cap1.write("**NF**"); cap2.write("**Unidade / Fornecedor**"); cap3.write("**Vencimento**"); cap4.write("**Valor**"); cap5.write("**Ação**")
        st.divider()
        
        for idx, row in df_f.iterrows():
            c1, c2, c3, c4, c5 = st.columns([1, 3, 1.5, 1.5, 1.2])
            c1.write(row['numero_nota'])
            c2.write(f"**{row['loja_destino']}** - {row['fornecedor_nome']}")
            c3.write(row['data_vencimento'].strftime('%d/%m/%Y'))
            c4.write(f"R$ {row['valor_parcela']:,.2f}")
            if not row['pago']:
                with c5.popover("Baixar"):
                    if st.button("Confirmar", key=f"b_{row['id']}"):
                        c = conectar_banco(); cur = c.cursor()
                        cur.execute("UPDATE contas_a_pagar SET pago = TRUE WHERE id = %s", (int(row['id']),))
                        c.commit(); cur.close(); c.close()
                        st.rerun()
            else: c5.write("✅")
            st.divider()

elif opcao == "Relatórios":
    st.title("📊 Relatório Financeiro Consolidado")
    if not df.empty:
        relatorio = df.pivot_table(index='loja_destino', columns='Categoria', values='valor_parcela', aggfunc='sum', fill_value=0).reset_index()
        for col in ['A pagar', 'Vencido', 'Pago']:
            if col not in relatorio.columns: relatorio[col] = 0
        relatorio['Total'] = relatorio['A pagar'] + relatorio['Vencido'] + relatorio['Pago']
        st.info(f"💰 **Valor Total Previsto: R$ {relatorio['Total'].sum():,.2f}**")
        st.dataframe(relatorio, use_container_width=True, hide_index=True)

elif opcao == "Importar XML":
    st.title("Importar XMLs")
    arquivos = st.file_uploader("Selecione", type=['xml'], accept_multiple_files=True)
    if arquivos and st.button("Processar"):
        conn = conectar_banco(); cur = conn.cursor()
        for arquivo in arquivos:
            try:
                xml_str = arquivo.read().decode('latin-1')
                xml_str = re.sub(r'\sxmlns="[^"]+"', '', xml_str) 
                root = ET.fromstring(xml_str)
                
                # --- BUSCA PRECISA DO FORNECEDOR (EMITENTE) CORRIGIDA ---
                emitente = root.find('.//emit/xNome')
                fornecedor = emitente.text if emitente is not None else "Desconhecido"
                
                # Busca outros dados
                n_nota = root.find('.//ide/nNF').text if root.find('.//ide/nNF') is not None else "0"
                v_total = root.find('.//ICMSTot/vNF').text if root.find('.//ICMSTot/vNF') is not None else "0.00"
                d_emi = (root.find('.//ide/dhEmi').text or root.find('.//ide/dEmi').text).split('T')[0]
                
                # CNPJ Destinatário para identificar a Loja
                dest_cnpj = root.find('.//dest/CNPJ').text if root.find('.//dest/CNPJ') is not None else "0"
                loja = LOJAS.get(dest_cnpj, f"Outros ({dest_cnpj})")
                
                # Chave
                infNFe = root.find('.//infNFe')
                chave = infNFe.attrib['Id'][3:] if infNFe is not None else "CH"+str(int(time.time()))

                cur.execute("SELECT id FROM notas_fiscais WHERE chave_acesso = %s", (chave,))
                if not cur.fetchone():
                    cur.execute("INSERT INTO notas_fiscais (chave_acesso, numero_nota, fornecedor_nome, fornecedor_cnpj, data_emissao, valor_total, loja_destino) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id", (chave, n_nota, fornecedor, '0', d_emi, v_total, loja))
                    id_nota = cur.fetchone()[0]
                    
                    # --- BUSCA PRECISA DE PARCELAS CORRIGIDA ---
                    duplicatas = root.findall('.//cobr/dup')
                    if duplicatas:
                        for dup in duplicatas:
                            venc = dup.find('dVenc').text
                            valor_p = dup.find('vDup').text
                            n_p = dup.find('nDup').text if dup.find('nDup') is not None else "1"
                            cur.execute("INSERT INTO contas_a_pagar (nota_fiscal_id, numero_parcela, data_vencimento, valor_parcela) VALUES (%s, %s, %s, %s)", (id_nota, n_p, venc, valor_p))
                    else:
                        cur.execute("INSERT INTO contas_a_pagar (nota_fiscal_id, numero_parcela, data_vencimento, valor_parcela) VALUES (%s, %s, %s, %s)", (id_nota, "1", d_emi, v_total))
                st.write(f"✅ NF {n_nota} - {fornecedor}")
            except Exception as e: st.error(f"Erro em {arquivo.name}: {e}")
        conn.commit(); cur.close(); conn.close()
        st.success("Processamento finalizado!")
