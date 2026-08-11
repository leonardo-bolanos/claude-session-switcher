---
name: teclas-y-raton
description: Diseño de la entrada del panel TUI de ccl. Por qué ninguna acción puede colgar de una letra suelta (se comería el filtrado), por qué Cmd no existe para un programa de terminal y el salto a la N-ésima es ⌥1..9, por qué tty.setraw se llama con termios.TCSANOW (con TCSAFLUSH de 5 teclas sobrevivía 1), cómo se sintetiza el doble clic y por qué hay que descartar el release, por qué el mapa fila→sesión se construye pintando y no calculando, el apagado del ratón antes de soltar la pantalla alternativa, y por qué la ayuda se pagina. Usar al añadir una tecla o acción, al tocar read_key, el parseo de secuencias de escape, el soporte de ratón o la ayuda.
---

## Las teclas que NO pueden ser letras

Cualquier letra empieza a filtrar, asi que ninguna accion puede colgar de una letra suelta:
se comeria el filtrado de todo lo que empiece por ella. Paso con `r` (refrescar), que impedia
buscar por "revisa" o "report", y por eso ahora es `Ctrl-R`. Lo mismo descarta `h` para la
ayuda — hay sesiones que empiezan por h — de ahi que sea `?`, que ademas es el estandar en TUIs.

Si añades una accion nueva: tecla de control, o un simbolo que nadie escribiria al buscar.
Las ocupadas hasta ahora: `Ctrl-R` refrescar, `Ctrl-N` nota, `Ctrl-P` pausar, `Ctrl-T` tabla,
`Ctrl-C`/`Ctrl-D` salir. Y un test lo fija a partir de la ayuda
(`test_ninguna_accion_es_una_letra_suelta`), asi que documentar la tecla y añadirla es el mismo
gesto: una accion sin fila en `HELP_EN`/`HELP_ES` no la vigila nadie.

**Antes de elegir una tecla de control, mira si el terminal ya la usa** (`stty -a`). `Ctrl-T` es
`VSTATUS` en macOS/BSD: la disciplina de linea lo intercepta, escribe su `load: 0.60  cmd: python…`
encima del panel y manda SIGINFO, y la tecla no llega nunca. El modo raw NO basta, porque
`read_key` entra en raw en cada lectura y lo restaura al salir: entre lectura y lectura el tty
esta en modo normal. Por eso `interactive()` desactiva `VSTATUS` mientras dura el panel
(`_sin_tecla_status`) y lo restaura al salir. Y ojo con como se prueba: es una carrera, asi que un
test que dependa del momento exacto sale intermitente — se comprueba el AJUSTE leyendo los
atributos desde el maestro del pty, que ve los del esclavo.

**La barra de estado se recorta al ancho.** Cada atajo nuevo la alarga; sin `clip` se envolvia en
ventanas estrechas y empujaba el panel una linea hacia arriba en cada repintado. Si añades uno
mas, mira si vale la pena en la barra o basta con la ayuda.

**`Cmd` no existe para un programa de terminal.** iTerm2 se queda `⌘1..9` para cambiar de
pestaña y no lo pasa por el TTY: no hay forma de leerlo desde `ccl`. Por eso el salto a la
N-esima ESPERANDO es `⌥1..9`, que con «Left Option key: Esc+» llega como `ESC` + digito. Esa
misma secuencia es la que enviaria un `⌘N` mapeado a *Send Escape Sequence*, asi que el codigo
sirve para ambos caminos sin ramas extra. Si alguien pide "que sea Cmd", la respuesta es un
atajo global (Hammerspoon → `ccl -w<n>`), no una tecla del panel.

**`⌥1..9` cuenta sobre `rows`, no sobre las filtradas.** A proposito: la tecla significa
"sacame de aqui, a la que me espera", y contando sobre lo filtrado el mismo numero llevaria a
sesiones distintas segun lo que tuvieras escrito.

**`tty.setraw()` descarta la entrada pendiente, y eso comia teclas.** Usa `TCSAFLUSH` por
defecto, que tira lo recibido y no leido; como `read_key` entra en modo raw en CADA lectura, todo
lo que llegara mientras el panel repintaba se perdia. Medido con un pty: **de 5 teclas seguidas
sobrevivia 1**. Se notaba al escribir rapido en el filtro, y hacia imposible el doble clic
(sus cuatro eventos llegan en una sola rafaga). Va con `termios.TCSANOW` — si alguien lo
"simplifica" a `tty.setraw(fd)`, vuelve.

**El terminal NO reporta dobles clics**, solo clics sueltos: el doble se sintetiza por tiempo y
fila (`DOUBLE_CLICK`). Y el **release hay que descartarlo**, o cada clic simple contaria dos veces
y pareceria doble.

**El mapa fila-de-terminal → sesion se construye pintando, no calculando.** Va dentro del bucle
de repintado (`screen[y] = i`) porque cualquier cosa que se añada arriba —la cabecera de grupo
fija, un aviso— desplaza todo; un calculo aparte se desincroniza en silencio y el clic acaba
enfocando la sesion vecina, que es el peor fallo posible: parece que funciona.

**`MOUSE_ON` se rearma en CADA repintado, no solo al arrancar.** Emitido una sola vez, cualquier
reset de los modos privados del terminal (tmux, un `reset` ajeno, iTerm restaurando la sesion)
apagaba los clics para siempre y el panel seguia tan tranquilo — el sintoma es "en algun momento
deja de funcionar el clic", y no apunta al terminal por ningun lado. Va dentro del `if dirty`, y
como el refresco de fondo lo dispara cada 4-20 s se cura solo. No se puede probar el reset en un
pty (esos modos son del emulador): se comprueba que se emite en cada repintado.

**Con el raton activo, el terminal deja de gestionar la seleccion de texto.** Por eso existe
`CCL_MOUSE=0`, y por eso el apagado (`MOUSE_OFF`) va **antes** de soltar la pantalla alternativa:
si el panel muere con el raton activo, el shell recibe escapes por cada clic. Para copiar hay tres
vias y conviene no confundirlas: `⌥`+arrastrar (iTerm2 no reporta el evento si ese modificador
esta pulsado — verificado en el binario de iTerm2 3.6.11, que lo registra como *"Not reporting
mouse event because you pressed option"*), `CCL_MOUSE=0`, o `ccl --list`. La ultima es la mejor
para copiar de verdad: el panel usa pantalla alternativa, asi que **al salir se restaura lo que
habia y se lleva la lista**.

**La ayuda se pagina porque ya no cabe.** Se pinta de arriba abajo, asi que sin paginar lo que
sobra se va por el borde SUPERIOR: se pierde el principio y **no hay ningun aviso** de que faltaba
algo. Si añades secciones, `TestAyuda` comprueba que ninguna pagina desborde la altura y que al
partir no se pierda ninguna linea. Los tests que buscan un texto en la ayuda tienen que recorrer
**todas** las paginas (`_texto_completo`), no solo `render_help(...)`.

**Al parsear una secuencia de escape hay que leer byte a byte.** Antes hacia `os.read(fd, 2)`
de golpe, lo que impedia distinguir `ESC`+digito (sin corchete) de `ESC[`. De paso: `PgUp`/`PgDn`
son `ESC [ 5 ~` y `ESC [ 6 ~` — hay que **consumir la tilde**, o queda en el buffer y la lectura
siguiente la ve como un `~` escrito, arrancando un filtro por "~" al pulsar PgDn.
