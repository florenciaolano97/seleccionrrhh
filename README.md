# ALBA v2 — Módulo 2

Versión estable de un solo archivo.

## Incluye

- Registro e inicio de sesión por correo.
- Logo obligatorio para la empresa.
- Logo visible en el portal y en las búsquedas.
- Configuración de empresa.
- Usuarios internos.
- Roles ADMIN, RECRUITER y VIEWER.
- Permisos personalizados.
- Activación y desactivación de usuarios.
- Restablecimiento de contraseña por administrador.
- Protección para conservar al menos un administrador activo.
- Auditoría básica.
- Portal empresa y portal candidato.
- Búsquedas y postulaciones.

## Archivos

Subir a la raíz del repositorio:

```text
app.py
requirements.txt
runtime.txt
README.md
```

## Despliegue

1. Reemplazar el `app.py` anterior.
2. Subir `requirements.txt`, `runtime.txt` y `README.md`.
3. Confirmar los cambios en GitHub.
4. Reiniciar la app en Streamlit Cloud.

## Nota del MVP

SQLite funciona para esta etapa. En producción se migrará a PostgreSQL
para asegurar persistencia, concurrencia y escalabilidad.
