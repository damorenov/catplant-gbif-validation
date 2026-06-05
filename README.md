# catplant-gbif-validation

Valida nombres científicos en el backbone taxonómico de GBIF (endpoint `species/match` v2) y genera un TSV con taxonomía superior, resultados y estado IUCN cuando aplique.

Usa `requests` directamente en lugar de `pygbif`: al importar, pygbif carga matplotlib/numpy y en servidores con CPU antigua puede provocar **Instrucción ilegal** (binarios compilados con AVX no soportado).

## Instalación

```bash
pip install -r requirements.txt
cp .env.template .env
```

Edita `.env` con las rutas de entrada y salida.

## Uso

```bash
python validate_gbif.py
```

## Entrada (CSV)

El CSV en una carpeta `data` en la raiz del código. Debe incluir al menos estas columnas:

Se acepta UTF-8 con o sin BOM (común en exportaciones desde Excel en Windows).

| Columna | Descripción |
|---------|-------------|
| `originalID` | Identificador del registro original |
| `scientificName` | Nombre científico a consultar en GBIF |

Ejemplo (`data/input.csv`):

```csv
originalID,scientificName
1,Persea americana
2,Tibouchina lepidota
```

## Salida (TSV)

Archivo delimitado por tabulaciones, codificación UTF-8. Columnas en este orden:

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
| `synonym` | raíz de la respuesta |
| `acceptedUsageKey` | `acceptedUsage.key` (sinónimos) |
| `acceptedUsageCanonicalName` | `acceptedUsage.canonicalName` |
| `acceptedUsageAuthorship` | `acceptedUsage.authorship` |
| `acceptedUsageRank` | `acceptedUsage.rank` |
| `kingdom` … `genus` | `classification[]` por `rank` (hasta género) |
| `datasetAlias` | `additionalStatus` solo si `datasetAlias == "IUCN"` |
| `status` | estado IUCN |
| `statusCode` | código IUCN (p. ej. `VU`) |

Si un campo no está presente en la respuesta de la API, la celda queda vacía.

## Configuración (.env)

| Variable | Descripción | Default |
|----------|-------------|---------|
| `INPUT_CSV` | Ruta al CSV de entrada | `./data/input.csv` |
| `OUTPUT_TSV` | Ruta al TSV de salida | `./data/output.tsv` |
| `API_DELAY_SECONDS` | Pausa entre llamadas a la API en segundos | `0.3` |
| `API_MAX_RETRIES` | Reintentos ante errores | `3` |
| `API_RETRY_BACKOFF_SECONDS` | Multiplicador exponencial del tiempo de reintento entre errores | `2` |
| `PROGRESS_EVERY` | Cada cuántas especies procesadas se imprime avance en consola (`0` desactiva) | `100` |

## Comportamiento

- Se consulta `GET https://api.gbif.org/v2/species/match?scientificName=...` por cada fila (equivalente a `pygbif.species.name_backbone`).
- Entre llamadas se espera al menos `API_DELAY_SECONDS`.
- Errores HTTP transitorios (429, 502, 503, 504), fallos de red y respuestas HTML se reintentan con un multiplicador exponencial de tiempo de reintento.
- Si la API falla definitivamente, se escribe una fila con campos vacíos (excepto `originalID` y `originalScientificName`) y el error se registra en stderr.
- La salida se escribe incrementalmente fila a fila.
- El progreso se reporta en consola cada `PROGRESS_EVERY` especies consultadas (p. ej. `Processed 50 species...`). Al terminar muestra el total: `Done. Wrote N API lookups to ...`.

## Licencia

Ver [LICENSE](LICENSE).
