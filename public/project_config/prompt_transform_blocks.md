# Prompt de transformacion a `blocks_semantic.json`

Objetivo:
- Leer `public/blocks_normalized.csv`.
- Convertir cada fila en una estructura semantica para apoyar agrupacion y matching BTZ.

Campos minimos por item:
- `code`
- `description`
- `description_prefix`
- `description_name`
- `active_tags`
- `inferred_tokens` (ejemplo: `N1`, `VESTUARIOS`, `SR1`, `ST1`, `PA`, `PG`)
- `project_zone_hint`
- `project_sector_hint`
- `forbidden_tokens_suggested`

Criterios:
- Mantener trazabilidad con `code`.
- Detectar aliases y abreviaturas.
- No eliminar filas; si no hay claridad, dejar hints vacios.
