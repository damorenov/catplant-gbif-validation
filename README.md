# catplant-gbif-validation

Valida nombres científicos en el backbone taxonómico de GBIF usando [pygbif](https://www.gbif.org/es/tool/OlyoYyRbKCSCkMKIi4oIT/pygbif-cliente-python-de-gbif) y genera un TSV con taxonomía superior, resultados y estado IUCN cuando aplique.

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
| `API_RETRY_BACKOFF_SECONDS` | Multiplicador del tiempo de reintento entre errores | `2` |

## Comportamiento

- Se llama a `species.name_backbone(scientificName=...)` por cada fila.
- Entre llamadas se espera al menos `API_DELAY_SECONDS`.
- Errores HTTP transitorios (429, 502, 503, 504), fallos de red y respuestas HTML se reintentan con backoff exponencial.
- Si la API falla definitivamente, se escribe una fila con campos vacíos (excepto `originalID` y `originalScientificName`) y el error se registra en stderr.
- La salida se escribe incrementalmente fila a fila.

## Licencia

Ver [LICENSE](LICENSE).
