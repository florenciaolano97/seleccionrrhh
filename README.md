# Alba — Módulo 2

## Incluye

- Registro e inicio de sesión por correo electrónico y contraseña.
- Cuenta de empresa y cuenta de candidato.
- Logo obligatorio al registrar una empresa.
- Usuario administrador inicial.
- Creación de usuarios internos.
- Roles y permisos personalizados.
- Activación y desactivación de usuarios.
- Portal separado para empresa y candidato.
- Importación de búsquedas desde:
  - Excel (`.xlsx`, `.xls`)
  - PDF
  - Word (`.docx`)
- Autocompletado de campos del puesto.
- Edición manual de todos los campos antes de guardar.
- Auditoría básica.
- SQLite.

## Archivos de la raíz

```text
app.py
requirements.txt
runtime.txt
README.md
```

## Ejecutar localmente

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud

1. Eliminá el `app.py` anterior.
2. Subí los cuatro archivos de este ZIP a la raíz del repositorio.
3. Seleccioná `app.py` como archivo principal.
4. Reiniciá la app.

## Consideración importante

SQLite y los logos guardados en disco sirven para el MVP. En una etapa
posterior conviene migrar a PostgreSQL y almacenamiento externo para evitar
pérdidas durante reinicios o redeploys.
