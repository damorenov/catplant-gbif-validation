# catplant-gbif-validation

Valida nombres científicos en el backbone taxonómico de GBIF (usando el endpoint `species/match` v2) y genera un TSV con taxonomía superior, resultados de validación y estado IUCN cuando aplique.

Usa `requests` directamente en lugar de `pygbif`: al importar, pygbif carga matplotlib/numpy y en equipos con alguna configuración de procesadores puede provocar un mensaje de **Instrucción ilegal** al ejecutar el script (Técnicamente son binarios compilados con AVX no soportado,para más información en [este enlace](https://itechhacks.com/check-cpu-support-avx/) ).

## Instalación

Clonar o descargar el proyecto.

Instalar dependencias y copiar archivo de configuración.

```bash
pip install -r requirements.txt
cp .env.template .env
```

Editar `.env` con las rutas de entrada, salida y otras variables.

## Uso

```bash
python validate_gbif.py  # En algunas distribuciones puede ser python3 
```

## Entrada (CSV)

El CSV de entrada se almacena en carpeta `data` en la raiz del proyecto. Debe incluir como mínimo estas columnas:

| Columna | Descripción |
|---------|-------------|
| `originalID` | Identificador del registro en fuente original |
| `scientificName` | Nombre científico, sin autoria, a consultar |

Se acepta codificación UTF-8 con o sin BOM (común en exportaciones desde Excel en Windows). Si el archivo viene desde Excel en Windows con caracteres especiales (tildes, eñes, diéreses), se debe usar en el .env `INPUT_CSV_ENCODING=cp1252`.

También se detecta automáticamente delimitador `,` o `;` (Generalemente configurado como delimitador por Locale en Excel en español). Puede forzar un delimitador con `INPUT_CSV_DELIMITER=;`.

Ejemplo de archivo `data/input.csv`:

```csv
originalID,scientificName
1,Persea americana
2,Tibouchina lepidota
```

## Salida (TSV)

Archivo delimitado por tabulaciones con codificación UTF-8. Columnas en este orden:

| Columna | Origen |
|---------|--------|
| `originalID` | CSV de entrada |
| `originalScientificName` | CSV de entrada |
| `matchType` | `diagnostics.matchType` |
| `usageKey` | `usage.key` |
| `usageName` | `usage.name` |
| `usageCanonicalName` | `usage.canonicalName` |
| `usageAuthorship` | `usage.authorship` |
| `usageRank` | `usage.rank` |
| `usageStatus` | `usage.status` |
| `synonym` | raíz de la respuesta, no es `acceptedUsage` |
| `acceptedUsageKey` | `acceptedUsage.key` |
| `acceptedUsageCanonicalName` | `acceptedUsage.canonicalName` |
| `acceptedUsageAuthorship` | `acceptedUsage.authorship` |
| `acceptedUsageRank` | `acceptedUsage.rank` |
| `kingdom` … `genus` | Llave `classification` y filto por `rank` (hasta género) |
| `datasetAlias` | `additionalStatus` solo si `datasetAlias == "IUCN"` |
| `status` | estado IUCN |
| `statusCode` | código IUCN (p. ej. `VU`) |

Si un campo no está presente en la respuesta de la API, la celda queda vacía.

## Configuración (.env)

| Variable | Descripción | Default |
|----------|-------------|---------|
| `INPUT_CSV` | Ruta al CSV de entrada | `./data/input.csv` |
| `OUTPUT_TSV` | Ruta al TSV de salida | `./data/output.tsv` |
| `INPUT_CSV_ENCODING` | Codificación del CSV (`cp1252` para Excel Windows; vacío = autodetectar) | autodetectar |
| `INPUT_CSV_DELIMITER` | Delimitador del CSV (`;` o `,`; vacío = autodetectar) | autodetectar |
| `RESUME` | Omitir `originalID` ya presentes en el TSV de salida | `false` |
| `API_DELAY_SECONDS` | Pausa entre llamadas a la API en segundos o fracción | `0.3` |
| `API_MAX_RETRIES` | Reintentos ante errores | `3` |
| `API_RETRY_BACKOFF_SECONDS` | Multiplicador exponencial del tiempo de reintento entre errores | `2` |
| `PROGRESS_EVERY` | Cada cuántas especies procesadas se imprime mensaje de avance en consola (`0` para desactivar ) | `100` |

## Comportamiento

- Se consulta `GET https://api.gbif.org/v2/species/match?scientificName=...` por cada fila (equivalente a `pygbif.species.name_backbone`).
- Entre llamadas se espera al menos `API_DELAY_SECONDS`.
- Errores HTTP transitorios (429, 502, 503, 504), fallos de red y respuestas HTML se reintentan con un multiplicador exponencial de tiempo de reintento.
- Si la API falla definitivamente, se escribe una fila con campos vacíos (excepto `originalID` y `originalScientificName`) y el error se registra en consola.
- La salida se escribe incrementalmente fila a fila.
- El progreso se reporta en consola cada `PROGRESS_EVERY` especies consultadas (p. ej. `Processed 100 species...`). Al terminar muestra el total: `Done. Wrote N API lookups to ...`.
- Con `RESUME=true` se omiten filas cuyo `originalID` ya está en el TSV y se añade al archivo existente (útil tras un error de codificación o interrupción).

### Reintentar tras error

Si aparece en la traza algo similar a `UnicodeDecodeError`, la última fila procesada con éxito está al final del TSV de salida (columnas `originalID` y `originalScientificName`). Para continuar:

```bash
# En .env
INPUT_CSV_ENCODING=cp1252
RESUME=true
```
Luego vuelve a ejecutar `python validate_gbif.py`.

En general, con cambiar la opción de `RESUME=true` se puede continuar el proceso en caso de fallo.

## Licencia

Ver [LICENSE](LICENSE).