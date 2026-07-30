# TODO

Lo que falta, con lo que ya se ha comprobado de cada cosa. Si te animas con alguna, los
issues y los PR son bienvenidos.

---

## Soportar Terminal.app

**Estado: viable, verificado.** Es lo siguiente más razonable de hacer.

Hoy el listado funciona en cualquier terminal, pero el salto de ventana solo en iTerm2. Para
Terminal.app la pieza que hacía falta existe: su diccionario de AppleScript expone `tty` por
pestaña, y tiene `selected tab`, `index` y `frontmost` para enfocar.

```
$ sdef /System/Applications/Utilities/Terminal.app | grep 'name="tty"'
<property name="tty" description="The tab's TTY device." code="ttty" type="text" access="r">
```

Lo que implica:

- Un `get_terminal_map()` paralelo a `get_iterm_map()`, y fusionar ambos mapas. El TTY es único
  por sesión, así que no hay colisión: cada uno aporta las suyas.
- Guardar en la fila qué aplicación la tiene, para saber a quién mandar el AppleScript de
  enfoque. Hoy `row["iterm"]` es `(window_id, tab)`; habría que generalizarlo a
  `(app, window_id, tab)`.
- Terminal.app direcciona pestañas por `index` dentro de la ventana, igual que iTerm2, así que
  hereda la misma limitación: el índice se desplaza si cierras una pestaña.
- Ojo con el rendimiento: la lección de `get_iterm_map()` aplica igual. Consultas masivas, no
  un bucle por sesión, o son segundos en vez de milisegundos.

## Soportar Windows

**Estado: es un port, no un ajuste.**

No es que falte una pieza: falta todo el mecanismo. Conviene saberlo antes de empezar.

| Pieza | En macOS | En Windows |
|---|---|---|
| Panel interactivo | `termios` + `tty` en modo raw | **no existen**: el script ni siquiera importa |
| PID → terminal | `ps -o tty=` | no hay TTY; habría que ir por la consola/pseudoconsola |
| Enfocar la ventana | AppleScript a iTerm2 | Win32 (`SetForegroundWindow`) o el modelo de pestañas de Windows Terminal |

Por dónde iría:

- Sustituir `termios`/`tty` por `msvcrt.getwch()` para leer teclas, tras un `sys.platform`.
  El resto del bucle (viewport, filtro, numeración) es agnóstico y se puede reutilizar tal cual.
- La lógica pura ya es portable: la suite entera corre en Linux en el CI, así que `vis`/`clip`,
  `assign_numbers`, `read_transcript` y el filtro no necesitan tocarse.
- Windows Terminal no expone sus pestañas por una API pública estable. La vía realista es
  localizar la ventana del proceso por PID con Win32 y llevarla al frente, aceptando que la
  **pestaña** concreta puede no ser direccionable. Un salto a nivel de ventana ya sería útil.
- Alternativa más barata que un port completo: que en Windows funcione solo `--list`, y que el
  panel interactivo avise de que no está soportado en lugar de reventar al importar.

## Otras terminales

En orden de lo que parece más factible:

- **tmux** — **verificado**, y probablemente el más fácil de todos: no necesita AppleScript.

  ```
  $ tmux list-panes -a -F '#{pane_tty} #{session_name}:#{window_index}.#{pane_index}'
  /dev/ttys082 mi-sesion:0.0
  ```

  Da el mapeo TTY → destino directo, y `tmux switch-client` + `select-window` + `select-pane`
  enfoca. Además no sufre el problema del índice de pestaña: el destino es estable.
- **kitty** *(sin verificar)* — tiene protocolo de control remoto (`kitty @ ls` devuelve ventanas y pestañas con
  su PID), así que el mapeo sería por PID en vez de por TTY.
- **WezTerm** *(sin verificar)* — `wezterm cli list --format json` incluye `pane_id` y el PID del proceso.
- **Ghostty, Alacritty** — sin control remoto que sirva para esto, por lo que se sabe.

## Cosas menores

- **El reloj de la columna de antigüedad solo avanza con el refresco.** En reposo (20 s) puede
  quedarse desactualizado hasta ese tiempo. Es cosmético; se arreglaría repintando sin
  recolectar datos.
- **El índice de pestaña se desplaza** si cierras una pestaña de la misma ventana entre listar y
  elegir. La ventana de riesgo es de segundos y el peor caso es enfocar la pestaña vecina, pero
  se podría revalidar el TTY justo antes de enfocar.
- **Matar o cerrar una sesión desde el panel.** Se descartó a propósito: una tecla que mata un
  proceso a un pulsación de distancia de las de navegación es una mala idea sin confirmación, y
  con confirmación deja de ser rápido.
- **`⌥1..9` necesita configurar iTerm2** (*Left Option key: `Esc+`*). Sin eso, `⌥1` manda `¡` y
  el panel lo trata como filtro. Se podría mapear también esos símbolos (`¡™£¢∞§¶•ª`) para que
  funcionara sin tocar nada, pero dependen de la distribución del teclado: con teclado español
  no salen los mismos. Antes de hacerlo, comprobarlo en varias distribuciones.
- **El modo de edición de notas vive suelto dentro de `interactive()`.** Su estado (`editando`)
  está en cuatro puntos del bucle: entrada, inicialización, reset cuando el filtro deja la lista
  vacía, pintado del prompt y manejo de teclas. Ya hubo que corregir uno de esos puntos porque
  divergía. Encaja como un objeto pequeño (`.activo`, `.tecla(k)`, `.pintar()`) sin partir el
  archivo único. No se hizo porque toca el corazón del bucle y el beneficio es organizativo, no
  funcional — pero si se le añade una tecla más (cursor con `←`/`→`), hacerlo antes.
- **El arnés de pty está duplicado** entre `test_panel.py` y `make_demo.py`: fork, `TIOCSWINSZ`,
  drenado acotado, con el mismo comentario justificativo repetido y ya con deriva (uno sondea a
  0,15 s y el otro a 0,1 s, sin razón). Cabría en un `pty_harness.py` — son archivos de
  desarrollo, así que no rompería el «un solo script sin dependencias», que es sobre lo que se
  distribuye. Son ~30 líneas herméticas y probadas, así que la urgencia es baja.
- **`test_panel.py` tarda ~2 min** porque son 46 arranques reales del panel, en serie y
  totalmente independientes (cada uno con su pty, su subproceso y su archivo de notas). Se
  paralelizarían bien, pero eso pide `pytest-xdist` y el proyecto presume de cero dependencias;
  habría que decidir si se acepta una dependencia **solo de desarrollo**. **No bajar los tiempos
  de espera**: están ajustados contra intermitencias y se escalan con `CCL_TEST_LENTO`.
- **Publicar una release etiquetada.** Un repo sin releases parece abandonado desde fuera, y un
  `git clone` de `master` no dice qué versión estás usando. Basta un tag `v1.0.0` con notas.
