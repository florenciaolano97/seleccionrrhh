# ALBA v2 — Módulo 3: búsquedas e importación

Versión estable de un solo archivo.

## Incluye

- Todas las funciones del Módulo 2.
- Creación manual de búsquedas.
- Importación desde Excel, PDF y Word.
- Autocompletado de:
  - puesto;
  - área;
  - seniority;
  - ubicación;
  - modalidad;
  - contratación;
  - descripción;
  - responsabilidades;
  - requisitos excluyentes;
  - requisitos deseables;
  - competencias.
- Edición de todos los campos antes de guardar.
- Visualización del texto extraído.
- Edición posterior de búsquedas.
- Estados ABIERTA, PAUSADA y CERRADA.
- Registro del archivo de origen.
- Auditoría de creación y modificación.
- Vista ampliada del aviso para el candidato.

## Archivos para GitHub

```text
app.py
requirements.txt
runtime.txt
README.md
```

Reemplazá los archivos anteriores y reiniciá la app en Streamlit Cloud.

## Limitación de PDF

Los PDF escaneados como imagen no tienen texto extraíble. En esta etapa
deben convertirse previamente a un PDF con texto. El OCR se incorporará
en un módulo posterior si resulta necesario.
