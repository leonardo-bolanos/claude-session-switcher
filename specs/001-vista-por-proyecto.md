---
capacidad: project-view
estado: aprobada
modo: prospectivo
rutas:
  - ccl
  - test_ccl.py
  - test_panel.py
  - README.md
  - README.es.md
verificada_contra_commit: 81cfeaa
fecha: 2026-11-09
---

# 001 · Vista por proyecto

## Qué se pide

> «Quiero agregar una vista que se pueda ver pestañas de acuerdo a proyecto.»

Interpretación: hoy el panel agrupa las sesiones —cada una vive en una pestaña— **por estado**
(TRABAJANDO, ESPERANDO, PAUSADAS…). Se pide poder agruparlas **por proyecto**: todas las pestañas
de `support_agent` juntas, todas las de `NewCariAI` juntas, cada grupo con su resumen de estados.
Es otra forma de mirar la misma lista, no otra lista: se elige, se salta y se filtra igual.

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
repo principal.** Se resuelve en una función nueva, `proyecto_de(cwd)`, sin subprocesos:

1. Subir desde `cwd` hacia arriba, **sin llegar a `HOME` ni a `/`**. En cada directorio `d`:
   - `d/.git` es un directorio → la raíz es `d`.
   - `d/.svn` es un directorio → la raíz es `d` (SVN ≥ 1.7 solo deja `.svn` en la raíz del
     checkout).
   - `d/.git` es un **archivo** → leer como mucho 4 KB. Si dice `gitdir: X` y `X` (resuelto
     relativo a `d`) tiene la forma `<R>/.git/worktrees/<nombre>`, es un **worktree vinculado**
     y la raíz es `R`. Si no tiene esa forma (un submódulo: `../.git/modules/x`), la raíz es `d`:
     un submódulo es su propio proyecto.
2. Sin ninguna marca, la raíz es el propio `cwd` — que es lo que se ve hoy.

Nombre del proyecto: `basename(raíz)`, **pasado por `sin_control()`**: el nombre de un directorio
viene de fuera y puede traer secuencias de escape (ver «Lo que se pinta viene de fuera» en
`CLAUDE.md`). Si dos raíces distintas comparten nombre en la misma lista, ambas se etiquetan con
sus dos últimos componentes (`cariai/api`, `personal/api`): la **clave** del grupo es la ruta de la
raíz, nunca el nombre.

### Verificado contra datos reales

El prototipo del algoritmo sobre los `cwd` de los 200 transcripts más recientes (`recent_rows`)
tardó **4,8 ms** y resolvió:

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
| R1 | `Ctrl-G` alterna la agrupación: **por estado** (la de hoy) ↔ **por proyecto**. Es independiente de `Ctrl-T`: las cuatro combinaciones (dos líneas o tabla × estado o proyecto) existen. |
| R2 | `ccl -p` / `ccl --projects` arranca agrupado por proyecto. Se combina con `--list`, `--table`, `--recent` y `--saved`. |
| R3 | Cabecera de cada grupo: nombre, total y resumen por estado con sus colores, omitiendo los ceros: `support_agent (6) · 2 working · 3 waiting · 1 paused`. |
| R4 | Orden de los grupos: **alfabético**, sin mayúsculas ni acentos; desempata la ruta de la raíz. Un proyecto cuyas filas son **todas** `faltante` (`--saved`) va al final. |
| R5 | Orden dentro de un grupo: el de `grouped()` aplicado a las filas de ese proyecto — estado y, dentro, actividad. Se reutiliza `grouped()`, no se reimplementa el orden. |
| R6 | Cada fila dice su estado, con la etiqueta y el color de `estado_de()`. En la tabla ya hay columna; en la vista de dos líneas se añade a la línea principal, que debe seguir cabiendo en 80 columnas sin perder la antigüedad. |
| R7 | En la vista por proyecto, el campo `repo` sale **vacío si `cwd` es la raíz** y con `basename(cwd)` si no: el nombre del worktree o de la subcarpeta. Repetir el proyecto seis veces bajo su propia cabecera es ruido; lo informativo es la excepción. |
| R8 | El filtro (`matches`) busca también por el nombre del proyecto, **en las dos agrupaciones**: escribir `emaus` encuentra una sesión cuyo `cwd` es `emaus/.claude/worktrees/offline-mode`. |
| R9 | La cabecera del panel añade `· N projects` en la vista por proyecto. |
| R10 | `^G` aparece en la barra de estado, detrás de `^T`, y en la ayuda (`HELP_EN`, `HELP_ES`) y el uso (`USO_EN`, `USO_ES`). |
| R11 | No cambia: la numeración, `⌥1…9` y `-w` (cola ESPERANDO global, ver Invariantes), `Enter`, clic y doble clic, notas, pausa, `Ctrl-O`. |
| R12 | La agrupación **no se recuerda** entre ejecuciones. Misma postura que la tabla en `TODO.md`: la bandera o un alias lo resuelven sin inventar una regla de precedencia. |

## Dónde se toca

Todo en `ccl`. La idea entera es que **la vista por proyecto es otra lista de grupos con la misma
forma** `[(etiqueta, color, filas)]` que devuelve `grouped()`: si se cumple, el cursor, el clic, el
scroll y la cabecera fija funcionan sin enterarse, igual que pasó con la tabla
(`build_table_display`, «devuelve los MISMOS roles a propósito»).

| Pieza | Cambio |
|---|---|
| `proyecto_de(cwd)` | **Nueva.** `(raíz, nombre)` según el algoritmo de arriba, con `lru_cache`. |
| `agrupar_por_proyecto(rows)` | **Nueva.** Misma forma que `grouped()`. Reparte por raíz, ordena según R4 y, dentro de cada proyecto, aplana `grouped(subconjunto)` (R5). Resuelve aquí las colisiones de nombre. |
| `grupos(rows, por_proyecto)` | **Nueva.** El único sitio que elige entre `grouped` y `agrupar_por_proyecto`. |
| `cabecera_grupo(…)` | **Nueva.** Hoy `render` y `build_display` construyen `f"{label} ({len(items)})"` cada uno por su cuenta; la del proyecto lleva además el resumen (R3). Una sola función para las dos, recortada al ancho **al construirla**. |
| `render`, `build_display`, `build_table_display`, `vista` | Reciben `por_proyecto` y llaman a `grupos()`. `build_table_display` mete una línea `head` por proyecto debajo de la de nombres de columna. |
| `main_line` | Con `por_proyecto`, columna de estado (R6) y `repo` según R7. |
| `table_line` | `repo` según R7; la columna de estado ya existe. |
| `matches` | Añade el nombre del proyecto al texto en el que se busca (R8). |
| `_read_key` | `"\x07"` (`Ctrl-G`) → `"proyectos"`. |
| `interactive` | Parámetro `por_proyecto`; la rama `k == "proyectos"` lo alterna y pone `requery`, como `Ctrl-T`. Cabecera con el número de proyectos (R9) y `^G` en la barra (R10). |
| `parse_args`, `main` | `-p`/`--projects`, propagado a las tres llamadas a `interactive` y a las de `render`. |
| `TEXTOS` | Claves nuevas en **los dos idiomas** con los mismos huecos (lo exige un test): la barra, la cabecera, el aviso al cambiar de vista y los resúmenes de estado si no se reutilizan las etiquetas existentes. |

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

## Criterios de aceptación

| # | Criterio | Cómo se verifica |
|---|---|---|
| CA1 | `ccl --list --projects` muestra un grupo por proyecto con las sesiones vivas del momento; la suma de los totales es la de `ccl --list`. El 2026-11-09 serían 7 grupos para 17 sesiones. | A mano, con datos reales; la propiedad, en `test_ccl.py`. |
| CA2 | `ccl --recent --list --projects` agrupa bajo **un solo** `emaus` los 12 directorios distintos que hoy salen con 9 nombres, incluidos los worktrees ya borrados. | A mano: los datos existen hoy en `~/.claude/projects`. |
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

## Plan

Tres tandas en serie: la 2 necesita las funciones de la 1, y la 3 documenta lo que quede. Dentro
de cada tanda las tareas son pequeñas y del mismo archivo; no compensa repartirlas.

**Fase 1 — lógica pura** (`ccl` + `test_ccl.py`)

- T1. `proyecto_de` con sus casos: repo, subcarpeta, worktree vinculado, worktree borrado,
  submódulo, SVN, SVN anidado, sin VCS, tope en `HOME`, `.git` ilegible. (CA3–CA5)
- T2. `agrupar_por_proyecto` y `grupos`: propiedad de exclusividad, orden R4, orden interno R5,
  faltantes al final, colisión de nombres. (CA1, CA12)
- T3. `cabecera_grupo` con resumen y recorte; `render` y `build_display` pasan a usarla. (CA9, CA13)
- T4. `main_line` y `table_line` con estado y `repo` según R6–R7; `build_table_display` con
  cabeceras de proyecto. (CA9)
- T5. `matches` con el proyecto. (CA10)
- T6. `parse_args` con `-p`/`--projects`; `pick_waiting` igual en las dos agrupaciones. (CA8)

**Fase 2 — panel** (`ccl` + `test_panel.py`)

- T7. `Ctrl-G` en `_read_key`, con su caso en `TestLecturaDeTeclas` y en `TestEntreLecturas`.
- T8. `interactive`: alternar, cabecera R9, barra R10; `main` propaga la bandera.
- T9. `TEXTOS`, `HELP_EN`/`HELP_ES`, `USO_EN`/`USO_ES`, en los dos idiomas.
- T10. Tests de panel: alternar con cursor estable, clic en las dos disposiciones, `⌥1`, el editor
  se queda `Ctrl-G`, arranque con `CCL_TEST_ARGS=--projects`. (CA6, CA7, CA8, CA11)

**Fase 3 — documentación y cierre**

- T11. `README.md` y `README.es.md` **en paralelo**: tecla, bandera, la sección «Two views» pasa a
  hablar de las dos agrupaciones.
- T12. `CLAUDE.md`: una sección corta con las trampas que queden (el tope en `HOME`, derivar en vez
  de almacenar, `⌥N` global). Skill `teclas-y-raton`: añadir `Ctrl-G` a las ocupadas y las
  descartadas con su motivo.
- T13. Comprobar CA1 y CA2 a mano con datos reales; versión `1.4.0` (minor: funcionalidad nueva).
- T14. Reconciliar esta spec y pasarla a `implementada` en el mismo commit que cierre el trabajo.

## Fuera de alcance

- **Ver la ventana y pestaña de iTerm** de cada sesión (`W2 · T3`). El dato existe (`ventana` en
  `build`), pero es otra columna con otro debate de ancho.
- **Plegar y desplegar grupos**, y saltar al proyecto siguiente con una tecla.
- **Nota por proyecto en la cabecera.** Las notas `por_repo` van por `cwd` exacto, no por raíz;
  mezclarlas pide decidir qué nota manda cuando un worktree tiene la suya.
- **Jerarquía proyecto › worktree.** Un nivel de grupos; el worktree se ve en el campo `repo` (R7).
- **Repos bare y sus worktrees, Mercurial, Jujutsu.** Caen al último paso del algoritmo: el propio
  `cwd`. Sin datos reales que lo pidan.
- **Recordar la agrupación entre ejecuciones** (R12).
- **Una imagen nueva en el README.** `make_demo.py` podría generar `projects.svg`; se decide al
  cerrar, según cómo quede la sección.

## Decisiones

Cerradas el 2026-11-09. D1 y D2 las confirmó el usuario; D3-D5 se quedan con la recomendación,
que se le presentó como suficiente sin objeción. Se conservan las alternativas: son lo que se
descartó y por qué.

| # | Pregunta | Decidido | Descartado |
|---|---|---|---|
| D1 | ¿En qué orden van los proyectos? | **Alfabético** (R4): no baila entre refrescos y se aprende dónde está cada uno, la misma razón por la que los anchos de la tabla no se ajustan al contenido (`TODO.md`). | Por actividad más reciente, como el resto del panel, a costa de que los grupos cambien de sitio cada 4 s. Por urgencia: primero los que tienen sesiones esperando. |
| D2 | ¿Agrupación y disposición son independientes? | **Sí** (R1): `Ctrl-T` cambia la disposición, `Ctrl-G` la agrupación. El código ya separa las dos cosas. | Una tercera vista en ciclo con `Ctrl-T` (lista → tabla → proyectos): una tecla menos, pero `Ctrl-T` deja de significar «tabla» y faltaría la tabla por proyecto. |
| D3 | ¿Qué tecla? | **`Ctrl-G`** (*group*): libre, sin significado para el tty. | Tab: no es letra, pero en muchas TUI es «siguiente campo». |
| D4 | ¿Un worktree es su propio proyecto o va con su repo? | **Con su repo** (es lo que deshace los 9 nombres de `emaus`), y su nombre visible en el campo `repo` (R7). | Proyecto propio: agrupar por `basename(cwd)` como hoy, sin función nueva — pero no arregla las subcarpetas. |
| D5 | En la tabla por proyecto, al hacer scroll la cabecera fija muestra el proyecto y la fila de nombres de columna se va. | **Aceptarlo en v1**: con grupos, los nombres de columna importan menos que saber en qué proyecto estás. | Fijar las dos: toca la lógica de la cabecera fija de `interactive`, que hoy pinta solo la `head` más cercana por encima del cursor. |

## Riesgos

- **`⌥N` no coincide con el orden visual** en la vista por proyecto. Está decidido (Invariantes);
  el riesgo es que parezca un fallo. Se mitiga en la ayuda: «cuenta sobre la cola ESPERANDO, en
  cualquier vista».
- **El `lru_cache` vive lo que el panel**, que puede llevar horas abierto. Si un directorio pasa
  a ser repo (`git init`) después de arrancar, seguirá saliendo como antes hasta reabrir `ccl`. Es
  raro y no cuesta nada; los tests llaman a `proyecto_de.cache_clear()` en `setUp`.
- **El `.git` de un worktree viene de fuera.** Solo se usa para calcular una ruta y su `basename`,
  nunca se ejecuta, se lee acotado y el nombre pasa por `sin_control()`.
