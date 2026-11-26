---
capacidad: wsl-tmux-jump
estado: borrador
modo: prospectivo
rutas:
  - ccl
  - install.sh
  - test_ccl.py
  - test_panel.py
  - README.md
  - README.es.md
  - TODO.md
ultima_verificacion_commit: c44f1ce
ultima_verificacion_fecha: 2026-11-26
---

# 006 · `ccl` en WSL, saltando por tmux

> **Borrador.** Lo lleva Jhonatan Ibarra (`jhondil`), que trabaja en Windows con WSL. Lo de
> *Estado actual* está verificado en un contenedor Ubuntu 24.04 (tmux 3.4, Python 3.12) con el
> `ccl` de `c44f1ce`. **En un WSL de verdad no se ha probado nada todavía**: esa es la primera
> tanda de trabajo (ver *Plan de pruebas*).

## Qué se pide

Que `ccl` funcione en WSL: listar las sesiones, el panel y **saltar a una sesión**. El usuario
fijó el alcance el 2026-11-26: el salto va **por tmux dentro de WSL**. Windows Terminal y Windows
nativo quedan fuera (ver *Fuera de alcance*).

## Por qué tmux y no Windows Terminal

WSL es Linux: `termios`, `tty`, `ps` y los ptys existen, así que el panel ya debería funcionar,
porque el CI lo prueba en Ubuntu en cada push. Lo que no hay es el equivalente de AppleScript. Windows
Terminal no expone qué pestaña tiene cada pty, así que no hay forma de ir de «la sesión con el
`pts/3`» a «la pestaña 4». Dentro de tmux, en cambio, cada sesión de Claude es un panel con su
tty, y tmux sí sabe llevar el cliente a ese panel. Es la misma pieza que ya funciona en macOS
(ver «Sesiones dentro de tmux» en `CLAUDE.md`). Lo que falla es solo cómo se reconoce un tty y
qué se hace al final del salto.

## Estado actual en Linux (verificado)

| Pieza | Qué pasa hoy | Dónde |
|---|---|---|
| `install.sh` | **Se niega a instalar**: sale con `This is macOS only` si `uname` no es `Darwin` | `install.sh`, primera comprobación |
| `get_iterm_map()`, `get_terminal_map()` | Devuelven `{}` sin fallar: `_consultar()` se traga que no exista `osascript` | `ccl` |
| `get_procesos()` | Funciona. `ps` da `pts/N`, y `?` (no `??`) para los procesos sin tty, que entran en el mapa como `"?"` | `ccl`, `get_procesos` |
| `get_tmux_map()` | **Devuelve `{}` siempre.** tmux da `/dev/pts/N` y `TTY_RE` solo acepta `tty[a-z]*\d+` (el formato de macOS): todas las líneas se descartan | `ccl`, `TTY_RE` y `get_tmux_map` |
| `focus()` con fila de tmux | Aun arreglando la regex, falla: `row["ventana"]` es `None` porque no hay mapa de iTerm, y entra en la rama de «tmux sin cliente», que llama a `pestaña_nueva()` → `osascript`. Sale `Couldn't focus: [Errno 2] No such file or directory: 'osascript'` | `ccl`, `focus` y `build` (donde se asigna `ventana` a las filas de tmux) |
| Filas fuera de tmux | Salen todas con ⚠ («no encuentro la ventana»), porque ninguna tiene ventana | `ccl`, `build` |
| Textos | Hablan de iTerm (`no_esta_en_iterm`, `aviso_sin_iterm`, `enganchada` «en una pestaña nueva») | `ccl`, `TEXTOS` |

Lo que **no** se pudo verificar en el contenedor y queda para WSL: si `claude agents --cwd ~ --json`
existe y devuelve los mismos campos en el Claude Code de Linux, y qué teclas y eventos de ratón
deja pasar Windows Terminal.

## Diseño propuesto

1. **`TTY_RE` acepta `pts/N`**: `(?:/dev/)?(?:tty[a-z]*\d+|pts/\d+)`. Con eso el mapa de tmux sale
   bien. Verificado en el contenedor: `{'pts/0': ('s1:0.0', 's1', ''), …}`. Ojo, que `TTY_RE`
   también valida los ttys que devuelve el AppleScript (`_parsear_mapa`): la trampa de los
   `text item delimiters` de `CLAUDE.md` depende de que una cadena pegada
   (`/dev/ttys035/dev/ttys036`) **no** case. Hace falta un test que lo siga fijando con la regex
   nueva.
2. **Salto con cliente enganchado y sin ventana conocida**: después de `select-window` y
   `select-pane`, un `tmux switch-client -c /dev/<cliente> -t <sesion>`, y listo. No lleva
   comprobación de plataforma: es lo que corresponde siempre que tmux tenga cliente y no sepamos
   en qué ventana vive.
3. **Sesión de tmux sin cliente (detached) y `ccl` corriendo dentro de tmux (`$TMUX`)**:
   `switch-client -t <sesion>` sobre el cliente actual, en vez de abrir una pestaña nueva.
4. **Sin `osascript`, un mensaje que diga qué hacer** (`tmux attach -t <sesion>`), no el
   `Errno 2`.
5. **`install.sh`** deja pasar Linux con un aviso: en Linux el salto solo funciona dentro de tmux.
6. **Textos**: los que dicen iTerm necesitan una variante neutra o una de tmux. Se añaden a la
   vez en inglés y en español (skill `i18n-y-demo`).
7. **Documentación**: «Limitations» y «What's missing» en los dos README a la vez, y la sección
   «Support Windows» de `TODO.md` (que hoy habla de Windows nativo y no menciona WSL).

## Plan de pruebas en WSL (primera tanda, antes de tocar código)

Clonar **dentro del sistema de archivos de WSL** (`~/…`), no en `/mnt/c/…`. Si git en Windows
convierte los finales de línea a CRLF, el shebang se rompe (`/usr/bin/env: 'python3\r'`). Además,
`/mnt/c` es mucho más lento. Hace falta Claude Code instalado **dentro de WSL**, con la sesión
iniciada.

1. `python3 --version`, `tmux -V`, `claude --version`, `uname -r` (para saber si es WSL1 o WSL2).
2. Las dos suites: `python3 test_ccl.py` y `CCL_TEST_LENTO=2 python3 test_panel.py`. Deberían
   pasar como en el CI de Ubuntu. Si alguna falla, eso es lo primero que hay que contar.
3. `claude agents --cwd ~ --json` con dos o tres sesiones abiertas: ¿existe el comando? ¿Trae
   `pid`, `sessionId`, `status`, `cwd`, `startedAt`? Al compartirlo, sin el contenido de los
   prompts.
4. `./ccl --list` con sesiones en pestañas de Windows Terminal sin tmux. Se espera que salgan
   todas con ⚠.
5. El panel (`./ccl`) en Windows Terminal, con `CCL_DEBUG=/tmp/ccl.log ./ccl`: flechas, filtro,
   Enter, `Ctrl-T`, `Ctrl-G`, `Ctrl-P`, `Ctrl-N`, `Ctrl-E`, `Alt-1…9`, clic y doble clic, y
   cambiar el tamaño de la ventana. Anotar las teclas que no llegan, mirando en el log si
   aparecen. Si una tecla no está en el log, la intercepta Windows Terminal y no es un fallo de
   `ccl`.
6. Sesiones de Claude dentro de tmux, una por ventana, y `./ccl --list`. Hoy debería salir sin el
   destino de tmux (es lo que arregla el punto 1 del diseño).
7. `./install.sh`. Hoy debería negarse.

Con eso se cierran las decisiones abiertas y se implementa en una rama con PR.

## Decisiones abiertas

- **¿El punto 2 del diseño cambia algo en macOS?** Hoy, una sesión de tmux cuyo cliente está en un
  terminal que no es iTerm (por ejemplo, el de VS Code) acaba en `pestaña_nueva`, que abre un
  segundo cliente en una pestaña nueva de iTerm. Con `switch-client` se quedaría en el cliente
  que ya tiene. Parece mejor, pero cambia el comportamiento en Mac y hay que confirmarlo con el
  dueño del repo.
- **El ⚠ en todas las filas fuera de tmux.** En WSL sin tmux no hay salto posible, así que el
  aviso no aporta nada y llena la pantalla. ¿Se quita cuando no hay ningún mapa de ventanas?
- **`--recent` y `--restore` en WSL.** Reanudan con `pestaña_nueva()` (AppleScript). Dentro de
  tmux se podría usar `tmux new-window -c <cwd> 'claude --resume <id>'`. Hoy no está en el
  alcance; decidir si entra o si basta con un mensaje claro.
- **El mapa de `get_procesos()` con `"?"`.** Es inocuo, pero conviene ignorar `?` igual que
  `??`.

## Fuera de alcance

- **Windows Terminal**: abrir pestañas con `wt.exe` desde WSL, o ir a una pestaña concreta. No hay
  forma de pasar de pty a pestaña.
- **Windows nativo** (sin WSL): no hay `termios`. `TODO.md` lo detalla.
- **`-w` desde un atajo global de Windows**: no hay un equivalente a Hammerspoon o Raycast en el
  diseño.
- **Escritorios (Spaces)**: son de macOS, y `_hs()` ya devuelve `None` sin Hammerspoon.
