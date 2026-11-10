---
capacidad: project-view
estado: implementada
modo: retroactivo
version: 1.4.0
rutas:
  - ccl
  - test_ccl.py
  - test_panel.py
  - README.md
  - README.es.md
  - .claude/skills/teclas-y-raton/SKILL.md
  - .claude/skills/pruebas/SKILL.md
ultima_verificacion_commit: 56ba405
ultima_verificacion_fecha: 2026-11-09
---

# 001 · Vista por proyecto

> **Implementada en 1.4.0** (`ca9997d`, `3337eb8`, `a9d810f`); el clic en las pestañas (R21),
> después. Se escribió antes del código y se reconcilió al cerrar: lo que sigue describe lo
> construido, y lo que salió distinto del diseño está en *Desviaciones*.

## Qué se pide

> «Quiero agregar una vista que se pueda ver pestañas de acuerdo a proyecto.»

Interpretación: el panel agrupaba las sesiones —cada una vive en una pestaña— **por estado**
(TRABAJANDO, ESPERANDO, PAUSADAS…). Se pide poder agruparlas **por proyecto**: todas las pestañas
de `support_agent` juntas, todas las de `NewCariAI` juntas, cada grupo con su resumen de estados.
Es otra forma de mirar la misma lista, no otra lista: se elige, se salta y se filtra igual.

Con las fases 1 y 2 ya hechas, el usuario pidió además pestañas: «¿se puede con tabs, si oprimo
flechas izq der se mueve?». Son R13-R20. Y ya publicada la 1.4.0, el clic: «que el clic funcione
sobre los tabs». Es R21.

Si lo que se quería era ver la estructura de ventanas y pestañas de iTerm (ventana 2 › pestaña 3),
eso es otra cosa y está en *Fuera de alcance*.

## Por qué hace falta

Medido el 2026-11-09 en esta máquina:

- **17 sesiones vivas en 7 proyectos**, con `support_agent` (6) y `NewCariAI` (4) repartidas entre
  TRABAJANDO y ESPERANDO. Para responder «¿qué tengo abierto en support_agent?» hay que recorrer
  los grupos de estado a ojo.
- **La columna `repo` miente con subcarpetas y worktrees.** Es `basename(cwd)` (`build`), así que
  de los transcripts en disco, los 12 directorios distintos de `emaus` salen con **9 nombres**:
  `emaus`, `web`, `api`, `offline-mode`, `audit-secuencias`, `special-case`,
  `santisimo-guardia-links`, `palancas-quick-phone-edit`, `.playwright-mcp`. Agrupar por ese
  campo no agruparía nada. Hace falta una noción de proyecto que no existe todavía.

## Qué es un proyecto

**La raíz del repositorio al que pertenece el `cwd`, con los worktrees vinculados dentro de su
repo principal.** Lo resuelve `proyecto_de(cwd)` (con `_raiz_de_worktree` para el `.git`
archivo), sin subprocesos:

1. Subir desde `cwd` hacia arriba, **sin llegar a `HOME` ni a `/`**. En cada directorio `d`:
   - `d/.git` es un directorio → la raíz es `d`.
   - `d/.svn` es un directorio → la raíz es `d` (SVN ≥ 1.7 solo deja `.svn` en la raíz del
     checkout).
   - `d/.git` es un **archivo** → leer como mucho 4 KB. Si dice `gitdir: X` y `X` (resuelto
     relativo a `d`) tiene la forma `<R>/.git/worktrees/<nombre>`, es un **worktree vinculado**
     y la raíz es `R`. Si no tiene esa forma (un submódulo: `../.git/modules/x`), la raíz es `d`:
     un submódulo es su propio proyecto.
2. Sin ninguna marca, la raíz es el propio `cwd` — que es lo que enseñaba la columna `repo`.

Nombre del proyecto: `basename(raíz)`, **pasado por `sin_control()`**: el nombre de un directorio
viene de fuera y puede traer secuencias de escape (ver «Lo que se pinta viene de fuera» en
`CLAUDE.md`). Si dos raíces distintas comparten nombre en la misma lista, ambas se etiquetan con
sus dos últimos componentes (`cariai/api`, `personal/api`): la **clave** del grupo es la ruta de la
raíz, nunca el nombre.

### Verificado contra datos reales

El prototipo sobre los `cwd` de los 200 transcripts más recientes (`recent_rows`) tardó
**4,8 ms** y resolvió lo mismo que la implementación final (CA2):

| `cwd` | Proyecto | Por qué |
|---|---|---|
| `…/emaus/apps/web`, `…/emaus/apps/api` | `emaus` | subcarpeta: sube hasta el `.git` |
| `…/emaus/.claude/worktrees/offline-mode` (ya **no existe**) | `emaus` | `isdir` de una ruta inexistente es False y se sigue subiendo |
| `/private/tmp/bukeala-brayan/wt-fix` | `NewCariAI` | `.git` archivo → `NewCariAI/.git/worktrees/…` |
| `~/system/skills/marca-cariai` | `system` | subcarpeta |
| `~/Developer/cariai/defybots_svn` | `defybots_svn` | `.svn` en la raíz |
| `~/Documents/Leo/Salud/ensayo` | `ensayo` | sin control de versiones: el propio `cwd` |

Y a mano: `/Users/lbolanos/Developer/cariai/worktrees/Colsanitas/.git` contiene
`gitdir: /Users/lbolanos/Developer/cariai/NewCariAI/.git/worktrees/Colsanitas` → `NewCariAI`.
`defybots_svn/phalcore_svn/.svn` existe: es otro checkout anidado y sale como proyecto propio, que
es lo correcto.

### Por qué así y no de otra forma

- **No `git rev-parse --git-common-dir`.** Un subproceso por `cwd` rompe la regla de las dos
  consultas masivas (`get_iterm_map`, `get_procesos`); falla con los worktrees ya borrados, que
  son justo los de `--recent`; y no sabe nada de SVN, que es el repo con más transcripts después
  de `emaus` y `support_agent`.
- **El tope en `HOME`.** Quien versiona su `HOME` (dotfiles con `~/.git`) vería todas las sesiones
  sin repo propio fundidas en un grupo gigante con su nombre de usuario. Aquí no hay `~/.git`,
  pero en otras máquinas es habitual.
- **Se deriva del `cwd` al agrupar; no es un campo que rellene `build`.** Las filas nacen en tres
  sitios: `build` (vivas), `fila_de_disco` (`--recent`, `--saved`) y el arnés de `test_panel.py`,
  que parchea `collect` y se salta `build`. Un campo nuevo en `build` saldría vacío en los otros
  dos sin que nada fallara — la trampa documentada en el skill `pruebas`. `proyecto_de` lleva
  `functools.lru_cache` por `cwd`: el filtro la llama en cada tecla.

## Comportamiento

| # | Requisito |
|---|---|
| R1 | `Ctrl-G` alterna la agrupación: **por estado** (la de siempre) ↔ **por proyecto**. Es independiente de `Ctrl-T`: las cuatro combinaciones (dos líneas o tabla × estado o proyecto) existen. |
| R2 | `ccl -p` / `ccl --projects` arranca agrupado por proyecto. Se combina con `--list`, `--table`, `--recent` y `--saved`. |
| R3 | Cabecera de cada grupo: nombre, total y resumen por estado con sus colores, omitiendo los ceros: `support_agent (7) · working 2 · waiting 5`. Etiqueta y luego número: `1 pausadas` no se puede decir en español y `pausadas 1` sí, sin claves nuevas para el plural. |
| R4 | Orden de los grupos: **alfabético**, sin mayúsculas ni acentos; desempata la ruta de la raíz. Un proyecto cuyas filas son **todas** `faltante` (`--saved`) va al final. Desde la spec 002, los que ordenes a mano van delante en tu orden, y el alfabético queda para los demás. |
| R5 | Orden dentro de un grupo: el de `grouped()` aplicado a las filas de ese proyecto — estado y, dentro, actividad. Se reutiliza `grouped()`, no se reimplementa el orden. |
| R6 | Cada fila dice su estado, con la etiqueta y el color de `estado_de()`. En la tabla ya hay columna; en la vista de dos líneas se añade a la línea principal, que debe seguir cabiendo en 80 columnas sin perder la antigüedad ni el ⚠ que va detrás (el nombre baja de 36 a 27). |
| R7 | En la vista por proyecto, el campo `repo` sale **vacío si `cwd` es la raíz** y con `basename(cwd)` si no: el nombre del worktree o de la subcarpeta. Repetir el proyecto seis veces bajo su propia cabecera es ruido; lo informativo es la excepción. |
| R8 | El filtro (`matches`) busca también por el nombre del proyecto, **en las dos agrupaciones**: escribir `emaus` encuentra una sesión cuyo `cwd` es `emaus/.claude/worktrees/offline-mode`. |
| R9 | La cabecera del panel añade `· N projects` en la vista por proyecto. |
| R10 | `^G` aparece en la barra de estado, detrás de `^T`, y en la ayuda (`HELP_EN`, `HELP_ES`) y el uso (`USO_EN`, `USO_ES`). |
| R11 | No cambia: la numeración, `⌥1…9` y `-w` (cola ESPERANDO global, ver Invariantes), `Enter`, clic y doble clic, notas, pausa, `Ctrl-O`. |
| R12 | La agrupación **no se recuerda** entre ejecuciones. Misma postura que la tabla en `TODO.md`: la bandera o un alias lo resuelven sin inventar una regla de precedencia. |

### Pestañas (← → y clic)

Añadido el 2026-11-09, ya implementadas las fases 1 y 2, a petición del usuario: «¿se puede con
tabs, si oprimo flechas izq der se mueve?». Va en esta spec y no en otra porque sale en la misma
versión: así la documentación se escribe una vez.

```
  22 sesiones · 4 activas · 7 proyectos
  ‹ emaus 3 │ Luna 1 │ ▐NewCariAI 4▌ │ support_agent 7 │ system 1 ›

  ESPERANDO (4)
  [10] N8N interface flux Cari     ...
```

| # | Requisito |
|---|---|
| R13 | En la vista por proyecto, una **barra de pestañas** bajo la cabecera del panel: **Todas** primero y luego una por proyecto, en el orden de los grupos (R4), cada una con su número de sesiones. La activa va resaltada. Solo existe con `Ctrl-G`: sin agrupar por proyecto no hay barra ni línea de más. |
| R14 | `←` / `→` cambian de pestaña, **en círculo** como `↑↓`: `→` en la última vuelve a Todas. Sin la vista por proyecto siguen sin hacer nada, como antes. |
| R15 | **Todas** es la vista por proyecto de R1-R12. Una pestaña de proyecto enseña solo ese proyecto, **agrupado por estado**: dentro de un proyecto lo que distingue una sesión de otra es si trabaja o te espera. Y `repo` es `donde`, como en Todas (R7): con datos reales, sin esto `support_agent` salía repetido en cada fila. Vale en las dos disposiciones (`Ctrl-T`). |
| R16 | La barra **se desplaza sola** si no cabe: la pestaña activa siempre se ve, y `‹` / `›` avisan de que hay más a cada lado. Con los 7 proyectos vivos del 2026-11-09 ocupa ~115 columnas; en `--recent` son 24 proyectos. |
| R17 | El filtro de texto se combina con la pestaña (las dos condiciones a la vez). Las pestañas y sus números salen de **todas** las filas, no de las filtradas: la barra no baila mientras escribes. Una pestaña sin coincidencias enseña «sin resultados» y desde ahí `← →` siguen funcionando. |
| R18 | Si el proyecto de la pestaña activa desaparece (se cerraron sus sesiones), se vuelve a **Todas**. `Ctrl-G` y `Ctrl-O` también la devuelven a Todas: la lista de pestañas cambia entera. |
| R19 | No cambia: teclear un número lleva a la sesión aunque esté en otra pestaña (`by_num` va sobre todas las filas), y `⌥1…9` / `-w` cuentan sobre la cola ESPERANDO entera. Si la sesión elegida no está en la pestaña activa, el cursor cae en la primera fila: lo que ya pasaba con el filtro. |
| R20 | `←→` aparece en la barra de estado y en la ayuda **solo con la vista por proyecto**, que es cuando hacen algo. En la barra va junto a `↑↓` y no al final: es navegación, y la barra se recorta por la derecha (a 100 columnas ya no cabía entera antes de esta spec). |
| R21 | Un **clic en una pestaña** va a ella, como si se llegara con `← →`. `‹` y `›` también se pulsan: traen la primera pestaña oculta de su lado, que es lo que prometen. Un clic en el separador `│`, o en la pestaña en la que ya estás, no hace nada, y dos clics rápidos en la barra no abren ninguna sesión: la barra no elige sesiones (Invariantes). Añadido tras publicar 1.4.0. |

## Dónde vive

Todo en `ccl`. La idea entera es que **la vista por proyecto es otra lista de grupos con la misma
forma** `[(etiqueta, color, filas)]` que devuelve `grouped()`: si se cumple, el cursor, el clic, el
scroll y la cabecera fija funcionan sin enterarse, igual que pasó con la tabla
(`build_table_display`, «devuelve los MISMOS roles a propósito»).

| Pieza | Cambio |
|---|---|
| `proyecto_de(cwd)` | `(raíz, nombre)` según el algoritmo de arriba, con `lru_cache`. El `.git` archivo lo interpreta `_raiz_de_worktree`. |
| `donde(r)` | Lo que va en `repo` dentro de un proyecto: vacío en la raíz, `basename(cwd)` si no (R7). |
| `_proyectos(rows)` | `[(raíz, etiqueta, color, filas)]`: reparte por raíz, ordena según R4, aplana `grouped(subconjunto)` dentro de cada proyecto (R5) y resuelve las colisiones de nombre (`_etiquetas_de_proyecto`). Es la fuente única de grupos y pestañas: no pueden salir en distinto orden ni con distinta etiqueta. |
| `agrupar_por_proyecto(rows)` | `_proyectos` sin la raíz: la misma forma que `grouped()`. |
| `grupos(rows, por_proyecto)` | El único sitio que elige entre `grouped` y `agrupar_por_proyecto`. |
| `cabecera_grupo(…)` | Antes `render` y `build_display` construían `f"{label} ({len(items)})"` cada uno por su cuenta; la del proyecto lleva además el resumen (R3). Una sola función para las dos, recortada al ancho **al construirla**. |
| `render`, `build_display`, `build_table_display`, `vista` | Reciben `por_proyecto` y llaman a `grupos()`. `build_table_display` mete una línea `head` por proyecto debajo de la de nombres de columna. |
| `main_line` | Con `por_proyecto`, columna de estado (R6) y `repo` según R7; con `en_proyecto` (la pestaña de un proyecto), solo `repo` según R7. |
| `table_line` | `repo` según R7 con cualquiera de los dos; la columna de estado ya existía. |
| `matches` | Añade el nombre del proyecto al texto en el que se busca (R8). |
| `_read_key` | `"\x07"` (`Ctrl-G`) → `"proyectos"`. |
| `interactive` | Parámetro `por_proyecto`; la rama `k == "proyectos"` lo alterna y pone `requery`, como `Ctrl-T`. Cabecera con el número de proyectos (R9) y `^G` en la barra (R10). |
| `parse_args`, `main` | `-p`/`--projects`, propagado a las tres llamadas a `interactive` y a las de `render`. |
| `TEXTOS` | Dos claves nuevas en **los dos idiomas** con los mismos huecos (lo exige un test): la barra (`barra_proyectos`) y la cabecera (`proyectos_n`). El resumen reutiliza las etiquetas de los grupos, y no hay aviso al cambiar: como con `Ctrl-T`, el cambio se ve solo. Las pestañas añaden `pestaña_todas` y `barra_pestañas`. |
| `pestañas_de(rows)`, `pestaña_vecina(…)` | La lista `[(clave, etiqueta, n)]` con «Todas» delante, sacada de `_proyectos`; y la de al lado, en círculo. |
| `barra_y_zonas(pestañas, activa, ancho)` | Pura. La línea de pestañas recortada a `ancho`, con la activa siempre dentro de la ventana y `‹ ›` cuando sobran, y sus **zonas** `[(col_ini, col_fin, clave)]` para el clic (R21), sacadas del mismo cálculo que la pinta. `barra_pestañas` devuelve solo la línea. Pura para probar el desplazamiento y las zonas sin pty. |
| `pestaña_en(zonas, col)`, `_mouse_event` | La zona que contiene una columna, o `None` (un separador). El clic llega como `click:<fila>:<columna>`: antes la columna se descartaba. |
| `interactive` (pestañas) | Estado `pestaña` (la **raíz** del proyecto, o `None` para Todas: la clave es la ruta, nunca el nombre). Al reconstruir, filtra `shown` por pestaña y pide `vista(…, por_proyecto=pestaña is None, en_proyecto=pestaña is not None)` (R15); `en_proyecto` llega a `main_line`/`table_line` para poner `donde` en `repo` sin la columna de estado. La barra se pinta entre la cabecera y la cabecera de grupo fija, y **resta una línea a `body` antes de calcular el scroll**: si se resta al pintar, la fila del cursor puede quedar fuera por abajo. `← →` en el bucle principal y en la rama de lista vacía (R17). Al pintar la barra se apuntan su fila y sus zonas (`barra_y`, `barra_zonas`); el clic en esa fila va antes que el de `screen` (R21). |

### Puntos de extensión

- **Otro control de versiones** (Mercurial, Jujutsu): una marca más en el bucle de `proyecto_de`.
- **Otro orden de proyectos**: la clave de `sorted` en `_proyectos`; grupos y pestañas lo heredan.
- **Otra línea fija arriba del panel**: como la barra de pestañas — fuera de `screen` y descontada
  de `body` antes del scroll (skill `teclas-y-raton`).
- **Otra columna en la vista por proyecto**: `main_line`/`table_line` y `_tabla_columnas`; el
  test de 80 columnas con fecha completa y ⚠ dice si sigue cabiendo.

## Invariantes que no se pueden romper

Todas están en `CLAUDE.md` o en los skills; se listan porque esta vista toca justo esas piezas.

- **Grupos excluyentes.** Cada fila aparece exactamente una vez. Con `grouped()` reaplicado dentro
  de cada proyecto se hereda, pero se prueba como propiedad: la unión de las filas de todos los
  grupos es `rows`, sin repetidas.
- **`waiting_rows()` sigue siendo la única fuente de la cola ESPERANDO.** `⌥N` y `-w` cuentan sobre
  ella, no sobre el orden de la vista: el mismo atajo no puede llevar a sesiones distintas según
  la vista, igual que no puede según el filtro. Consecuencia aceptada: en la vista por proyecto,
  `⌥1` no es «la primera amarilla que se ve».
- **El cursor sigue a `clave_de()`**, no a la posición: al pulsar `Ctrl-G` se queda en la misma
  sesión aunque cambie de sitio.
- **Las líneas `head` no se recortan al pintar** (`interactive` solo recorta `main` y `sub`). Una
  cabecera de proyecto larga —el resumen de estados la alarga— se tiene que construir ya recortada
  a `width - 4`, o envuelve y descoloca todo el panel.
- **El mapa fila → sesión se construye pintando** (`screen[y] = i`). No se toca: si la nueva vista
  produce los mismos roles, el clic acierta solo.
- **Ninguna acción cuelga de una letra suelta** (`test_ninguna_accion_es_una_letra_suelta`).
  `Ctrl-G` no es carácter especial del tty en macOS (`stty -a`: discard, dsusp, eof, erase, intr,
  kill, lnext, quit, reprint, start, status, stop, susp, werase). Descartadas a propósito:
  `Ctrl-S`/`Ctrl-Q` (control de flujo IXON, que `_preparar_tty` **no** apaga: congelaría la
  salida entre lecturas) y `Ctrl-Y` (VDSUSP: con ISIG encendido es una señal de suspensión).
- **El editor de notas se queda el teclado.** `"proyectos"` no es imprimible, así que el editor
  la ignora; aun así lleva su test, como cada tecla de acción (skill `pruebas`).
- **Cero subprocesos nuevos y repintado solo con `dirty`.** `proyecto_de` hace `stat` y como mucho
  una lectura de 4 KB por `cwd` distinto, cacheada.
- **`← →` son del editor de notas mientras escribes** (mueven el cursor del texto). El editor va
  primero en el manejo de teclas, así que no cambian de pestaña debajo; lleva su test igual.
- **La línea de pestañas no entra en el mapa fila → sesión.** Un clic en ella no selecciona ninguna
  sesión: cambia de pestaña (R21). Tiene su propio mapa, columna → pestaña, y se construye igual que
  `screen`: pintando. Las zonas salen de `barra_y_zonas`, el mismo cálculo que dibuja la barra;
  calculadas aparte, el día que cambie un separador el clic caería en la pestaña vecina sin que
  nada falle.

## Criterios de aceptación

| # | Criterio | Cómo se verifica |
|---|---|---|
| CA1 | `ccl --list --projects` muestra un grupo por proyecto con las sesiones vivas del momento; la suma de los totales es la de `ccl --list`. | A mano, con datos reales; la propiedad, en `test_ccl.py`. |
| CA2 | `ccl --recent --list --projects` agrupa bajo **un solo** `emaus` los 12 directorios distintos que la columna `repo` enseña con 9 nombres, incluidos los worktrees ya borrados. | A mano: los datos existían el 2026-11-09 en `~/.claude/projects`. |
| CA3 | Un worktree vinculado fuera del repo (`.git` archivo → `<R>/.git/worktrees/<n>`) cae en `R`; un submódulo (`gitdir` sin `/worktrees/`) es su propio proyecto. | `test_ccl.py` con directorios temporales. Ejemplo real: `Colsanitas` → `NewCariAI`. |
| CA4 | SVN: la raíz con `.svn` es el proyecto; un checkout anidado con su propio `.svn` es otro. | `test_ccl.py`. Real: `defybots_svn` y `phalcore_svn`. |
| CA5 | Una carpeta sin control de versiones, y `HOME` mismo, son su propio proyecto; la búsqueda no sube por encima de `HOME`. | `test_ccl.py`, con `HOME` temporal que **sí** tenga `.git`. |
| CA6 | `Ctrl-G` alterna y vuelve; el cursor sigue en la misma sesión; funciona en dos líneas y en tabla. | `test_panel.py`. |
| CA7 | El clic y el doble clic seleccionan/abren la fila pulsada en la vista por proyecto, en las dos disposiciones. | `test_panel.py`; en tabla la fila se busca por contenido (skill `pruebas`). |
| CA8 | `⌥1` y `ccl -w` van a la misma sesión agrupando por estado y por proyecto. | `test_ccl.py` sobre `pick_waiting`; `test_panel.py` sobre `⌥1`. |
| CA9 | Ninguna línea, cabecera de proyecto incluida, pasa del ancho a 80 y a 200 columnas. | `test_ccl.py` con `vis()`, nunca `len()`. |
| CA10 | El filtro `emaus` encuentra una sesión cuyo `cwd` es un worktree de `emaus`, en las dos agrupaciones. | `test_ccl.py`. |
| CA11 | Con `Ctrl-N` abierto, `Ctrl-G` ni cambia la vista ni ensucia la nota. | `test_panel.py`. |
| CA12 | Dos raíces con el mismo nombre salen como dos grupos con etiqueta desambiguada. | `test_ccl.py`. |
| CA13 | Un nombre de directorio con `\033[2A` no mueve el cursor del terminal al pintar la cabecera. | `test_ccl.py`, como los de `sin_control`. |
| CA14 | Las dos suites en verde, también en el entorno del CI sin locale. | `env -u LANG -u LC_ALL -u LC_MESSAGES python3 test_ccl.py` y lo mismo con `test_panel.py`. |
| CA15 | Con `Ctrl-G`, `→` pasa de Todas al primer proyecto y enseña solo sus sesiones agrupadas por estado; `←` desde Todas va al último. | `test_panel.py`. |
| CA16 | `barra_pestañas` nunca pasa de `ancho` y siempre contiene la activa, con 1 y con 24 proyectos, en cualquier posición, a 40, 80 y 100 columnas; `‹ ›` salen solo si hay pestañas ocultas a ese lado. | `test_ccl.py`. |
| CA17 | Sin `Ctrl-G`, `← →` no cambian nada (el cursor sigue en su sitio y el panel vivo). | `test_panel.py`. |
| CA18 | Un clic en una sesión dentro de una pestaña la selecciona; uno en la línea de pestañas cambia de pestaña sin mover el cursor de sesión. | `test_panel.py`. |
| CA19 | Filtro y pestaña a la vez; desde «sin resultados» `←` sigue cambiando de pestaña. | `test_panel.py`. |
| CA20 | Si muere la última sesión del proyecto de la pestaña activa, el panel vuelve a Todas. | `test_panel.py`, con `CCL_TEST_MATAR` y refresco corto. |
| CA21 | Escribiendo una nota, `←` mueve el cursor del texto y no cambia de pestaña. | `test_panel.py`. |
| CA22 | En las columnas de cada zona está pintada esa pestaña, con 1, 5 y 24 proyectos, a 40, 80 y 100 columnas, con etiquetas CJK y con eñes; ninguna zona se pisa ni se sale de la barra; el separador no es de nadie; `‹ ›` llevan a la primera oculta de su lado. | `test_ccl.py`. Mutando el origen de las zonas una columna, falla. |
| CA23 | En el panel, un clic en una pestaña va a ella (también por su borde derecho); en el separador no cambia nada; dos clics rápidos en la barra no abren nada. | `test_panel.py`. |

**Verificación final** (2026-11-09, `a9d810f`), todos en verde. CA1 a mano: 22 sesiones vivas en 7
grupos, el mismo total agrupando por estado y por proyecto. CA2 a mano: `emaus (75)` en un solo
grupo en `--recent`. Las pestañas, además, en el panel real sobre un pty de 100 columnas: la barra
se desplaza con `‹` al llegar a `support_agent`. El resto, por las suites: 364 tests en
`test_ccl.py` y 132 en `test_panel.py`, también sin locale.

**R21** (clic en las pestañas), 2026-11-09: CA22 y CA23 en verde, con 375 tests en `test_ccl.py` y
135 en `test_panel.py`.

## Cómo se hizo

| Fase | Commit | Qué |
|---|---|---|
| Spec | `45fe0f9`, `ea2487b` | La spec, y su ampliación con las pestañas |
| 1 — lógica pura | `ca9997d` | `proyecto_de`, agrupación, cabeceras, filtro, `--projects` en `--list` (T1-T6) |
| 2 — panel | `3337eb8` | `Ctrl-G`, cabecera, barra, ayuda y sus tests de panel (T7-T10) |
| 2b — pestañas | `a9d810f` | `_proyectos`, `barra_pestañas`, `← →` y sus tests (T15-T18) |
| 3 — cierre | el de esta reconciliación | README en paralelo, skills, `demo.svg`/`table.svg`, versión 1.4.0 (T11-T14) |
| 4 — clic en pestañas | tras 1.4.0 | La columna en el evento del ratón, `barra_y_zonas`, el clic en `interactive`, ayuda y README (R21) |

Las fases fueron en serie, como estaba previsto: cada una necesitaba las funciones de la anterior.

## Fuera de alcance

- **Ver la ventana y pestaña de iTerm** de cada sesión (`W2 · T3`). El dato existe (`ventana` en
  `build`), pero es otra columna con otro debate de ancho.
- **Plegar y desplegar grupos.** Las pestañas cubren lo de «ver solo un proyecto».
- **Elegir la pestaña desde la línea de comandos** (`ccl -p emaus`) y recordarla entre ejecuciones.
- **Nota por proyecto en la cabecera.** Las notas `por_repo` van por `cwd` exacto, no por raíz;
  mezclarlas pide decidir qué nota manda cuando un worktree tiene la suya.
- **Jerarquía proyecto › worktree.** Un nivel de grupos; el worktree se ve en el campo `repo` (R7).
- **Repos bare y sus worktrees, Mercurial, Jujutsu.** Caen al último paso del algoritmo: el propio
  `cwd`. Sin datos reales que lo pidan.
- **Recordar la agrupación entre ejecuciones** (R12).
- **Una imagen nueva en el README.** `make_demo.py` podría generar `projects.svg`. Descartado en
  1.4.0: el bloque de texto de la sección «Views» basta, y cada imagen es otro paso del CI que
  mantener al día.

## Decisiones

Cerradas el 2026-11-09. D1, D2 y D6-D9 las confirmó el usuario; D3-D5 se quedan con la
recomendación, que se le presentó como suficiente sin objeción. Se conservan las alternativas: son lo que se
descartó y por qué.

| # | Pregunta | Decidido | Descartado |
|---|---|---|---|
| D1 | ¿En qué orden van los proyectos? | **Alfabético** (R4); con orden a mano desde la 002: no baila entre refrescos y se aprende dónde está cada uno, la misma razón por la que los anchos de la tabla no se ajustan al contenido (`TODO.md`). | Por actividad más reciente, como el resto del panel, a costa de que los grupos cambien de sitio cada 4 s. Por urgencia: primero los que tienen sesiones esperando. |
| D2 | ¿Agrupación y disposición son independientes? | **Sí** (R1): `Ctrl-T` cambia la disposición, `Ctrl-G` la agrupación. El código ya separa las dos cosas. | Una tercera vista en ciclo con `Ctrl-T` (lista → tabla → proyectos): una tecla menos, pero `Ctrl-T` deja de significar «tabla» y faltaría la tabla por proyecto. |
| D3 | ¿Qué tecla? | **`Ctrl-G`** (*group*): libre, sin significado para el tty. | Tab: no es letra, pero en muchas TUI es «siguiente campo». |
| D4 | ¿Un worktree es su propio proyecto o va con su repo? | **Con su repo** (es lo que deshace los 9 nombres de `emaus`), y su nombre visible en el campo `repo` (R7). | Proyecto propio: agrupar por `basename(cwd)`, como la columna `repo`, sin función nueva — pero no arregla las subcarpetas. |
| D5 | En la tabla por proyecto, al hacer scroll la cabecera fija muestra el proyecto y la fila de nombres de columna se va. | **Aceptarlo en v1**: con grupos, los nombres de columna importan menos que saber en qué proyecto estás. | Fijar las dos: toca la lógica de la cabecera fija de `interactive`, que hoy pinta solo la `head` más cercana por encima del cursor. |
| D6 | ¿Pestañas siempre o solo con `Ctrl-G`? | **Solo con `Ctrl-G`** (R13): son parte de la vista por proyecto. | Siempre: una línea más en el panel para quien no las usa. |
| D7 | Dentro de la pestaña de un proyecto, ¿cómo se agrupa? | **Por estado** (R15). | Lista plana por actividad. |
| D8 | ¿`→` en la última pestaña? | **Vuelve a Todas** (R14), como `↑↓` dan la vuelta. | Quedarse en la última. |
| D9 | ¿Cambiar de pestaña con un clic? | **Después**, en 1.4.0; hecho a continuación cuando el usuario lo pidió (R21). | En 1.4.0: obligaba a leer la columna del ratón y a tocar sus tests, y las flechas no lo necesitaban. |
| D10 | ¿Qué hace un clic en `‹` o `›`? | **Trae la primera pestaña oculta de ese lado** (R21): es lo que la flecha promete, «hay más por aquí». | Inertes, como un adorno: se ven pulsables y no hacen nada. Como `← →`: desde una activa en mitad de la ventana iría a una pestaña que ya se veía. |

## Desviaciones del diseño

Lo que se construyó distinto de lo escrito antes del código, y por qué. Cada una se corrigió en la
spec en el mismo commit que el código.

| Diseño | Construido | Por qué |
|---|---|---|
| Resumen `2 working · 3 waiting` | `working 2 · waiting 3` (R3) | «1 pausadas» no se puede decir en español; así no hacen falta claves de plural |
| El nombre cede ocho columnas (36 → 28) | Cede nueve (→ 27) (R6) | Con ocho, una sesión vieja y sin ventana llegaba a 77 y el recorte se comía el ⚠ |
| Aviso al cambiar de agrupación | Ninguno | Como con `Ctrl-T`: el cambio se ve solo, y son dos claves de traducción menos |
| Una pestaña de proyecto = la vista por estado filtrada | Más `en_proyecto`: `repo` es `donde` (R15) | Probado con datos reales, `support_agent` salía repetido en cada fila |
| `←→` al final de la barra de estado | Junto a `↑↓` (R20) | Al final era lo primero que se perdía al recortar |
| T12: una sección en `CLAUDE.md` | Dos skills (`teclas-y-raton`, `pruebas`) y una línea en `CLAUDE.md` que apunta a `specs/` | `CLAUDE.md` se carga en cada turno; esto solo importa al tocar la vista (skill `claude-models` §5) |
| Sin pestañas | R13-R20 | Pedidas por el usuario tras la fase 2; salen en la misma versión |
| Pestañas solo con flechas (D9) | También con clic (R21) | Pedido por el usuario tras publicar 1.4.0 |

## Riesgos y deuda

- **`⌥N` no coincide con el orden visual** en la vista por proyecto. Está decidido (Invariantes);
  el riesgo es que parezca un fallo. Se mitiga en la ayuda: «cuenta sobre la cola ESPERANDO, en
  cualquier vista».
- **El `lru_cache` vive lo que el panel**, que puede llevar horas abierto. Si un directorio pasa
  a ser repo (`git init`) después de arrancar, seguirá saliendo como antes hasta reabrir `ccl`. Es
  raro y no cuesta nada; los tests llaman a `proyecto_de.cache_clear()` en `setUp`.
- **El `.git` de un worktree viene de fuera.** Solo se usa para calcular una ruta y su `basename`,
  nunca se ejecuta, se lee acotado y el nombre pasa por `sin_control()`.
- **La barra de estado ya no enseña `? help` a 100 columnas.** Con `^G` mide 110 en inglés por
  estado (antes 97, cabía) y 119 por proyecto; en español 120 y 133. Por debajo de eso el recorte
  se come lo último, que es justo la ayuda — y la ayuda es por donde se descubre todo lo demás.
  Arreglo barato: subir `?` al principio de la barra. No se hizo aquí porque cambia el orden de
  una barra que no era de esta spec.
