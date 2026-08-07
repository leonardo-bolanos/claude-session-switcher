#!/usr/bin/env python3
"""
Genera demo.svg: una animacion del panel, grabada del programa de verdad.

    python3 make_demo.py                  # escribe demo.svg
    python3 make_demo.py salida.svg
    python3 make_demo.py --table          # escribe table.svg: la vista de tabla, quieta

Sin dependencias, como el resto del proyecto: arranca `ccl` en un pty, le manda un
guion de pulsaciones, captura lo que pinta y lo convierte en un SVG animado. No hay
paso de grabacion manual, asi que cuando cambie la interfaz el demo se regenera solo.

Es hermetico igual que test_panel.py, y por las mismas razones:
  - las sesiones son SINTETICAS, para que el demo sea estable y no exponga los repos
    ni los prompts reales de quien lo genere;
  - `get_iterm_map` y `focus` estan anulados: **nadie toca ventanas de nadie**, ni se
    ejecuta osascript. El salto se ve en el mensaje, sin robarle el foco a nadie.
"""

import fcntl
import os
import pty
import re
import select
import struct
import sys
import termios
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_CCL = os.path.join(_HERE, "ccl")

FILAS, COLUMNAS = 20, 96
LIMPIAR = "\033[H\033[2J"
SGR_RE = re.compile(r"\033\[([0-9;]*)m")

# ─────────────────────── aspecto del SVG ───────────────────────

FUENTE = ("ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, "
          "'DejaVu Sans Mono', monospace")
TAM = 14
AVANCE = TAM * 0.60          # ancho de un caracter en una monoespaciada
ALTO_LINEA = TAM * 1.42
MARGEN_X, MARGEN_Y = 18, 14
BARRA = 28                    # la barra de titulo con los tres circulos

FONDO = "#1d1f21"
BARRA_FONDO = "#2b2d30"
TEXTO = "#c5c8c6"

# Los colores que emite ccl. Paleta oscura legible, no la ANSI cruda: el rojo y el
# azul puros sobre fondo oscuro se leen mal.
COLORES = {
    "30": "#4a4a4a", "31": "#e06c75", "32": "#98c379", "33": "#e5c07b",
    "34": "#61afef", "35": "#c678dd", "36": "#56b6c2", "37": "#c5c8c6",
    "90": "#7f848e", "91": "#e06c75", "92": "#98c379", "93": "#e5c07b",
    "94": "#61afef", "95": "#c678dd", "96": "#56b6c2", "97": "#ffffff",
}

# ─────────────────────── guion del demo ───────────────────────

# (que enviar, cuanto se queda en pantalla). None = solo esperar (el estado inicial).
# El guion cuenta lo que hace la herramienta, en este orden: mirar, anotar, buscar por lo
# anotado, saltar. Tres flechas para llegar a `api`, que es el unico repo que no comparte
# cwd con otra fila: asi la nota sale en una sola linea y no confunde.
GUION = [
    (None,                       2.4),
    (b"\033[B",                  0.55),  # bajar
    (b"\033[B",                  0.55),
    (b"\033[B",                  0.75),
    (b"\x0e",                    0.85),  # Ctrl-N: abre la nota
    (b"blocks the release", 1.7),
    (b"\r",                      2.2),   # guardar: aparece el ✎
    (b"release",                 2.1),   # y se puede buscar por ella
    (b"\033",                    0.9),   # esc limpia el filtro
    (b"\0331",                   2.6),   # ⌥1: salta a la primera que espera
]

# El otro SVG del README: la vista de tabla, y quieta. Es una imagen fija a proposito —
# lo que hay que ver son las columnas alineadas y la columna de estado, no un movimiento.
# El guion deja antes una nota y una pausada para que la captura enseñe los tres estados
# (WORKING / WAITING / PAUSED) y el color de la nota en la ultima columna.
GUION_TABLA = [
    (b"\033[B",                       0),
    (b"\033[B",                       0),
    (b"\033[B",                       0),   # hasta `api`, que no comparte cwd con nadie
    (b"\x0e",                         0),   # Ctrl-N
    (b"waiting on Ana's schema", 0),
    (b"\r",                           0),
    (b"\x10",                         0),   # Ctrl-P: a PAUSED
    (b"\x14",                         3.0),  # Ctrl-T: y a la tabla. Este es el fotograma
]

# La tabla necesita mas ancho que el panel de dos lineas: es lo que enseña. A 128 salen
# todas las columnas —por debajo de 110 desaparece la rama, y de 124 el modelo— y aun
# quedan treinta columnas para la nota, que es la otra cosa que hay que ver.
COLUMNAS_TABLA = 128

# Sesiones de mentira, con la pinta de un dia normal de trabajo.
SESIONES = [
    # (numero, nombre, repo, rama, modelo, effort, prompt, minutos, estado)
    (3,  "fix-login-redirect-loop",   "web-app",  "fix/login",  "opus-5",   "high",
     "the redirect loops when the token has expired", 1,   "busy"),
    (7,  "invoice-pdf-margins",       "billing",  "main",       "sonnet-5", None,
     "the margins are off on A4", 4,   "busy"),
    (1,  "web-app-checkout-rework",   "web-app",  "main",       "opus-5",   "xhigh",
     "review the payment flow and tell me what's missing", 12,  "idle"),
    (5,  "api-rate-limit-headers",    "api",      "develop",    "sonnet-5", None,
     "add the rate limit headers", 47,  "idle"),
    (2,  "migrate-jobs-to-queue",     "workers",  "main",       "opus-5",   "high",
     "migrate the crons to the new queue", 190, "idle"),
    (9,  "docs-api-reference",        "docs",     "main",       "haiku-4-5", None,
     "generate the reference from the types", 1400, "idle"),
]

ARRANQUE = f'''
import datetime, importlib.machinery, importlib.util, os, sys
cargador = importlib.machinery.SourceFileLoader("ccl_mod", {_CCL!r})
ccl = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("ccl_mod", cargador))
cargador.exec_module(ccl)

ahora = datetime.datetime.now(datetime.timezone.utc)

def fila(num, nombre, repo, rama, modelo, effort, prompt, minutos, estado):
    marca = (ahora - datetime.timedelta(minutes=minutos)).isoformat().replace("+00:00", "Z")
    return {{"num": num, "name": nombre, "account": "", "repo": repo, "cwd": "/x/" + repo,
            "kind": "interactive", "status": estado, "sessionId": "sid-%d" % num,
            "pid": num, "tty": "ttys%03d" % num,
            # un par ventana/pestaña de mentira: sin esto todas saldrian con el ⚠ de
            # "no esta en iTerm", que en un demo parece que la herramienta esta rota
            "ventana": ("iTerm2", "1", num), "ts": marca, "branch": rama, "model": modelo,
            "effort": effort, "title": None, "prompt": prompt, "startedAt": num}}

FIJAS = [fila(*s) for s in {SESIONES!r}]

ccl.collect = lambda: list(FIJAS)
ccl.get_iterm_map = lambda: {{}}
ccl.focus = lambda fila, quiet=False: 0   # NADIE toca ventanas: el salto solo se anuncia
ccl.REFRESH_SECONDS = 9999                # el layout no se mueve durante la grabacion
ccl.REFRESH_IDLE = 9999
# El guion escribe una nota, y las notas SI van a disco: desviarlas o generar el demo
# dejaria una nota de mentira en el ~/.claude de quien lo genere.
ccl.NOTES_FILE = os.environ["CCL_DEMO_NOTES"]
sys.exit(ccl.main())
'''


# ─────────────────────── grabar ───────────────────────


def grabar(notas, guion=GUION, columnas=COLUMNAS):
    """
    [(lineas, segundos)] — un fotograma por paso del guion.

    Un paso con duracion 0 se pulsa pero **no se captura**: asi un guion puede dejar el
    panel en el estado que interesa (una nota escrita, una sesion pausada) y quedarse
    solo con el fotograma final.
    """
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.environ["CCL_MOUSE"] = "0"     # el raton no aporta nada a una grabacion
        os.environ["CCL_DEMO_NOTES"] = notas
        # El demo va en INGLES aunque quien lo genere tenga el locale en español: es la
        # portada del README, y el README esta en ingles.
        os.environ["CCL_LANG"] = "en"
        os.execv(sys.executable, [sys.executable, "-c", ARRANQUE])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", FILAS, columnas, 0, 0))

    trozos = []

    def drenar(segundos):
        fin = time.time() + segundos
        while time.time() < fin:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    trozos.append(os.read(fd, 65536).decode("utf-8", "ignore"))
                except OSError:
                    return

    # La cabecera del panel: "  6 sessions · 2 active" / "  6 sesiones · 2 activas". Se
    # reconoce por la FORMA (numero, palabra, ·) y no por el texto: filtrar por "sesiones"
    # dejaba de capturar en cuanto la interfaz se puso en ingles, y el generador terminaba
    # sin un solo fotograma.
    CABECERA_RE = re.compile(r"^\s*\d+ \S+ ·", re.M)

    def ultima_pantalla():
        # La regex va sobre el texto SIN escapes: la cabecera lleva codigos de color entre
        # el numero y la palabra ("6\033[0m\033[2m sessions"), asi que sobre el texto en
        # crudo no casa nada.
        pantallas = [p for p in "".join(trozos).split(LIMPIAR)
                     if CABECERA_RE.search(SGR_RE.sub("", p))]
        return pantallas[-1] if pantallas else ""

    fotogramas = []
    drenar(1.0)                                   # que acabe de pintar el primer cuadro
    for tecla, duracion in guion:
        if tecla is not None:
            os.write(fd, tecla)
            drenar(0.45)                          # dejar que repinte
        if duracion:
            fotogramas.append((ultima_pantalla(), duracion))

    os.write(fd, b"\x03")
    time.sleep(0.2)
    for cerrar in (lambda: os.close(fd), lambda: os.waitpid(pid, 0)):
        try:
            cerrar()
        except OSError:
            pass
        except ChildProcessError:
            pass
    return fotogramas


# ─────────────────────── ANSI -> SVG ───────────────────────


NIVELES_256 = (0, 95, 135, 175, 215, 255)   # los seis valores del cubo de color de xterm


def color_256(indice):
    """
    Un indice de la paleta de 256 a hex, como lo define xterm.

    Hace falta porque el panel pinta la nota con `38;5;N`: sin esto el generador se comia
    el codigo y la nota salia BLANCA en el demo — y el demo es justo la pieza del README
    que ensena el color.
    """
    if indice < 8:
        return COLORES[str(30 + indice)]
    if indice < 16:
        return COLORES[str(90 + indice - 8)]
    if indice < 232:                          # cubo 6x6x6
        n = indice - 16
        return "#%02x%02x%02x" % (NIVELES_256[n // 36],
                                  NIVELES_256[(n // 6) % 6],
                                  NIVELES_256[n % 6])
    gris = 8 + (indice - 232) * 10            # rampa de grises
    return "#%02x%02x%02x" % (gris, gris, gris)


def trozos_con_color(linea):
    """[(texto, color, tenue, negrita, fondo)] a partir de una linea con codigos SGR."""
    salida, pos = [], 0
    color, tenue, negrita, fondo = None, False, False, None
    for m in SGR_RE.finditer(linea):
        if m.start() > pos:
            salida.append((linea[pos:m.start()], color, tenue, negrita, fondo))
        codigos = (m.group(1) or "0").split(";")
        i = 0
        while i < len(codigos):
            codigo = codigos[i]
            if codigo in ("", "0"):
                color, tenue, negrita, fondo = None, False, False, None
            elif codigo == "1":
                negrita = True
            elif codigo == "2":
                tenue = True
            elif codigo == "38" and codigos[i + 1:i + 2] == ["5"]:
                # 38;5;N : color de la paleta de 256. Consume los dos codigos siguientes.
                try:
                    color = color_256(int(codigos[i + 2]))
                except (IndexError, ValueError):
                    pass
                i += 2
            elif codigo == "48" and codigos[i + 1:i + 2] == ["5"]:
                # 48;5;N : FONDO de la paleta de 256, la banda de la fila seleccionada.
                # Sin esta rama el generador se comia el codigo y el demo salia sin banda
                # — el mismo fallo que ya tuvo con el `38;5;N` de la nota, un año despues.
                try:
                    fondo = color_256(int(codigos[i + 2]))
                except (IndexError, ValueError):
                    pass
                i += 2
            elif codigo == "49":
                fondo = None
            elif codigo in COLORES:
                color = COLORES[codigo]
            i += 1
        pos = m.end()
    if pos < len(linea):
        salida.append((linea[pos:], color, tenue, negrita, fondo))
    return salida


def escapar(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fotograma_svg(lineas, indice):
    """Un fotograma como grupo. Quien lo enciende y apaga es el CSS de construir_svg."""
    partes, rects = [], []
    for n, linea in enumerate(lineas):
        if not SGR_RE.sub("", linea).strip():
            continue
        y = BARRA + MARGEN_Y + (n + 1) * ALTO_LINEA
        tspans, columna = [], 0
        for texto, color, tenue, negrita, fondo in trozos_con_color(linea.rstrip("\r")):
            if not texto:
                continue
            estilo = []
            if color:
                estilo.append(f'fill="{color}"')
            if tenue:
                estilo.append('opacity="0.55"')
            if negrita:
                estilo.append('font-weight="600"')
            x = MARGEN_X + columna * AVANCE
            if fondo:
                # Un SVG no tiene "color de fondo" del texto: hay que pintar un rectangulo
                # DEBAJO. Van todos en su propia lista y se emiten antes del <text>, o
                # taparian las letras que ya estuvieran puestas.
                rects.append(
                    f'<rect x="{x:.1f}" y="{y - TAM:.1f}" '
                    f'width="{len(texto) * AVANCE:.1f}" height="{ALTO_LINEA:.1f}" '
                    f'fill="{fondo}"/>')
            # textLength fuerza el ancho exacto del trozo. Sin esto el texto se pinta
            # con el avance REAL de la fuente que elija el visor, que no es el que yo
            # asumo: un trozo largo (el ultimo prompt, ~45 caracteres) acumulaba la
            # diferencia y su final se montaba encima del tspan siguiente — se veia la
            # comilla de cierre pisando la ultima letra. lengthAdjust="spacing" reparte
            # la correccion entre los huecos y no deforma las letras.
            ancho = len(texto) * AVANCE
            tspans.append(f'<tspan x="{x:.1f}" y="{y:.1f}" textLength="{ancho:.1f}" '
                          f'lengthAdjust="spacing" '
                          f'{" ".join(estilo)}>{escapar(texto)}</tspan>')
            columna += len(texto)
        if tspans:
            partes.append("".join(tspans))

    # Los tspan van DENTRO de un <text>: un tspan suelto no se renderiza, y el SVG sale
    # con el marco pintado y ni una letra. Cada tspan lleva su x/y absolutos, asi que un
    # unico <text> por fotograma basta para colocar todas las lineas.
    return (f'<g class="f f{indice}">' + "".join(rects)
            + "<text>" + "".join(partes) + "</text></g>")


def hoja_de_estilo(fotogramas):
    """
    Los fotogramas se encienden con CSS, no con SMIL, y por dos razones.

    La primera es soporte: SMIL esta deprecado en los navegadores basados en Chromium,
    mientras que las animaciones CSS de un SVG cargado como <img> funcionan en todas
    partes (es lo que usan las demos de terminal que se ven en GitHub).

    La segunda es la que importa de verdad: **el primer fotograma se deja visible por
    defecto**, y la animacion solo lo apaga. Asi, si el visor no anima nada (Quick Look,
    un lector que sanee el SVG, una vista previa cualquiera), se ve un fotograma fijo en
    vez de un rectangulo vacio. Con SMIL y visibility="hidden" el demo salia EN BLANCO,
    que es peor que no tener demo.
    """
    total = sum(d for _, d in fotogramas)
    reglas = [".f{opacity:0}", ".f0{opacity:1}"]   # sin animacion, se ve el primero
    if len(fotogramas) == 1:
        # Una sola captura es una imagen fija: con la regla de abajo, el unico fotograma
        # se apagaria al llegar al 100% y la imagen parpadearia a negro.
        return "\n".join(reglas)
    inicio = 0.0
    for i, (_, duracion) in enumerate(fotogramas):
        a, b = inicio / total * 100, (inicio + duracion) / total * 100
        reglas.append(f".f{i}{{animation:k{i} {total:.2f}s step-end infinite}}")
        if i == 0:
            reglas.append(f"@keyframes k0{{0%{{opacity:1}}{b:.2f}%{{opacity:0}}}}")
        else:
            reglas.append(f"@keyframes k{i}{{0%{{opacity:0}}{a:.2f}%{{opacity:1}}"
                          f"{b:.2f}%{{opacity:0}}}}")
        inicio += duracion
    # step-end: los cambios son cortes secos. Un terminal no hace fundidos, y con
    # transicion suave se ven los dos fotogramas superpuestos un instante.
    return "\n".join(reglas)


def construir_svg(fotogramas, titulo="ccl — panel de sesiones de Claude Code",
                  columnas=COLUMNAS):
    ancho = int(MARGEN_X * 2 + columnas * AVANCE)
    usadas = max(len([l for l in f.split("\n") if SGR_RE.sub("", l).strip()])
                 for f, _ in fotogramas)
    alto = int(BARRA + MARGEN_Y * 2 + (usadas + 1.5) * ALTO_LINEA)

    grupos = [fotograma_svg(p.split("\n"), i) for i, (p, _) in enumerate(fotogramas)]
    estilo = hoja_de_estilo(fotogramas)

    circulos = "".join(
        f'<circle cx="{18 + i * 18}" cy="{BARRA / 2:.0f}" r="5.5" fill="{c}"/>'
        for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")))

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}" height="{alto}" \
viewBox="0 0 {ancho} {alto}" font-family="{FUENTE}" font-size="{TAM}px">
  <title>{titulo}</title>
  <style>
{estilo}
  </style>
  <rect width="{ancho}" height="{alto}" rx="10" fill="{FONDO}"/>
  <path d="M0 10a10 10 0 0 1 10-10h{ancho - 20}a10 10 0 0 1 10 10v{BARRA - 10}H0z" \
fill="{BARRA_FONDO}"/>
  {circulos}
  <text x="{ancho / 2:.0f}" y="{BARRA / 2 + 4:.0f}" fill="#8b8f93" font-size="11px" \
text-anchor="middle">ccl</text>
  <g fill="{TEXTO}" xml:space="preserve">
{chr(10).join("    " + g for g in grupos)}
  </g>
</svg>
'''


def main():
    argv = [a for a in sys.argv[1:] if a != "--table"]
    tabla = "--table" in sys.argv[1:]
    por_defecto = "table.svg" if tabla else "demo.svg"
    destino = argv[0] if argv else os.path.join(_HERE, por_defecto)
    if not hasattr(os, "openpty"):
        print("make_demo.py necesita un pty: solo funciona en Unix.", file=sys.stderr)
        return 1
    # Las notas del guion van a un temporal que se borra: generar el demo no puede
    # dejar rastro en la configuracion de quien lo genere.
    import shutil
    import tempfile
    guion = GUION_TABLA if tabla else GUION
    columnas = COLUMNAS_TABLA if tabla else COLUMNAS
    tmp = tempfile.mkdtemp(prefix="ccl-demo-")
    try:
        fotogramas = grabar(os.path.join(tmp, "notas.json"), guion, columnas)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not any(p.strip() for p, _ in fotogramas):
        print("no se capturo nada: ¿arranca `python3 ccl`?", file=sys.stderr)
        return 1
    titulo = ("ccl — la vista de tabla" if tabla
              else "ccl — panel de sesiones de Claude Code")
    svg = construir_svg(fotogramas, titulo, columnas)
    with open(destino, "w") as fh:
        fh.write(svg)
    print(f"{destino} — {len(fotogramas)} fotogramas, "
          f"{sum(d for _, d in fotogramas):.1f}s, {len(svg) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
