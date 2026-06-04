CATALOGO RICARDONE - BORRADOR INICIAL

Archivos:
1) ricardone_activos_maestro.csv
   - 1 fila por activo PR del Excel
   - sirve para auditoria y reproceso
2) sectores_subsectores_btz_manual_ricardone_borrador.csv
   - borrador compatible con el esquema legacy del picker manual
3) ricardone_catalogo_revision.csv
   - raices o casos a revisar antes de usar el catalogo final

Reglas usadas para el borrador:
- cada raiz PR se tomo como SECTOR
- cada hijo inmediato que es LGC o que tiene descendientes se tomo como SUBSECTOR
- cada hoja bajo un subsector se tomo como UNIDAD
- si un sector tenia hojas directas, se creo un SUBSECTOR sintetico 'GENERAL'
- si una raiz no tenia LGC o no tenia descendientes, se marco para revision

Este borrador no reemplaza validacion manual.
Sirve para arrancar rapido y despues depurarlo.
