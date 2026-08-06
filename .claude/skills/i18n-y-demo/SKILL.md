---
name: i18n-y-demo
description: La interfaz bilingüe de ccl (TEXTOS, HELP_EN/HELP_ES, t(), detect_lang) y la generación del demo.svg. Recoge las cuatro cosas que se rompieron al hacerlo bilingüe, con la regla de fondo: nada debe localizar algo buscando texto de la interfaz (mordió cuatro veces, incluido el propio CI). Incluye los comandos para reproducir el entorno del CI sin locale y el escenario de "Claude Code no instalado" con HOME vacío, más las trampas de make_demo.py (tspan dentro de text, textLength, animación CSS y no SMIL, y por qué una imagen de un solo fotograma no lleva animación). Cubre también table.svg, la imagen fija de la vista de tabla que genera el mismo script con --table. Usar al añadir texto visible, tocar traducciones, regenerar demo.svg o table.svg, o editar los README.
---

### La interfaz bilingüe

Todo el texto que ve el usuario sale de `TEXTOS` (dict plano) o de `HELP_EN`/`HELP_ES` (la ayuda,
que son 33 filas y como claves planas resultaba ilegible). `t("clave", hueco=…)` devuelve el texto
del idioma activo. `detect_lang()` mira `CCL_LANG`, luego `LC_ALL`, `LC_MESSAGES` y `LANG` — ese
orden es el de POSIX, y quien exporta `LC_ALL=C` espera que gane.

Cuatro cosas que se rompieron al hacerlo bilingüe, y que un test fija ahora:

- **`color_age` decidía el color mirando el TEXTO** (`empieza por "hace "`). En inglés no empieza
  por "hace", así que **todo salía en gris** sin que nada fallara. Por eso existe
  `minutes_since()`: el color se decide con el número.
- **Los tests heredaban el locale de quien los ejecutaba.** Pasaban con `LANG=es_ES` y fallaban en
  el CI, que corre sin locale. Ahora `test_ccl.py` fija `ccl.LANG = "en"` y `test_panel.py` exporta
  `CCL_LANG=es`; los asserts que dependen de un texto usan `ccl.t(...)` en vez de escribirlo.

  **Ojo: `test_panel.py` arranca subprocesos por DOS caminos** —`Panel` (fork del pty) y
  `TestSinPanel._correr` (`subprocess.run` con un entorno construido a mano)— y cada uno tiene que
  fijar `CCL_LANG` y `CCL_TEST_NOTES` por su cuenta. La primera vez se arreglo solo el primero y el
  CI lo cazo. **Antes de empujar, reproduce el entorno del CI**, que no es el tuyo:

  ```bash
  env -u LANG -u LC_ALL -u LC_MESSAGES python3 test_ccl.py
  env -u LANG -u LC_ALL -u LC_MESSAGES python3 test_panel.py
  ```
- **Nada debe localizar algo buscando texto de la interfaz.** Mordió **cuatro** veces:
  `color_age` (arriba); el helper `aviso()` de `test_panel.py` —buscaba "sesiones", en inglés
  devolvía cadena vacía y los asserts sobre el aviso pasaban **sin comprobar nada**—;
  `make_demo.py`, que filtraba los fotogramas igual y se quedaba sin uno solo; y el propio **CI**,
  cuyo paso «degrada bien sin Claude Code» grepeaba el error en español y se puso rojo en cuanto
  la interfaz pasó a inglés — el programa hacía lo correcto y el que estaba mal era el CI.

  Dentro del programa, localiza por **forma**: un hueco de tres espacios, una regex de la cabecera
  (`\d+ \S+ ·`)… y aplicándola sobre el texto **sin escapes**, porque la cabecera lleva códigos de
  color entre el número y la palabra. Desde fuera (CI, scripts), **fija `CCL_LANG`** y comprueba
  ese idioma; el paso del CI lo hace ahora en los dos, así la traducción queda probada en el
  binario de verdad.

  Para reproducirlo en local hace falta **`HOME` vacío además de un PATH mínimo**: con tu `HOME`,
  `claude_bin()` encuentra `claude` en `~/.nvm/...` y el escenario «no está instalado» no se da.

  ```bash
  env -i HOME=/tmp/home-vacio PATH=/usr/bin:/bin ./ccl --list   # debe salir con 1
  ```
- `t()` **cae al inglés si falta una clave** en vez de reventar, y hay un test que comprueba que
  las dos tablas tienen exactamente las mismas claves y los mismos huecos `{…}`.

Si añades texto visible: va a `TEXTOS` en los dos idiomas. El guardarraíl de las letras sueltas
(`test_ninguna_accion_es_una_letra_suelta`) recorre **las dos** ayudas.

**Los dos README van en paralelo: si tocas uno, toca el otro.** Tienen las mismas secciones en el
mismo orden justamente para que el diff sea comparable. El enlace cruzado va arriba, bajo el
titular.

Lo largo va en bloques `<details>` plegados: lo que un recien llegado necesita (que es, demo,
instalar, teclas) tiene que caber en la primera pantalla, y los detalles internos —el PATH de
launchd, la configuracion de iTerm2, el rendimiento del AppleScript— hundian eso.

`demo.svg` **se genera, no se edita**: `python3 make_demo.py` graba el programa de verdad en un
pty. Dos cosas que se rompieron al escribirlo y que no hay que "simplificar":

- **Los `<tspan>` van dentro de un `<text>`.** Sueltos no se renderizan: el SVG sale con el marco
  pintado y ni una letra.
- **Cada trozo lleva `textLength`.** Sin eso el visor usa el avance real de SU fuente, que no es
  el que asume el generador, y un trozo largo se monta encima del siguiente — se veia la comilla
  de cierre pisando la ultima letra del prompt.
- La animacion es **CSS, no SMIL**, y el primer fotograma queda visible por defecto: asi un visor
  que no anime (Quick Look, una vista previa cualquiera) muestra un fotograma fijo en vez de un
  rectangulo vacio.

El mismo script escribe la otra imagen del README: `python3 make_demo.py --table` genera
`table.svg`, la vista de tabla **quieta**. Sus dos trampas propias:

- **Un solo fotograma no lleva animacion.** La regla normal lo apagaria al llegar al 100% y la
  imagen del README parpadearia a negro. Con `len(fotogramas) == 1` se emiten solo las dos reglas
  base.
- **Un paso del guion con duracion 0 se pulsa pero no se captura.** Es lo que deja el panel en el
  estado que interesa (nota escrita, sesion pausada, vista de tabla) sin meter fotogramas
  intermedios.

Y va a 128 columnas, no a las 96 del demo animado: por debajo de 110 desaparece la columna de la
rama y por debajo de 124 la del modelo, que son justo las que la imagen quiere enseñar.

Los dos SVG los vigila el CI comparando **solo el texto** (el resto del archivo cambia en cada
grabacion por las posiciones en coma flotante), y avisa sin fallar: el demo es documentacion.
