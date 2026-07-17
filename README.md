# ALBA v2 — Módulo 3.2

Esta versión corrige la compatibilidad con bases antiguas.

## Cambios

- Migra automáticamente la tabla `audit_log`.
- Migra columnas faltantes de `candidates`.
- Confirma la modificación de la búsqueda antes de auditar.
- Una falla de auditoría ya no rompe ni revierte el guardado.
- Muestra `Versión 3.2.0` en la barra lateral.
- Mantiene diagnóstico visible para errores capturados.

## Actualización

Reemplazar en GitHub:

- app.py
- requirements.txt
- runtime.txt
- README.md

Luego hacer commit y reiniciar la app.
