# CLAUDE.md

Un solo script: `ccl`, Python sin dependencias externas. Lista las sesiones
de Claude Code y salta a su ventana de iTerm2. El README explica qué hace y por qué existe;
esto son las trampas que no se ven leyendo el código.

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

`TestAyuda.test_ninguna_accion_es_una_letra_suelta` es un guardarraíl de diseño, no una
comprobación de formato: si documentas una acción en una letra, falla.

Lo que los tests NO cubren, porque necesita iTerm o un terminal real: el bucle interactivo,
el salto de ventana y el refresco en segundo plano.

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

## Multi-cuenta

`config_dirs()` detecta `~/.claude` mas los hermanos `~/.claude-*` con `projects/`.
Cada sesion se etiqueta con `_cfg` (su directorio de config) y `_account`.
**`read_transcript` necesita el `_cfg`**: sin el buscaria siempre en `~/.claude` y las
sesiones de la segunda cuenta saldrian sin rama, modelo ni prompt.

Si falla la cuenta principal se aborta; si falla una secundaria se ignora — no tiene
sentido dejar sin panel al usuario porque una config extra este rota.

## Estilo

Comentarios y documentación en español, igual que el resto del repo. Los comentarios explican
**por qué**, no qué hace la línea — casi todos apuntan a una de las trampas de arriba.
