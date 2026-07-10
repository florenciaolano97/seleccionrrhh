# Alba Platform — Módulo 1

Primera base funcional de una plataforma universal de selección de personal.

## Incluye

- Arquitectura modular.
- Base SQLite.
- Portal inicial del reclutador.
- Portal inicial del candidato.
- Gestión de empresas.
- Gestión de búsquedas.
- Registro de postulaciones.
- Auditoría.
- Política de privacidad.
- Criterio inicial de scoring explicable.

## No incluye todavía

- Carga masiva de CV.
- Parser y ranking automático.
- Avatar D-ID.
- Entrevista por texto/voz.
- Informes finales.
- Login real y permisos.

Estos componentes se incorporan en módulos siguientes para mantener estabilidad y trazabilidad.

## Ejecutar localmente

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

## Deploy en Streamlit Community Cloud

1. Subir todos los archivos a un repositorio de GitHub.
2. Crear una app nueva en Streamlit Community Cloud.
3. Seleccionar `app.py` como archivo principal.
4. Reiniciar la app después del primer despliegue.

## Próximo módulo

Módulo 2: usuarios, autenticación, roles y permisos.
