---
capacidad: tab-order
estado: implementada
modo: retroactivo
rutas:
  - ccl
  - test_ccl.py
  - test_panel.py
  - README.md
  - README.es.md
  - .claude/skills/teclas-y-raton/SKILL.md
ultima_verificacion_commit: 56ba405
ultima_verificacion_fecha: 2026-11-09
---

# 002 · Orden de las pestañas a mano

> **Implementada** el 2026-11-09, sin versión publicada todavía. Se escribió antes del código y se
> reconcilió al terminar: lo que sigue describe lo construido, y lo que salió distinto está en
> *Desviaciones*. Se apoya en la 001 (vista por proyecto) y cambia su R4: el orden deja de ser
> solo alfabético.
>
> **Falta CA10**, que solo se puede comprobar a mano en el iTerm del usuario.

## Qué se pide

> «¿Se puede que pueda arrastrar para fijar la posición del tab?»

Poder poner las pestañas de la vista por proyecto en el orden que uno quiera, arrastrándolas con
el ratón. Lo pidió el usuario recién hecho el clic en las pestañas (001 R21).

## Por qué hace falta

El orden alfabético (001 D1) se eligió para que las pestañas no se movieran solas, y eso se
mantiene. Lo que no da es *tu* orden: el proyecto en el que trabajas todo el día puede quedar el
sexto, detrás de cinco que miras una vez por semana. Con 8 proyectos vivos (2026-11-09) la barra
ya no cabe en 100 columnas, así que el que va al final ni siquiera se ve sin desplazarla.

Un orden manual **tampoco se mueve solo**: respeta la razón de D1 mejor que cualquier orden
automático, porque solo cambia cuando tú lo cambias.

## Comportamiento

| # | Requisito |
|---|---|
| R1 | **Arrastrar una pestaña** (pulsar sobre ella y soltar sobre otra) la lleva al sitio de la otra; las de en medio se corren un puesto, como en un navegador. La pestaña salta al soltar: mientras arrastras no se mueve nada. |
| R2 | **`Shift-←` / `Shift-→`** mueven la pestaña activa un puesto. En los extremos no hacen nada: no dan la vuelta, a diferencia de `← →`, porque mover no es navegar. |
| R3 | ***Todas* va siempre primera** y no se mueve. Soltar una pestaña sobre *Todas* la pone la primera de los proyectos: es a donde ibas al arrastrar del todo a la izquierda. |
| R4 | El orden **se guarda** en `ccl-notes.json` y sobrevive a cerrar `ccl`. |
| R5 | El mismo orden vale para las **pestañas, los grupos de *Todas* y `ccl --list --projects`**: los tres salen de `_proyectos`, y así siguen saliendo en el mismo orden (001 R13). |
| R6 | Un proyecto que **no está en el orden guardado** (nuevo, o de `--recent`) va detrás de los ordenados, en orden alfabético. Uno que está guardado y ahora no tiene sesiones **conserva su puesto** para cuando vuelva. |
| R7 | Un proyecto cuyas filas son todas `faltante` (`--saved`) sigue yendo al final, como hoy (001 R4): el orden manual manda dentro de cada uno de los dos bloques. |
| R8 | Soltar fuera de la barra, sobre un separador, o sobre la misma pestaña que se pulsó, no cambia el orden. Un clic normal sigue siendo solo un clic: **soltar en la misma columna en la que se pulsó nunca es un arrastre**, aunque debajo haya ahora otra pestaña (ver *Desviaciones*). |
| R9 | Escribiendo una nota, `Shift-← →` mueven el cursor del texto como `← →`, y el ratón no hace nada (como hoy). |
| R10 | Ayuda y README en los dos idiomas. La barra de estado no cambia: ya no cabe. |

## Cómo

### El ratón ya trae lo que hace falta

No hace falta pedir al terminal el movimiento (modo 1002). En SGR (1006) **el terminal informa
de la columna también al soltar** (`ESC [ < 0 ; col ; fila m`): pulsar en una columna y soltar en
otra ya es un arrastre. Hoy `_read_mouse_sgr` tira el release sin mirarlo (`"mouse-release"`);
pasa a devolver `soltar:<fila>:<col>` para el botón izquierdo. En X10 el release no dice qué botón
se soltó, pero sí dónde: también da `soltar:`.

El release se sigue ignorando en todo lo demás —ni repinta ni cuenta para el doble clic—; si no,
cada clic simple parecería doble (skill `teclas-y-raton`).

**Pendiente de verificar en el iTerm del usuario** con `CCL_DEBUG` (CA10): que un arrastre real
llega como un `click:` y un `soltar:` con columnas distintas. Es lo que dice el protocolo, pero el
pty de los tests no tiene emulador y no puede probarlo.

### Dónde vive

| Pieza | Cambio |
|---|---|
| `_read_mouse_sgr`, `_read_mouse_x10` | El release del botón izquierdo devuelve `soltar:<fila>:<col>`. |
| `_read_csi` | `ESC[1;2C` / `ESC[1;2D` (modificador 2 = Shift) dan `shift-right` / `shift-left`. Los demás modificadores siguen sin cambiar la tecla, como ahora. |
| `orden_proyectos()` | Lee la lista de raíces guardada. Tolera basura: solo cadenas, sin repetidas. |
| `guardar_estado(…, orden=None)` | Escribe también `orden_proyectos`. **Con `orden=None` conserva el que haya en disco**: quien guarda una nota o una pausa no sabe nada del orden y no puede borrarlo. Es el fallo que ya pasó con las pausadas (`CLAUDE.md`), cerrado por construcción y no por disciplina de los que llaman. |
| `load_state` | La detección del formato viejo mira también `orden_proyectos`. |
| `mover_proyecto(orden, visibles, clave, destino)` | Pura. El orden nuevo tras llevar `clave` al sitio de `destino` (`None` = *Todas* → el primero). |
| `reordenar_pestaña(rows, clave, destino)` | Mueve y guarda; devuelve si cambió algo, para no reescribir el archivo ni repintar por nada. La comparten el arrastre y `Shift-← →`. |
| `guardar_orden_proyectos(orden)` | El único camino para escribir el orden: pasa por `guardar_estado`. |
| `_proyectos(rows, orden=None)` | Ordena por (`solo_faltan`, puesto en el orden guardado, alfabético, raíz). Sin `orden`, lo lee. |
| `interactive` | Estado `arrastre`: `(clave, columna)` pulsadas en la barra. `soltar:` se atiende antes que el editor y antes de marcar `dirty`, para que soltar no repinte ni borre el aviso, y vacía `arrastre` siempre. `Shift-← →` en el bucle principal; en la rama de lista vacía y en el editor hacen de `← →`. |

### El algoritmo de `mover_proyecto`

1. La lista completa: el orden guardado, y detrás las raíces visibles que no estén en él, en el
   orden en que se ven (el alfabético, por R6). Las pestañas visibles salen de esa lista en ese
   mismo orden, así que mover dentro de ella mueve lo que se ve.
2. Se quita `clave` y se mete **delante** de `destino` si iba hacia la izquierda, **detrás** si iba
   hacia la derecha. Es lo que hace un navegador: la soltada ocupa el sitio de la otra.
3. Las raíces guardadas que ahora no se ven no se tocan: conservan su puesto relativo (R6).

## Invariantes

- **Un solo escritor de `ccl-notes.json`: `guardar_estado()`.** Y ahora además nadie puede borrar
  el orden por no conocerlo.
- **Las zonas de la barra salen del mismo cálculo que la pinta** (001 R21): soltar usa las zonas
  del último repintado, que es lo que el usuario ve al soltar (pulsar ya activó la pestaña y
  repintó, y la barra pudo desplazarse).
- **Ninguna acción cuelga de una letra suelta.** `Shift-←` no es letra.
- `⌥1-9`, `-w` y los números no cambian: no dependen del orden de los grupos.

## Criterios de aceptación

| # | Criterio | Cómo se verifica |
|---|---|---|
| CA1 | `mover_proyecto`: a la derecha, a la izquierda, sobre *Todas*, sobre sí misma; los nuevos detrás en alfabético; un guardado que no se ve conserva su puesto. | `test_ccl.py`. |
| CA2 | `_proyectos`, `pestañas_de` y `agrupar_por_proyecto` siguen el orden guardado; los `faltante` siguen al final. | `test_ccl.py`. |
| CA3 | Guardar una nota, pausar y aprender un escritorio **no borran** el orden. | `test_ccl.py`. |
| CA4 | `ESC[1;2C`/`ESC[1;2D` son `shift-right`/`shift-left`; `ESC[1;5D` sigue siendo `left`; soltar da `soltar:<fila>:<col>` en SGR y en X10. | `test_ccl.py`, con pty (`TestLecturaDeTeclas`). |
| CA5 | En el panel: arrastrar `delta` sobre `compartido` la pone delante, y sigue así al reabrir el panel con el mismo archivo de notas. | `test_panel.py`. |
| CA6 | `Shift-→` mueve la pestaña activa; en el extremo no hace nada; sin la vista por proyecto no hace nada. | `test_panel.py`. |
| CA7 | Un clic simple, soltar fuera de la barra o sobre un separador no cambian el orden; el doble clic sobre una sesión sigue abriéndola. A 44 columnas, un clic en una pestaña del borde —que desplaza la barra al activarla— no la arrastra. | `test_panel.py`; el doble clic, por los tests de ratón de siempre. El de 44 columnas falla si se quita la condición de la misma columna (comprobado mutándola). |
| CA8 | Escribiendo una nota, `Shift-←` mueve el cursor del texto. | `test_panel.py`. |
| CA9 | `test_ccl.py` no lee el `~/.claude/ccl-notes.json` real: los tests de agrupación darían otro orden en cuanto el usuario arrastrara algo. | `NOTES_FILE` parcheado a un temporal para todo el módulo. |
| CA10 | **Pendiente.** Un arrastre real en iTerm2 llega como `click:` + `soltar:` con columnas distintas, y `Shift-←` como `shift-left`. | A mano, con `CCL_DEBUG`, en la máquina del usuario. |

**Verificación** (2026-11-09): CA1-CA9 en verde, con 390 tests en `test_ccl.py` y 142 en
`test_panel.py`, también sin locale. El test de CA3 falla si `guardar_estado` deja de conservar el
orden (comprobado mutándolo). CA10, pendiente.

## Cómo se hizo

| Paso | Qué |
|---|---|
| Spec | Esta, en modo prospectivo, con D1-D4 cerradas por el usuario |
| Código y tests | Persistencia, `mover_proyecto`, lectura de `soltar:` y `Shift`, el panel; ayuda, README, skills `teclas-y-raton`, `notas`, `pruebas` |
| Reconciliación | Esta reescritura |

## Desviaciones del diseño

| Diseño | Construido | Por qué |
|---|---|---|
| Soltar sobre otra pestaña es un arrastre | Solo si además se suelta en **otra columna** (R8) | Pulsar activa la pestaña, y si la barra no cabe se desplaza para enseñarla: bajo el ratón queda la vecina, y un clic simple la arrastraría. Se vio repasando el código antes de probarlo, y un test a 44 columnas lo fija |
| `Shift-← →` en la rama de lista vacía mueven | **Navegan**, como `← →` | Ahí no se pinta la barra: mover una pestaña que no se ve no se puede comprobar |
| `test_ccl.py` ya aislaba `ccl-notes.json` | Hubo que desviarlo para **todo el módulo** (CA9) | Solo lo hacían las clases que escriben; las de agrupación lo leían sin saberlo, y con el orden guardado ahí darían otro resultado en la máquina del usuario. El guardarraíl de «apunta al home» pasó a mirar el valor de antes del desvío |

## Fuera de alcance

- **Ver la pestaña moverse mientras arrastras.** Exige el modo 1002 (un evento por cada celda que
  cruza el ratón con el botón pulsado) y repintar en cada uno. Decidido por el usuario: que salte.
- **Soltar en una zona oculta de la barra.** Se suelta sobre lo que se ve, `‹ ›` incluidos (llevan
  a la primera oculta de su lado). Para llevar una pestaña lejos está `Shift-← →`.
- **Volver al orden alfabético** con una tecla. Se borra la clave `orden_proyectos` del JSON.
- **Purgar del orden los proyectos que ya no existen.** Son unas rutas; mismo criterio que las
  notas y las pausadas, que tampoco se purgan.
- **Reordenar grupos por estado** (TRABAJANDO, ESPERANDO…). Ese orden tiene significado.

## Decisiones

Cerradas el 2026-11-09. D1-D4 las respondió el usuario («1 sí, 2 sí, 3 sí, 4 salte»); D5 y D6 se
quedan con la recomendación.

| # | Pregunta | Decidido | Descartado |
|---|---|---|---|
| D1 | ¿Se guarda el orden entre ejecuciones? | **Sí**, en `ccl-notes.json` (R4). | Solo mientras dura el panel: habría que rehacerlo cada vez. |
| D2 | ¿Vale para los grupos de *Todas* y `--list -p`? | **Sí**, un solo orden (R5). | Solo la barra: pestañas y grupos saldrían en distinto orden. |
| D3 | ¿También con teclado? | **Sí**, `Shift-← →` (R2): sirve con `CCL_MOUSE=0` y para llevar una pestaña lejos. | Solo ratón. |
| D4 | ¿Se ve moverse al arrastrar? | **No: salta al soltar** (R1). | Modo 1002 con repintado continuo. |
| D5 | ¿Qué pasa al soltar sobre *Todas*? | **Pasa a ser la primera** (R3). | No hacer nada: el arrastre más natural hacia la izquierda se pasa de largo. |
| D6 | ¿`Shift-← →` dan la vuelta en los extremos? | **No** (R2). | Como `← →`: llevar la primera al final de un toque sorprende más que ayuda. |

## Riesgos

- **iTerm2 podría reservarse `Shift-←/→`** en algún preset de teclas. Lo estándar (xterm) es
  `ESC[1;2D`/`ESC[1;2C`, pero no está verificado en el iTerm del usuario: entra en CA10. Si no
  llegan, `CCL_DEBUG` lo enseña (`desconocida`, o nada).
- **El orden guardado crece** con cada proyecto que se toca y nunca se purga. Son rutas de unas
  decenas de bytes.
