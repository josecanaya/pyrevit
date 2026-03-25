# BTZ - Asignar parámetros BTZ desde blocks.csv

Herramienta pyRevit **independiente** para asignar parámetros compartidos BTZ a elementos de Revit usando un archivo CSV como fuente de datos.

## Estructura de carpetas

```
btz.extension/
├── README.md
├── resources/
│   ├── BTZ_SharedParameters.txt   # Archivo de Shared Parameters (parámetros BTZ)
│   └── blocks.csv                 # Fuente de datos: code, description, etc.
└── btz.tab/
    └── BTZ.panel/
        └── AsignarBTZ.pushbutton/
            └── script.py
```

## Dónde copiar cada archivo

La extensión se instala en:

```
%APPDATA%\pyRevit\Extensions\btz.extension\
```

O en Windows:

```
C:\Users\<Usuario>\AppData\Roaming\pyRevit\Extensions\btz.extension\
```

**Copiar toda la carpeta `btz.extension`** dentro de `Extensions\` para que pyRevit la detecte automáticamente.

## Configuración de rutas

Al inicio de `script.py` puedes modificar:

- `SHARED_PARAMS_FILE`: ruta al archivo TXT de Shared Parameters
- `BLOCKS_CSV_FILE`: ruta al CSV de bloques

Por defecto apuntan a `resources/` dentro de la extensión.

## Formato del CSV (blocks.csv)

Columnas requeridas: `code`, `description`

Ejemplo:

```csv
code,description,start_date,end_date,displacement_date
05VPO,F1.PER.HABILITACION-MUNICIPAL,,,
05VN4,F1.DSC.VAR-CONEXION-SIST-BALANZA,,,
```

Encoding soportado: UTF-8, UTF-8-sig, cp1252, latin-1 (compatible con exportaciones de Excel).

## Estrategia de guardado (Opción B)

Los valores se guardan en formato: `code - description`

Ejemplo: `05VPO - F1.PER.HABILITACION-MUNICIPAL`

## Uso

1. Selecciona uno o varios elementos en Revit (o deja vacío para seleccionar al ejecutar)
2. Ejecuta el botón "Asignar BTZ"
3. Indica si marcar BTZ_Description = "*"
4. Para cada BTZ_Description_01..13, elige un bloque desde el CSV
5. Los valores se aplican a todos los elementos seleccionados
