import streamlit as st
import psycopg2
import xml.etree.ElementTree as ET
import pandas as pd
import re
from datetime import date
import time

st.set_page_config(page_title="Financeiro", layout="wide")

LOJAS = {
    "79503280000100": "Matriz", "14995048000191": "VD", "79503280000291": "Papanduva", 
    "79503280000372": "Via", "79503280000453": "Queluz", "79503280000615": "Bruda"
}

def conectar_banco():
    return psycopg2.connect(st.secrets["postgres_url"])

# --- MENU LATERAL ---
with st.sidebar:
    st.title("Gestão Financeiro")
    st.markdown("---")
    opcao = st.radio("MENU", ["Gestão de NFs", "Relatórios", "Importar XML"])
    st.markdown("---")

# --- LÓGICA GERAL DE CARREGAMENTO ---
if opcao in ["Gestão de NFs", "Relatórios"]:
    try:
        conn = conectar_banco()
        query = "SELECT c.id, n.loja_destino, n.numero_nota, n.fornecedor_nome, c.data_vencimento, c.valor_parcela, c.pago FROM contas_a_pagar c JOIN notas_fiscais n ON c.nota_fiscal_id = n.id ORDER BY c.data_vencimento ASC"
        df = pd.read_sql(query, conn)
        conn.close()
        
        if not df.empty:
            hoje = date.today()
            df['numero_nota'] = df['numero_nota'].fillna('S/N')
            df['Categoria'] = df.apply(
                lambda r: "Pago" if r['pago'] 
                else ("Vencido" if r['data_vencimento'] < hoje else "A pagar"), axis=1
            )
    except Exception as e:
        st.error(f"Erro ao conectar: {e}")
        df = pd.DataFrame()

# --- PÁGINA 1: GESTÃO DE NFs ---
if opcao == "Gestão de NFs":
    st.title("Gestão de pagamentos")
    if not df.empty:
        hoje = date.today()
        df['Status'] = df.apply(lambda r: "Pago ✅" if r['pago'] else ("Vencido 🚨" if r['data_vencimento'] < hoje else "A pagar ⏳"), axis=1)
        
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

# --- PÁGINA 2: RELATÓRIOS ---
elif opcao == "Relatórios":
    st.title("📊 Relatório Financeiro Consolidado")
    if not df.empty:
        # Pivot Table
        relatorio = df.pivot_table(
            index='loja_destino', 
            columns='Categoria', 
            values='valor_parcela', 
            aggfunc='sum', 
            fill_value=0
        ).reset_index()

        for col in ['A pagar', 'Vencido', 'Pago']:
            if col not in relatorio.columns: relatorio[col] = 0

        relatorio['Total da Loja'] = relatorio['A pagar'] + relatorio['Vencido'] + relatorio['Pago']
        
        # Cálculo do Total Geral da Rede
        total_previsto = relatorio['Total da Loja'].sum()
        
        # Adiciona a linha de TOTAL GERAL ao final do DataFrame
        linha_total = pd.DataFrame([{
            'loja_destino': 'TOTAL GERAL DA REDE',
            'A pagar': relatorio['A pagar'].sum(),
            'Pago': relatorio['Pago'].sum(),
            'Vencido': relatorio['Vencido'].sum(),
            'Total da Loja': total_previsto
        }])
        
        relatorio_completo = pd.concat([relatorio, linha_total], ignore_index=True)

        # Métrica de destaque
        st.subheader("Resumo Financeiro Total")
        st.info(f"💰 **Valor Total Previsto (Bruto): R$ {total_previsto:,.2f}**")

        st.divider()

        # Exibição da Tabela
        relatorio_completo.columns = ['Unidade', 'A Pagar (R$)', 'Pago (R$)', 'Vencido (R$)', 'Total Bruto (R$)']
        st.dataframe(
            relatorio_completo.style.format({
                'A Pagar (R$)': '{:,.2f}',
                'Pago (R$)': '{:,.2f}',
                'Vencido (R$)': '{:,.2f}',
                'Total Bruto (R$)': '{:,.2f}'
            }), 
            use_container_width=True,
            hide_index=True
        )

# --- PÁGINA 3: IMPORTAR XML ---
elif opcao == "Importar XML":
    st.title("Importar XMLs")
    arquivos = st.file_uploader("Selecione os arquivos", type=['xml'], accept_multiple_files=True)
    if arquivos and st.button("Processar"):
        conn = conectar_banco(); cur = conn.cursor()
        for arquivo in arquivos:
            try:
                xml_str = arquivo.read().decode('latin-1')
                xml_str = re.sub(r'\sxmlns="[^"]+"', '', xml_str) 
                root = ET.fromstring(xml_str)
                tags = {el.tag.split('}')[-1]: el.text for el in root.iter()}
                n_nota = tags.get('nNF', '0')
                fornecedor = tags.get('xNome', 'Desconhecido')
                valor_total = tags.get('vNF', '0.00').replace(',', '.')
                data_emi = (tags.get('dhEmi') or tags.get('dEmi') or str(date.today())).split('T')[0]
                lista_cnpj = [el.text for el in root.iter() if 'CNPJ' in el.tag]
                d_cnpj = lista_cnpj[1] if len(lista_cnpj) > 1 else (lista_cnpj[0] if lista_cnpj else '0')
                loja = LOJAS.get(d_cnpj, f"CNPJ: {d_cnpj}")
                chave = "CH" + str(int(time.time())) + n_nota
                for el in root.iter():
                    if 'infNFe' in el.tag and 'Id' in el.attrib: chave = el.attrib['Id'][3:]

                cur.execute("SELECT id FROM notas_fiscais WHERE chave_acesso = %s", (chave,))
                if not cur.fetchone():
                    cur.execute("INSERT INTO notas_fiscais (chave_acesso, numero_nota, fornecedor_nome, fornecedor_cnpj, data_emissao, valor_total, loja_destino) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id", (chave, n_nota, fornecedor, '0', data_emi, valor_total, loja))
                    id_nota = cur.fetchone()[0]
                    cur.execute("INSERT INTO contas_a_pagar (nota_fiscal_id, numero_parcela, data_vencimento, valor_parcela) VALUES (%s, %s, %s, %s)", (id_nota, "1", data_emi, valor_total))
                st.write(f"✅ {fornecedor} - NF {n_nota}")
            except Exception as e: st.error(f"Erro em {arquivo.name}: {e}")
        conn.commit(); cur.close(); conn.close()
        st.success("Fim do processamento!")