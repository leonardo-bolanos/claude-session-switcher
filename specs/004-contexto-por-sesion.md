---
capacidad: context-usage
estado: implementada
modo: retroactivo
rutas:
  - ccl
  - test_ccl.py
  - test_panel.py
  - make_demo.py
  - demo.svg
  - table.svg
  - CLAUDE.md
  - README.md
  - README.es.md
ultima_verificacion_commit: 464e2bc
ultima_verificacion_fecha: 2026-11-10
---

# 004 · Cuánto contexto lleva cada sesión

> **Implementada** el 2026-11-10, sin versión publicada todavía. Se escribió antes del código, con
> las dos decisiones del usuario (abajo), y se reconcilió al terminar: salió como se diseñó; lo
> poco que cambió está en *Cómo quedó*.

## Qué se pide

> «Una vista para ver el estado % de contexto de cada sesión.»

Lo que hoy da la statusline de cada sesión (`41% /1000K`), pero de todas a la vez, en el panel.

**Decisiones del usuario** (2026-11-10):

1. **En las vistas que ya hay**, no en una aparte: una columna en la tabla (`Ctrl-T`) y un trozo
   `ctx 41%` en la línea de detalle de la lista, junto al modelo y el effort. Sin tecla nueva.
2. **El % solo**, con los colores de su statusline (`~/.claude/statusline.sh`): verde por debajo
   del 50 %, amarillo del 50 al 80, rojo desde el 80.

## De dónde sale (verificado el 2026-11-10, Claude Code 2.1.319)

Nada de esto está en `claude agents --json` ni en `sessions/<pid>.json`: los dos se miraron
campo a campo. La statusline lo recibe de Claude Code por stdin (`context_window.used_percentage`,
`context_window_size`), pero eso no queda escrito en ningún sitio.

| Dato | Fuente |
|---|---|
| **Tokens en contexto** | El `message.usage` de la última respuesta del hilo principal del transcript: `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`. Es la misma suma que usa la statusline (sin `output_tokens`). |
| **Tras compactar** | La entrada `system` con `subtype: "compact_boundary"` trae `compactMetadata.postTokens`. Sin ella, una sesión recién compactada seguiría marcando lo de antes hasta su siguiente respuesta. En 10 días de transcripts: 244 con `postTokens` y 7 sin él (versiones viejas). |
| **Tamaño de la ventana** | `<cfg>/cache/model-catalog/*.json`, el catálogo de modelos que cachea Claude Code: `runtime.max_input_tokens` por `id`. Hoy 1 000 000 para Opus 5.5, Fable, Sonnet 5/5.5 y Haiku 5.5, y 200 000 para `claude-haiku-4-5-20251001`. Coincide con lo observado: hay transcripts de Opus 5.5 con 967K tokens en contexto. |

Las 29 sesiones vivas del 2026-11-10 van de 73K a 484K (7-48 %).

### Por qué no basta la cola de 64 KB

En 6 de esas 29, la última respuesta queda **más atrás** que los 64 KB que lee
`read_transcript`: a 230-480 KB del final. En 5 es una autocompactación —tras el
`compact_boundary` Claude Code vuelve a inyectar los archivos como `attachment`, cientos de KB— y en
la otra son adjuntos sin más. Así que la cola no siempre trae ni la respuesta ni la marca.

## Comportamiento

| # | Requisito |
|---|---|
| R1 | La línea de detalle lleva `ctx 41%` después del modelo y el effort. |
| R2 | La tabla lleva una columna `ctx` con `41%`, delante de *visto*. Es prescindible como la rama y el modelo, pero la última en caer: aparece desde 86 columnas de tabla (más 11 con varias cuentas). Por debajo, el hueco se lo queda la nota. A 80, la fila ya va justa y se perdería el ⚠. |
| R3 | Color por umbral: verde < 50 %, amarillo 50-79 %, rojo ≥ 80 %. El % se redondea hacia abajo, para que el rojo salga en cuanto se llega al 80. |
| R4 | Si no se conoce la ventana (el modelo no está en el catálogo, o no hay catálogo), sale el número de tokens en gris (`ctx 412K`): sin % no hay color que dar. Es el caso de las sesiones de GLM. |
| R5 | Si no se sabe cuánto lleva (sin respuestas todavía, o compactada sin `postTokens`), no sale nada: ni columna rellena ni trozo en el detalle. |
| R6 | Una sesión recién compactada marca `postTokens`, no lo de antes de compactar. |
| R7 | Las filas recuperables (`--recent`, las grises de `--saved`) lo llevan igual: sirve para saber qué se va a reanudar. |
| R8 | Coste: lo de siempre en el caso normal. La búsqueda más atrás de la cola solo corre cuando la cola no trae nada, y su resultado se cachea por tamaño y `mtime` del transcript. El catálogo se lee una vez y se relee solo si cambia. |
| R9 | Si el formato del transcript o del catálogo cambia, se degrada a R4 o R5, sin errores. |

## Cómo quedó

- **`read_transcript`** añade `ctx` (tokens o None) y `ctx_model` (el `message.model` de la
  respuesta que lo dio). La regla vive en dos funciones que comparten la cola y la lectura lejana:
  - `_contexto_de_entrada` dice qué aporta una entrada. Ignora `isSidechain`, el modelo
    `<synthetic>` (los mensajes de error de la API, que traen uso a cero) y el uso a cero.
  - `_contexto_desde_el_final` recibe las entradas **de la más nueva a la más vieja**, y decide la
    primera respuesta del hilo principal o la primera `compact_boundary`. Si decide una
    compactación, sigue hacia atrás solo hasta encontrar el modelo de la respuesta anterior.
  - Las líneas cortadas se descartan al parsear.
- **`_contexto_lejano(ruta, firma)`**, con `firma = (tamaño, mtime_ns)`: si la cola no trajo ni
  respuesta ni marca, lee los últimos `CONTEXTO_BYTES` (2 MB). Le pasa a la misma regla un
  generador que va de atrás hacia delante y solo parsea las líneas con `"usage"` o
  `compact_boundary`, así que se detiene en cuanto decide. Lo cachea en un dict por ruta: una
  sesión compactada y parada no se vuelve a leer.
- **`ventana_de(modelo, cfg)`**: recorre los JSON de `<cfg>/cache/model-catalog/` y junta
  `{id: max_input_tokens}` de cualquier dict que tenga `id` y `runtime.max_input_tokens`. La
  caché es por `cfg`, con la firma `(nombre, mtime)` de los archivos. Busca el id exacto y, si
  no, sin el sufijo de fecha (`-20251001`). Si dos archivos dan valores distintos para un id, gana
  el mayor.
- **`build` y `fila_de_disco`** guardan `ctx` y `ctx_ventana` en la fila. **`marca_contexto(r)`**
  da el texto ya coloreado; la usan `detail_line` y la celda `ctx` de `table_line`.
- Textos: `col_ctx` y `ctx`, los dos `ctx`, en los dos idiomas. La etiqueta del detalle va en
  `DIM` y el valor con su color.
- **`make_demo.py`** da contexto a las sesiones de mentira (de 10 % a 83 %, los tres colores, y
  una de Haiku 4.5 con su ventana de 200K). Así `demo.svg` y `table.svg` lo enseñan.
- **Un test del panel exigía el prompt entero en `--list --table`.** Sin TTY la tabla sale a 110
  columnas; ahí ya entra la de contexto, que le quita seis a la nota, y «prompt de alfa» llega
  cortado. Es el reparto que fija R2, así que el test exige ahora solo el comienzo del prompt: lo
  que vigila es que el detalle vaya en la misma línea.
- De paso, el README decía que en una ventana estrecha caía «primero la rama, luego el modelo», y
  es al revés: el modelo cae por debajo de 120 y la rama por debajo de 106. Corregido en los dos
  README.

## Invariantes

- `table_head` y `table_line` siguen saliendo de `_tabla_columnas`.
- Ninguna línea desborda el ancho (los tests de siempre, con la columna nueva).
- Cero subprocesos nuevos.

## Criterios de aceptación

| # | Criterio | Cómo se verifica |
|---|---|---|
| CA1 | Tokens de la última respuesta principal. Se ignoran sidechain, `<synthetic>` y uso a cero. | `test_ccl.py`, transcript sintético. |
| CA2 | Tras un `compact_boundary`, `postTokens`. Sin `postTokens`, nada. Una respuesta posterior a la marca vuelve a mandar. | `test_ccl.py`. |
| CA3 | Con la última respuesta a más de 64 KB del final, se encuentra igual, y la segunda lectura sale de la caché. | `test_ccl.py`, con relleno de `attachment`. |
| CA4 | `ventana_de` lee el catálogo con la forma real (anidado, varios archivos), con fecha y sin ella. Sin catálogo da None; con un JSON roto también. | `test_ccl.py`, directorio temporal. |
| CA5 | Colores por umbral (49/50/79/80), redondeo hacia abajo, tokens en gris sin ventana, nada sin dato. | `test_ccl.py`. |
| CA6 | La columna aparece desde 86 y no a 80; ninguna fila desborda a ningún ancho, con varias cuentas tampoco. | `test_ccl.py` (`TestTabla`). |
| CA7 | Con los datos reales: las sesiones vivas sacan su %, y las 6 de la cola larga dan lo mismo que leyendo el transcript entero. | A mano, comparando con un recorrido completo. |

**Verificación** (2026-11-10):

- CA1-CA6 en verde, con 424 tests en `test_ccl.py` (22 en `TestContexto` y 2 en `TestTabla`),
  también sin locale.
- Comprobado mutando el código que los tests caen si:
  - se quita la regla de la compactación;
  - se quita la lectura lejana o su caché;
  - el umbral de la columna baja a 80;
  - se redondea en vez de truncar;
  - en el catálogo gana el último valor leído en vez del mayor. Este solo lo cazó tras invertir el
    orden de los archivos del test.
- CA7 con las 29 sesiones vivas: las 29 coinciden con un recorrido completo de su transcript,
  incluidas las 6 de la cola larga. En las compactadas sale lo que dejó la compactación
  (`11c29455`: 27K, no los 322K de antes). Las dos de GLM salen en tokens.
- Leer las 29 con las cachés ya calientes cuesta 14 ms en total.

## Fuera de alcance

- **Una vista aparte ordenada por %**: descartada por el usuario (decisión 1).
- **El % exacto de la statusline.** Claude Code no lo escribe en disco. Para tenerlo habría que
  tocar la statusline de cada usuario para que lo vuelque en un archivo.
- **Avisar** cuando una sesión pase del 80 %.
- **El umbral de autocompactación.** En los datos compacta entre 204K y 486K, muy por debajo de la
  ventana. No es un % fijo (hay un `away_summary` justo antes: parece compactar al volver tras un
  rato), así que no se puede pintar «cuánto le falta para compactar».

## Riesgos

- **El catálogo es un formato interno sin documentar**, como `sessions/<pid>.json`. Va a la tabla
  de contratos externos de `CLAUDE.md`, y si cambia, R4.
- **Una ventana distinta de la del catálogo** (un usuario que desactive el contexto de 1M, por
  ejemplo) daría un % por debajo del real. Se vería en cuanto pasara del 100 %, y no se recorta
  para que se vea.
- **`postTokens` es la estimación de Claude Code** tras compactar, no un uso medido por la API.
  Basta para un indicador.
