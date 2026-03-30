# BTZ Console

Consola local desktop para monitorear y revisar el flujo real BTZ.

## Ejecutar

```bash
python -m btz_console.main
```

o con ruta explícita:

```bash
python -m btz_console.main --public-dir "C:/ruta/al/proyecto/public"
```

## Fase actual

- Fase 1: stack PySide6, layout base, navegación, sidebar/topbar, persistencia de ventana.
- Fase 2: lectura real de artefactos BTZ desde `public/` (Prepare + Groups básico).

