# ALBA v2 — Módulo 1

Base modular estable.

## Incluye

- Login por email y contraseña.
- Registro de empresa.
- Registro de candidato.
- Portal empresa.
- Portal candidato.
- Creación manual de búsquedas.
- Postulaciones.
- SQLite.
- Arquitectura modular.

## Estructura

```text
app.py
config.py
requirements.txt
runtime.txt
auth/
candidate/
company/
core/
database/
shared/
```

## Ejecutar

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud

Subir todo el contenido del ZIP respetando la estructura de carpetas.
Seleccionar `app.py` como archivo principal.
