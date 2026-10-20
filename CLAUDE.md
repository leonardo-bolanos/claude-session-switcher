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

**El cursor sigue a la sesión, no al índice.** La lista se reordena por actividad en cada
refresco; si el cursor fuera posicional, saltaría solo.

**Y la identidad de una fila es el PROCESO, no el `sessionId`** (`clave_de()`). `claude --resume`
sobre una conversación que sigue abierta en otra pestaña no crea una nueva: dos procesos con el
mismo sessionId. Con el sessionId como identidad salían con el mismo número y el cursor, al bajar
a la segunda, volvía a encontrar la primera — "al bajar con flechas no me deja pasar". Ahora
`_marcar_claves()` (en `get_sessions`) deja el sessionId a secas a la más antigua y
`sessionId@pid` a las demás; la numeración y el cursor van por esa clave. Lo que es de
la conversación —nota, pausa, escritorio— sigue por sessionId, y es correcto: es la misma.

**La clave de una copia es pegajosa.** Si se cierra la ORIGINAL —que es lo que pide el aviso
rojo—, la copia pasaría a ser `sessionId` a secas: heredaría el número de la otra y el cursor, que
la seguía por su clave, saltaría arriba. `assign_numbers()` le conserva `sessionId@pid` mientras
siga en el índice. Por lo mismo `--save` deduplica por sessionId y no por clave: filtrando por
"clave == sessionId", una copia superviviente no se guardaba.

Y se **avisa en rojo** (`marcar_duplicadas()`, al final de `build`): las dos escriben en el mismo
transcript y casi nunca es lo que quieres. Va en las DOS filas, no solo en la copia, y con el
número de la gemela (`misma conversación que [26]`), que es lo que hace falta para decidir cuál
cerrar; el rojo solo no se ve en `--list | pbcopy`. Las recuperables no cuentan como gemelas.

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

**Entre lectura y lectura el kernel edita la linea, y hay que quitarselo.** `read_key` entra en
raw en CADA lectura y lo restaura al salir, asi que mientras el panel repinta o refresca el tty
esta en modo normal, y una tecla que cae en esa ventana la procesa la disciplina de linea antes de
que nadie la lea. Medido en un pty: `Ctrl-T` (VSTATUS) imprime su `load: 0.60  cmd: python…`
encima del panel; `Ctrl-R` (VREPRINT) pinta un `^R`; el retroceso, `Ctrl-W` y `Ctrl-U` editan la
linea del kernel y no llegan; con ECHO cualquier letra se pinta sobre el panel. Y el peor,
**`Ctrl-O` es VDISCARD: se come la tecla y DESCARTA TODA LA SALIDA** hasta el siguiente `Ctrl-O`
— el panel se queda congelado y parece que ccl se ha colgado.

Es una CARRERA: en una maquina rapida se acierta casi siempre, y por eso pasaba en local y la
cazo dos veces el runner de macOS del CI, que es mas lento — primero con `Ctrl-T` y luego con
`Ctrl-O`. El primer arreglo apagaba solo VSTATUS, y se quedo corto por lo mismo que se quedaron
cortas las flechas: tecla a tecla siempre falta una. `_preparar_tty()` apaga ICANON, IEXTEN y
ECHO mientras dura el panel (ISIG se queda: Ctrl-C y Ctrl-Z siguen siendo señales) y
`_restaurar_tty()` lo devuelve. `TestEntreLecturas` lo prueba SIN carrera: escribe las teclas
antes de leer, que es justo esa ventana, y lleva su caso de control.

**El fondo de la fila del cursor hay que REARMARLO tras cada reset.** El texto ya viene
coloreado y `c()` cierra cada trozo con `\033[0m`, que apaga tambien el fondo: sin rearmarlo, la
banda se corta en el primer color y el resto de la fila queda pelada — parece un fallo de pintado,
no un resalte. Y hay que **rellenar hasta el ancho** con `pad()`, porque un fondo solo llega hasta
donde llega el texto. Todo eso vive en `con_fondo()`, y el `▌` se queda ademas de la banda: es lo
unico que marca la fila en un terminal sin 256 colores o con `CCL_CURSOR_BG=0`.

**La barra de estado se recorta (`clip`) al ancho.** Con seis atajos ya no cabe en una ventana
estrecha, y al envolverse empujaba el panel una linea hacia arriba en cada repintado.

## Sesiones dentro de tmux

**Una sesion en un panel de tmux es invisible para `get_iterm_map()`.** Su tty es el
pseudoterminal que creo tmux, no el de iTerm, asi que salia siempre con el ⚠ de "no la
encuentro" — y es justo la que mas interesa localizar, porque **sobrevive a que el terminal se
caiga**.

**El puente entre los dos mapas es el tty del CLIENTE.** `get_tmux_map()` devuelve
`{tty del panel: (destino, sesion, tty del cliente)}`, y ese ultimo si es un tty de iTerm: es
donde esta enganchada la sesion de tmux. `build()` resuelve `row["iterm"]` con el, no con el tty
del panel.

**Sin cliente (detached) no es un error.** Es el caso de "se cayo iTerm y tmux aguanto": entonces
`focus()` engancha la sesion en una pestaña nueva (`tmux attach`) en vez de decir que no la
encuentra. Y el `select-pane` va SIEMPRE, este enganchada o no, para que al aparecer la pestaña ya
este en el panel correcto.

**Dos consultas, ~11 ms.** Misma leccion que con AppleScript: nada de un comando por sesion. Sale
gratis si no hay tmux instalado o no hay servidor levantado — `_tmux()` devuelve None y el mapa
queda vacio, que es el caso de casi todo el mundo.

## Devolver una sesion a su escritorio (Spaces)

**No se mueve ninguna ventana, y eso es la decision entera.** `hs.spaces.moveWindowToSpace` esta
roto desde macOS 15 (devuelve `true` sin mover nada) y el unico apaño que existe —arrastrar la
miniatura en Mission Control— **con iTerm falla**: la suelta en pantalla completa. Esta todo
documentado en el skill `space-restore` del usuario, que se peleo con ello durante dias.

Se hace al reves: **`gotoSpace` al destino y luego crear la ventana ahi**. Una ventana nueva nace
en el Space activo. Verificado en vivo.

**Hay que mover el CURSOR a la pantalla destino antes.** iTerm crea la ventana en el monitor donde
esta el raton, no en el que tiene el Space activo: sin eso la ventana nace en el monitor
equivocado y todo el ejercicio no sirve. Medido — pasaba siempre.

**Y hay que crear una VENTANA, no una pestaña.** Una pestaña se añade a la ventana actual, que
puede estar en otro escritorio. Por eso `pestaña_nueva()` recibe `space` y cambia de modo.

**El Space se aprende usando `ccl`.** `try_focus()` lo apunta despues de enfocar con exito: la
ventana esta delante, asi que el Space activo ES el suyo.

**Y ademas se puede LEER de todas las ventanas a la vez** (`spaces_de_ventanas()`). Aqui ponia que
los ids de iTerm y los de Hammerspoon "eran mundos distintos y no casaban", y **era falso**: el
`id of window` del AppleScript de iTerm es el CGWindowID, el mismo numero que devuelve
`hs.spaces.windowsForSpace(sid)`. Verificado el 2026-10-12 con doce ventanas: las doce aparecian
tal cual, cada una en un solo escritorio, en 0,03 s. Lo usa `--save`. El aprendizaje por salto se
queda porque cubre a `--recent` cuando no hubo foto: sin un `--save` previo, es lo unico que sabe
donde vivia cada sesion.

**Se guarda el ORDINAL, no el ID.** Los IDs de Space cambian entre reinicios. El orden es el de
`allScreens()` y dentro de cada pantalla el de `spacesForScreen`, solo los de tipo `user` — la
misma convencion que el sistema de restauracion del usuario, para que los numeros coincidan.

**Todo esto es opcional.** Sin Hammerspoon, `_hs()` devuelve None y `ccl` funciona igual: se abre
la pestaña donde caiga. Y `_hs` busca una MARCA en la salida porque `hs -c` escupe sus
"-- Loading extension: ..." la primera vez que toca una extension.

## Recuperar sesiones muertas (`--recent`)

**Cuando el terminal se cae, `claude agents --json` deja de ver las sesiones — y a veces no ve
NADA.** Medido en una caida real: 20 sesiones perdidas y el registro devolviendo `[]` aun con dos
procesos `claude` vivos. Por eso `recent_rows()` no se apoya en el: si `get_sessions()` falla,
asume que no hay ninguna viva y las lista todas. Fallar ahi seria fallar exactamente en el
escenario para el que existe la funcion.

**El estado esta en el transcript, no en el proceso.** `cwd`, `sessionId`, `timestamp` y
`gitBranch` salen del `.jsonl`, y con eso `claude --resume <id>` la recupera. El nombre del
archivo **es** el sessionId (verificado); el `cwd` hay que sacarlo de dentro, porque el nombre del
directorio de `projects/` codifica la ruta con guiones y eso no se puede deshacer sin ambiguedad.

**El `mtime` solo preselecciona candidatos.** El orden final va por el `timestamp` de dentro, por
la misma razon de siempre: el transcript se escribe en bloque y varias sesiones comparten mtime.
Se leen `limite * 3` colas y se recorta despues.

**`is_waiting()` excluye las recuperables**, o `-w`/`⌥N` te mandarian a una sesion que ya no
existe. Y **no llevan el ⚠**: ese simbolo significa "esta viva y no la encuentro en iTerm", que en
una muerta es alarmar por lo normal.

**`FeedFijo` existe porque el `Feed` normal las borraria.** Refresca llamando a `collect()`, que
devuelve las vivas: a los cuatro segundos la lista de recuperables se sustituiria sola.

**Al reanudar hay DOS capas de comillas.** La ruta se entrecomilla con `shlex.quote` para el
shell, y el comando entero entra en el AppleScript por `argv`, nunca interpolado — la ruta sale
del transcript, o sea de fuera. Hay tests para las dos.

Limitacion conocida y documentada en el README: si el registro esta desactualizado puede colarse
una sesion viva, y reanudarla abre una segunda pestaña sobre la misma conversacion.

## Guardar y restaurar (`--save` / `--restore`)

Para el reset **planificado** del terminal. `--recent` no servia para esto: lista las cien y pico
del disco, no "las que tenia abiertas", y reanuda de una en una. `--save` apunta en
`ccl-snapshot.json` las vivas con su ventana, pestaña y escritorio; `--restore` las devuelve
agrupadas por ventana, con sus pestañas en orden, recorriendo los escritorios una sola vez.

**Con cero sesiones `--save` NO escribe nada**, y la foto anterior se conserva como `.prev`. El
momento mas probable para teclearlo por error es justo DESPUES del reset, con la lista vacia:
sobrescribir ahi tiraria la foto buena.

**`--restore` salta las que ya estan vivas.** Restaurar dos veces, o sin haber reseteado nada, no
puede duplicar conversaciones. Y salta las que ya no tienen directorio: el `cd` fallaria y
quedaria una pestaña con un error. `--restore --list` enseña el plan sin abrir nada.

**Un AppleScript por ventana, escribiendo en los objetos creados** (`set w to (create window…)`,
`set t to (create tab…)`). Mismo motivo que `pestaña_nueva`: tras cambiar de escritorio la
ventana nueva aun no es la "current", y escribir ahi teclea el comando en la que tenias delante.

**Se reanuda con su cuenta.** `orden_reanudar()` pone `CLAUDE_CONFIG_DIR` cuando la sesion es de
una cuenta secundaria. Faltaba tambien en `--recent`: una sesion de `~/.claude-personal` se
buscaba en la principal y no aparecia. Por eso las filas vivas llevan ahora `_cfg`.

**Todo vuelve a iTerm2**, tambien lo que estaba en Terminal.app: crear pestañas en Terminal.app
por AppleScript no tiene comando propio (hay que simular ⌘T). Y los paneles divididos vuelven como
pestañas. Las dos cosas estan en el README.

### `--saved`: las que faltan, en gris

El panel normal mas las sesiones de la foto que aun no han vuelto, en un grupo POR VOLVER **al
final** (arriba empujarian fuera de pantalla lo que si esta) y en gris. Enter las reanuda porque
llevan `recoverable`; el gris lo pone `faltante`.

**Solo con el comando, no siempre.** Si saliera en el panel normal, cada sesion cerrada a
proposito despues de un `--save` se quedaria en gris para siempre. Hay un test que lo fija.

**El Feed recalcula las que faltan en cada refresco** (`Feed(rows, fuente=…)`): segun reanudas,
cada una pasa sola de gris a su grupo de verdad. La `fuente` se resuelve al llamar y no como valor
por defecto de la firma — con `fuente=collect` ahi, parchear `ccl.collect` en los tests no surtiria
efecto.

**El gris va al FINAL de cada linea y quitando antes los colores** (`gris_si_falta`). Un
`\033[90m` delante no gana a un `\033[35m` del repo que viene despues: el ultimo codigo manda.

**Se numeran detras de las vivas**, para que teclear un numero lleve a una sola sesion.

`fila_de_disco()` la comparten `--recent` y `--saved`: las dos son sesiones muertas que se
reanudan con Enter, y montarlas en dos sitios era garantizar que divergieran.

## `$N`: cuantos comandos esta ejecutando una sesion

`busy` no distingue "esta corriendo un comando" de "esta generando texto", y son cosas muy
distintas cuando miras el panel para decidir a quien atender. `get_procesos()` cuenta los hijos
**directos** de cada `claude` que son un shell: cada `zsh` que cuelga de ahi es una llamada a Bash
en vuelo.

**Hijos directos y solo shells.** Contar descendientes a secas no dice nada: una sesion OCIOSA
arrastra cinco o siete hijos que son servidores MCP (`context7-mcp`, `chrome-devtools-mcp`,
`npm exec`) y viven todo el rato. Verificado ademas que hay sesiones `busy` cuyo unico hijo es
`caffeinate` — esas estan generando, no ejecutando.

**Un `ps` completo, no dos consultas.** `ps -eo pid=,ppid=,tty=,comm=` cuesta 35 ms —**menos** que
preguntar por unos pocos pids, medido— y de paso trae el arbol. Por eso `get_procesos()` sustituyo
a `get_ttys()`: misma llamada, dos datos. Es la misma leccion de `get_iterm_map`.

**Un login shell sale como `-zsh`**, con guion delante. Sin normalizarlo no se contaria.

## Una flecha sin nombre acaba siendo `esc`

`read_key` devuelve `"esc"` para toda secuencia CSI que no reconoce, y `esc` significa dos cosas
destructivas: en el editor de notas **cancela**, y en el panel sin filtro **sale**. Asi que
mientras `C`/`D` no estuvieron en la tabla, la flecha izquierda tiraba la nota que estabas
escribiendo y, fuera del editor, **cerraba ccl entero** — reportado como "le doy a la flecha y se
sale".

La leccion no era de esas dos teclas, y el primer arreglo lo demostro al quedarse corto: mapeo
`C`/`D`/`H`/`F` y dejo Supr, Ctrl-←, Inicio en su otra forma y ⌥+letra cerrando el panel igual.
Lo encontro la revision del cierre. El arreglo de verdad esta en `_read_csi()`:

- **Se lee hasta el byte FINAL** (0x40-0x7E), no un solo byte tras el corchete. Es lo unico que
  dice donde acaba la secuencia: leyendo uno, el resto quedaba en el buffer — Supr (`ESC[3~`)
  dejaba un `~` que arrancaba un filtro, Ctrl-← (`ESC[1;5D`) dejaba `;5D`.
- **Lo que no se reconoce es `"desconocida"`, nunca `"esc"`**, y el bucle la ignora sin repintar.
  `esc` es destructivo en los dos sitios donde llega; una tecla sin uso tiene que ser inocua.
- **⌥+letra llega como `ESC` + letra** con «Left Option: Esc+», que hace falta para ⌥1-9. Tambien
  era `esc`: cerraba ccl al escribir con Option.
- **`ESC O x` (SS3)** es como mandan flechas e Inicio/Fin en modo aplicacion; se mapea igual.

Si añades una tecla, se añade a `_CSI_FINAL` / `_CSI_TILDE` y ya; lo que no este ahi es inocuo.

El cursor del editor se pinta **donde esta** (`editando[:pos] + "▏" + editando[pos:]`), no siempre
al final: si no, moverlo no se ve y parece que la tecla no hace nada.

## El raton se REARMA en cada repintado

`MOUSE_ON` se emitia una sola vez, al arrancar el panel. Cualquier cosa que resetee los modos
privados del terminal —tmux, un `reset` de otro programa, iTerm restaurando la sesion— apagaba el
reporte de clics **para siempre**, y el panel seguia vivo sin enterarse: los clics dejaban de
hacer nada y **ningun sintoma apuntaba al terminal**. Reportado como "en algun momento deja de
funcionar el clic".

Ahora va dentro del `if dirty`, delante del borrado de pantalla. Son 16 bytes, es idempotente, y
como el refresco de fondo marca `dirty` cada 4-20 s **se cura solo** sin que el usuario haga nada.

Ojo al probarlo: **el reset de verdad no se puede simular en un pty**, porque esos modos viven en
el EMULADOR de terminal y ahi no hay ninguno — escribir `\033[?1000l` en el maestro es teclearlo,
no apagarlo. Lo que se comprueba es el contrato: que se emita en cada repintado.

## `CCL_DEBUG`: la traza para cuando "deja de funcionar el clic"

`CCL_DEBUG=/tmp/ccl.log ccl` apunta cada tecla que **llega**, el arranque (version, pid, TERM,
raton si/no) y cada rearmado del raton. Existe para contestar una pregunta que no se puede
contestar de otro modo:

- El log **no** muestra `click:` al pulsar → el que dejo de reportar es el TERMINAL.
- El log **si** los muestra y el cursor no se mueve → el fallo es nuestro, en el manejo.

Envuelve `_read_key` en vez de repartirse por sus quince `return`: asi no se puede añadir una
salida nueva y olvidarse de registrarla. Los `None` del timeout no se registran — son 2,5 por
segundo y ahogarian el log en horas. Apagado no cuesta nada (una comparacion contra None) y con
una ruta imposible se traga el error: una traza de diagnostico no puede ser la causa de un fallo.

**Y lo primero que hay que mirar ante un "deja de funcionar" es la EDAD del proceso**
(`ps -o lstart= -p <pid>`). Un panel lleva horas abierto y Python leyo el archivo al arrancar: un
arreglo de hace un rato no esta en el proceso que corre. Paso exactamente asi — siete horas de
panel contra un arreglo de hacia seis.

## Ningun subproceso hereda el terminal

**Todos van con `stdin=subprocess.DEVNULL`.** `capture_output=True` redirige la salida pero **no
stdin**, asi que el hijo se queda con el tty en el fd 0 y puede reconfigurarlo. `claude` es una TUI
de Node y pone stdin en modo raw; si muere a mitad por una señal no lo deshace, y te deja la
terminal **sin Ctrl-C ni Ctrl-Z**. Hay un test que cuenta las llamadas a `subprocess.run` en el
fuente y exige que todas lo lleven: una nueva sin `stdin` reabre el agujero, y el sintoma aparece
muy lejos de la causa.

**Y el texto de fuera va por `argv`, nunca interpolado en el AppleScript.** El sitio donde pasa es
`resume()`/`pestaña_nueva()`, con la ruta que sale del transcript. Interpolarla convierte una
comilla en un error de sintaxis, y algo peor que una comilla en ejecucion de AppleScript
arbitrario. Con `on run argv` el texto es un dato y no puede volverse codigo. `sin_control()` no
vale para esto: protege el dibujado, no a `osascript`.

## Hubo un `--notify` y se quito

Vigilaba en segundo plano y mandaba una notificacion de macOS cuando una sesion pasaba a
esperarte. Se retiro a peticion del usuario: **las notificaciones salian por `osascript`, asi que
macOS se las atribuye a Script Editor** —ese icono, y ese es el permiso que hay que conceder— y en
uso real no aportaba. Si alguien lo vuelve a pedir, hacerlo bien exige empaquetar una app firmada
y notarizada con su bundle id, que es mucha maquinaria para una linea de AppleScript.

Lo que SI hay que conservar de aquello esta arriba: el `stdin=DEVNULL` de todos los subprocesos y
el paso de texto por `argv`. Los dos se descubrieron por `--notify` pero no eran suyos.

## Contratos externos que pueden romperse## Contratos externos que pueden romperse

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

**`claude --resume <id>` conserva el sessionId.** Es la premisa entera de `--saved` y
`--restore`: si una sesion reanudada naciera con un id nuevo, la foto nunca la veria volver —
`--restore` la duplicaria cada vez y `--saved` la dejaria en gris para siempre. Verificado el
2026-10-12 en Claude Code 2.1.292: cuatro sesiones de la foto arrancaron DESPUES de guardarla
(`startedAt` posterior) con el mismo id. Si algun dia cambia, el sintoma es ese: grises que no se
van tras reanudar. (Existe `--fork-session` para lo contrario; `ccl` no lo usa.)

**Una actualizacion de Claude Code VACIA el registro de sesiones.** Verificado el 2026-08-06 al
pasar de 2.1.220 a 2.1.224: tres sesiones seguian corriendo, `claude agents --json` devolvia `[]`,
y una sesion arrancada DESPUES aparecia al momento. O sea que los procesos anteriores a la
actualizacion quedan huerfanos del registro hasta que se reinician. No es cosa de `ccl`, pero se
ve como "no hay sesiones activas" y manda a diagnosticar el sitio equivocado: por eso
`procesos_claude()` cuenta los `claude` vivos con `pgrep` y, si los hay, el mensaje lo explica y
manda a `--recent`, que lee de disco y no depende del registro.

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
| `TODO.md` | inglés — el README en inglés lo enlaza tres veces, y es donde se pide contribuir |
| Código, comentarios, nombres de test, `CLAUDE.md`, los skills | español |

La regla de fondo: **lo que ve quien USA la herramienta sigue su idioma; lo que ve quien TOCA el
código va en español.** `TODO.md` empezo en español por caer del lado del codigo, pero es
contributor-facing: el README en ingles lo enlaza tres veces (incluido "What's missing") y ahi es
donde se invita a abrir issues y PR. Quien llega a contribuir se topaba con una pared de español.

Lo publico y en ingles, para no volver a mezclarlo: la descripcion del repo, los dos README (uno
en cada idioma), `TODO.md`, las notas y titulos de las releases. Los mensajes de commit y las
anotaciones de tag van en español, como el resto de lo que mira quien toca el codigo.

Los comentarios explican **por qué**, no qué hace la línea — casi todos apuntan a una de las
trampas de arriba.

**Los dos README van en paralelo: si tocas uno, toca el otro.** Tienen las mismas secciones en el
mismo orden justamente para que el diff sea comparable.
