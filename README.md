# ALBA v2 — Módulo 3.1: corrección de guardado

Esta revisión corrige el guardado de modificaciones de las búsquedas.

## Cambios

- Actualización y auditoría dentro de una misma transacción.
- Eliminación del `st.rerun()` inmediato después de editar.
- Conexiones SQLite cerradas siempre mediante `finally`.
- Timeout y reintentos si la base está temporalmente bloqueada.
- Comprobación de que la búsqueda pertenezca a la empresa.
- Diagnóstico visible en pantalla si aparece otro error.
- Mantiene importación desde Excel, PDF y Word.

## Subida a GitHub

Reemplazar en la raíz:

- `app.py`
- `requirements.txt`
- `runtime.txt`
- `README.md`

Luego confirmar el commit y reiniciar la app en Streamlit Cloud.
