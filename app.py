import streamlit as st
import psycopg2
import xml.etree.ElementTree as ET
import pandas as pd
import re
from datetime import date, datetime
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

# --- LÓGICA DE CARREGAMENTO DE DADOS ---
if opcao in ["Gestão de NFs", "Relatórios"]:
    try:
        conn = conectar_banco()
        query = "SELECT c.id, n.loja_destino, n.numero_nota, n.fornecedor_nome, c.data_vencimento, c.valor_parcela, c.pago FROM contas_a_pagar c JOIN notas_fiscais n ON c.nota_fiscal_id = n.id ORDER BY c.data_vencimento ASC"
        df = pd.read_sql(query, conn)
        conn.close()
        
        if not df.empty:
            hoje = date.today()
            # Tratamento de segurança para as datas funcionarem matematicamente
            df['data_vencimento'] = pd.to_datetime(df['data_vencimento']).dt.date
            df['pago'] = df['pago'].astype(bool)
            
            # A REGRA MÁGICA AQUI: Baixa automática 1 dia após o vencimento
            df['Categoria'] = df.apply(lambda r: "Pago" if r['pago'] or r['data_vencimento'] < hoje else "A pagar", axis=1)
    except Exception as e:
        st.error(f"Erro ao carregar banco: {e}")
        df = pd.DataFrame()

# --- PÁGINA: GESTÃO DE NFs ---
if opcao == "Gestão de NFs":
    st.title("Gestão de pagamentos")
    if not df.empty:
        hoje = date.today()
        # Aplica a mesma regra para o Status visual
        df['Status'] = df.apply(lambda r: "Pago ✅" if r['pago'] or r['data_vencimento'] < hoje else "A pagar ⏳", axis=1)
        
        # Como o "Vencido" não existe mais na prática, deixamos apenas 2 colunas de métricas
        m1, m2 = st.columns(2)
        m1.metric("A Pagar (Hoje e Futuros)", f"R$ {df[df['Categoria'] == 'A pagar']['valor_parcela'].sum():,.2f}")
        m2.metric("Pago (Manuais e Automáticos)", f"R$ {df[df['Categoria'] == 'Pago']['valor_parcela'].sum():,.2f}")
        
        st.divider()
        f1, f2 = st.columns(2)
        with f1: l_f = st.multiselect("Loja", df['loja_destino'].unique(), default=df['loja_destino'].unique())
        # Filtro default mostra apenas o que está "A pagar" para limpar a tela
        with f2: s_f = st.multiselect("Status", ["A pagar ⏳", "Pago ✅"], default=["A pagar ⏳"])
        
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
            
            # Só exibe botão de baixar se estiver "A pagar"
            if row['Status'] == "A pagar ⏳":
                with c5.popover("Baixar"):
                    if st.button("Confirmar", key=f"b_{row['id']}"):
                        c = conectar_banco(); cur = c.cursor()
                        cur.execute("UPDATE contas_a_pagar SET pago = TRUE WHERE id = %s", (int(row['id']),))
                        c.commit(); cur.close(); c.close()
                        st.rerun()
            else: c5.write("✅")
            st.divider()
    else:
        st.info("Nenhum dado encontrado. Importe XMLs para começar.")

# --- PÁGINA: RELATÓRIOS ---
elif opcao == "Relatórios":
    st.title("Relatório Financeiro Detalhado")
    if not df.empty:
        df['Mês/Ano'] = df['data_vencimento'].apply(lambda x: x.strftime('%m/%Y'))
        
        meses_disponiveis = sorted(df['Mês/Ano'].unique(), key=lambda x: datetime.strptime(x, '%m/%Y'))
        mes_selecionado = st.multiselect("Filtrar por Mês/Ano", meses_disponiveis, default=meses_disponiveis)
        df_filtrado = df[df['Mês/Ano'].isin(mes_selecionado)]

        t_geral = df_filtrado['valor_parcela'].sum()
        t_pago = df_filtrado[df_filtrado['Categoria'] == 'Pago']['valor_parcela'].sum()
        t_pendente = df_filtrado[df_filtrado['Categoria'] != 'Pago']['valor_parcela'].sum()

        c1, c2, c3 = st.columns(3)
        c1.metric("Total no Período", f"R$ {t_geral:,.2f}")
        c2.metric("Total Pago", f"R$ {t_pago:,.2f}")
        c3.metric("Total Pendente", f"R$ {t_pendente:,.2f}")

        st.divider()

        lojas_no_df = sorted(df_filtrado['loja_destino'].unique())
        tabs = st.tabs(lojas_no_df)

        for i, nome_loja in enumerate(lojas_no_df):
            with tabs[i]:
                df_loja = df_filtrado[df_filtrado['loja_destino'] == nome_loja]
                
                # Tabela de evolução mensal da loja
                st.write(f"**Resumo Mensal - {nome_loja}**")
                pivot_loja = df_loja.pivot_table(index='Mês/Ano', columns='Categoria', values='valor_parcela', aggfunc='sum', fill_value=0).reset_index()
                
                # CORREÇÃO 1: Formata apenas as colunas de dinheiro do Resumo Mensal
                colunas_dinheiro = [c for c in pivot_loja.columns if c != 'Mês/Ano']
                st.dataframe(pivot_loja.style.format({c: "R$ {:,.2f}" for c in colunas_dinheiro}), use_container_width=True, hide_index=True)

                with st.expander("Ver todas as notas desta unidade"):
                    # CORREÇÃO 2: Formata a coluna de valor na tabela detalhada
                    df_exibicao = df_loja[['numero_nota', 'fornecedor_nome', 'data_vencimento', 'valor_parcela', 'Categoria']].copy()
                    df_exibicao['valor_parcela'] = df_exibicao['valor_parcela'].apply(lambda x: f"R$ {x:,.2f}")
                    st.table(df_exibicao)

        st.divider()
        st.subheader("Matriz Consolidada (Loja x Mês)")
        matriz = df_filtrado.pivot_table(index='loja_destino', columns='Mês/Ano', values='valor_parcela', aggfunc='sum', fill_value=0)
        st.dataframe(matriz.style.format("R$ {:,.2f}"), use_container_width=True)

    else:
        st.info("Importe XMLs para visualizar os relatórios.")

# --- PÁGINA: IMPORTAR XML ---
elif opcao == "Importar XML":
    st.title("Importar XMLs")
    arquivos = st.file_uploader("Selecione os arquivos", type=['xml'], accept_multiple_files=True)
    if arquivos and st.button("Processar Lote"):
        conn = conectar_banco(); cur = conn.cursor()
        for arquivo in arquivos:
            try:
                raw_data = arquivo.read()
                try: xml_str = raw_data.decode('utf-8')
                except UnicodeDecodeError: xml_str = raw_data.decode('latin-1')
                xml_str = re.sub(r'\sxmlns="[^"]+"', '', xml_str) 
                root = ET.fromstring(xml_str)
                emit_node = root.find('.//emit/xNome')
                fornecedor = emit_node.text.strip() if emit_node is not None else "Desconhecido"
                n_nota = root.find('.//ide/nNF').text if root.find('.//ide/nNF') is not None else "0"
                v_total = root.find('.//ICMSTot/vNF').text if root.find('.//ICMSTot/vNF') is not None else "0.00"
                d_emi_node = root.find('.//ide/dhEmi') or root.find('.//ide/dEmi')
                d_emi = d_emi_node.text.split('T')[0] if d_emi_node is not None else str(date.today())
                dest_cnpj = root.find('.//dest/CNPJ').text if root.find('.//dest/CNPJ') is not None else "0"
                loja = LOJAS.get(dest_cnpj, f"Outros ({dest_cnpj})")
                infNFe = root.find('.//infNFe')
                chave = infNFe.attrib['Id'][3:] if infNFe is not None else "CH"+str(int(time.time()))

                cur.execute("SELECT id FROM notas_fiscais WHERE chave_acesso = %s", (chave,))
                if not cur.fetchone():
                    cur.execute("INSERT INTO notas_fiscais (chave_acesso, numero_nota, fornecedor_nome, fornecedor_cnpj, data_emissao, valor_total, loja_destino) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id", (chave, n_nota, fornecedor, '0', d_emi, v_total, loja))
                    id_nota = cur.fetchone()[0]
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
