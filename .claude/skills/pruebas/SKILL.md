---
name: pruebas
description: Cómo se prueba ccl y las trampas de su arnés de test. Cubre test_ccl.py (lógica pura, hermético, parchea INDEX_FILE/HOME/config_dirs) y test_panel.py (arranca el panel entero en un pty, ~3 min), incluidos CCL_TEST_ARGS para probar banderas, el layout fijo de la vista de dos líneas frente a la geometría de la tabla, y por qué cada tecla de acción necesita un test de que el editor de notas se la queda. Explica por qué read_key necesita un pty real y escribir los bytes DESPUÉS del modo raw, por qué no se debe probar focus ni Enter a ciegas (roba el foco de la máquina), cómo parchear collect con filas sintéticas para afirmar qué fila corresponde a qué sesión, y qué queda sin cubrir. Usar al escribir, arreglar o ejecutar tests, al tocar vis/pad/clip, assign_numbers, get_iterm_map o read_transcript, o cuando un test pase en local y falle en el CI.
---

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

Ese layout fijo vale para la vista de dos lineas (`FILA_DE`/`SUB_DE`). **En la vista de tabla la
geometria es otra** —cabecera de columnas y una sola linea por sesion—, asi que ahi la fila se
busca por su contenido en vez de darla por sabida. Y es donde mas falta hace probar el clic: el
mapa fila→sesion se construye pintando, y un calculo aparte se desincronizaria justo al cambiar
de vista.

**`proyecto_de` lleva `lru_cache` y lee el disco.** Los tests que montan un repo en un temporal
(`.git`, `.svn`, el `.git` archivo de un worktree) llaman a `ccl.proyecto_de.cache_clear()` en
`setUp`, y parchean `ccl.HOME`, porque la busqueda se para ahi. Una ruta que no existe (`/x/api`)
es su propio proyecto: por eso las filas sinteticas agrupan sin montar nada. En `test_panel.py`
eso da tres proyectos —`compartido` (alfa, beta), `delta`, `gamma`— y las filas se buscan por su
NUMERO (`[ 4]`), no por el nombre, que sale tambien en la cabecera del proyecto y en la barra de
pestañas. Diseño: `specs/001-vista-por-proyecto.md`.

**Tras una mutacion de prueba, borra `__pycache__/cclcpython-*.pyc`.** Los tests cargan `ccl`
con `SourceFileLoader`, que guarda bytecode, y Python lo da por bueno si coinciden el TAMAÑO del
fuente y su `mtime` en segundos. Cambiar `col = 3` por `col = 4` y devolverlo en el mismo segundo
deja las dos cosas iguales: los tests siguieron corriendo la version mutada, con el fuente ya
restaurado, y fallaron como si el codigo estuviera mal. Si un test falla y el codigo que lees dice
otra cosa, `dis.dis` de la funcion cargada lo confirma.

**Con `CCL_TEST_REFRESH` bajo, `ultima()` puede ser un repintado a medias.** El panel repinta en
cada refresco, y el drenado corta donde le pille: en el runner de macOS del CI, que es lento, un
test de pestañas leyo una pantalla sin sus ultimas filas y fallo sin nada roto. Si el test
necesita refresco, lee el ultimo repintado que ya trae la barra de estado (`↑↓`), que es lo
ultimo que se pinta (`TestPestañas.ultima_completa`). Sin refresco no pasa: tras el drenado no
llega nada mas.

**`collect` parcheado se salta `build`**, que es quien pega `note` y `paused` a las filas. El
arnes replica los dos pasos; si añades un campo que `build` calcule, hay que añadirlo ahi o el
panel de los tests lo vera siempre vacio — y parecera un fallo de persistencia que no existe.

`TestAyuda.test_ninguna_accion_es_una_letra_suelta` es un guardarraíl de diseño, no una
comprobación de formato: si documentas una acción en una letra, falla.

`python3 test_panel.py` arranca **el panel entero en un pty** y cubre lo que antes solo se podia
comprobar a mano: flechas, rueda, clic, doble clic, `⌥N`, `Ctrl-N`/`Ctrl-P`/`Ctrl-T`, la
paginacion de la ayuda y los caminos sin panel. Tarda ~3 min (un arranque real del programa por
test), asi que va aparte de la suite rapida. Las esperas se escalan con `CCL_TEST_LENTO` — el CI
usa 2, porque un runner compartido es mas lento y si no falla sin que nada este roto.

**Las banderas de la linea de comandos se pasan con `CCL_TEST_ARGS`.** El panel se arranca con
`python -c`, asi que no hay `sys.argv` que parsear: el arnes lo fabrica. Es lo que permite probar
`ccl --table` arrancando de verdad, y no solo el constructor de lineas.

**Cada tecla de accion necesita un test de que el editor de notas se la queda.** El modo edicion
va primero en el manejo de teclas justamente para eso, y es una linea facil de mover al añadir
una accion: hay uno por tecla (`Ctrl-P`, `Ctrl-T`) que escribe una nota con la tecla en medio y
comprueba que ni actuo ni ensucio el texto.

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
