# ALBA v2 — Módulo 4.2

## Funciones incorporadas

- Filtros independientes por país, ciudad y localidad.
- Provincia/Estado continúa disponible como dato administrativo.
- Vista de CV asignados dentro de cada búsqueda.
- Descarga directa del CV desde la búsqueda.
- Resumen por búsqueda: cantidad asignada, candidatos que avanzan y pendientes.
- Explicación exhaustiva de por qué un candidato:
  - avanza;
  - queda en revisión;
  - no avanza;
  - incumple requisitos obligatorios.
- Comparación del puntaje con los umbrales configurados.
- Detalle de fortalezas, brechas, evidencias y próximos pasos.
- Banco inteligente de CV.
- Sugerencias automáticas para búsquedas abiertas.
- Exclusión de candidatos que ya están asignados.
- Asignación humana desde la sugerencia al pipeline.
- Actualización de sugerencias cuando cambian los criterios.
- Compatibilidad con bases anteriores.

## Protección contra sesgos

Edad, país, ciudad, localidad, nombre, correo y teléfono no participan
en el cálculo de coincidencia. País, ciudad, localidad y edad se utilizan
exclusivamente como filtros administrativos.

## Instalación

Reemplazar en GitHub:

- app.py
- requirements.txt
- runtime.txt
- README.md

Después hacer commit y reiniciar Streamlit Cloud. Verificar que la
barra lateral muestre `Versión 4.2.0`.
