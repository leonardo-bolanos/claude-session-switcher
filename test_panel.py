#!/usr/bin/env python3
"""
Tests del panel interactivo de ccl, sobre un pty de verdad.

    python3 test_panel.py           # todos
    python3 test_panel.py -v        # verboso

`test_ccl.py` cubre la logica pura; esto cubre lo que solo se ve corriendo el panel:
que una tecla mueva el cursor donde debe, que un clic caiga en la fila correcta y que
la ayuda pagine. Son los caminos que antes solo se podian comprobar a mano.

Como se hace hermetico, y por que cada pieza:

  - `ccl.collect` devuelve filas SINTETICAS y `REFRESH_SECONDS` es enorme. Sin las dos
    cosas la lista se reordena bajo los pies entre el arranque y la pulsacion, y no se
    puede afirmar que fila de la terminal corresponde a que sesion — que es justo lo
    que hay que comprobar del raton.
  - `ccl.get_iterm_map` devuelve {} : **nadie toca ventanas de nadie**. El salto falla
    con elegancia y se ve el flujo sin robarle el foco a quien este usando la maquina.
  - No se ejecuta `claude` ni `osascript` en ningun momento.

El tamaño del pty se fija con TIOCSWINSZ: sin eso el viewport queda diminuto y parece
que faltan lineas que si estan.
"""

import atexit
import fcntl
import itertools
import os
import pty
import re
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_CCL = os.path.join(_HERE, "ccl")

LIMPIAR = "\033[H\033[2J"      # el panel empieza cada repintado limpiando la pantalla

# Sesiones fijas, de mas reciente a mas antigua. El panel las agrupa todas en ESPERANDO
# (status idle, kind interactive), asi que el layout es predecible:
#   fila 1  cabecera "N sesiones · ..."
#   fila 2  "ESPERANDO (4)"
#   fila 3  alfa      fila 4  su detalle
#   fila 5  beta      fila 6  su detalle
#   fila 7  gamma     fila 8  su detalle
#   fila 9  delta     fila 10 su detalle
NOMBRES = ["alfa", "beta", "gamma", "delta"]
FILA_DE = {"alfa": 3, "beta": 5, "gamma": 7, "delta": 9}
SUB_DE = {n: f + 1 for n, f in FILA_DE.items()}
CABECERA_GRUPO = 2
HUECO = 11

ARRANQUE = f'''
import datetime, importlib.machinery, importlib.util, os, sys
cargador = importlib.machinery.SourceFileLoader("ccl_mod", {_CCL!r})
ccl = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("ccl_mod", cargador))
cargador.exec_module(ccl)

ahora = datetime.datetime.now(datetime.timezone.utc)

def fila(num, nombre, horas):
    marca = (ahora - datetime.timedelta(hours=horas)).isoformat().replace("+00:00", "Z")
    # `alfa` y `beta` comparten cwd A PROPOSITO: es el escenario del bug que hizo que la
    # nota pasara a ser por sesion (escribirla en una la pintaba en las vecinas).
    # `gamma` y `delta` tienen el suyo, para el caso normal.
    return {{"num": num, "name": nombre, "account": "", "repo": "repo",
            "cwd": "/x/compartido" if nombre in ("alfa", "beta") else "/x/" + nombre,
            "kind": "interactive", "status": "idle", "sessionId": "sid-" + nombre,
            "pid": num, "tty": "", "iterm": None, "ts": marca, "branch": "main",
            "model": "sonnet-5", "effort": None, "title": None,
            "prompt": "prompt de " + nombre, "startedAt": num}}

FIJAS = [fila(i + 1, n, i + 1) for i, n in enumerate({NOMBRES!r})]

# Para probar "la sesion que estabas anotando desaparece": si existe el fichero señal,
# `collect` deja de devolver esa sesion, como si su proceso hubiera muerto.
_MATAR = os.environ.get("CCL_TEST_MATAR")
_MUERTA = os.environ.get("CCL_TEST_MUERTA", "alfa")

def coleccionar():
    # Se parchea `collect`, que se salta `build`, y es build quien pega las notas a las
    # filas. Hay que replicar ese paso aqui o la nota no reaparece al reabrir el panel:
    # se veria solo la copia en memoria del panel que la escribio.
    notas_sesion, notas_repo, pausadas = ccl.load_state()
    filas = [dict(f) for f in FIJAS]
    if _MATAR and os.path.exists(_MATAR):
        filas = [f for f in filas if f["name"] != _MUERTA]
    for f in filas:
        f["note"] = ccl.note_for(f, notas_sesion, notas_repo)
        f["paused"] = f["sessionId"] in pausadas
    return filas

ccl.collect = coleccionar
ccl.get_iterm_map = lambda: {{}}     # NADIE toca ventanas
# Sin refresco por defecto, para que el layout no se mueva bajo los pies. Los tests que
# necesitan un refresco de verdad lo bajan con CCL_TEST_REFRESH.
_refresco = float(os.environ.get("CCL_TEST_REFRESH", "9999"))
ccl.REFRESH_SECONDS = _refresco
ccl.REFRESH_IDLE = _refresco
# Las notas SI se escriben en disco desde el panel: hay que desviarlas a un temporal o
# los tests ensuciarian el ~/.claude de quien los ejecute. Se exige la variable en vez de
# tirar de un valor por defecto: un descuido tiene que fallar ruidosamente aqui, no
# acabar escribiendo en la configuracion de verdad.
_notas = os.environ.get("CCL_TEST_NOTES")
if not _notas:
    raise SystemExit("falta CCL_TEST_NOTES: el test escribiria en el ~/.claude real")
ccl.NOTES_FILE = _notas
# El panel se arranca con `python -c`, asi que no hay linea de comandos que parsear:
# los tests de banderas (--table) la pasan por aqui.
sys.argv = ["ccl"] + os.environ.get("CCL_TEST_ARGS", "").split()
sys.exit(ccl.main())
'''


def press(fila, col=10):
    """Un clic completo (pulsar y soltar) en modo SGR, sobre esa fila de la terminal."""
    return (f"\033[<0;{col};{fila}M\033[<0;{col};{fila}m").encode()


def _cargar(nombre, archivo):
    """
    Un archivo del repo como modulo, para usar sus funciones desde los tests.

    Los subprocesos del panel llevan su propia copia de este arranque dentro de
    `ARRANQUE` — ahi tiene que ir en el texto que ejecuta el hijo, no puede importarse.
    """
    import importlib.machinery
    import importlib.util
    cargador = importlib.machinery.SourceFileLoader(nombre, os.path.join(_HERE, archivo))
    modulo = importlib.util.module_from_spec(
        importlib.util.spec_from_loader(nombre, cargador))
    cargador.exec_module(modulo)
    return modulo


def _cargar_make_demo():
    return _cargar("make_demo_mod", "make_demo.py")


# El regex de ANSI sale de `ccl`, no de una copia: `pantallas()` depende de quitar
# EXACTAMENTE los codigos que el panel emite, y una copia divergiria en silencio.
ANSI_RE = _cargar("ccl_para_tests", "ccl").ANSI_RE


# Las esperas son de reloj, asi que en una maquina lenta (un runner de CI compartido) se
# quedan cortas y los tests fallan sin que nada este roto. Se escalan con esta variable
# en vez de subir el valor base, que ralentizaria a todo el mundo: el CI usa 2.
FACTOR_ESPERA = float(os.environ.get("CCL_TEST_LENTO", "1"))


_NOTAS_TMP = tempfile.mkdtemp(prefix="ccl-test-notas-")
atexit.register(shutil.rmtree, _NOTAS_TMP, True)
_contador_notas = itertools.count()


class Panel:
    """Arranca el panel en un pty, manda eventos y recoge lo que pinta."""

    FILAS, COLUMNAS = 30, 100

    def __init__(self, entorno=None, arranque=0.9, por_evento=0.55, notas=None):
        arranque *= FACTOR_ESPERA
        self.por_evento = por_evento * FACTOR_ESPERA
        # Un archivo de notas propio por panel, salvo que el test pase uno para
        # comprobar que la nota sobrevive de un arranque al siguiente.
        self.notas = notas or os.path.join(
            _NOTAS_TMP, f"notas-{next(_contador_notas)}.json")
        self.trozos = []
        self.pid, self.fd = pty.fork()
        if self.pid == 0:                                  # hijo: es el panel
            os.environ["TERM"] = "xterm-256color"
            os.environ["CCL_TEST_NOTES"] = self.notas
            # Idioma FIJO: si no, el panel hereda el locale de quien ejecute los tests y
            # las cadenas cambian — pasaban con LANG=es_ES y fallaban en el CI, que corre
            # sin locale. Los asserts de aqui estan en español; el ingles lo cubre
            # `TestIdiomaDelPanel`.
            os.environ["CCL_LANG"] = "es"
            os.environ.update(entorno or {})
            os.execv(sys.executable, [sys.executable, "-c", ARRANQUE])
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ,
                    struct.pack("HHHH", self.FILAS, self.COLUMNAS, 0, 0))
        self._drenar(arranque)

    def _drenar(self, segundos):
        """
        Lee lo que haya durante un rato ACOTADO.

        Un `while select(...)` sin limite no termina nunca: el panel repinta solo.
        """
        fin = time.time() + segundos
        while time.time() < fin:
            if select.select([self.fd], [], [], 0.15)[0]:
                try:
                    self.trozos.append(os.read(self.fd, 65536).decode("utf-8", "ignore"))
                except OSError:
                    return

    def enviar(self, *eventos):
        for e in eventos:
            os.write(self.fd, e)
            self._drenar(self.por_evento)
        return self

    def cerrar(self):
        try:
            os.write(self.fd, b"\x03")      # Ctrl-C: sale por el finally, restaurando todo
            self._drenar(0.4 * FACTOR_ESPERA)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass

    # ─────────── lo que se pinto, ya interpretado ───────────

    @property
    def bruto(self):
        return "".join(self.trozos)

    def pantallas(self):
        """Cada repintado, en orden, sin codigos de color."""
        return [ANSI_RE.sub("", p) for p in self.bruto.split(LIMPIAR) if p.strip()]

    def ultima(self):
        return self.pantallas()[-1] if self.pantallas() else ""

    def cursor(self):
        """El nombre de la sesion marcada con ▌ en el ultimo repintado."""
        for linea in self.ultima().split("\n"):
            if "▌" in linea:
                for nombre in NOMBRES:
                    if nombre in linea:
                        return nombre
        return None

    def aviso(self):
        """
        El mensaje a la derecha de la cabecera (el 'flash').

        Se localiza por la FORMA y no por el texto: buscaba la palabra "sesiones" y con
        la interfaz en ingles ("sessions") devolvia siempre cadena vacia, con lo que los
        asserts sobre el aviso pasaban sin comprobar nada.
        """
        lineas = [l for l in self.ultima().split("\n") if l.strip()]
        if not lineas:
            return ""
        cabecera = lineas[0].replace("↕", "").rstrip()
        # el flash se pega a la cabecera tras un hueco de tres espacios
        m = re.search(r"\S\s{3,}(.+)$", cabecera)
        return m.group(1).strip() if m else ""

    def barra(self):
        """La barra de estado de abajo: dice si hay filtro activo o numero teclado."""
        for linea in reversed(self.ultima().split("\n")):
            if linea.strip():
                return linea.strip()
        return ""


def con_panel(*args, **kwargs):
    """Context manager: garantiza que el proceso del panel se cierre pase lo que pase."""
    class _Ctx:
        def __enter__(self):
            self.p = Panel(*args, **kwargs)
            return self.p

        def __exit__(self, *_):
            self.p.cerrar()
            return False
    return _Ctx()


@unittest.skipUnless(hasattr(os, "openpty"), "necesita pty (no existe en Windows)")
class TestArranque(unittest.TestCase):
    def test_el_layout_es_el_esperado(self):
        """
        Si esto falla, el resto de la clase miente: todas las comprobaciones del raton
        dependen de que la fila N de la terminal sea la sesion que se cree.
        """
        with con_panel() as p:
            lineas = [l.rstrip("\r") for l in p.ultima().split("\n")]
            self.assertIn("4 sesiones", lineas[0])
            self.assertIn("ESPERANDO (4)", lineas[CABECERA_GRUPO - 1])
            for nombre, fila in FILA_DE.items():
                self.assertIn(nombre, lineas[fila - 1],
                              f"{nombre} deberia estar en la fila {fila}")
                self.assertIn("prompt de " + nombre, lineas[SUB_DE[nombre] - 1])

    def test_arranca_con_la_primera_seleccionada(self):
        with con_panel() as p:
            self.assertEqual(p.cursor(), "alfa")

    def test_entra_y_sale_de_la_pantalla_alternativa(self):
        """Si no se restaura, el usuario se queda sin su scrollback al salir."""
        with con_panel() as p:
            pass
        self.assertIn("\033[?1049h", p.bruto)
        self.assertIn("\033[?1049l", p.bruto)


@unittest.skipUnless(hasattr(os, "openpty"), "necesita pty (no existe en Windows)")
class TestTeclado(unittest.TestCase):
    def test_las_flechas_mueven(self):
        with con_panel() as p:
            self.assertEqual(p.enviar(b"\033[B").cursor(), "beta")
        with con_panel() as p:
            self.assertEqual(p.enviar(b"\033[B", b"\033[B").cursor(), "gamma")

    def test_arriba_desde_la_primera_da_la_vuelta(self):
        with con_panel() as p:
            self.assertEqual(p.enviar(b"\033[A").cursor(), "delta")

    def test_pgdn_no_arranca_un_filtro(self):
        """
        PgDn es ESC [ 6 ~ : si la '~' se queda sin leer, la lectura siguiente la ve como
        texto escrito y empieza a filtrar por "~".
        """
        with con_panel() as p:
            p.enviar(b"\033[6~")
            self.assertNotIn("filtro:", p.barra())
            self.assertNotIn("~", p.barra())

    def test_escribir_filtra_sin_perder_letras(self):
        """
        Las cinco letras llegan en una rafaga. Con el TCSAFLUSH que trae tty.setraw por
        defecto sobrevivia solo la primera, y el filtro acababa siendo "g".
        """
        with con_panel() as p:
            p.enviar(b"gamma")
            self.assertIn("gamma", p.barra())
            self.assertIn("1 coincide", p.barra())

    def test_esc_limpia_el_filtro_y_deja_el_cursor_donde_estaba(self):
        """
        Al limpiar el filtro vuelve la lista completa, pero el cursor NO vuelve al
        principio: sigue al sessionId, no a la posicion. Es lo que se quiere — filtras
        para encontrar algo, limpias el filtro y sigues sobre ello.
        """
        with con_panel() as p:
            p.enviar(b"beta")
            self.assertEqual(p.cursor(), "beta")
            p.enviar(b"\033")
            self.assertNotIn("filtro:", p.barra())
            self.assertEqual(p.cursor(), "beta")
            self.assertIn("delta", p.ultima(), "la lista completa debe estar de vuelta")

    def test_un_numero_prepara_el_salto_sin_ejecutarlo(self):
        with con_panel() as p:
            p.enviar(b"3")
            self.assertIn("gamma", p.barra())
            self.assertIn("enter confirma", p.barra())
            self.assertEqual(p.cursor(), "alfa", "teclear un numero no mueve el cursor")

    def test_option_digito_salta_a_la_nesima_esperando(self):
        """⌥N llega como ESC + digito. Con el mapa de iTerm vacio el salto avisa."""
        for n, nombre in ((1, "alfa"), (3, "gamma"), (4, "delta")):
            with con_panel() as p:
                p.enviar(b"\033" + str(n).encode())
                self.assertIn(nombre, p.aviso(), f"⌥{n} deberia ir a {nombre}")

    def test_option_digito_fuera_de_rango_avisa(self):
        with con_panel() as p:
            p.enviar(b"\0339")
            self.assertIn("solo hay 4", p.aviso())


@unittest.skipUnless(hasattr(os, "openpty"), "necesita pty (no existe en Windows)")
class TestRaton(unittest.TestCase):
    def test_activa_y_apaga_el_reporte_de_raton(self):
        """
        El apagado va ANTES de soltar la pantalla alternativa: si el panel muere con el
        raton activo, el shell recibe escapes por cada clic.
        """
        with con_panel() as p:
            pass
        self.assertIn("\033[?1006h", p.bruto)
        self.assertIn("\033[?1006l", p.bruto)
        self.assertLess(p.bruto.index("\033[?1006l"), p.bruto.index("\033[?1049l"))

    def test_un_clic_selecciona_esa_fila(self):
        with con_panel() as p:
            self.assertEqual(p.enviar(press(FILA_DE["gamma"])).cursor(), "gamma")

    def test_un_clic_en_la_linea_de_detalle_selecciona_su_sesion(self):
        with con_panel() as p:
            self.assertEqual(p.enviar(press(SUB_DE["beta"])).cursor(), "beta")

    def test_un_clic_en_la_cabecera_no_hace_nada(self):
        with con_panel() as p:
            self.assertEqual(p.enviar(press(CABECERA_GRUPO)).cursor(), "alfa")

    def test_un_clic_en_un_hueco_no_hace_nada(self):
        with con_panel() as p:
            self.assertEqual(p.enviar(press(HUECO)).cursor(), "alfa")

    def test_doble_clic_abre(self):
        """Los cuatro eventos van en una rafaga, como los manda el terminal de verdad."""
        with con_panel() as p:
            p.enviar(press(FILA_DE["delta"]) + press(FILA_DE["delta"]))
            self.assertIn("delta", p.aviso())

    def test_dos_clics_lentos_no_son_un_doble(self):
        with con_panel() as p:
            p.enviar(press(FILA_DE["delta"]), press(FILA_DE["delta"]))
            self.assertEqual(p.aviso(), "", "no deberia haber abierto nada")
            self.assertEqual(p.cursor(), "delta")

    def test_dos_clics_en_filas_distintas_no_son_un_doble(self):
        with con_panel() as p:
            p.enviar(press(FILA_DE["beta"]) + press(FILA_DE["delta"]))
            self.assertEqual(p.aviso(), "")
            self.assertEqual(p.cursor(), "delta")

    def test_la_rueda_mueve_la_seleccion(self):
        with con_panel() as p:
            p.enviar(b"\033[<65;10;5M", b"\033[<65;10;5M")
            self.assertEqual(p.cursor(), "gamma")

    def test_la_rueda_arriba_no_da_la_vuelta(self):
        """A diferencia de las flechas: con la rueda, pasar del borde desorienta."""
        with con_panel() as p:
            self.assertEqual(p.enviar(b"\033[<64;10;5M").cursor(), "alfa")

    def test_CCL_MOUSE_0_lo_desactiva_del_todo(self):
        with con_panel(entorno={"CCL_MOUSE": "0"}) as p:
            p.enviar(press(FILA_DE["delta"]) + press(FILA_DE["delta"]))
            self.assertEqual(p.cursor(), "alfa")
            self.assertEqual(p.aviso(), "")
        self.assertNotIn("\033[?1006h", p.bruto)


@unittest.skipUnless(hasattr(os, "openpty"), "necesita pty (no existe en Windows)")
class TestAyuda(unittest.TestCase):
    def test_la_abre_y_la_pagina(self):
        """
        En 30 filas la ayuda no cabe. Se pinta de arriba abajo, asi que sin paginar lo
        que sobra se iria por el borde SUPERIOR, sin ningun aviso.
        """
        with con_panel() as p:
            p.enviar(b"?")
            self.assertIn("atajos", p.ultima())
            self.assertIn("página 1/", p.ultima())

    def test_el_espacio_avanza_de_pagina(self):
        with con_panel() as p:
            p.enviar(b"?")
            primera = p.ultima()
            p.enviar(b" ")
            self.assertNotEqual(p.ultima(), primera)
            self.assertIn("página 2/", p.ultima())

    def test_entre_todas_las_paginas_se_ve_como_copiar(self):
        """Con el raton activo la seleccion normal no funciona: hay que explicarlo."""
        with con_panel() as p:
            p.enviar(b"?", b" ", b" ")
            visto = "\n".join(p.pantallas())
            for pista in ("copiar", "--list", "CCL_MOUSE"):
                self.assertIn(pista, visto, f"la ayuda no explica {pista!r}")

    def test_ninguna_pagina_parte_una_seccion(self):
        """La pagina siguiente no debe empezar por una nota sin su tecla ni su titulo."""
        with con_panel() as p:
            p.enviar(b"?", b" ")
            for pantalla in p.pantallas():
                if "página 2/" not in pantalla:
                    continue
                primera = next(l for l in pantalla.split("\n") if l.strip())
                self.assertFalse(primera.startswith("      "),
                                 f"la página 2 empieza por una nota huérfana: {primera!r}")

    def test_cualquier_otra_tecla_vuelve_al_panel(self):
        with con_panel() as p:
            p.enviar(b"?", b"x")
            self.assertIn("sesiones", p.ultima())
            self.assertNotIn("atajos", p.ultima())


@unittest.skipUnless(hasattr(os, "openpty"), "necesita pty (no existe en Windows)")
class TestSinPanel(unittest.TestCase):
    """Los caminos no interactivos se prueban directo, sin pty."""

    def _correr(self, *args):
        # Este camino construye su entorno a mano, asi que hay que fijar aqui LAS DOS
        # cosas que `Panel` fija en el fork, y por las mismas razones:
        #   - CCL_TEST_NOTES: aunque estos caminos no escriban notas, si las LEEN, y sin
        #     desviarlo saldrian las notas reales del usuario en la salida.
        #   - CCL_LANG: sin fijarlo hereda el locale de quien ejecute los tests. Pasaba en
        #     una maquina con LANG=es_ES y fallaba en el CI, que corre sin locale — y aqui
        #     se escapo justo eso la primera vez.
        entorno = dict(os.environ,
                       CCL_TEST_NOTES=os.path.join(_NOTAS_TMP, "sin-panel.json"),
                       CCL_LANG="es")
        return subprocess.run([sys.executable, "-c", ARRANQUE.replace(
            "sys.exit(ccl.main())",
            "sys.argv = ['ccl'] + %r\nsys.exit(ccl.main())" % list(args),
        )], capture_output=True, text=True, timeout=30, env=entorno)

    def test_list_no_lleva_codigos_de_color(self):
        """Por tuberia va sin color, para poder pegarlo: `ccl --list | pbcopy`."""
        r = self._correr("--list")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("\033", r.stdout)
        for nombre in NOMBRES:
            self.assertIn(nombre, r.stdout)

    def test_w_fuera_de_rango_avisa_y_no_salta(self):
        r = self._correr("-w", "99")
        self.assertEqual(r.returncode, 1)
        self.assertIn("solo hay 4", r.stderr)

    def test_un_numero_que_no_existe_avisa(self):
        r = self._correr("77")
        self.assertEqual(r.returncode, 1)
        self.assertIn("77", r.stderr)

    def test_opcion_desconocida_devuelve_2(self):
        r = self._correr("--sarasa")
        self.assertEqual(r.returncode, 2)
        self.assertIn("sarasa", r.stderr)

    def test_help_no_necesita_sesiones(self):
        r = self._correr("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("panel interactivo", r.stdout)


@unittest.skipUnless(hasattr(os, "openpty"), "necesita pty (no existe en Windows)")
class TestNotas(unittest.TestCase):
    """
    La nota se escribe con Ctrl-N y se guarda por repo. Lo que hay que vigilar de un
    modo de edicion es que **se quede el teclado**: si no, en medio de la frase una 'q'
    cierra el panel y un digito arranca el selector por numero.
    """

    def test_ctrl_n_abre_el_editor_con_el_repo_en_el_prompt(self):
        with con_panel() as p:
            p.enviar(b"\x0e")
            self.assertIn("nota de", p.barra())
            self.assertIn("enter guarda", p.barra())

    def test_escribir_y_guardar(self):
        with con_panel() as p:
            p.enviar(b"\x0e", b"backend de facturacion", b"\r")
            self.assertIn("✎ backend de facturacion", p.ultima())
            self.assertIn("guardada", p.aviso())

    def test_esc_cancela_sin_guardar(self):
        with con_panel() as p:
            p.enviar(b"\x0e", b"esto no deberia quedar", b"\033")
            self.assertNotIn("esto no deberia quedar", p.ultima())
            self.assertIn("sin cambios", p.aviso())

    def test_la_nota_sobrevive_a_cerrar_el_panel(self):
        """Es la razon de guardarla por repo y no por sesion."""
        archivo = os.path.join(_NOTAS_TMP, "compartido.json")
        with con_panel(notas=archivo) as p:
            p.enviar(b"\x0e", b"nota persistente", b"\r")
        with con_panel(notas=archivo) as q:
            self.assertIn("✎ nota persistente", q.ultima())

    def test_una_nota_vacia_la_borra(self):
        archivo = os.path.join(_NOTAS_TMP, "borrado.json")
        with con_panel(notas=archivo) as p:
            p.enviar(b"\x0e", b"temporal", b"\r")
            self.assertIn("✎ temporal", p.ultima())
            p.enviar(b"\x0e", b"\x7f" * 8, b"\r")     # borrar las 8 letras y guardar
            # "✎ temporal", no solo "✎": el aviso de la cabecera tambien lleva el simbolo
            self.assertNotIn("✎ temporal", p.ultima())
            self.assertIn("borrada", p.aviso())

    def test_corrige_la_nota_que_ya_habia(self):
        """Ctrl-N arranca con el texto actual: corregir no es reescribir."""
        with con_panel() as p:
            p.enviar(b"\x0e", b"bakend", b"\r")
            p.enviar(b"\x0e", b"\x7f" * 5, b"ackend")   # bakend -> backend
            self.assertIn("backend", p.barra())

    def test_la_q_no_cierra_el_panel_mientras_escribes(self):
        with con_panel() as p:
            p.enviar(b"\x0e", b"quedarse aqui", b"\r")
            self.assertIn("✎ quedarse aqui", p.ultima(),
                          "la 'q' cerro el panel en medio de la nota")

    def test_un_digito_no_arranca_el_selector_mientras_escribes(self):
        with con_panel() as p:
            p.enviar(b"\x0e", b"sprint 3", b"\r")
            self.assertIn("✎ sprint 3", p.ultima())
            self.assertNotIn("enter confirma", p.barra())

    def test_la_nota_no_se_pega_a_las_vecinas_del_mismo_repo(self):
        """
        El bug reportado: `alfa` y `beta` comparten cwd, y escribir la nota en una la
        pintaba en la otra. Ahora la nota es de la sesion; la del repo solo hace de
        respaldo cuando la sesion no tiene la suya.
        """
        with con_panel() as p:
            p.enviar(b"\x0e", b"solo para alfa", b"\r")
            pantalla = p.ultima()
            fila_alfa = pantalla.split("\n")[SUB_DE["alfa"] - 1]
            fila_beta = pantalla.split("\n")[SUB_DE["beta"] - 1]
            self.assertIn("✎ solo para alfa", fila_alfa)
            self.assertNotIn("✎", fila_beta, "la nota se pegó a la sesión vecina")

    def test_si_la_sesion_muere_mientras_escribes_no_se_guarda_en_otra(self):
        """
        EL FALLO: el editor se ataba a la FILA (`lines[cl]`), que se resuelve en cada
        vuelta del bucle. Si la sesion que estabas anotando moria y el refresco reordenaba
        la lista, esa fila pasaba a ser otra sesion y el Enter guardaba tu texto ahi.
        """
        señal = os.path.join(_NOTAS_TMP, f"matar-{next(_contador_notas)}")
        with con_panel(entorno={"CCL_TEST_MATAR": señal, "CCL_TEST_MUERTA": "alfa",
                                "CCL_TEST_REFRESH": "1"}) as p:
            p.enviar(b"\x0e", "para alfa y solo alfa".encode())
            self.assertIn("para alfa", p.barra(), "el editor deberia estar abierto")
            open(señal, "w").close()          # alfa muere
            p._drenar(2.5 * FACTOR_ESPERA)    # deja pasar un refresco
            # el aviso se comprueba AQUI: el Enter de despues ya es un Enter normal
            # (enfoca la fila seleccionada) y sobreescribe el flash
            self.assertIn("ya no está", p.aviso(), "deberia avisar de que se perdio")
            self.assertNotIn("para alfa", p.barra(), "el editor sigue abierto")
            p.enviar(b"\r")                   # el Enter que antes guardaba en beta
            self.assertNotIn("para alfa", p.ultima(), "el texto acabó en otra sesión")
        # y tampoco quedó en el fichero: de hecho no se escribió nada, porque la única
        # nota en curso era la de la sesión que murió
        if os.path.exists(p.notas):
            with open(p.notas) as fh:
                self.assertNotIn("para alfa", fh.read())

    def test_option_n_limpia_el_numero_a_medio_teclear(self):
        """
        EL FALLO: `⌥N` movia el cursor pero no limpiaba `typed`, y el Enter da prioridad
        al numero teclado. Resultado: veias resaltada una sesion y Enter enfocaba otra.
        """
        with con_panel() as p:
            p.enviar(b"3")                      # prepara el salto por numero
            self.assertIn("enter confirma", p.barra())
            p.enviar(b"\0331")                  # ⌥1: salta a la primera esperando
            self.assertNotIn("enter confirma", p.barra(),
                             "el número a medio teclear sigue activo tras ⌥N")

    def test_se_puede_escribir_con_acentos(self):
        """
        Las teclas se leen byte a byte, asi que un caracter multibyte hay que juntarlo:
        antes "facturación" se guardaba como "facturacin". En un proyecto en español, y
        para un texto que escribe el usuario a mano, no es un detalle.
        """
        with con_panel() as p:
            p.enviar(b"\x0e", "facturación ñ".encode(), b"\r")
            self.assertIn("✎ facturación ñ", p.ultima())

    def test_se_puede_filtrar_por_la_nota(self):
        """Media razon para escribirla: encontrar `repo` buscando "facturacion"."""
        with con_panel() as p:
            p.enviar(b"\x0e", b"facturacion", b"\r")
            p.enviar(b"factur")
            self.assertIn("1 coincide", p.barra())

    def test_no_escribe_en_el_claude_del_usuario(self):
        """Guardarrail: el panel escribe notas de verdad en disco."""
        with con_panel() as p:
            p.enviar(b"\x0e", b"nota de prueba", b"\r")
            self.assertTrue(os.path.exists(p.notas))
            self.assertTrue(p.notas.startswith(_NOTAS_TMP))


@unittest.skipUnless(hasattr(os, "openpty"), "necesita pty (no existe en Windows)")
class TestPausadas(unittest.TestCase):
    """
    Ctrl-P marca la sesion que espera a OTRO. Las cuatro sesiones sinteticas arrancan en
    ESPERANDO, con `alfa` la primera y seleccionada.
    """

    def test_ctrl_p_la_baja_al_grupo_de_pausadas(self):
        with con_panel() as p:
            p.enviar(b"\x10")
            pantalla = p.ultima()
            self.assertIn("PAUSADAS (1)", pantalla)
            self.assertIn("ESPERANDO (3)", pantalla)
            self.assertIn("en pausa", p.aviso())
            # y el grupo va DESPUES de esperando: lo que te espera a ti, primero
            self.assertLess(pantalla.index("ESPERANDO"), pantalla.index("PAUSADAS"))

    def test_pulsarla_otra_vez_la_devuelve(self):
        with con_panel() as p:
            p.enviar(b"\x10")
            p.enviar(b"\x10")
            self.assertNotIn("PAUSADAS", p.ultima())
            self.assertIn("ESPERANDO (4)", p.ultima())
            self.assertIn("vuelve a esperando", p.aviso())

    def test_option_1_se_salta_la_pausada(self):
        """
        El sentido entero de la pausa. `alfa` es la primera esperando; pausada, ⌥1 tiene
        que llevar a `beta`. Nadie enfoca nada (get_iterm_map devuelve {}), asi que el
        aviso es el del fallo elegante — pero dice a QUE sesion iba.
        """
        with con_panel() as p:
            p.enviar(b"\x10")      # alfa a pausadas
            p.enviar(b"\0331")     # ⌥1
            self.assertIn("beta", p.aviso())
            self.assertNotIn("alfa", p.aviso())

    def test_la_pausa_sobrevive_a_cerrar_el_panel(self):
        archivo = os.path.join(_NOTAS_TMP, "pausa-persistente.json")
        with con_panel(notas=archivo) as p:
            p.enviar(b"\x10")
            self.assertIn("PAUSADAS (1)", p.ultima())
        with con_panel(notas=archivo) as q:
            self.assertIn("PAUSADAS (1)", q.ultima())

    def test_pausar_no_se_lleva_por_delante_la_nota(self):
        """Comparten archivo: con dos escritores, guardar una borraba la otra."""
        archivo = os.path.join(_NOTAS_TMP, "pausa-y-nota.json")
        with con_panel(notas=archivo) as p:
            p.enviar(b"\x0e", b"esperando a Felipe", b"\r")
            p.enviar(b"\x10")
            self.assertIn("✎ esperando a Felipe", p.ultima())
        with con_panel(notas=archivo) as q:
            self.assertIn("PAUSADAS (1)", q.ultima())
            self.assertIn("✎ esperando a Felipe", q.ultima())


@unittest.skipUnless(hasattr(os, "openpty"), "necesita pty (no existe en Windows)")
class TestVistaDeTabla(unittest.TestCase):
    def test_ctrl_t_pinta_una_linea_por_sesion(self):
        with con_panel() as p:
            p.enviar(b"\x14")
            pantalla = p.ultima()
            self.assertIn("estado", pantalla, "falta la cabecera de columnas")
            self.assertNotIn("ESPERANDO (4)", pantalla, "sigue la cabecera de grupo")
            fila = next(l for l in pantalla.split("\n") if "alfa" in l)
            self.assertIn("prompt de alfa", fila,
                          "el detalle deberia ir en la misma linea que la sesion")

    def test_cada_fila_lleva_su_estado(self):
        with con_panel() as p:
            p.enviar(b"\x10")      # alfa pausada
            p.enviar(b"\x14")
            pantalla = p.ultima()
            self.assertIn("PAUSADAS", next(l for l in pantalla.split("\n")
                                           if "alfa" in l))
            self.assertIn("ESPERANDO", next(l for l in pantalla.split("\n")
                                            if "beta" in l))

    def test_ctrl_t_vuelve_a_la_vista_de_dos_lineas(self):
        with con_panel() as p:
            p.enviar(b"\x14")
            p.enviar(b"\x14")
            self.assertIn("ESPERANDO (4)", p.ultima())

    def test_el_cursor_se_queda_en_la_misma_sesion(self):
        """Sigue al sessionId, no a la fila: cambiar de vista no puede moverlo."""
        with con_panel() as p:
            p.enviar(b"\033[B")    # abajo: de alfa a beta
            p.enviar(b"\x14")
            self.assertEqual(p.cursor(), "beta")

    def test_la_tabla_no_desborda_el_ancho_de_la_terminal(self):
        """Una fila mas ancha que la ventana se envuelve y descuadra todo lo de abajo."""
        with con_panel() as p:
            p.enviar(b"\x14")
            for linea in p.ultima().split("\n"):
                self.assertLessEqual(len(linea.rstrip("\r")), Panel.COLUMNAS,
                                     f"linea demasiado ancha: {linea!r}")

    def test_arranca_en_tabla_con_la_bandera(self):
        with con_panel(entorno={"CCL_TEST_ARGS": "--table"}) as p:
            self.assertIn("estado", p.ultima())
            self.assertNotIn("ESPERANDO (4)", p.ultima())


@unittest.skipUnless(hasattr(os, "openpty"), "necesita pty (no existe en Windows)")
class TestGeneradorDelDemo(unittest.TestCase):
    """
    `make_demo.py` graba el panel y escribe demo.svg. Cada comprobacion de aqui es un
    fallo que ya ocurrio y que **no se ve** salvo abriendo el SVG: los dos primeros
    dejaban una imagen en blanco o con el texto pisado, y el SVG seguia siendo valido.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls._tmp = tempfile.TemporaryDirectory()
        destino = os.path.join(cls._tmp.name, "demo.svg")
        r = subprocess.run([sys.executable, os.path.join(_HERE, "make_demo.py"), destino],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            raise AssertionError(f"make_demo.py fallo: {r.stderr}")
        with open(destino) as fh:
            cls.svg = fh.read()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_los_tspan_van_dentro_de_un_text(self):
        """Un tspan suelto NO se renderiza: el SVG salia con el marco y ni una letra."""
        self.assertIn("<text>", self.svg)
        primer_tspan = self.svg.index("<tspan")
        self.assertLess(self.svg.index("<text>"), primer_tspan,
                        "hay tspans antes del primer <text>: quedarian sin renderizar")

    def test_cada_trozo_fija_su_ancho(self):
        """
        Sin textLength el visor usa el avance de SU fuente, no el que asume el
        generador, y un trozo largo se monta encima del siguiente.
        """
        self.assertEqual(self.svg.count("<tspan"), self.svg.count("textLength="))

    def test_el_primer_fotograma_se_ve_sin_animacion(self):
        """
        Si el visor no anima, debe quedar un fotograma fijo y no un rectangulo vacio.
        Con visibility=hidden + SMIL el demo salia EN BLANCO.
        """
        self.assertIn(".f0{opacity:1}", self.svg)
        self.assertIn("@keyframes k0", self.svg)
        self.assertNotIn("<animate", self.svg)     # SMIL esta deprecado en Chromium

    def test_los_fotogramas_no_se_solapan(self):
        """Cada uno se apaga justo cuando arranca el siguiente."""
        apagados = re.findall(r"@keyframes k(\d+)\{0%\{opacity:0\}([\d.]+)%", self.svg)
        encendidos = [float(b) for _, b in apagados]
        self.assertEqual(encendidos, sorted(encendidos), "los inicios no van en orden")

    def test_muestra_el_filtro_y_el_salto(self):
        """Un demo que solo mueva el cursor no cuenta lo que hace la herramienta."""
        texto = re.sub(r"<[^>]+>", "", self.svg)
        # en ingles: el demo se graba con CCL_LANG=en, aunque quien lo genere tenga el
        # locale en español
        self.assertIn("filter:", texto, "el demo no muestra el filtrado")
        self.assertIn("waiting #", texto, "el demo no muestra el salto")

    def test_la_nota_sale_con_color_y_no_en_blanco(self):
        """
        El panel pinta la nota con `38;5;N` (paleta de 256). El generador solo entendia
        los 16 basicos, asi que se comia el codigo y la nota salia BLANCA — y justo en la
        pieza del README que sirve para ensenar el color.
        """
        # "✎ blocks", el texto que escribe el guion de make_demo, y no un ✎ cualquiera:
        # el prompt del editor tambien lleva uno y ese va DIM a proposito, sin color.
        # En INGLES porque el demo se graba con CCL_LANG=en: es la portada del README.
        m = re.search(r"<tspan[^>]*>✎ blocks[^<]*</tspan>", self.svg)
        self.assertIsNotNone(m, "el demo deberia mostrar la nota ya guardada")
        self.assertIn("fill=", m.group(), "la nota sale sin color")

    def test_la_paleta_de_256_se_convierte_bien(self):
        """La aritmetica del cubo 6x6x6 de xterm es facil de equivocar."""
        md = _cargar_make_demo()
        casos = {0: "#4a4a4a", 15: "#ffffff", 16: "#000000", 174: "#d78787",
                 196: "#ff0000", 231: "#ffffff", 232: "#080808", 255: "#eeeeee"}
        for indice, esperado in casos.items():
            self.assertEqual(md.color_256(indice), esperado, f"indice {indice}")

    def test_no_expone_datos_reales(self):
        """Las sesiones son sinteticas: el demo no puede filtrar repos ni prompts."""
        texto = re.sub(r"<[^>]+>", "", self.svg)
        self.assertNotIn(os.path.expanduser("~"), texto)
        self.assertIn("web-app", texto)          # una de las sinteticas


@unittest.skipUnless(hasattr(os, "openpty"), "necesita pty (no existe en Windows)")
class TestImagenDeLaTabla(unittest.TestCase):
    """
    `make_demo.py --table` escribe la otra imagen del README: la vista de tabla, quieta.
    Es una captura de un solo fotograma, y eso tiene su propia trampa.
    """

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls._tmp = tempfile.TemporaryDirectory()
        destino = os.path.join(cls._tmp.name, "table.svg")
        r = subprocess.run([sys.executable, os.path.join(_HERE, "make_demo.py"),
                            "--table", destino],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            raise AssertionError(f"make_demo.py --table fallo: {r.stderr}")
        with open(destino) as fh:
            cls.svg = fh.read()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _texto(self):
        return re.sub(r"<[^>]+>", "", self.svg)

    def test_enseña_las_columnas_y_los_tres_estados(self):
        """Si no salen los tres, la imagen no explica para que sirve la columna."""
        texto = self._texto()
        for pista in ("state", "session", "branch", "WORKING", "WAITING", "PAUSED"):
            self.assertIn(pista, texto, f"la imagen no enseña {pista!r}")

    def test_es_un_solo_fotograma_y_no_parpadea(self):
        """
        Con un fotograma la regla de animacion lo apagaba al llegar al 100%: la imagen
        del README se quedaba en negro la mitad del tiempo.
        """
        self.assertEqual(self.svg.count('class="f f'), 1)
        self.assertNotIn("@keyframes", self.svg)

    def test_la_nota_conserva_su_color(self):
        """El `38;5;174` es lo que se rompio la primera vez que se genero un SVG."""
        self.assertIn("✎", self._texto())
        self.assertIn('fill="#d78787"', self.svg)


@unittest.skipUnless(hasattr(os, "openpty"), "necesita pty (no existe en Windows)")
class TestIdiomaDelPanel(unittest.TestCase):
    """
    El panel arranca en INGLES por defecto: es lo que vera quien llegue desde el README.
    El resto de las clases fijan español porque sus asserts estan en español.
    """

    def test_en_ingles_por_defecto(self):
        with con_panel(entorno={"CCL_LANG": "en"}) as p:
            pantalla = p.ultima()
            self.assertIn("WAITING", pantalla)
            self.assertIn("sessions", pantalla)
            self.assertNotIn("ESPERANDO", pantalla)
            self.assertIn("move", p.barra())

    def test_el_filtro_cuenta_en_ingles(self):
        with con_panel(entorno={"CCL_LANG": "en"}) as p:
            p.enviar(b"beta")
            self.assertIn("filter:", p.barra())
            self.assertIn("1 match", p.barra())

    def test_la_nota_en_ingles(self):
        with con_panel(entorno={"CCL_LANG": "en"}) as p:
            p.enviar(b"\x0e")
            self.assertIn("note for", p.barra())
            p.enviar(b"blocks the release", b"\r")
            self.assertIn("✎ blocks the release", p.ultima())
            self.assertIn("saved", p.aviso())

    def test_la_ayuda_en_ingles(self):
        with con_panel(entorno={"CCL_LANG": "en"}) as p:
            p.enviar(b"?")
            self.assertIn("shortcuts", p.ultima())
            self.assertIn("page 1/", p.ultima())

    def test_el_aviso_de_esperando_en_ingles(self):
        with con_panel(entorno={"CCL_LANG": "en"}) as p:
            p.enviar(b"\0339")
            self.assertIn("only 4 waiting", p.aviso())


if __name__ == "__main__":
    unittest.main(verbosity=2)
