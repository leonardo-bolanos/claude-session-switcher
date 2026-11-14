---
name: notas
description: Las notas personales de ccl (Ctrl-N) y las sesiones pausadas (Ctrl-P), que comparten archivo y escritor. Decisiones de diseño de las dos. Van por sessionId con la del cwd como respaldo, y por qué (atarlas solo al cwd contagiaba la nota a las otras sesiones del mismo directorio). Cubre note_for() y la precedencia, la lectura del formato viejo, por qué no se purga nada, por qué el editor se ata a la sesión y no a la fila, la limpieza de typed al mover el cursor, el modo edición tomando el teclado primero, el color NOTE (1;38;5;174) y el fondo de la fila del cursor (con_fondo, CURSOR_BG) como las dos únicas salidas de los 16 colores ANSI, con la trampa de rearmar el fondo tras cada reset, y su efecto en make_demo.py. Usar al tocar notas, el editor del panel, ccl-notes.json o el color de la línea de detalle.
---

## Notas personales (`Ctrl-N`)

**Van por `sessionId`, con la del `cwd` como respaldo.** La primera version las ataba solo al
`cwd`, y fue un fallo reportado: escribir "esperando que felipe haga algo" en una sesion la pintaba
en las otras tres del mismo directorio. Con 16 sesiones en 11 directorios, **el 43% no podia tener
nota propia** — y las notas que la gente escribe de verdad son de estado ("esperando X"), no
etiquetas de repo.

Las dos siguen existiendo porque son dos usos distintos: el estado es de UNA conversacion; la
etiqueta ("backend de facturacion") describe el repo, vale para todas sus sesiones y **sobrevive a
reiniciar Claude Code**, que cambia el sessionId. `note_for()` resuelve la precedencia: la propia
tapa la del repo, y borrar la propia hace reaparecer la del repo — asi se "quita lo mio" sin editar
el JSON.

**El formato viejo se sigue leyendo.** El archivo era un `{cwd: nota}` plano y ahora es
`{"por_sesion": …, "por_repo": …}`; un dict plano se interpreta como `por_repo`. Quien ya tenia
notas escritas no puede perderlas por un cambio de formato, y hay un test que lo fija — mas otro
que comprueba que el primer guardado no pisa lo migrado.

**No se purga nada**, ni sesiones muertas ni directorios inexistentes. Un disco externo desmontado
o un repo movido de sitio borraria algo que el usuario escribio a mano. Al contrario que
`ccl-numbers.json`, que si se purga, porque ahi el dato lo genera el programa y se regenera.

**El editor se ata a la SESION, no a la fila.** `lines[cl]` se resuelve en cada vuelta del bucle,
asi que si la sesion que estabas anotando muere y el refresco reordena la lista, esa fila pasa a
ser otra sesion y el Enter guardaba el texto **en la equivocada** — el mismo fallo del contagio de
notas, por otro camino. Por eso hay `editando_sid`/`editando_repo`, y si esa sesion desaparece la
edicion se cancela con aviso (`nota_perdida`) antes de que el Enter pueda guardar en otra.

**Cualquier tecla que mueva el cursor tiene que limpiar `typed`.** `⌥N` no lo hacia: veias el
cursor saltar a la sesion que espera, pero el numero a medio teclear seguia teniendo prioridad y
el Enter siguiente enfocaba ESE numero. Lo hacen ya las flechas, PgUp/PgDn, la rueda y el clic.

**El modo edicion se queda el teclado, y va PRIMERO en el manejo de teclas.** Si no, en medio de
una frase la `q` cierra el panel y un digito arranca el selector por numero. Hay dos tests justo
para eso (`test_la_q_no_cierra_el_panel_mientras_escribes`).

**Al guardar hay que aplicar la nota en memoria a mano**, recorriendo `rows` por `sessionId`. Si no,
no se ve hasta el refresco (4 s) y parece que no se guardo. Y se recalcula con `note_for()` en vez
de meter el texto tal cual: asi al borrar la propia reaparece la del repo en el mismo instante.

**La nota se pinta con `NOTE` (negrita + salmon apagado), nunca con un color a secas.** La linea
de detalle es casi toda `DIM` y grises, y sin resaltar la nota se perdia entre la rama y el modelo
— justo lo contrario de para lo que sirve.

**Es uno de los dos unicos sitios que se salen de los 16 colores ANSI** (el otro es el fondo del cursor, mas abajo), y no por capricho: los
disponibles estaban todos cogidos —magenta el repo, verde/azul/gris los modelos, amarillo el
effort, gris la rama, cian el numero y la UI— y de rojo solo hay `31`, que aqui significa error y
`⚠`. Una nota no es una alarma, hace falta un rojo desaturado, y eso solo existe en la paleta de
256: `1;38;5;174` (#d78787). Un terminal sin 256 colores ignora el codigo y pinta el texto normal:
se pierde el enfasis, no se rompe nada.

Ese `38;5;N` **rompio el generador del demo**, que solo entendia los 16 basicos: se comia el
codigo y la nota salia BLANCA en `demo.svg`, justo en la pieza que sirve para ensenar el color.
Por eso `make_demo.py` tiene `color_256()` con el cubo 6x6x6 de xterm, y hay un test que
comprueba que la nota del demo lleva `fill=`.

El codigo va combinado (`1;38;5;174`) y no `BOLD(...)`: anidado deja dos resets pegados. Los tests
comprueban **`NOTE`** y no el codigo concreto —el color ya se cambio dos veces—, mas uno que
verifica que ningun otro elemento de la fila usa el mismo color, que es como se colo el magenta
duplicado con el repo.

El otro sitio con color de 256 es el **fondo de la fila del cursor** (`con_fondo`, `CURSOR_BG`,
238 por defecto). No choca con la nota —uno es fondo y la otra texto— pero si alguien cambia
cualquiera de los dos, que compruebe el otro: una nota salmon sobre un fondo salmon desaparece.
Y ahi la trampa es distinta: **cada reset del texto apaga el fondo**, asi que hay que rearmarlo
detras de cada `\033[0m` y rellenar hasta el ancho con `pad()`.

**Y el gris (`90`) y el tenue (`2`) se cambian dentro de la banda** por el gris de 256 que mas
contrasta con ella (`_gris_sobre`). Estan pensados para el fondo del terminal: en un tema oscuro
real el `90` era #414868 sobre la banda #444444, contraste 1,1, y al seleccionar una recuperable
(las que faltan de la foto van enteras en gris) no se leia nada. Ojo al tocarlo: un umbral fijo
de luminancia elegia el peor gris en bandas de color, y lo cazo el test que recorre las 240. Si
añades un color nuevo que pueda quedar tenue sobre la banda, se cambia en `con_fondo`, no en cada
sitio que pinta.

**El editor arranca con la nota que ya hubiera** — corregir no es reescribir. Y el cursor `▏` del
prompt no es decoracion: sin el, una nota vacia no se distingue de "no estoy editando" y parece
que la tecla no hizo nada.

Ojo al probar el panel: `test_panel.py` parchea `collect`, que **se salta `build`**, y es build
quien pega las notas a las filas. El arnes replica ese paso; sin eso, la nota no reaparece al
reabrir el panel y parece un fallo de persistencia que no existe. Y `NOTES_FILE` se desvia a un
temporal: es el unico archivo que el panel escribe de verdad en disco.

## Pausadas (`Ctrl-P`), en el mismo archivo

`ccl-notes.json` guarda `por_sesion`, `por_repo`, `pausadas` (lista de sessionId),
`pausada_desde` (cuándo se pausó cada una: solo un prompt tuyo posterior la despausa, ver
CLAUDE.md), `spaces` y `orden_proyectos` (el orden a mano de las pestañas, specs/002).

**Un solo escritor: `guardar_estado()`.** `save_note` se escribia el JSON entero por su cuenta con
dos claves, asi que la primera nota borraba todas las pausadas. Cualquier cosa nueva que se guarde
ahi pasa por `load_state()` y `guardar_estado()`; **nadie mas llama a
`escribir_json(NOTES_FILE, …)`**. El orden de proyectos no viaja en la tupla de `load_state`:
`guardar_estado(…, orden=None)` relee el que haya en disco y lo conserva, asi que quien guarda una
nota no puede borrarlo por no saber que existe. Si añades otra clave, hazlo igual.

**La deteccion del formato viejo mira todas las claves.** Con solo `por_sesion`/`por_repo`, un
archivo que unicamente tuviera `pausadas` se leia como el formato plano `{cwd: nota}` y la lista
acababa siendo la nota de un repo llamado "pausadas".

**Pausada la excluye `is_waiting()`**, no `grouped()`: ahi esta el valor, porque `-w`/`⌥N` dejan
de mandarte a la sesion que espera a otro. Los grupos son excluyentes — una pausada `busy` va a
TRABAJANDO, una de background pausada solo a PAUSADAS.

**Y la pausada `busy` lleva `⏸` delante del nombre** (`marca_pausa`, en la lista y en la tabla).
Sin ella, pausar una que trabajaba no movia nada, parecia que Ctrl-P no hizo nada, y pulsarlo
otra vez la despausaba. Solo ahi: en PAUSADAS ya lo dice el grupo. El nombre cede los dos
caracteres de la marca para no pegarse a la columna siguiente.

**Se aplica en memoria al pulsar**, igual que la nota: hasta el refresco siguiente (4 s) no
cambiaria de grupo y pareceria que la tecla no hizo nada.

**Y despues hay que llamar a `feed.cambio_local(rows)`**, en las dos. El refresco de fondo lee
`ccl-notes.json` al empezar y publica al acabar: uno que lo leyo antes de la tecla y llegaba
despues devolvia la sesion a ESPERANDO, y pulsar otra vez —"no funciono"— la despausaba de
verdad. Reportado como "a veces el Ctrl-P no funciona". `cambio_local` tira el refresco en
vuelo, sustituye el publicado sin recoger y pide otro al momento. Cualquier tecla nueva que
escriba algo que viaje en las filas tiene que llamarlo; los tests son
`test_un_refresco_en_vuelo_no_deshace_*` (panel) y `TestFeedCambioLocal`.

Tampoco se purga: un sessionId es un UUID y no se reutiliza, asi que una entrada huerfana no puede
pausar a nadie por error.
