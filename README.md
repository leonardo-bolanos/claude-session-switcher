# claude-session-switcher

Un panel para todas tus sesiones de Claude Code, y un atajo para saltar a la ventana de iTerm2
que tiene cada una.

Si trabajas con varias sesiones de Claude Code abiertas a la vez —una por repo, varias por
repo— llega un punto en que no sabes cuál está en qué pestaña, ni cuál dejaste a medias.
`ccl` las lista todas con lo que estaban haciendo, y con `Enter` te lleva a su ventana.

```
  17 sesiones · 2 activas ↕

  TRABAJANDO (2)
▌ [ 6] api-rate-limit-retry              backend-api      ahora
▌   main · opus-5 · xhigh · "añade backoff exponencial al cliente"
  [ 3] mobile-deeplink-spec              mobile-app       hace 12m
      develop · sonnet-5 · high · "revisa la spec de deep linking"

  ESPERANDO (15)
  [16] fix-onboarding-flow               backend-api      hace 29m
      main · opus-5 · xhigh · "commit your changes"
  [ 9] docs-migration                    docs             ayer 18:36
      main · sonnet-5 · high · "adelgaza el README"

  ↑↓ mover  enter abrir  nº ir  r refrescar  esc salir
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

- **macOS** y **iTerm2** — el salto de ventana usa AppleScript contra iTerm2.
  En Terminal.app el listado funciona, pero el salto no.
- **Python 3.7+** (por `datetime.fromisoformat`). Sin dependencias externas.
- **Claude Code** v2.1.139 o superior (cuando apareció `claude agents`).

## Instalación

```bash
git clone https://github.com/leonardo-bolanos/claude-session-switcher.git
cd claude-session-switcher
./install.sh
```

El instalador crea un symlink en `~/.local/bin/ccl` y te imprime la función de shell que
debes añadir a tu `.zshrc` o `.bashrc`. **No modifica tu shell por su cuenta.**

### A mano

```bash
ln -sf "$PWD/ccl" ~/.local/bin/ccl        # asegúrate de que ~/.local/bin está en tu PATH
```

## Uso

```bash
ccl              # panel interactivo
ccl --list       # listado estático de una pasada (útil en scripts)
ccl 7            # salta directo a la sesión número 7
```

### Teclas del panel

| Tecla | Acción |
|---|---|
| `↑` `↓` | Mover selección |
| `PgUp` `PgDn` | Media página |
| `Enter` | Abrir esa sesión (enfoca su ventana y pestaña de iTerm) |
| `1` `2` … | Teclear el número de sesión; `⌫` corrige, `Enter` confirma |
| `r` | Forzar refresco |
| `esc` / `q` | Salir |

El panel **se refresca solo** y **no se cierra al saltar**: vuelves a la lista con una
confirmación de a dónde fuiste.

### Numeración estable

El número de cada sesión se guarda en `~/.claude/ccl-numbers.json` y **no cambia entre
ejecuciones**, aunque la lista se reordene por actividad. Puedes memorizar "el 7 es el backend".
Cuando una sesión muere, su número se libera y se recicla.

### Colores

| Elemento | Significado |
|---|---|
| Antigüedad | verde reciente → amarillo → gris viejo |
| Modelo | azul Opus · verde Sonnet · gris Haiku · magenta Fable |
| `effort` | amarillo solo en `xhigh` / `max` |
| ⚠ rojo | La sesión no está en una ventana de iTerm |

## Cómo funciona

1. **Origen de datos**: `claude agents --cwd ~ --json` da PID, cwd, nombre y estado de cada
   sesión viva.
2. **PID → ventana de iTerm**: `ps -o tty=` da el TTY de cada proceso, y un AppleScript
   devuelve el par ventana/pestaña de iTerm2 para cada TTY.
3. **Contexto de cada sesión**: se leen **solo los últimos 64 KB** del transcript
   (`~/.claude/projects/*/<sessionId>.jsonl`) para sacar la última actividad, la rama, el
   modelo, el effort y el último prompt. Es imprescindible: esos archivos llegan a superar los
   100 MB y leerlos enteros haría el comando inusable.
4. **Refresco**: en un hilo aparte, cada 4 s mientras interactúas, relajándose a 20 s tras dos
   minutos sin teclear. En reposo el panel consume 0 % de CPU.

Un par de detalles de rendimiento que costaron encontrar:

- El AppleScript **no** recorre sesión por sesión. Resolver la ruta completa
  (`tty of session s of tab t of window w`) cuesta una llamada IPC por propiedad y tardaba
  2,2 s con 44 pestañas. Con dos consultas masivas y reconstrucción en Python baja a ~0,5 s.
- **El `mtime` del transcript no sirve** como "última actividad": se escribe en bloque y
  varias sesiones acaban con la misma marca. Hay que usar el último campo `timestamp` de
  dentro del archivo.

## Limitaciones conocidas

- **Solo una instalación de Claude Code**: la de `~/.claude`. Si usas varias cuentas apuntando
  `CLAUDE_CONFIG_DIR` a otro directorio, esas sesiones no salen.
- **Formato interno no documentado**: `aiTitle` y `lastPrompt` vienen del transcript de Claude
  Code, que Anthropic no documenta y puede cambiar en cualquier versión. Se tratan como
  opcionales — si desaparecen, el panel sigue funcionando sin esa información.
- **Los índices de pestaña se desplazan** si cierras una pestaña de la misma ventana entre
  listar y elegir. El riesgo es de segundos y el peor caso es enfocar la pestaña vecina.
- **Solo iTerm2.** Terminal.app, Ghostty, WezTerm y otros no exponen el TTY por AppleScript
  del mismo modo. El listado funciona en cualquiera; el salto, no.

## Licencia

MIT — ver [LICENSE](LICENSE).
