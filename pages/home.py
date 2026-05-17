import streamlit as st
from datetime import datetime

def mostrar(usuario):
    st.title("🧠 PsicoNexo")
    st.markdown(f"### Bienvenido/a, {usuario['nombre'].split()[0]} 👋")
    st.info("Usá el menú de la izquierda para navegar.")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Materias aprobadas", "—")
    with col2:
        st.metric("En curso", "—")
    with col3:
        st.metric("Avance", "—")
