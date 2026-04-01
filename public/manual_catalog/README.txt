BTZ manual catalogo jerarquico

Archivo principal esperado (prioridad):
1) public/sectores_subsectores_btz_manual.csv
2) resources/sectores_subsectores_btz_manual.csv
3) public/sectores_subsectores_btz_manual_*.csv
4) resources/sectores_subsectores_btz_manual_*.csv

Formato CSV recomendado:
planta_codigo,planta_nombre,sector_codigo,sector_nombre,sector_lgc,subsector_nombre,subsector_lgc

Escritura en Revit:
- BTZ_Description_01 = planta_codigo
- BTZ_Description_02 = sector_lgc
- BTZ_Description_03 = subsector_lgc (si no se elige, queda vacio)

Diagramas de referencia:
- public/manual_catalog/diagramas/PP.png
- public/manual_catalog/diagramas/P10.png
- public/manual_catalog/diagramas/TE.png
