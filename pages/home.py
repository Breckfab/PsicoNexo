import streamlit as st
from auth import logout

def mostrar(usuario: dict):
    with st.sidebar:
        st.markdown(f"### 👤 {usuario['nombre']}")
        st.markdown("---")
        st.markdown("📋 **Menú**")
        st.button("🏠 Inicio", disabled=True)
        st.markdown("---")
        if st.button("Cerrar sesión"):
            logout()
            st.rerun()

    st.title("🧠 PsicoNexo")
    st.markdown(f"### Bienvenido/a, {usuario['nombre'].split()[0]} 👋")
    st.info("Sistema en construcción. Próximamente: plan de estudios, cursadas, historial y más.")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Materias aprobadas", "—")
    with col2:
        st.metric("En curso", "—")
    with col3:
        st.metric("Avance", "—")
