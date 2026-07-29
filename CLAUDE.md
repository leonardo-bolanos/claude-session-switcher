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
nada. Por eso hay dos grupos y no los tres del panel oficial.

## Cómo probar

`python3 test_ccl.py` cubre toda la lógica pura, sin dependencias. Son herméticos: parchean
`INDEX_FILE`, `HOME` y `config_dirs` a temporales — **si añades un test que llame a
`get_sessions`, parchea también `config_dirs` y `shutil.which`**, o pasará aquí y fallará en un
runner limpio, que es exactamente lo que ocurrió la primera vez que corrió el CI.

**Si tocas `vis`/`pad`/`clip`, `assign_numbers`, `get_iterm_map` o `read_transcript`, corre los
tests**: esas cuatro son justo las que han fallado en silencio antes.

`TestLecturaDeTeclas` si prueba `read_key` con un pty de verdad, porque es la unica forma de ver
como se descomponen las secuencias de escape. Dos detalles que lo hacian fallar:
**hay que escribir los bytes DESPUES de que `read_key` entre en modo raw** (`tty.setraw` usa
`TCSAFLUSH`, que descarta la entrada pendiente, asi que lo escrito antes se pierde) — de ahi el
`threading.Timer` — y `sys.stdin` se parchea sobre el modulo (`ccl.sys.stdin`), no sobre el del
test.

`pick_waiting` es puro y se prueba directo. **No lo pruebes llamando a `focus`**: robaria el
foco a quien este usando la maquina. El salto lo hace quien llama, justamente para esto.

**Para probar el panel entero, parchea `collect` con filas sinteticas y `REFRESH_SECONDS` alto.**
Sin eso la lista se reordena entre ejecuciones y con el refresco de fondo, y no puedes afirmar
que fila de la terminal corresponde a que sesion — que es justo lo que hay que verificar del
clic. Con datos fijos el layout es exacto: fila 1 cabecera, 2 grupo, 3 primera sesion, 4 su
detalle, 5 la segunda… Y `get_iterm_map()` devolviendo `{}` para no tocar ventanas de nadie.

`TestAyuda.test_ninguna_accion_es_una_letra_suelta` es un guardarraíl de diseño, no una
comprobación de formato: si documentas una acción en una letra, falla.

`python3 test_panel.py` arranca **el panel entero en un pty** y cubre lo que antes solo se podia
comprobar a mano: flechas, rueda, clic, doble clic, `⌥N`, la paginacion de la ayuda y los caminos
sin panel. Tarda ~1 min (32 arranques reales del programa), asi que va aparte de la suite rapida.
Las esperas se escalan con `CCL_TEST_LENTO` — el CI usa 2, porque un runner compartido es mas
lento y si no falla sin que nada este roto.

Lo que sigue SIN cubrir, porque necesita iTerm de verdad: el salto de ventana (`focus` con un
mapa real) y el refresco en segundo plano contra `claude agents`.

El modo interactivo necesita un TTY: no se puede probar con un pipe. Usa `pty.fork()` y **fija
el tamaño con `TIOCSWINSZ`** — sin eso el viewport queda diminuto y parece que faltan líneas
que sí están.

Al drenar la salida del pty, acota el tiempo. Un `while select(...)` sin límite no termina
nunca si el panel repinta.

**No pruebes `Enter` a ciegas: le roba el foco a quien esté usando la máquina.** Para verificar
que el panel no se cierra al saltar, usa una copia con `get_iterm_map()` devolviendo `{}`; el
salto falla con elegancia y se comprueba el flujo sin tocar ninguna ventana.

Los caminos no interactivos (`--list`, `ccl <n>`, salida por pipe) sí se prueban directo.

## Las teclas que NO pueden ser letras

Cualquier letra empieza a filtrar, asi que ninguna accion puede colgar de una letra suelta:
se comeria el filtrado de todo lo que empiece por ella. Paso con `r` (refrescar), que impedia
buscar por "revisa" o "report", y por eso ahora es `Ctrl-R`. Lo mismo descarta `h` para la
ayuda — hay sesiones que empiezan por h — de ahi que sea `?`, que ademas es el estandar en TUIs.

Si añades una accion nueva: tecla de control, o un simbolo que nadie escribiria al buscar.

**`Cmd` no existe para un programa de terminal.** iTerm2 se queda `⌘1..9` para cambiar de
pestaña y no lo pasa por el TTY: no hay forma de leerlo desde `ccl`. Por eso el salto a la
N-esima ESPERANDO es `⌥1..9`, que con «Left Option key: Esc+» llega como `ESC` + digito. Esa
misma secuencia es la que enviaria un `⌘N` mapeado a *Send Escape Sequence*, asi que el codigo
sirve para ambos caminos sin ramas extra. Si alguien pide "que sea Cmd", la respuesta es un
atajo global (Hammerspoon → `ccl -w<n>`), no una tecla del panel.

**`⌥1..9` cuenta sobre `rows`, no sobre las filtradas.** A proposito: la tecla significa
"sacame de aqui, a la que me espera", y contando sobre lo filtrado el mismo numero llevaria a
sesiones distintas segun lo que tuvieras escrito.

**`tty.setraw()` descarta la entrada pendiente, y eso comia teclas.** Usa `TCSAFLUSH` por
defecto, que tira lo recibido y no leido; como `read_key` entra en modo raw en CADA lectura, todo
lo que llegara mientras el panel repintaba se perdia. Medido con un pty: **de 5 teclas seguidas
sobrevivia 1**. Se notaba al escribir rapido en el filtro, y hacia imposible el doble clic
(sus cuatro eventos llegan en una sola rafaga). Va con `termios.TCSANOW` — si alguien lo
"simplifica" a `tty.setraw(fd)`, vuelve.

**El terminal NO reporta dobles clics**, solo clics sueltos: el doble se sintetiza por tiempo y
fila (`DOUBLE_CLICK`). Y el **release hay que descartarlo**, o cada clic simple contaria dos veces
y pareceria doble.

**El mapa fila-de-terminal → sesion se construye pintando, no calculando.** Va dentro del bucle
de repintado (`screen[y] = i`) porque cualquier cosa que se añada arriba —la cabecera de grupo
fija, un aviso— desplaza todo; un calculo aparte se desincroniza en silencio y el clic acaba
enfocando la sesion vecina, que es el peor fallo posible: parece que funciona.

**Con el raton activo, el terminal deja de gestionar la seleccion de texto.** Por eso existe
`CCL_MOUSE=0`, y por eso el apagado (`MOUSE_OFF`) va **antes** de soltar la pantalla alternativa:
si el panel muere con el raton activo, el shell recibe escapes por cada clic. Para copiar hay tres
vias y conviene no confundirlas: `⌥`+arrastrar (iTerm2 no reporta el evento si ese modificador
esta pulsado — verificado en el binario de iTerm2 3.6.11, que lo registra como *"Not reporting
mouse event because you pressed option"*), `CCL_MOUSE=0`, o `ccl --list`. La ultima es la mejor
para copiar de verdad: el panel usa pantalla alternativa, asi que **al salir se restaura lo que
habia y se lleva la lista**.

**La ayuda se pagina porque ya no cabe.** Se pinta de arriba abajo, asi que sin paginar lo que
sobra se va por el borde SUPERIOR: se pierde el principio y **no hay ningun aviso** de que faltaba
algo. Si añades secciones, `TestAyuda` comprueba que ninguna pagina desborde la altura y que al
partir no se pierda ninguna linea. Los tests que buscan un texto en la ayuda tienen que recorrer
**todas** las paginas (`_texto_completo`), no solo `render_help(...)`.

**Al parsear una secuencia de escape hay que leer byte a byte.** Antes hacia `os.read(fd, 2)`
de golpe, lo que impedia distinguir `ESC`+digito (sin corchete) de `ESC[`. De paso: `PgUp`/`PgDn`
son `ESC [ 5 ~` y `ESC [ 6 ~` — hay que **consumir la tilde**, o queda en el buffer y la lectura
siguiente la ve como un `~` escrito, arrancando un filtro por "~" al pulsar PgDn.

## Notas personales (`Ctrl-N`)

**Van por `cwd`, NO por `sessionId`.** Los sessionId cambian cada vez que reinicias Claude Code,
asi que una nota atada a la sesion se quedaria huerfana justo cuando mas hace falta. El precio,
aceptado: dos sesiones del mismo repo comparten nota.

**No se purgan las de directorios inexistentes.** Un disco externo desmontado o un repo movido de
sitio borraria algo que el usuario escribio a mano. Al contrario que `ccl-numbers.json`, que si se
purga, porque ahi el dato lo genera el programa y se puede regenerar.

**El modo edicion se queda el teclado, y va PRIMERO en el manejo de teclas.** Si no, en medio de
una frase la `q` cierra el panel y un digito arranca el selector por numero. Hay dos tests justo
para eso (`test_la_q_no_cierra_el_panel_mientras_escribes`).

**Al guardar hay que aplicar la nota en memoria a mano**, recorriendo `rows` por `cwd`. Si no, no
se ve hasta el refresco (4 s) y parece que no se guardo.

**La nota va en `NOTE` (negrita + cian), no en `CYAN` a secas.** La linea de detalle es casi toda
`DIM` y grises, y en cian plano la nota se perdia entre la rama y el modelo — justo lo contrario
de para lo que sirve. El codigo es `1;36` combinado y no `BOLD(CYAN(x))`: anidado deja dos resets
pegados.

**El editor arranca con la nota que ya hubiera** — corregir no es reescribir. Y el cursor `▏` del
prompt no es decoracion: sin el, una nota vacia no se distingue de "no estoy editando" y parece
que la tecla no hizo nada.

Ojo al probar el panel: `test_panel.py` parchea `collect`, que **se salta `build`**, y es build
quien pega las notas a las filas. El arnes replica ese paso; sin eso, la nota no reaparece al
reabrir el panel y parece un fallo de persistencia que no existe. Y `NOTES_FILE` se desvia a un
temporal: es el unico archivo que el panel escribe de verdad en disco.

## Multi-cuenta

`config_dirs()` detecta `~/.claude` mas los hermanos `~/.claude-*` con `projects/`.
Cada sesion se etiqueta con `_cfg` (su directorio de config) y `_account`.
**`read_transcript` necesita el `_cfg`**: sin el buscaria siempre en `~/.claude` y las
sesiones de la segunda cuenta saldrian sin rama, modelo ni prompt.

Si falla la cuenta principal se aborta; si falla una secundaria se ignora — no tiene
sentido dejar sin panel al usuario porque una config extra este rota.

## Estilo e idioma

Código, comentarios, mensajes al usuario, nombres de test y este archivo: **en español**. Los
comentarios explican **por qué**, no qué hace la línea — casi todos apuntan a una de las trampas
de arriba.

La excepción es el README, y solo por alcance: quien busca una herramienta para Claude Code busca
en inglés.

| Archivo | Idioma |
|---|---|
| `README.md` | inglés — es la portada del repo |
| `README.es.md` | español — traducción completa, misma estructura |
| Todo lo demás (`ccl`, tests, `CLAUDE.md`, `TODO.md`) | español |

**Los dos README van en paralelo: si tocas uno, toca el otro.** Tienen las mismas secciones en el
mismo orden justamente para que el diff sea comparable. El enlace cruzado va arriba, bajo el
titular.

Lo largo va en bloques `<details>` plegados: lo que un recien llegado necesita (que es, demo,
instalar, teclas) tiene que caber en la primera pantalla, y los detalles internos —el PATH de
launchd, la configuracion de iTerm2, el rendimiento del AppleScript— hundian eso.

`demo.svg` **se genera, no se edita**: `python3 make_demo.py` graba el programa de verdad en un
pty. Dos cosas que se rompieron al escribirlo y que no hay que "simplificar":

- **Los `<tspan>` van dentro de un `<text>`.** Sueltos no se renderizan: el SVG sale con el marco
  pintado y ni una letra.
- **Cada trozo lleva `textLength`.** Sin eso el visor usa el avance real de SU fuente, que no es
  el que asume el generador, y un trozo largo se monta encima del siguiente — se veia la comilla
  de cierre pisando la ultima letra del prompt.
- La animacion es **CSS, no SMIL**, y el primer fotograma queda visible por defecto: asi un visor
  que no anime (Quick Look, una vista previa cualquiera) muestra un fotograma fijo en vez de un
  rectangulo vacio.
