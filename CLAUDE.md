# CLAUDE.md

Un solo script: `ccl`, Python sin dependencias externas. Lista las sesiones
de Claude Code y salta a su ventana de iTerm2. El README explica qué hace y por qué existe;
esto son las trampas que no se ven leyendo el código.

## Flujo de git

**Se trabaja sobre `master` y se commitea ahí directamente.** Es un proyecto de un solo autor:
no hay PR que revisar ni nadie a quien no romperle la rama.

Si por lo que sea el trabajo acabó en una rama, el cierre es siempre el mismo: mergear a `master`
(en fast-forward, el historial va lineal), empujar, y **borrar la rama en local y en remoto**. No
se dejan ramas colgando.

Antes de empujar, las dos suites en verde: `python3 test_ccl.py` y `python3 test_panel.py`.
El CI **solo se dispara con push a `master`** (o con un PR), asi que empujar a una rama no prueba
nada.

## Trampas verificadas

Cada una costó encontrarla. Si "simplificas" alguna, vuelve el problema.

**El AppleScript no recorre sesión por sesión, a propósito.** Resolver la ruta completa
(`tty of session s of tab t of window w`) cuesta una llamada IPC por propiedad: tardaba 2,2 s
con 44 pestañas. `get_iterm_map()` usa dos consultas masivas y reconstruye la estructura en
Python (~0,5 s). Si lo reescribes con bucles anidados "más legibles", vuelves a los 2,2 s.

**Al coercer listas de AppleScript hay que fijar `text item delimiters`.** Sin eso,
`(tty of sessions of tabs of windows) as text` concatena sin separador
(`/dev/ttys035/dev/ttys036...`) y el resultado **enfoca ventanas equivocadas en silencio**.
Cualquier cambio ahí se verifica comparando contra la versión lenta, fila por fila.

**El `mtime` del transcript NO es la última actividad.** Se escribe en bloque: varias sesiones
acaban con la misma marca exacta. Usa el último campo `timestamp` de dentro del archivo.

**Los transcripts superan los 100 MB.** `read_transcript()` lee solo los últimos
`TAIL_BYTES` (64 KB) y descarta la primera línea si quedó cortada. Leerlos enteros hace el
comando inusable.

**Los códigos ANSI rompen `ljust()`**: cuenta los escapes como caracteres visibles y desalinea
las columnas. Para cualquier texto con color usa `vis()`, `pad()` y `clip()`, nunca `len()`
ni `ljust()` directos.

**`clip()` solo cierra el color si de verdad abrió uno.** Si no, en salidas sin color (pipes,
`--list`) aparece un `[0m` literal como texto.

**El panel repinta solo cuando `dirty`.** Sin ese flag repintaba cada 0,4 s aunque no cambiara
nada, quemando CPU. En reposo debe consumir 0 %.

**El refresco se relaja solo**: `REFRESH_SECONDS` (4 s) mientras interactúas,
`REFRESH_IDLE` (20 s) tras `IDLE_AFTER` (120 s) sin teclear. Cada ciclo cuesta ~0,2 s de CPU
entre `claude agents` y `osascript`; a 4 s fijos serían ~5 % de un núcleo indefinidamente.

**El cursor sigue al `sessionId`, no al índice.** La lista se reordena por actividad en cada
refresco; si el cursor fuera posicional, saltaría solo.

## Pausadas y vista de tabla

**Pausada es una marca del usuario, no un estado que dé Claude Code.** El JSON solo trae
`busy`/`idle`, asi que una sesion parada esperando a un compañero se ve igual que una que te
espera a ti. `Ctrl-P` la marca y **`is_waiting()` la excluye**: ahi esta todo el valor, porque
`-w`/`⌥N` dejan de mandarte a la unica que no puedes desatascar. Como `waiting_rows()` es la
unica fuente de verdad, el panel y el atajo global no pueden discrepar.

Los grupos de `grouped()` son **excluyentes**: una pausada que vuelve a `busy` se pinta en
TRABAJANDO (si corre, no espera a nadie) y una de background pausada sale solo en PAUSADAS. Si
añades un grupo, revisa que ninguna fila pueda caer en dos.

**Un solo escritor de `ccl-notes.json`: `guardar_estado()`.** El archivo ya guarda tres cosas
(notas por sesion, notas por repo, pausadas) y `save_note` se escribia el JSON entero por su
cuenta con dos claves — la primera nota borraba todas las pausadas. Por eso `load_state()`
devuelve las tres y **nadie mas llama a `escribir_json(NOTES_FILE, …)`**. Lo mismo vale para la
deteccion del formato viejo: mira las tres claves, porque un archivo que solo tuviera `pausadas`
se leia como el formato plano y la lista acababa de nota de un repo.

**La tabla se construye con `width - 4`.** El panel pinta cada fila como `clip(texto, cols - 4)`
—margen mas barra del cursor— asi que construyendola al ancho entero el recorte se comia la
ultima columna. Y la cabecera es peor: las lineas `head` **no se recortan al pintar**, asi que
una cabecera de exactamente `cols` columnas se salia una posicion y envolvia.

**`table_head` y `table_line` salen de `_tabla_columnas()`.** Es lo unico que las mantiene
alineadas; dos listas de anchos en paralelo divergen y la tabla deja de ser tabla. Las columnas
prescindibles (rama, modelo) **desaparecen** bajo su umbral en vez de encogerse: recortar todas
las columnas a la vez las vuelve ilegibles antes de que sobre sitio.

**La antiguedad ocupa 13, no 9.** Una sesion vieja pone `03-aug 17:52`, doce columnas; con nueve
se recortaba a `03-aug 1`, que no dice ni el dia entero ni la hora.

**`Ctrl-T` hay que quitarselo al terminal, no basta con el modo raw.** En macOS y los BSD es
`VSTATUS`: la disciplina de linea lo intercepta, imprime su `load: 0.60  cmd: python…` **encima
del panel** y manda SIGINFO. Nunca llega al programa. Y `read_key` entra en raw en CADA lectura y
lo restaura al salir, asi que entre lectura y lectura el tty esta en modo normal — una tecla que
caiga en esa ventana se la come el kernel. Es una CARRERA: en una maquina rapida se acierta casi
siempre, y por eso paso en local y fallo en el CI, cuyo runner de macOS es mas lento y caia
siempre. `_sin_tecla_status()` lo desactiva mientras dura el panel y `_restaurar_tty()` lo
devuelve. Si añades una tecla, mira antes si el terminal ya la usa (`stty -a`).

**La barra de estado se recorta (`clip`) al ancho.** Con seis atajos ya no cabe en una ventana
estrecha, y al envolverse empujaba el panel una linea hacia arriba en cada repintado.

## Contratos externos que pueden romperse

Dos dependencias no documentadas por Anthropic. Trátalas siempre como opcionales.

**`claude` no esta en el PATH de un lanzador.** Hammerspoon, Raycast, launchd y cron arrancan el
proceso con el PATH minimo de launchd (`/usr/bin:/bin:/usr/sbin:/sbin`), y con npm bajo nvm
`claude` vive en `~/.nvm/versions/node/<version>/bin` — ruta que ademas cambia al actualizar Node,
asi que no se puede fijar a mano en la config de nadie. Por eso `claude_bin()` busca fuera del
PATH (`CLAUDE_EXTRA`) y **elige por fecha, no por nombre**: ordenando los nombres, v25.9.0 queda
por delante de v25.10.0. Sin esto, `ccl -w` fallaba desde el atajo global y funcionaba desde la
terminal, que es el peor sintoma posible — parece cosa del atajo y no lo es. La alternativa
(`zsh -ic`) costaba ~0,7 s por pulsacion; `zsh -lc` no sirve, porque nvm se carga en `.zshrc` y
un shell de login no lo lee.

| Fuente | Qué se usa | Si cambia |
|---|---|---|
| `claude agents --cwd ~ --json` | `pid`, `cwd`, `kind`, `name`, `sessionId`, `startedAt`, `status` | El panel se queda sin datos |
| Transcript `<cfg>/projects/*/<id>.jsonl` | `timestamp`, `gitBranch`, `effort`, `message.model`, y los tipos `ai-title` / `last-prompt` | Esos campos desaparecen; el resto sigue |

Verificado en Claude Code v2.1.220: el JSON **solo** trae `busy`/`idle`. Los campos `state` y
`waitingFor` que aparecen en la documentación no existen en la salida real, y `--all` no añade
nada. Por eso los grupos que salen de los datos son dos —y no los tres del panel oficial—, y por
eso PAUSADAS lo marca el usuario a mano: no hay de dónde deducirlo.
## Cuándo cargar cada skill

Las trampas condicionales viven en `.claude/skills/`. Se cargan solas cuando su `description`
casa con lo que estás haciendo; esta tabla está por los síntomas que una `description` no dice.

| Trigger / situación | Skill |
| --- | --- |
| Escribir o arreglar tests; un test que pasa en local y falla en el CI; tocar `vis`/`pad`/`clip`, `assign_numbers`, `get_iterm_map` o `read_transcript` | `pruebas` |
| Añadir una tecla o acción al panel; tocar `read_key`, el parseo de secuencias de escape, el ratón o la ayuda paginada | `teclas-y-raton` |
| Tocar las notas (`Ctrl-N`), las pausadas (`Ctrl-P`), el editor del panel, `ccl-notes.json` o el color de la línea de detalle | `notas` |
| Añadir texto visible al usuario; tocar traducciones; regenerar `demo.svg` o `table.svg`; editar los README | `i18n-y-demo` |

Un guardarraíl que no depende de cargar nada: **ninguna acción del panel puede colgar de una letra
suelta**, porque se comería el filtrado. Hay un test que lo fija (`test_ninguna_accion_es_una_letra_suelta`).

## Lo que se pinta viene de fuera: `sin_control()`

El panel pinta el nombre de la sesion, el repo, la rama, el titulo y **el ultimo prompt**, y ese
ultimo sale del transcript de Claude Code — o sea de lo que se teclea **y se pega** ahi. Todo eso
pasa por `sin_control()` en `build()`, una vez, y no en cada sitio que pinta.

**El caso que importa no es el color, es `\033[2A`**: mueve el cursor dos lineas arriba y el texto
siguiente reescribe la fila de OTRA sesion. En una herramienta cuyo trabajo es "llevame a la sesion
correcta", falsear una fila es el peor fallo posible. `\n`, `\r` y `\t` ya se quitaban al normalizar
espacios; lo que llegaba intacto eran las secuencias que empiezan por ESC y el BEL.

**El orden de las alternativas del regex importa.** La del OSC va primera porque hay que comerse su
carga entera: puesta despues, la generica de dos bytes casa solo `ESC ]` y el payload
(`1337;SetUserVar=…`) se queda como texto visible en la fila.

De paso arregla un descuadre real: `ANSI_RE` solo reconoce SGR (`\033[…m`), asi que una secuencia
OSC no se contaba en el ancho visible — 51 columnas calculadas para 101 bytes.

**Por el editor de notas no entran escapes** y conviene saber por que, para no "simplificar" el
filtro: se acepta texto solo con `len(k) == 1 and k.isprintable()`, e `isprintable()` es False para
ESC, BEL, el RTL-override y los zero-width; ademas `read_key` intercepta ESC antes, como inicio de
secuencia. `save_note` lo sanea igualmente, porque el JSON se puede editar a mano.

**`ccl-notes.json` se escribe con 0600.** Son datos personales —nombres de gente, en que estas
esperando— y con el umask habitual (022) salia legible por el grupo. En una maquina de un solo
usuario no hay exposicion real, pero es gratis no dejarlo abierto.

## Multi-cuenta

`config_dirs()` detecta `~/.claude` mas los hermanos `~/.claude-*` con `projects/`.
Cada sesion se etiqueta con `_cfg` (su directorio de config) y `_account`.
**`read_transcript` necesita el `_cfg`**: sin el buscaria siempre en `~/.claude` y las
sesiones de la segunda cuenta saldrian sin rama, modelo ni prompt.

Si falla la cuenta principal se aborta; si falla una secundaria se ignora — no tiene
sentido dejar sin panel al usuario porque una config extra este rota.

## Estilo e idioma

| Qué | Idioma |
|---|---|
| `README.md` | inglés — es la portada del repo |
| `README.es.md` | español — traducción completa, misma estructura |
| **La interfaz** (ayuda, errores, barra de estado) | **inglés por defecto, español si el locale lo pide** |
| Código, comentarios, nombres de test, `CLAUDE.md`, `TODO.md` | español |

La regla de fondo: **lo que ve quien USA la herramienta sigue su idioma; lo que ve quien TOCA el
código va en español.** Los comentarios explican **por qué**, no qué hace la línea — casi todos
apuntan a una de las trampas de arriba.

**Los dos README van en paralelo: si tocas uno, toca el otro.** Tienen las mismas secciones en el
mismo orden justamente para que el diff sea comparable.
