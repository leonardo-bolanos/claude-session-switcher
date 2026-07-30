# claude-session-switcher

[![CI](https://github.com/leonardo-bolanos/claude-session-switcher/actions/workflows/ci.yml/badge.svg)](https://github.com/leonardo-bolanos/claude-session-switcher/actions/workflows/ci.yml)
![macOS](https://img.shields.io/badge/macOS-iTerm2-black)
![Python](https://img.shields.io/badge/python-3.7%2B-blue)
![dependencias](https://img.shields.io/badge/dependencias-ninguna-brightgreen)
[![Licencia: MIT](https://img.shields.io/badge/licencia-MIT-green)](LICENSE)

**Un panel para todas tus sesiones de Claude Code, y un atajo para saltar a la ventana de iTerm2
que tiene cada una.**

*[Read this in English](README.md)*

Si trabajas con varias sesiones de Claude Code abiertas a la vez —una por repo, varias por
repo— llega un punto en que no sabes cuál está en qué pestaña, ni cuál dejaste a medias.
`ccl` las lista todas con lo que estaban haciendo, y con `Enter` te lleva a su ventana.

![ccl en acción](demo.svg)

Cada sesión muestra su rama, modelo, nivel de `effort` y el último prompt que le diste, para que
reconozcas en cuál estabas sin tener que entrar. El número de la izquierda es fijo: lo tecleas y
saltas.

```bash
ccl        # panel interactivo
ccl -w     # salta a la sesión que llevas más tiempo sin atender
```

## Por qué existe

Claude Code no tiene forma nativa de ver todas tus sesiones interactivas:

| Alternativa | Por qué no sirve |
|---|---|
| `claude agents` (panel oficial) | Solo muestra agentes en **background**. Tus sesiones de terminal no aparecen ahí |
| App de escritorio | Solo ve las sesiones abiertas desde la propia app |
| Dashboard desde el móvil | Pedido en el issue [#35607](https://github.com/anthropics/claude-code/issues/35607), **cerrado como "not planned"** |

La única fuente que las ve todas es `claude agents --json`, que no tiene interfaz.
`ccl` es esa fuente, con interfaz y con el salto a la ventana correcta.

## Requisitos

- **macOS** y **iTerm2** — el salto de ventana usa AppleScript contra iTerm2. En Terminal.app el
  listado funciona, pero el salto no.
- **Python 3.7+** (por `datetime.fromisoformat`). Sin dependencias externas.
- **Claude Code** v2.1.139 o superior (cuando apareció `claude agents`).

## Instalación

```bash
git clone https://github.com/leonardo-bolanos/claude-session-switcher.git
cd claude-session-switcher
./install.sh
```

El instalador crea un symlink en `~/.local/bin/ccl` y te imprime la función de shell que debes
añadir a tu `.zshrc` o `.bashrc`. **No modifica tu shell por su cuenta.**

<details>
<summary>A mano</summary>

```bash
ln -sf "$PWD/ccl" ~/.local/bin/ccl        # asegúrate de que ~/.local/bin está en tu PATH
```

</details>

## Uso

```bash
ccl              # panel interactivo
ccl --list       # listado estático de una pasada (útil en scripts)
ccl 7            # salta directo a la sesión número 7
ccl -w           # salta a la sesión que llevas más tiempo sin atender
ccl -w2          # ídem, la segunda de la cola de ESPERANDO
ccl --version    # imprime la versión
```

### Teclas del panel

| Tecla | Acción |
|---|---|
| `↑` `↓` | Mover selección |
| `PgUp` `PgDn` | Media página |
| `Enter` | Abrir esa sesión (enfoca su ventana y pestaña de iTerm) |
| `1` `2` … | Teclear el número de sesión; `⌫` corrige, `Enter` confirma |
| `⌥1` … `⌥9` | Saltar a la 1ª, 2ª … de **ESPERANDO**, sin confirmar |
| `Ctrl-N` | Escribir **tu propia nota** sobre esta sesión |
| clic | Seleccionar esa sesión |
| doble clic | Abrirla, igual que `Enter` |
| rueda | Mover la selección |
| cualquier letra | **Filtrar** por nombre, repo, rama, cuenta o nota |
| `Ctrl-R` | Forzar refresco |
| `?` | **Ayuda** con todos los atajos |
| `esc` | Limpia el filtro; si no hay filtro, sale |
| `q` | Salir (si no estás filtrando — con filtro activo es texto) |

La interfaz sigue **tu locale**: en español si tu `LANG` lo dice, y en inglés en caso contrario.
Se puede forzar con `CCL_LANG=es` / `CCL_LANG=en`.

El panel **se refresca solo** y **no se cierra al saltar**: vuelves a la lista con una
confirmación de a dónde fuiste.

<details>
<summary><b>Ir a la que te está esperando</b> — incluido un atajo global</summary>

`-w` salta a la N-ésima sesión del grupo **ESPERANDO**, en el mismo orden en que las pinta el
panel (actividad más reciente primero). No necesita TTY ni abrir el panel, así que está pensado
para colgarlo de un **atajo global**. Con Hammerspoon:

```lua
-- ⌃⌘1 … ⌃⌘9 : salta a la 1ª, 2ª … sesión esperando, desde cualquier app
local ccl = os.getenv("HOME") .. "/.local/bin/ccl"
for n = 1, 9 do
  hs.hotkey.bind({ "ctrl", "cmd" }, tostring(n), function()
    if not hs.fs.attributes(ccl) then
      hs.alert.show("ccl no está en " .. ccl)
      return
    end
    hs.task.new(ccl, nil, { "-w" .. n }):start()
  end)
end
```

`⌃⌘` en vez de `⌘` a secas porque `⌘1..9` ya cambia de pestaña en iTerm2, en el navegador y en
media docena de apps más; robárselo a todas para esto no vale la pena.

**No hace falta envolverlo en un shell de login.** Un lanzador arranca el proceso con el PATH
mínimo de launchd (`/usr/bin:/bin:/usr/sbin:/sbin`), donde `claude` no está — con npm bajo nvm
vive en `~/.nvm/versions/node/<versión>/bin`, que además cambia al actualizar Node. `ccl` lo
busca por su cuenta en las ubicaciones habituales (ver `CLAUDE_EXTRA` en el script), así que
`hs.task` vale tal cual; `zsh -ic` costaba ~0,7 s por pulsación.

Dentro del panel, `⌥1` … `⌥9` hacen lo mismo. `⌥1..9` cuenta siempre sobre la **lista completa,
ignorando el filtro activo**: la tecla significa «sácame de aquí, a la que me espera», y si
contara sobre lo filtrado el mismo número llevaría a sesiones distintas según lo que tuvieras
escrito.

**Para que `⌥` llegue al programa** hay que poner **Left Option key: `Esc+`** en iTerm2
(Settings → Profiles → Keys). Sin eso, `⌥1` produce un símbolo (`¡`) y el panel lo trata como
texto de filtro. `⌘1..9` no puede usarse: iTerm2 se lo queda para cambiar de pestaña y nunca
llega a `ccl` — si lo prefieres, mapea `⌘N` → *Send Escape Sequence* `N` y funcionará igual, a
costa de perder el cambio de pestaña.

</details>

<details>
<summary><b>Tu propia nota en una sesión</b></summary>

`Ctrl-N` escribe una nota sobre la sesión seleccionada — un nombre que signifique algo para *ti*,
cuando `web-app` no dice lo suficiente:

```
[ 1] web-app-checkout-rework   web-app   hace 12m
     ✎ backend de facturación · main · opus-5 · "revisa el flujo de pago…"
```

`Enter` guarda, una nota vacía la borra, `esc` cancela. `Ctrl-N` arranca con el texto que ya
hubiera, así que corregir no es reescribir. **También se busca por ella al filtrar**, que es media
razón para escribirla: etiquetas como "facturación" un repo que se llama `web-app` y lo encuentras
por esa palabra.

Las notas son **por sesión**, con la del repo como respaldo: una sesión sin nota propia muestra la
de su directorio. Hacen falta las dos porque son dos usos distintos — *«esperando que Felipe haga
algo»* es el estado de UNA conversación, mientras que *«backend de facturación»* describe el repo y
vale para todas sus sesiones (y sobrevive a reiniciar Claude Code, que cambia el `sessionId`).

Se guarda en `~/.claude/ccl-notes.json`:

```json
{
  "por_sesion": { "<sessionId>": "esperando que Felipe haga algo" },
  "por_repo":   { "/Users/tu/code/api": "backend de facturación" }
}
```

`Ctrl-N` escribe la de la sesión; borrarla hace reaparecer la del repo. Las de repo se editan a
mano en ese archivo — es JSON plano a propósito. El formato anterior (un `{ruta: nota}` plano) se
sigue leyendo como notas de repo, así que nada de lo escrito antes se pierde.

No se purga nada: ni las sesiones muertas ni los directorios que ya no existen. Un disco externo
desmontado o un repo movido de sitio borraría en silencio algo que escribiste a mano, y el archivo
son unos pocos KB aunque acumule.

</details>

<details>
<summary><b>Ratón, y cómo seleccionar texto para copiar</b></summary>

Clic selecciona, **doble clic abre**, la rueda mueve la selección. El doble clic no lo reporta el
terminal — solo llegan clics sueltos — así que se sintetiza midiendo el tiempo entre dos clics en
la misma fila (400 ms).

Mientras el panel está abierto **los clics son suyos**, así que arrastrar no selecciona texto.
Tres vías, de la más rápida a la más cómoda:

| Cómo | Cuándo |
|---|---|
| `⌥` + arrastrar, luego `⌘C` | Copiar algo suelto sin salir del panel |
| `CCL_MOUSE=0 ccl` | Vas a copiar mucho: arranca sin ratón y la selección es la normal |
| `ccl --list` | Lo más cómodo: sin panel, y queda en pantalla. `ccl --list \| pbcopy` copia todo |

`⌥` funciona porque iTerm2 no le pasa el evento al programa cuando ese modificador está pulsado.
Y ojo con el panel: usa la pantalla alternativa, así que **al salir se restaura lo que había y se
lleva la lista** — si quieres copiar de ahí, hazlo antes de salir. Por eso `--list` suele ser
mejor idea: escribe en la pantalla normal y se queda en el scrollback.

Como `--list` detecta que no escribe a un terminal, la salida por tubería va **sin códigos de
color**, lista para pegar.

</details>

<details>
<summary><b>Filtrar</b></summary>

Con muchas sesiones, escribe para reducir la lista: `supp` deja solo las de `support-agent`.
Ignora mayúsculas y acentos (`migracion` encuentra `migración`), y varios términos se combinan
sin importar el orden: `api backend` casa igual que `backend api`.

Mientras filtras, los dígitos forman parte del texto (para buscar `v5` o `0042`); con el filtro
vacío vuelven a ser selección de número.

En ventanas pequeñas la cabecera del grupo queda **fija arriba** al hacer scroll, para que no
pierdas de vista si estás en TRABAJANDO o en ESPERANDO.

</details>

<details>
<summary><b>Varias cuentas de Claude Code</b></summary>

Detecta sola `~/.claude` y cualquier `~/.claude-<algo>` que tenga un `projects/` dentro, así que
las sesiones de una segunda cuenta aparecen sin configurar nada. Cuando hay más de una, se añade
una columna con el nombre de la cuenta.

Para fijar la lista a mano:

```bash
export CCL_CONFIG_DIRS=~/.claude:~/.claude-trabajo
```

</details>

<details>
<summary><b>Numeración estable y colores</b></summary>

El número de cada sesión se guarda en `~/.claude/ccl-numbers.json` y **no cambia entre
ejecuciones**, aunque la lista se reordene por actividad. Puedes memorizar "el 7 es el backend".
Cuando una sesión muere, su número se libera y se recicla.

| Elemento | Significado |
|---|---|
| Nota `✎` | salmón apagado en negrita — es lo único de esa línea que escribiste tú |
| Antigüedad | verde reciente → amarillo → gris viejo |
| Modelo | azul Opus · verde Sonnet · gris Haiku · magenta Fable |
| `effort` | amarillo solo en `xhigh` / `max` |
| ⚠ rojo | La sesión no está en una ventana de iTerm |

</details>

<details>
<summary><b>Cómo funciona</b>, y dos trampas de rendimiento</summary>

1. **Origen de datos**: `claude agents --cwd ~ --json` da PID, cwd, nombre y estado de cada
   sesión viva.
2. **PID → ventana de iTerm**: `ps -o tty=` da el TTY de cada proceso, y un AppleScript devuelve
   el par ventana/pestaña de iTerm2 para cada TTY.
3. **Contexto de cada sesión**: se leen **solo los últimos 64 KB** del transcript
   (`~/.claude/projects/*/<sessionId>.jsonl`) para sacar la última actividad, la rama, el modelo,
   el effort y el último prompt. Es imprescindible: esos archivos llegan a superar los 100 MB y
   leerlos enteros haría el comando inusable.
4. **Refresco**: en un hilo aparte, cada 4 s mientras interactúas, relajándose a 20 s tras dos
   minutos sin teclear. En reposo el panel consume 0 % de CPU.

Un par de detalles que costaron encontrar:

- El AppleScript **no** recorre sesión por sesión. Resolver la ruta completa
  (`tty of session s of tab t of window w`) cuesta una llamada IPC por propiedad y tardaba 2,2 s
  con 44 pestañas. Con dos consultas masivas y reconstrucción en Python baja a ~0,5 s.
- **El `mtime` del transcript no sirve** como "última actividad": se escribe en bloque y varias
  sesiones acaban con la misma marca. Hay que usar el último campo `timestamp` de dentro del
  archivo.

</details>

## Tests

```bash
python3 test_ccl.py         # lógica pura — rápido (~2 s)
python3 test_panel.py       # el panel de verdad, sobre un pty (~1 min)
```

Sin dependencias, y **ninguno de los dos toca iTerm ni lanza `claude`**.

`test_ccl.py` cubre la lógica pura: helpers de ancho, numeración estable, parseo de la salida de
AppleScript, lectura de transcripts, agrupación y orden, filtro, multi-cuenta, formato de la
tabla, la pantalla de ayuda, la decodificación de teclas y ratón, y el manejo de errores.

`test_panel.py` arranca **el panel entero en un pty** y comprueba lo que solo se ve corriéndolo:
que las flechas y la rueda muevan el cursor donde deben, que un clic caiga en la fila correcta,
que el doble clic abra y dos clics lentos no, que la ayuda pagine y que `--list` salga sin
colores. Es hermético porque sustituye la lista de sesiones por datos sintéticos y deja el mapa de
iTerm vacío: **el salto falla con elegancia y no le roba el foco a nadie**.

Uno de ellos es un guardarraíl de diseño: comprueba que **ninguna acción cuelgue de una letra
suelta**, porque cualquier letra empieza a filtrar. Ya pasó dos veces (`r` impedía buscar
"revisa").

El CI corre las dos suites en Linux (Python 3.9/3.11/3.13) y en macOS, donde además comprueba que
el script degrada con un error claro cuando Claude Code no está instalado.

<details>
<summary>Regenerar el demo</summary>

```bash
python3 make_demo.py
```

Graba el programa de verdad en un pty con sesiones sintéticas y escribe `demo.svg`. Sin
dependencias, sin paso de grabación manual, y no expone ninguno de tus repos ni prompts reales.

</details>

## Limitaciones conocidas

- **Formato interno no documentado**: `aiTitle` y `lastPrompt` vienen del transcript de Claude
  Code, que Anthropic no documenta y puede cambiar en cualquier versión. Se tratan como
  opcionales — si desaparecen, el panel sigue funcionando sin esa información.
- **Los índices de pestaña se desplazan** si cierras una pestaña de la misma ventana entre listar
  y elegir. El riesgo es de segundos y el peor caso es enfocar la pestaña vecina.
- **Solo iTerm2** para el salto de ventana. El listado funciona en cualquier terminal.
  Terminal.app sí sería viable (expone `tty` por AppleScript) y tmux también; ver
  [TODO.md](TODO.md).
- **Solo macOS.** En Windows el script ni arranca: el panel usa `termios`/`tty`, que no existen
  ahí. Portarlo es un trabajo real, no un ajuste — está desglosado en [TODO.md](TODO.md).

## Qué falta

Terminal.app, Windows, otras terminales y algunos detalles menores, con lo ya investigado de cada
uno: [TODO.md](TODO.md).

## Licencia

MIT — ver [LICENSE](LICENSE).
