---
capacidad: model-advice-and-columns
estado: implementada
modo: retroactivo
rutas:
  - ccl
  - test_ccl.py
  - test_panel.py
  - make_demo.py
  - table.svg
  - CLAUDE.md
  - README.md
  - README.es.md
ultima_verificacion_commit: 7f85583
ultima_verificacion_fecha: 2026-11-11
---

# 005 · El modelo que recomienda la IA, y columnas a la carta

> **Implementada** el 2026-11-11, sin versión publicada todavía. Se escribió antes del código, con
> la decisión del usuario (abajo), y se reconcilió al terminar: salió como se diseñó; lo que se
> añadió por el camino está en *Cómo quedó*.

## Qué se pide

> «Coloca una nueva columna con el modelo recomendado por la IA para esa sesión. Una forma de
> esconder y mostrar columnas.»

Dos piezas que van juntas: la columna nueva aprieta una tabla que ya iba justa, y esconder las
que no miras es lo que le hace sitio.

**Decisión del usuario** (2026-11-11): la recomendación la da **Haiku, en segundo plano, solo
cuando aparece una sesión o cambia su tema**. Descartadas: pedirla con una tecla (coste cero, pero
la columna estaría casi siempre vacía) y reglas locales sin IA (gratis, pero adivina).

## De dónde sale la recomendación (verificado el 2026-11-11, Claude Code 2.1.319)

**Claude Code no la guarda en ningún sitio.** Lo más parecido es `advisorModel` en cada respuesta
del transcript, pero es el modelo asesor configurado (`claude-opus-5-5` o `claude-fable-5-1`), el
mismo en todas las sesiones: no recomienda nada. Así que hay que pedirla.

La llamada, medida a mano con tres sesiones:

```
claude -p --model haiku --no-session-persistence --restricted --strict-mcp-config
       --tools "" --disable-slash-commands --output-format json --json-schema <esquema>
       --system-prompt <guía> --max-budget-usd 0.05 <sesiones en JSON>
```

| Qué | Medido |
|---|---|
| Tiempo | 5 s |
| Coste | $0,0007 (1 659 tokens de entrada, 725 de salida) |
| Transcript | Ninguno (`--no-session-persistence`); no aparecería en `--recent` |
| `claude agents --json` | No aparece mientras corre; no se cuela en el panel |
| Hooks, MCP, CLAUDE.md | No se cargan (`--restricted` ignora los settings de usuario y proyecto; `--strict-mcp-config` sin `--mcp-config` deja cero servidores) |
| Respuesta | `structured_output` con la forma del esquema |

`--bare` no sirve: exige `ANTHROPIC_API_KEY` y no lee el OAuth de la suscripción.

**El último prompt engaña, y el título también.** En la prueba, la sesión de este repo («Add
context percentage view per session») salió `haiku` porque su último prompt era «comit push».
Y en la primera versión, que solo mandaba el título y el último prompt, la sesión más cara del día
(«new Web php 8.5», una migración por `ssh` y `sed`) salió `sonnet`: Claude Code la había
retitulado con su última subtarea, «agregar a lista de máquinas web». Lo comprobó el usuario
contrastándola con una revisión hecha a mano. Por eso Haiku recibe también el **nombre** de la
sesión y **lo que ha hecho** (R15).

## Comportamiento

| # | Requisito |
|---|---|
| R1 | La tabla lleva una columna `ia` con la familia recomendada: `haiku`, `sonnet`, `opus` o `fable`. Va detrás de `modelo`, para compararlas de un vistazo. |
| R2 | Si coincide con la familia que usa la sesión, sale tenue. Si no, con el color de su familia y una flecha: `↓sonnet` (bastaría uno más barato), `↑opus` (le haría falta uno mejor). Si el modelo actual no es de Claude (GLM), sin flecha. |
| R3 | Se pide por sesión viva **cuando su tema es distinto del de la última recomendación**: al aparecer, cuando Claude Code le cambia el título y cuando la renombras. El tema es el `ai-title`, y si no hay, el nombre de la sesión: una sesión con nombre desde el principio nunca recibe `ai-title`. Sin ninguno de los dos, no se pide. |
| R4 | Solo lo pide el **panel**, en un hilo aparte: nunca bloquea el pintado. `--list`, `-w` y los demás comandos enseñan lo que haya guardado y no llaman a nada. |
| R5 | Una sola llamada a la vez, con todas las pendientes (hasta 20), y al menos 30 s entre una y la siguiente. Si falla, esas sesiones no se reintentan en 10 minutos. |
| R6 | Se guarda en `~/.claude/ccl-ia.json`: `{sessionId: {titulo, modelo, porque, cuando}}`. Es caché: si se borra o se rompe, se vuelve a pedir. Se purgan las entradas de más de 30 días. |
| R7 | La recomendación solo vale para el tema con el que se pidió. Si el `ai-title` cambió, la columna sale vacía hasta que llegue la nueva (unos segundos). |
| R8 | `CCL_IA=0` apaga las llamadas. Sin `claude` en el sistema, tampoco se hacen. |
| R9 | La guía de la llamada es la de la skill `claude-models` §2, y el `porque` viene en el idioma de la interfaz. El `porque` se guarda pero no se pinta (fuera de alcance). |
| R15 | Por cada sesión se manda su nombre, su título, el último prompt recortado, el modelo y effort actuales, y cuántas veces ha usado cada herramienta y cada programa de Bash en los últimos 8 MB del transcript (solo los nombres, sin argumentos). La guía le dice que juzgue por ese trabajo real. |
| R16 | Cada recomendación guarda la versión del criterio (`v`). Si cambia lo que se manda, lo pedido con el criterio viejo deja de valer y se vuelve a pedir una vez. |
| R17 | **`a_mano`**: el usuario puede fijar la recomendación de una sesión escribiendo `"a_mano": "<familia>"` en su entrada de `ccl-ia.json`, o creando una con solo eso. Manda sobre Haiku sea cual sea el tema, esa sesión ya no se pregunta, y no caduca ni se pierde al cambiar de versión. Vale cualquier forma que diga la familia (`Sonnet-5-5`). Una errata no se aplica, pero tampoco se borra. Pedido por el usuario el 2026-11-11. |

### Columnas a la carta

| # | Requisito |
|---|---|
| R10 | `Ctrl-E` abre un selector con las columnas que se pueden esconder: estado, cuenta (solo con varias), repo, rama, modelo, ia, ctx, visto. Las demás no: el número es lo que se teclea, el nombre es la sesión, y la nota se queda el sitio que sobra. |
| R11 | En el selector: `↑ ↓` mueven, `espacio` o `enter` marcan y desmarcan, `esc` o `Ctrl-E` vuelven. Cada cambio se ve al volver. |
| R12 | Desde la vista de lista, `Ctrl-E` pasa a la tabla y abre el selector: las columnas son de la tabla. |
| R13 | Se recuerda entre arranques, en `ccl-notes.json` (`columnas_ocultas`), por el escritor único `guardar_estado`. Cuenta también para `ccl --list --table`. |
| R14 | Esconder una columna le deja su sitio a las demás. Las prescindibles siguen cayendo por anchura, en este orden: primero `ia`, luego modelo, luego rama y al final ctx. Sin nada escondido, los umbrales de antes no cambian (ctx 86, rama 106, modelo 120) e `ia` aparece desde 128. Con varias cuentas, 11 más. |

## Cómo quedó

- **`_tabla_columnas(width, multi, ocultas=())`** pasó de umbrales fijos a un reparto. Primero
  van las fijas visibles (`_FIJAS`). Después, las prescindibles por prioridad
  (`_PRESCINDIBLES`: ctx, rama, modelo, ia), cada una con la nota mínima que se le garantiza a la
  cola (9, 16, 21, 21). Con `ocultas` vacío da exactamente los umbrales de antes. Una
  prescindible que no cabe corta las siguientes: a 119 cabría `ia` por ancho, pero no sale porque
  `modelo` ya no cabe. El orden de pintado es aparte (`_ORDEN_COLUMNAS`), con `ia` detrás de
  `modelo`.
- **`marca_ia(r)`** pinta la celda (R2), como `marca_contexto`. `familia()` saca la familia del
  nombre corto o largo del modelo.
- **`build` y `fila_de_disco`** ponen `ia` en la fila con `recomendacion(cache, sid, titulo)`, que
  solo devuelve algo si el tema coincide (R7). `leer_ia()` se cachea por tamaño y `mtime`, porque
  `--recent` monta hasta doscientas filas.
- **`Recomendador`** lo crea `interactive`, y `pedir(filas)` se llama en cada refresco del `Feed`
  (no en el modo de recuperables). Decide las pendientes (R3, R5) y lanza `_correr` en un hilo con
  copias de las filas. Al terminar, `guardar_ia` escribe la caché, purgando lo caducado, y
  `feed.force()` refresca, que es lo que pinta el resultado. Un fallo, o una sesión que la
  respuesta no trae, va a `fallos` con su tema.
- **`pedir_recomendaciones(lote)`** hace la llamada con `stdin=DEVNULL`, el texto por `argv` y
  `cwd` en el directorio temporal. Ids `s1…sN` para no mandar los `sessionId`. El último prompt va
  recortado a 300 caracteres. El `porque` se sanea con `sin_control` y se recorta a 80. Nunca
  lanza.
- **`actividad_reciente(sid, cfg)`** (R15) lee los últimos `IA_VENTANA` (8 MB) del transcript, solo
  en el hilo y solo al pedir: 0,13 s para trece sesiones. Cuenta los `tool_use` del hilo principal,
  con los MCP juntos por servidor (`mcp:Zoho_Sprints`). Con 2 MB, en una sesión pesada solo
  entraban sus últimas ~70 llamadas, que son la última subtarea y no la sesión.
- **`_comandos_de(orden)`** saca los programas de una orden de Bash: parte por `&&`, `||`, `;` y
  saltos de línea, pero no por la tubería, porque lo de detrás de un `|` es un filtro. Vacía lo
  entrecomillado y corta en el heredoc, porque su contenido (`import`, `def`, `EOF`) no son
  órdenes. Salta `cd`, `echo` y compañía, y los prefijos `do`, `then`, `sudo` y `time`. Hace
  falta porque mucho trabajo de código va entero por Bash: «new Web php 8.5» hizo 1 410 llamadas
  a Bash y 66 ediciones en dos días.
- **`tema_de(fila)`** (R3) da el `ai-title` o, si no hay, el nombre. La primera versión pedía solo
  con `ai-title`, y el usuario vio la columna vacía en cuatro sesiones vivas: «Éxito por opción»,
  «Sección agentes», «Cobranza voz fricciones» y «Paola Colsanitas ION». Sus transcripts tenían
  cero `ai-title` y decenas de `custom-title`, porque tenían nombre desde el principio y Claude
  Code no les genera título. Con el arreglo, una llamada de 5 s las rellenó.
- **`IA_VERSION`** (R16) va en cada entrada de la caché, y `leer_ia` descarta las de otra
  versión.
- **`a_mano`** (R17): `leer_ia` devuelve una vista limpia con `a_mano` normalizado por `familia()`
  y la parte de Haiku solo si es de la versión actual. `recomendacion` mira primero `a_mano`, y
  como `pendientes` usa `recomendacion`, una sesión fijada no se pregunta. `guardar_ia` parte del
  archivo crudo, no de la vista: conserva las entradas con `a_mano` (sin purgarlas por edad, y
  también con una errata) y se lo mantiene a la que reescribe con la respuesta de Haiku. Va en
  la ayuda, junto a la columna.
- **`Ctrl-E`** es `"columnas"` en `read_key`. `elegir_columnas` es un bucle propio, como el de la
  ayuda: `↑ ↓` (y la rueda), `espacio`/`enter` o un **clic** en la fila, y `esc`, `q` o `Ctrl-E`
  para volver. `render_columnas` pone la primera en la fila 3 de la terminal, y los clics cuentan
  con eso. Cada columna lleva una frase de qué es. Al pie, el aviso de que una marcada puede caer
  igual por ancho: si no, el usuario la marca, no la ve y cree que no funciona.
- **`columnas_ocultas()`** lee el estado como `orden_proyectos()` y solo acepta nombres de
  `COLUMNAS_OCULTABLES`. `guardar_estado(…, ocultas=None)` las conserva si no se las pasan, y
  `load_state` reconoce la clave al detectar el formato. `render` (`--list --table`) las respeta.
- **La barra de estado** lleva `^E columnas` solo en la vista de tabla. **La ayuda** tiene tres
  filas nuevas en *vista de tabla*: `Ctrl-E`, qué es `ia` con sus flechas, y `CCL_IA=0`.
- **Tras la revisión de código del cierre** (nueve hallazgos; seis arreglados):
  - La columna `ia` no ocupa sitio si ninguna fila trae nada (`ocultas_de_verdad`). Con
    `CCL_IA=0`, sin `claude` o antes de la primera respuesta, eran ocho columnas vacías.
  - Escondida la columna de estado, la tabla por estado recupera las cabeceras de grupo. Si no,
    dejaba de decir quién te espera, que es para lo que existe `ccl`.
  - `guardar_ia` no escribe si el archivo existe y no se entiende (una coma de más al editar
    `a_mano`), y eso cuenta como fallo para no volver a pagar cada 30 s. `escribir_json` pasó a
    escribir en un temporal y hacer `os.replace`, para todos los JSON de `ccl`.
  - `_sin_heredocs` quita solo el cuerpo de un heredoc. Antes se cortaba en el primer `<<`, y se
    perdía el `git push` de un `git commit -m "$(cat <<'EOF' …)" && git push`.
  - El selector se repinta si cambia el ancho de la ventana, y solo entonces o al pulsar.
  - Los fallos caducados se purgan; antes, un panel abierto días los acumulaba.
  - Descartados, con motivo:
    - El coste de leer 8 MB por sesión: medidos 0,13 s para trece.
    - Que `Ctrl-E` desde la lista deje la tabla puesta: es R12, a propósito.
    - Que la IA venga activada por defecto: es decisión del usuario, pendiente antes de publicar
      (ver *Riesgos*).
- **`make_demo.py`** da una recomendación a cada sesión de mentira (la misma, `↓haiku` y
  `↑sonnet`) y graba la tabla a 140 columnas, porque a 128 la de la IA no entraba. Los dos
  arneses de prueba (`test_panel.py` y `make_demo.py`) desvían `IA_FILE` y ponen `CCL_IA=0`.

## Criterios de aceptación

| # | Criterio | Cómo se verifica |
|---|---|---|
| CA1 | Pendientes: sesión nueva con título sí; mismo título no; título cambiado sí; sin título no; recuperables no; en vuelo o con fallo reciente no. | `test_ccl.py` |
| CA2 | La respuesta se valida: ids que no se enviaron, familias desconocidas, JSON roto o `is_error` no entran en la caché. | `test_ccl.py`, con `subprocess.run` simulado |
| CA3 | La llamada lleva `--no-session-persistence`, `--restricted`, `--tools ""`, `--model haiku`, `stdin=DEVNULL`, y no se hace con `CCL_IA=0` ni sin `claude`. | `test_ccl.py` |
| CA4 | `marca_ia`: igual tenue, `↓` más barato, `↑` mejor, sin flecha si el actual no es de Claude, nada sin dato. | `test_ccl.py` |
| CA5 | `_tabla_columnas`: umbrales de siempre con nada oculto; `ia` desde 128 y no a 127; esconder hace sitio; ninguna fila desborda con ningún subconjunto oculto a ningún ancho. | `test_ccl.py` |
| CA6 | `columnas_ocultas` sobrevive a guardar una nota o una pausa, descarta nombres desconocidos, y un archivo con solo esa clave no se lee como el formato viejo. | `test_ccl.py` |
| CA7 | En el panel: `Ctrl-E` desde la lista abre el selector en la tabla; esconder `repo` lo quita de la cabecera y queda guardado. | `test_panel.py` |
| CA8 | Con las sesiones reales: cada una recibe su recomendación en una sola llamada, y un segundo arranque del panel no vuelve a pedirla. | A mano |
| CA9 | La actividad cuenta solo el hilo principal, junta los MCP por servidor, se limita a la ventana y a las más usadas; los programas salen bien de tuberías, comillas, heredocs, asignaciones y bucles; a Haiku le llegan el nombre y la actividad, no el `sessionId`; lo pedido con otra versión se vuelve a pedir. | `test_ccl.py` |
| CA10 | Con las sesiones reales, el veredicto coincide con una revisión hecha a mano en las que la revisión daba por claras. | A mano |
| CA11 | `a_mano` manda sobre Haiku y sobre el tema, sin tema también; una errata no cuenta y no se borra; no se pregunta por esa sesión; sobrevive a una escritura de Haiku, a la caducidad y a otra versión; la fila de disco lo lleva. | `test_ccl.py` |

**Verificación** (2026-11-11):

- CA1-CA6, CA9 y CA11 en verde, con 471 tests en `test_ccl.py`: 26 en `TestRecomendacionIA`, 4 en
  `TestMarcaIA`, 12 en `TestColumnasOcultas` y 5 en `TestSelectorDeColumnas`. Sin locale también.
  Los arreglos de la revisión: siete mutaciones, siete caídas.
- CA7 en `test_panel.py`
  (`test_ctrl_e_desde_la_lista_esconde_una_columna_y_lo_recuerda`).
- Mutando el código, los tests caen en diez de diez casos:
  - pedir también por las recuperables;
  - `continue` en vez de `break` en el reparto;
  - ignorar el tema en `recomendacion`;
  - quitar `--no-session-persistence`;
  - no conservar las ocultas al guardar una nota;
  - invertir la flecha;
  - quitar la pausa entre llamadas;
  - aceptar familias inventadas;
  - quitar el plazo tras un fallo;
  - que `--list --table` ignore las ocultas. Esta última sobrevivió al principio: el test usaba
    un repo más largo que su columna, que salía recortado se escondiera o no. Corregido.
- Y con R15-R16, siete de ocho: ignorar la versión, contar los subagentes, no mandar el nombre,
  contar el heredoc, quitar los prefijos, no juntar los MCP, quitar el tope. La octava (no cortar
  por la tubería al leer cada trozo) sobrevivió porque ese código era muerto: solo se toma la
  primera palabra de cada trozo, y la tubería no parte trozos. Se quitó, y partir por `|` sí lo
  caza el test.
- CA8 con las sesiones del 2026-11-11: 11 vivas, 7 con `ai-title`. Una sola llamada de 5,9 s, sin
  fallos, y la segunda pasada no dejó ninguna pendiente. A 160 columnas la tabla enseña `ia` con
  sus flechas (`↓sonnet` en tres de Opus, `↑opus` en una de Sonnet). A 127 cae la primera, y
  escondiendo la rama vuelve.
- CA10, contra la revisión a mano del 2026-11-11 (gasto de dos días y herramientas de 48 h por
  sesión). Con R15, de nueve sesiones vivas: «new Web php 8.5» pasó de `sonnet` a `opus`, y
  «Coordinador Informes Clientes A» de `opus` a `sonnet`, que es lo que daba la revisión. «single
  sign on» y «logs maquinas» siguen en `opus`. «loops» sale `↑opus` (102 ediciones), y «deepseek
  cambia precios» `opus` por su `ssh` y `git`. Ahí la revisión la veía candidata a Sonnet, pero es
  discutible. Tres llamadas de 8-9 s, sin fallos.
- `a_mano`: las cuatro mutaciones caen (que no mande, que caduque, que Haiku lo pise, no
  normalizarlo). Con una copia de la caché real y `"a_mano": "sonnet"` en «logs maquinas», la
  tabla pasó de `opus` a `↓sonnet` y esa sesión dejó de salir entre las pendientes.

## Fuera de alcance

- **Pintar el `porque`.** No cabe en la tabla. Si hace falta, el sitio natural es la línea de
  detalle de la lista.
- **La columna en la vista de lista.** Se pidió una columna; la lista no tiene columnas.
- **Recomendar effort.** Va implícito en el `porque`, si acaso.
- **Cambiar el modelo de la sesión.** El panel no escribe en las sesiones.
- **Reordenar columnas.** Solo esconder y mostrar.

## Riesgos

- **Coste.** Una llamada por tema nuevo, agrupadas: con ~30 sesiones y unos pocos cambios de tema
  al día, céntimos al mes. El tope `--max-budget-usd 0.05` corta una llamada desbocada.
- **Privacidad.** El nombre, el título y el último prompt de cada sesión, y los nombres de las
  herramientas y programas que usó, van a Anthropic, que es quien ya los tiene. `CCL_IA=0` lo
  apaga.
- **Activada por defecto, también para quien instale `ccl` por Homebrew.** El usuario la eligió
  para él. Antes de publicar la 1.6.0 queda por decidir si para los demás debe ser opt-in
  (`CCL_IA=1`), o anunciarse al primer arranque: gasta cuota de la suscripción sin que nadie lo
  haya pedido. Lo señaló la revisión de código del cierre.
- **Flags de `claude -p`.** Son interfaz pública del CLI, pero si cambian, la llamada falla y la
  columna se queda vacía (R5): el panel sigue igual.
