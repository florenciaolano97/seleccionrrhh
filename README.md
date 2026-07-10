# ALBA v2 — Módulo 3.2: fix del error al guardar ediciones

Esta revisión corrige el error genérico de Streamlit ("Oh no. Error running app")
que aparecía al guardar cambios en una búsqueda.

## Causa encontrada

1. `init_db()` se ejecutaba en cada rerun del script (es decir, en cada clic,
   incluido "Guardar cambios"), abriendo y cerrando ~14 conexiones SQLite
   sin ningún manejo de errores. Si en ese instante la base estaba bloqueada
   por otra conexión, la excepción no era atrapada por el resto del código
   (que sí tiene buen manejo de errores) y tiraba abajo toda la app.
2. La base usaba el modo de bloqueo por defecto de SQLite (rollback journal),
   que es más propenso a errores de "database is locked" cuando hay varias
   sesiones de usuario corriendo en paralelo, como pasa en Streamlit.

## Cambios en esta versión

- `init_db()` ahora corre una sola vez por despliegue (cacheada con
  `st.cache_resource`), no en cada clic.
- Si la inicialización de la base falla, se muestra un error explicativo
  en vez de romper toda la app.
- Se activó el modo **WAL** de SQLite (`PRAGMA journal_mode = WAL`), que
  permite lecturas y escrituras simultáneas sin bloquearse entre sí.

## Subida a GitHub

Reemplazar en la raíz:

- `app.py`
- `requirements.txt`
- `runtime.txt`
- `README.md`

Luego confirmar el commit y reiniciar la app en Streamlit Cloud.

## Si el error vuelve a aparecer

Este mensaje genérico de Streamlit no muestra el detalle real del error.
Para diagnosticarlo con precisión hace falta el traceback completo, que se
ve así:

1. Entrá a share.streamlit.io y abrí tu app.
2. Abajo a la derecha, click en "Manage app".
3. En el panel de logs vas a ver el traceback en rojo (texto en inglés
   con "Traceback (most recent call last)..."). Copiá ese texto completo.
