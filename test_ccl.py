#!/usr/bin/env python3
"""
Tests de ccl. Solo stdlib, sin dependencias.

    python3 test_ccl.py           # todos
    python3 test_ccl.py -v        # verboso

Cubre la logica pura: helpers de ancho, numeracion estable, parseo de la salida de
AppleScript, lectura de transcripts y formato. NO toca iTerm ni lanza `claude`.

Son herméticos: `assign_numbers` y `read_transcript` escriben/leen en directorios
temporales, nunca en el ~/.claude real del usuario que corra los tests.
"""

import importlib.machinery
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("ccl_mod", os.path.join(_HERE, "ccl"))
_spec = importlib.util.spec_from_loader("ccl_mod", _loader)
ccl = importlib.util.module_from_spec(_spec)
_loader.exec_module(ccl)

ccl._TTY = True  # forzar colores: es lo que hace interesantes los tests de ancho


def iso(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat().replace("+00:00", "Z")


# ────────────────────────── helpers de ancho ──────────────────────────


class TestAnchoVisible(unittest.TestCase):
    """Los codigos ANSI no deben contar como caracteres. Fallar aqui desalinea columnas."""

    def test_vis_ignora_codigos_de_color(self):
        self.assertEqual(ccl.vis("hola"), 4)
        self.assertEqual(ccl.vis(ccl.BOLD("hola")), 4)
        self.assertEqual(ccl.vis(ccl.CYAN(ccl.BOLD("hola"))), 4)

    def test_pad_rellena_por_ancho_visible(self):
        # el bug original: ljust() contaba los escapes y dejaba la columna corta
        self.assertEqual(ccl.vis(ccl.pad(ccl.BOLD("ab"), 10)), 10)
        self.assertEqual(ccl.vis(ccl.pad("ab", 10)), 10)

    def test_pad_no_recorta_si_ya_es_mas_largo(self):
        self.assertEqual(ccl.pad("abcdef", 3), "abcdef")

    def test_clip_recorta_por_ancho_visible(self):
        self.assertEqual(ccl.vis(ccl.clip(ccl.BOLD("abcdefghij"), 4)), 4)

    def test_clip_no_parte_una_secuencia_de_escape(self):
        out = ccl.clip(ccl.CYAN("abcdefghij"), 3)
        self.assertNotIn("\033[3", out.replace("\033[36m", "").replace("\033[0m", ""))
        self.assertTrue(out.endswith("\033[0m"))

    def test_clip_sin_color_no_anade_reset(self):
        # si no, en pipes aparecia un "[0m" literal como texto
        self.assertEqual(ccl.clip("abcdefghij", 4), "abcd")
        self.assertNotIn("\033", ccl.clip("abcdefghij", 4))


    def test_cjk_cuenta_como_dos_columnas(self):
        # los ideogramas ocupan 2 columnas en la terminal, no 1
        self.assertEqual(ccl.vis("abc"), 3)
        self.assertEqual(ccl.vis("会话"), 4)
        self.assertEqual(ccl.vis("a会b"), 4)

    def test_combinantes_no_ocupan_columna(self):
        self.assertEqual(ccl.vis("e\u0301"), 1)   # e + acento combinante

    def test_pad_alinea_con_cjk(self):
        self.assertEqual(ccl.vis(ccl.pad("会话", 10)), 10)
        self.assertEqual(ccl.vis(ccl.pad("ab", 10)), 10)

    def test_clip_no_parte_un_caracter_doble(self):
        # cortar a 3 con "会话" (2+2) debe dejar solo el primero, no medio caracter
        out = ccl.clip("会话xx", 3)
        self.assertEqual(ccl.vis(out), 2)
        self.assertEqual(out, "会")

    def test_clip_devuelve_igual_si_cabe(self):
        s = ccl.BOLD("corto")
        self.assertEqual(ccl.clip(s, 50), s)


# ────────────────────────── numeracion estable ──────────────────────────


class TestNumeracion(unittest.TestCase):
    """El numero de una sesion no puede cambiar entre ejecuciones."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self._orig = ccl.INDEX_FILE
        ccl.INDEX_FILE = self.tmp.name  # NUNCA tocar el indice real del usuario

    def tearDown(self):
        ccl.INDEX_FILE = self._orig
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    @staticmethod
    def s(*ids):
        return [{"sessionId": i} for i in ids]

    def test_asigna_desde_uno_y_es_correlativo(self):
        n = ccl.assign_numbers(self.s("a", "b", "c"))
        self.assertEqual(sorted(n.values()), [1, 2, 3])

    def test_es_estable_entre_llamadas(self):
        primera = dict(ccl.assign_numbers(self.s("a", "b", "c")))
        segunda = ccl.assign_numbers(self.s("c", "a", "b"))  # otro orden
        self.assertEqual(primera, segunda)

    def test_purga_las_muertas_y_recicla_el_numero(self):
        ccl.assign_numbers(self.s("a", "b", "c"))
        n = ccl.assign_numbers(self.s("a", "c"))  # muere 'b'
        self.assertNotIn("b", n)
        n2 = ccl.assign_numbers(self.s("a", "c", "d"))
        self.assertEqual(n2["d"], 2, "la nueva debe tomar el hueco que dejo 'b'")

    def test_las_existentes_conservan_su_numero_al_entrar_otra(self):
        antes = dict(ccl.assign_numbers(self.s("a", "b")))
        despues = ccl.assign_numbers(self.s("a", "b", "z"))
        self.assertEqual(despues["a"], antes["a"])
        self.assertEqual(despues["b"], antes["b"])

    def test_indice_corrupto_no_revienta(self):
        with open(self.tmp.name, "w") as fh:
            fh.write("{ esto no es json")
        n = ccl.assign_numbers(self.s("a"))
        self.assertEqual(n["a"], 1)


# ────────────────────── parseo de la salida de iTerm ──────────────────────


class TestMapaITerm(unittest.TestCase):
    """
    Reconstruir tty -> (ventana, pestaña) desde dos gets masivos.
    Un fallo aqui enfoca la ventana EQUIVOCADA en silencio.
    """

    def _map(self, salida):
        class Fake:
            stdout = salida
        orig = ccl.subprocess.run
        ccl.subprocess.run = lambda *a, **k: Fake()
        try:
            return ccl.get_iterm_map()
        finally:
            ccl.subprocess.run = orig

    def test_reconstruye_ventana_y_pestana(self):
        got = self._map("100:2,200:1,@@@/dev/ttys001,/dev/ttys002,/dev/ttys003")
        self.assertEqual(got, {"ttys001": ("100", 1),
                               "ttys002": ("100", 2),
                               "ttys003": ("200", 1)})

    def test_ttys_concatenados_se_descartan(self):
        # El bug real: `as text` sin text item delimiters concatena sin comas.
        # Debe quedar vacio (y verse el aviso "sin iTerm"), nunca una clave basura
        # como "ttys001ttys002" que ademas podria casar por accidente.
        self.assertEqual(self._map("100:2,@@@/dev/ttys001/dev/ttys002"), {})

    def test_valores_que_no_son_tty_se_ignoran(self):
        got = self._map("100:2,@@@basura,/dev/ttys007")
        self.assertEqual(got, {"ttys007": ("100", 1)})

    def test_salida_sin_marcador_devuelve_vacio(self):
        self.assertEqual(self._map("basura sin arroba"), {})

    def test_menos_ttys_que_pestanas_no_revienta(self):
        got = self._map("100:5,@@@/dev/ttys001")
        self.assertEqual(got, {"ttys001": ("100", 1)})

    def test_conteo_no_numerico_se_ignora(self):
        got = self._map("100:x,200:1,@@@/dev/ttys009")
        self.assertEqual(got, {"ttys009": ("200", 1)})

    def test_iterm_caido_devuelve_vacio(self):
        orig = ccl.subprocess.run
        ccl.subprocess.run = lambda *a, **k: (_ for _ in ()).throw(OSError("no iTerm"))
        try:
            self.assertEqual(ccl.get_iterm_map(), {})
        finally:
            ccl.subprocess.run = orig


# ────────────────────────── lectura de transcripts ──────────────────────────


class TestTranscript(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._orig = ccl.HOME
        ccl.HOME = self.dir  # nunca leer los transcripts reales
        os.makedirs(os.path.join(self.dir, ".claude", "projects", "proj"))

    def tearDown(self):
        ccl.HOME = self._orig

    def _write(self, sid, lineas):
        p = os.path.join(self.dir, ".claude", "projects", "proj", f"{sid}.jsonl")
        with open(p, "w") as fh:
            fh.write("\n".join(json.dumps(o) if isinstance(o, dict) else o for o in lineas))
        return p

    def test_extrae_los_campos_esperados(self):
        self._write("s1", [
            {"timestamp": "2026-01-01T10:00:00Z", "gitBranch": "main", "effort": "high"},
            {"type": "ai-title", "aiTitle": "Un titulo"},
            {"type": "last-prompt", "lastPrompt": "haz algo"},
            {"type": "assistant", "message": {"model": "claude-opus-5"}},
        ])
        got = ccl.read_transcript("s1")
        self.assertEqual(got["branch"], "main")
        self.assertEqual(got["effort"], "high")
        self.assertEqual(got["title"], "Un titulo")
        self.assertEqual(got["prompt"], "haz algo")
        self.assertEqual(got["model"], "claude-opus-5")

    def test_se_queda_con_el_ultimo_valor(self):
        self._write("s2", [
            {"timestamp": "2026-01-01T10:00:00Z", "gitBranch": "vieja"},
            {"timestamp": "2026-01-02T10:00:00Z", "gitBranch": "nueva"},
        ])
        got = ccl.read_transcript("s2")
        self.assertEqual(got["branch"], "nueva")
        self.assertEqual(got["ts"], "2026-01-02T10:00:00Z")

    def test_linea_cortada_por_el_tail_se_ignora(self):
        self._write("s3", ['{"roto": "sin cerrar', {"gitBranch": "ok"}])
        self.assertEqual(ccl.read_transcript("s3")["branch"], "ok")

    def test_transcript_inexistente_devuelve_vacio(self):
        self.assertEqual(ccl.read_transcript("no-existe"), {})

    def test_solo_lee_la_cola(self):
        # una entrada antigua fuera de los ultimos TAIL_BYTES no debe aparecer
        relleno = [{"filler": "x" * 200} for _ in range(600)]
        self._write("s4", [{"gitBranch": "antiquisima"}] + relleno + [{"effort": "max"}])
        got = ccl.read_transcript("s4")
        self.assertEqual(got["effort"], "max")
        self.assertNotIn("branch", got, "no deberia haber leido tan atras")


# ────────────────────────── formato ──────────────────────────


class TestFormato(unittest.TestCase):
    def test_ago_maneja_ausente_y_basura(self):
        self.assertEqual(ccl.ago(None), "?")
        self.assertEqual(ccl.ago("no es una fecha"), "?")

    def test_ago_reciente(self):
        self.assertEqual(ccl.ago(iso(seconds=10)), "ahora")
        self.assertEqual(ccl.ago(iso(minutes=5)), "hace 5m")

    def test_ago_horas(self):
        self.assertEqual(ccl.ago(iso(hours=3)), "hace 3h")
        self.assertEqual(ccl.ago(iso(hours=23)), "hace 23h")

    def test_ago_no_depende_de_la_hora_del_dia(self):
        # el bug que cazo el CI: cruzar medianoche cambiaba "hace 3h" por "ayer 23:00"
        # para el mismo tiempo transcurrido
        self.assertEqual(ccl.ago(iso(hours=3)), "hace 3h")

    def test_ago_ayer_y_mas_atras(self):
        self.assertTrue(ccl.ago(iso(hours=30)).startswith("ayer "))
        self.assertFalse(ccl.ago(iso(days=5)).startswith(("hace", "ayer")))

    def test_ago_futuro_no_muestra_negativos(self):
        futuro = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        self.assertEqual(ccl.ago(futuro), "ahora")

    def test_short_model(self):
        self.assertIsNone(ccl.short_model(None))
        self.assertEqual(ccl.short_model("claude-opus-5"), "opus-5")
        self.assertEqual(ccl.short_model("claude-sonnet-5"), "sonnet-5")

    def test_color_model_por_familia(self):
        self.assertIn("34", ccl.color_model("opus-5"))     # azul
        self.assertIn("32", ccl.color_model("sonnet-5"))   # verde
        self.assertIn("90", ccl.color_model("haiku"))      # gris
        self.assertIn("35", ccl.color_model("fable-5"))    # magenta
        self.assertEqual(ccl.color_model(None), "")

    def test_color_effort_solo_resalta_lo_caro(self):
        self.assertIn("33", ccl.color_effort("xhigh"))     # amarillo
        self.assertIn("33", ccl.color_effort("max"))
        self.assertIn("2", ccl.color_effort("high"))       # tenue
        self.assertEqual(ccl.color_effort(None), "")


# ────────────────────────── agrupacion y orden ──────────────────────────


def row(num, sid, status="idle", ts=None, kind="interactive"):
    return {"num": num, "name": f"s{num}", "repo": "r", "cwd": "/x", "kind": kind,
            "status": status, "sessionId": sid, "pid": num, "tty": "", "iterm": None,
            "ts": ts, "branch": None, "model": None, "effort": None,
            "title": None, "prompt": None, "startedAt": num}


class TestAgrupacion(unittest.TestCase):
    def test_separa_activas_de_esperando(self):
        g = ccl.grouped([row(1, "a", "busy"), row(2, "b", "idle")])
        self.assertEqual([lbl for lbl, _, _ in g], ["TRABAJANDO", "ESPERANDO"])

    def test_omite_grupos_vacios(self):
        g = ccl.grouped([row(1, "a", "idle")])
        self.assertEqual([lbl for lbl, _, _ in g], ["ESPERANDO"])

    def test_background_solo_aparece_si_existe(self):
        sin_bg = ccl.grouped([row(1, "a", "idle")])
        self.assertNotIn("BACKGROUND", [lbl for lbl, _, _ in sin_bg])
        con_bg = ccl.grouped([row(1, "a", "idle"), row(2, "b", "idle", kind="background")])
        self.assertIn("BACKGROUND", [lbl for lbl, _, _ in con_bg])

    def test_ordena_por_actividad_mas_reciente(self):
        vieja = row(1, "a", "idle", ts=iso(days=3))
        nueva = row(2, "b", "idle", ts=iso(minutes=1))
        _, _, items = ccl.grouped([vieja, nueva])[0]
        items = sorted(items, key=ccl.sort_key, reverse=True)
        self.assertEqual(items[0]["sessionId"], "b")

    def test_sin_timestamp_va_al_final(self):
        con = row(1, "a", "idle", ts=iso(days=9))
        sin = row(2, "b", "idle", ts=None)
        items = sorted([sin, con], key=ccl.sort_key, reverse=True)
        self.assertEqual(items[-1]["sessionId"], "b")


class TestEsperando(unittest.TestCase):
    """
    `pick_waiting` es lo que hay detras de Option-1..9 y de `ccl -w`. Se prueba puro
    porque saltar de verdad le robaria el foco a quien este usando la maquina.
    """

    def test_el_orden_es_el_mismo_que_pinta_el_panel(self):
        rows = [row(1, "vieja", "idle", ts=iso(days=2)),
                row(2, "media", "idle", ts=iso(hours=3)),
                row(3, "nueva", "idle", ts=iso(minutes=1))]
        _, _, del_grupo = next(g for g in ccl.grouped(rows) if g[0] == "ESPERANDO")
        self.assertEqual([r["sessionId"] for r in ccl.waiting_rows(rows)],
                         [r["sessionId"] for r in del_grupo])

    def test_primera_segunda_y_tercera(self):
        rows = [row(1, "vieja", "idle", ts=iso(days=2)),
                row(2, "media", "idle", ts=iso(hours=3)),
                row(3, "nueva", "idle", ts=iso(minutes=1))]
        for n, esperado in ((1, "nueva"), (2, "media"), (3, "vieja")):
            elegida, aviso = ccl.pick_waiting(rows, n)
            self.assertIsNone(aviso)
            self.assertEqual(elegida["sessionId"], esperado, f"-w{n}")

    def test_ignora_las_ocupadas_y_las_de_background(self):
        rows = [row(1, "trabajando", "busy", ts=iso(minutes=1)),
                row(2, "bg", "idle", ts=iso(minutes=2), kind="background"),
                row(3, "la-buena", "idle", ts=iso(minutes=3))]
        elegida, _ = ccl.pick_waiting(rows, 1)
        self.assertEqual(elegida["sessionId"], "la-buena")

    def test_sin_ninguna_esperando_avisa_y_no_elige(self):
        elegida, aviso = ccl.pick_waiting([row(1, "a", "busy", ts=iso(minutes=1))], 1)
        self.assertIsNone(elegida)
        self.assertIn("ninguna", aviso)

    def test_pedir_mas_de_las_que_hay_avisa_cuantas_son(self):
        elegida, aviso = ccl.pick_waiting([row(1, "a", "idle", ts=iso(minutes=1))], 4)
        self.assertIsNone(elegida)
        self.assertIn("1", aviso)

    def test_cero_y_negativos_no_dan_la_ultima(self):
        """n<1 debe avisar, no indexar desde el final como haria pend[-1] en Python."""
        rows = [row(1, "a", "idle", ts=iso(minutes=1)), row(2, "b", "idle", ts=iso(hours=2))]
        for n in (0, -1):
            elegida, aviso = ccl.pick_waiting(rows, n)
            self.assertIsNone(elegida, f"n={n} no debe elegir nada")
            self.assertTrue(aviso)


class TestParseoDeArgumentos(unittest.TestCase):
    def test_sin_argumentos_es_el_panel(self):
        opts, err = ccl.parse_args([])
        self.assertIsNone(err)
        self.assertEqual(opts, {"list": False, "num": None, "waiting": None, "help": False})

    def test_numero_suelto_es_ir_a_esa_sesion(self):
        opts, err = ccl.parse_args(["7"])
        self.assertIsNone(err)
        self.assertEqual(opts["num"], 7)

    def test_waiting_pegado_suelto_y_a_secas(self):
        for argv, esperado in ((["-w2"], 2), (["-w", "2"], 2), (["-w"], 1),
                               (["--waiting", "3"], 3), (["--waiting"], 1)):
            opts, err = ccl.parse_args(argv)
            self.assertIsNone(err, argv)
            self.assertEqual(opts["waiting"], esperado, argv)

    def test_el_numero_de_w_no_se_confunde_con_el_de_sesion(self):
        """`-w 2` es 'la 2a esperando', no 'la sesion [2]'. Consumirlo mal las mezclaba."""
        opts, err = ccl.parse_args(["-w", "2"])
        self.assertIsNone(err)
        self.assertEqual(opts["waiting"], 2)
        self.assertIsNone(opts["num"])

    def test_list_y_help(self):
        self.assertTrue(ccl.parse_args(["--list"])[0]["list"])
        self.assertTrue(ccl.parse_args(["-l"])[0]["list"])
        self.assertTrue(ccl.parse_args(["--help"])[0]["help"])
        self.assertTrue(ccl.parse_args(["-h"])[0]["help"])

    def test_cero_es_error_no_la_ultima(self):
        self.assertTrue(ccl.parse_args(["-w0"])[1])
        self.assertTrue(ccl.parse_args(["-w", "0"])[1])

    def test_opcion_desconocida_da_error(self):
        opts, err = ccl.parse_args(["--sarasa"])
        self.assertIn("--sarasa", err)


class TestBuildDisplay(unittest.TestCase):
    def test_roles_y_solo_main_es_seleccionable(self):
        lines = ccl.build_display([row(1, "a", "busy", ts=iso(minutes=1))], width=100)
        roles = [r for r, _, _ in lines]
        self.assertEqual(roles[0], "head")
        self.assertIn("main", roles)
        self.assertEqual(roles[-1], "blank")
        mains = [r for r, _, _ in lines if r == "main"]
        self.assertEqual(len(mains), 1)

    def test_la_cabecera_no_lleva_fila_asociada(self):
        lines = ccl.build_display([row(1, "a", "idle")], width=100)
        head = next(l for l in lines if l[0] == "head")
        self.assertIsNone(head[2])


# ────────────────────── errores al consultar `claude` ──────────────────────


class TestSessionsUnavailable(unittest.TestCase):
    """
    'No pude preguntar' y 'no hay sesiones' son cosas distintas. Confundirlas hacia
    que el usuario leyera "no hay sesiones activas" cuando faltaba Claude Code.
    """

    def _run(self, fake):
        # Parchear tambien config_dirs: en una maquina limpia (CI) no existe ~/.claude
        # y get_sessions abortaria antes de llegar al mock. Lo cazo el CI, no la
        # maquina de desarrollo, donde ~/.claude si existe.
        #
        # Y `claude_bin`, no `shutil.which`: ahora hay un fallback que busca en disco, asi
        # que anular which no basta para simular "no esta instalado" — encontraria el
        # claude real de la maquina y el test dejaria de ser hermetico.
        orig_run, orig_dirs = ccl.subprocess.run, ccl.config_dirs
        orig_bin = ccl.claude_bin
        ccl.subprocess.run = fake
        ccl.config_dirs = lambda: ["/tmp/fake-claude"]
        ccl.claude_bin = lambda: "/usr/bin/claude"
        try:
            return ccl.get_sessions()
        finally:
            ccl.subprocess.run, ccl.config_dirs = orig_run, orig_dirs
            ccl.claude_bin = orig_bin

    def test_sin_ningun_directorio_de_config(self):
        orig_dirs, orig_bin = ccl.config_dirs, ccl.claude_bin
        ccl.config_dirs = lambda: []
        ccl.claude_bin = lambda: "/usr/bin/claude"   # el comando SI existe
        try:
            with self.assertRaises(ccl.SessionsUnavailable) as cm:
                ccl.get_sessions()
            self.assertIn("config", str(cm.exception))
        finally:
            ccl.config_dirs, ccl.claude_bin = orig_dirs, orig_bin

    def test_comando_ausente_gana_al_de_config(self):
        # si no hay ni comando ni config, el mensaje util es el del comando
        orig_dirs, orig_bin = ccl.config_dirs, ccl.claude_bin
        ccl.config_dirs = lambda: []
        ccl.claude_bin = lambda: None
        try:
            with self.assertRaises(ccl.SessionsUnavailable) as cm:
                ccl.get_sessions()
            self.assertIn("no encuentro el comando", str(cm.exception))
        finally:
            ccl.config_dirs, ccl.claude_bin = orig_dirs, orig_bin

    def test_comando_ausente(self):
        def boom(*a, **k):
            raise FileNotFoundError("claude")
        with self.assertRaises(ccl.SessionsUnavailable) as cm:
            self._run(boom)
        self.assertIn("claude", str(cm.exception))

    def test_timeout(self):
        def lento(*a, **k):
            raise ccl.subprocess.TimeoutExpired("claude", 30)
        with self.assertRaises(ccl.SessionsUnavailable) as cm:
            self._run(lento)
        self.assertIn("30s", str(cm.exception))

    def test_salida_que_no_es_json(self):
        class R:
            stdout = "Unknown command: agents"
            stderr = ""
        with self.assertRaises(ccl.SessionsUnavailable) as cm:
            self._run(lambda *a, **k: R())
        self.assertIn("JSON", str(cm.exception))

    def test_json_valido_devuelve_la_lista_etiquetada(self):
        class R:
            stdout = '[{"sessionId": "x"}]'
            stderr = ""
        got = self._run(lambda *a, **k: R())
        self.assertEqual(got[0]["sessionId"], "x")
        self.assertIn("_cfg", got[0], "cada sesion debe saber de que cuenta viene")
        self.assertIn("_account", got[0])

    def test_lista_vacia_NO_es_error(self):
        # cero sesiones es un estado valido, no un fallo
        class R:
            stdout = "[]"
            stderr = ""
        self.assertEqual(self._run(lambda *a, **k: R()), [])


# ────────────────────────── multi-cuenta ──────────────────────────


class TestBuscarClaude(unittest.TestCase):
    """
    Un atajo global arranca el proceso con el PATH minimo de launchd, donde `claude` no
    esta: con npm bajo nvm vive en ~/.nvm/versions/node/<version>/bin. Sin esta busqueda,
    `ccl -w` fallaba desde el atajo y funcionaba desde la terminal.
    """

    def setUp(self):
        self.orig_which, self.orig_extra = ccl.shutil.which, ccl.CLAUDE_EXTRA
        ccl._claude_bin = None      # el cache es de modulo: hay que limpiarlo entre tests

    def tearDown(self):
        ccl.shutil.which, ccl.CLAUDE_EXTRA = self.orig_which, self.orig_extra
        ccl._claude_bin = None

    def _ejecutable(self, ruta, mtime):
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w") as fh:
            fh.write("#!/bin/sh\n")
        os.chmod(ruta, 0o755)
        os.utime(ruta, (mtime, mtime))

    def test_el_PATH_manda_si_esta_ahi(self):
        ccl.shutil.which = lambda _: "/usr/bin/claude"
        ccl.CLAUDE_EXTRA = ["/no/existe/claude"]
        self.assertEqual(ccl.claude_bin(), "/usr/bin/claude")

    def test_lo_busca_fuera_del_PATH(self):
        ccl.shutil.which = lambda _: None
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "nvm", "v25.9.0", "bin", "claude")
            self._ejecutable(ruta, 1000)
            ccl.CLAUDE_EXTRA = [os.path.join(tmp, "nvm", "*", "bin", "claude")]
            self.assertEqual(ccl.claude_bin(), ruta)

    def test_con_varias_versiones_de_node_coge_la_mas_reciente(self):
        """Por fecha, no por nombre: ordenar los nombres pone v25.9.0 antes de v25.10.0."""
        ccl.shutil.which = lambda _: None
        with tempfile.TemporaryDirectory() as tmp:
            vieja = os.path.join(tmp, "nvm", "v25.9.0", "bin", "claude")
            nueva = os.path.join(tmp, "nvm", "v25.10.0", "bin", "claude")
            self._ejecutable(vieja, 1000)
            self._ejecutable(nueva, 2000)
            ccl.CLAUDE_EXTRA = [os.path.join(tmp, "nvm", "*", "bin", "claude")]
            self.assertEqual(ccl.claude_bin(), nueva)

    def test_ignora_lo_que_no_es_ejecutable(self):
        ccl.shutil.which = lambda _: None
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "claude")
            self._ejecutable(ruta, 1000)
            os.chmod(ruta, 0o644)          # existe pero no se puede ejecutar
            ccl.CLAUDE_EXTRA = [ruta]
            self.assertIsNone(ccl.claude_bin())

    def test_si_no_esta_en_ningun_sitio_devuelve_None(self):
        ccl.shutil.which = lambda _: None
        ccl.CLAUDE_EXTRA = ["/no/existe/en/absoluto/claude"]
        self.assertIsNone(ccl.claude_bin())

    def test_no_repite_la_busqueda(self):
        """Se cachea: el glob no puede correr en cada refresco, que es cada 4s."""
        veces = []
        ccl.shutil.which = lambda _: (veces.append(1), "/usr/bin/claude")[1]
        ccl.claude_bin()
        ccl.claude_bin()
        self.assertEqual(len(veces), 1)


class TestMultiCuenta(unittest.TestCase):
    """Ver tambien las sesiones de una segunda cuenta (~/.claude-personal, etc.)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._home, self._env = ccl.HOME, os.environ.get("CCL_CONFIG_DIRS")
        ccl.HOME = self.dir
        os.environ.pop("CCL_CONFIG_DIRS", None)

    def tearDown(self):
        ccl.HOME = self._home
        if self._env is None:
            os.environ.pop("CCL_CONFIG_DIRS", None)
        else:
            os.environ["CCL_CONFIG_DIRS"] = self._env

    def _mk(self, name, con_projects=True):
        d = os.path.join(self.dir, name)
        os.makedirs(os.path.join(d, "projects") if con_projects else d, exist_ok=True)
        return d

    def test_detecta_la_principal_y_las_secundarias(self):
        self._mk(".claude"); self._mk(".claude-personal")
        got = [os.path.basename(d) for d in ccl.config_dirs()]
        self.assertEqual(got, [".claude", ".claude-personal"])

    def test_ignora_directorios_sin_projects(self):
        self._mk(".claude"); self._mk(".claude-basura", con_projects=False)
        got = [os.path.basename(d) for d in ccl.config_dirs()]
        self.assertEqual(got, [".claude"])

    def test_CCL_CONFIG_DIRS_manda_sobre_la_deteccion(self):
        self._mk(".claude"); otro = self._mk(".claude-personal")
        os.environ["CCL_CONFIG_DIRS"] = otro
        self.assertEqual(ccl.config_dirs(), [otro])

    def test_etiqueta_de_cuenta(self):
        self.assertEqual(ccl.account_label("/x/.claude"), "")
        self.assertEqual(ccl.account_label("/x/.claude-personal"), "personal")
        self.assertEqual(ccl.account_label("/x/.claude-trabajo"), "trabajo")

    def test_la_columna_de_cuenta_solo_sale_si_hay_varias(self):
        una = [dict(row(1, "a"), account="")]
        varias = [dict(row(1, "a"), account=""), dict(row(2, "b"), account="personal")]
        self.assertFalse(ccl.multi_account(una))
        self.assertTrue(ccl.multi_account(varias))

    def test_transcript_se_busca_en_la_cuenta_correcta(self):
        otro = self._mk(".claude-personal")
        proj = os.path.join(otro, "projects", "p")
        os.makedirs(proj)
        with open(os.path.join(proj, "sid.jsonl"), "w") as fh:
            fh.write(json.dumps({"gitBranch": "de-la-personal"}))
        # sin cfg_dir busca en ~/.claude y no lo encuentra
        self.assertEqual(ccl.read_transcript("sid"), {})
        # con cfg_dir si
        self.assertEqual(ccl.read_transcript("sid", otro)["branch"], "de-la-personal")


# ────────────────────────── filtro de busqueda ──────────────────────────


class TestFiltro(unittest.TestCase):
    def r(self, **kw):
        base = {"name": "api-rate-limit", "repo": "backend", "branch": "main", "account": ""}
        base.update(kw)
        return base

    def test_vacio_deja_pasar_todo(self):
        self.assertTrue(ccl.matches(self.r(), ""))

    def test_casa_por_nombre_repo_rama_y_cuenta(self):
        self.assertTrue(ccl.matches(self.r(), "rate"))
        self.assertTrue(ccl.matches(self.r(), "backend"))
        self.assertTrue(ccl.matches(self.r(), "main"))
        self.assertTrue(ccl.matches(self.r(account="personal"), "personal"))

    def test_ignora_mayusculas(self):
        self.assertTrue(ccl.matches(self.r(), "API"))
        self.assertTrue(ccl.matches(self.r(name="Migración"), "migracion"))

    def test_ignora_acentos_en_ambos_sentidos(self):
        self.assertTrue(ccl.matches(self.r(name="migración"), "migracion"))
        self.assertTrue(ccl.matches(self.r(name="migracion"), "migración"))

    def test_varios_terminos_son_AND_y_sin_orden(self):
        self.assertTrue(ccl.matches(self.r(), "api backend"))
        self.assertTrue(ccl.matches(self.r(), "backend api"))
        self.assertFalse(ccl.matches(self.r(), "api inexistente"))

    def test_no_casa_devuelve_falso(self):
        self.assertFalse(ccl.matches(self.r(), "zzz"))

    def test_campos_nulos_no_revientan(self):
        self.assertTrue(ccl.matches({"name": "x", "repo": None, "branch": None}, "x"))

    def test_strip_accents(self):
        self.assertEqual(ccl.strip_accents("áéíóúñü"), "aeiounu")
        self.assertEqual(ccl.strip_accents("sin acentos"), "sin acentos")


# ────────────────────────── lectura de teclas ──────────────────────────


class TestLecturaDeTeclas(unittest.TestCase):
    """
    `read_key` sobre un pty de verdad: es la unica forma de ver como se descomponen
    las secuencias de escape. Distinguir ESC+digito (Option-N) de ESC+[ (flechas) es
    exactamente el tipo de cosa que falla en silencio.
    """

    def _pulsar(self, data):
        """Devuelve lo que read_key() decodifica al recibir `data` por el terminal."""
        maestro, esclavo = os.openpty()
        # Escribir DESPUES de que read_key entre en modo raw: tty.setraw usa TCSAFLUSH,
        # que descarta la entrada pendiente, asi que lo escrito antes se perderia.
        hilo = threading.Timer(0.05, lambda: os.write(maestro, data))
        stdin_real = ccl.sys.stdin
        try:
            ccl.sys.stdin = open(esclavo, "rb", buffering=0, closefd=False)
            hilo.start()
            return ccl.read_key(timeout=3.0)
        finally:
            hilo.cancel()
            ccl.sys.stdin.close()
            ccl.sys.stdin = stdin_real
            os.close(esclavo)
            os.close(maestro)

    def test_option_digito_llega_como_alt(self):
        self.assertEqual(self._pulsar(b"\x1b1"), "alt-1")
        self.assertEqual(self._pulsar(b"\x1b9"), "alt-9")

    def test_las_flechas_siguen_funcionando(self):
        self.assertEqual(self._pulsar(b"\x1b[A"), "up")
        self.assertEqual(self._pulsar(b"\x1b[B"), "down")

    def test_pgup_pgdn_no_dejan_la_tilde_en_el_buffer(self):
        """
        ESC [ 5 ~ : si no se consume la '~', la lectura siguiente la ve como texto
        escrito y PgDn arrancaba un filtro por "~".
        """
        for data, esperado in ((b"\x1b[5~", "pgup"), (b"\x1b[6~", "pgdn")):
            maestro, esclavo = os.openpty()
            hilo = threading.Timer(0.05, lambda: os.write(maestro, data))
            stdin_real = ccl.sys.stdin
            try:
                ccl.sys.stdin = open(esclavo, "rb", buffering=0, closefd=False)
                hilo.start()
                self.assertEqual(ccl.read_key(timeout=3.0), esperado)
                # nada mas que leer: la tilde ya se consumio
                self.assertIsNone(ccl.read_key(timeout=0.3), f"quedo basura tras {esperado}")
            finally:
                hilo.cancel()
                ccl.sys.stdin.close()
                ccl.sys.stdin = stdin_real
                os.close(esclavo)
                os.close(maestro)

    def test_esc_suelto_sigue_siendo_esc(self):
        self.assertEqual(self._pulsar(b"\x1b"), "esc")

    def test_no_se_pierden_las_teclas_que_llegan_juntas(self):
        """
        `tty.setraw` usa TCSAFLUSH por defecto, que DESCARTA la entrada recibida y no
        leida. Como se entra en modo raw en cada lectura, de 5 teclas seguidas llegaba 1:
        se comia letras al escribir rapido y el doble clic (press,release,press,release
        de golpe) no llegaba nunca a verse como doble.
        """
        maestro, esclavo = os.openpty()
        stdin_real = ccl.sys.stdin
        hilo = threading.Timer(0.05, lambda: os.write(maestro, b"abcde"))
        try:
            ccl.sys.stdin = open(esclavo, "rb", buffering=0, closefd=False)
            hilo.start()
            leidas = []
            for _ in range(5):
                k = ccl.read_key(timeout=1.0)
                if k is None:
                    break
                leidas.append(k)
        finally:
            hilo.cancel()
            ccl.sys.stdin.close()
            ccl.sys.stdin = stdin_real
            os.close(esclavo)
            os.close(maestro)
        self.assertEqual(leidas, ["a", "b", "c", "d", "e"])

    def test_dos_clics_seguidos_llegan_los_dos(self):
        """El doble clic depende de esto: los 4 eventos vienen en una sola rafaga."""
        maestro, esclavo = os.openpty()
        stdin_real = ccl.sys.stdin
        rafaga = b"\x1b[<0;5;9M\x1b[<0;5;9m\x1b[<0;5;9M\x1b[<0;5;9m"
        hilo = threading.Timer(0.05, lambda: os.write(maestro, rafaga))
        try:
            ccl.sys.stdin = open(esclavo, "rb", buffering=0, closefd=False)
            hilo.start()
            leidas = [ccl.read_key(timeout=1.0) for _ in range(4)]
        finally:
            hilo.cancel()
            ccl.sys.stdin.close()
            ccl.sys.stdin = stdin_real
            os.close(esclavo)
            os.close(maestro)
        self.assertEqual(leidas, ["click:9", "mouse-release", "click:9", "mouse-release"])

    def test_clic_izquierdo_da_la_fila(self):
        """SGR: ESC [ < boton ; columna ; fila M — solo interesa la fila."""
        self.assertEqual(self._pulsar(b"\x1b[<0;42;7M"), "click:7")
        self.assertEqual(self._pulsar(b"\x1b[<0;1;23M"), "click:23")

    def test_soltar_el_boton_no_es_un_clic(self):
        """Si el release contara, cada clic simple pareceria doble."""
        self.assertEqual(self._pulsar(b"\x1b[<0;42;7m"), "mouse-release")

    def test_rueda(self):
        self.assertEqual(self._pulsar(b"\x1b[<64;10;5M"), "wheelup")
        self.assertEqual(self._pulsar(b"\x1b[<65;10;5M"), "wheeldn")

    def test_botones_que_no_usamos(self):
        for data in (b"\x1b[<1;10;5M", b"\x1b[<2;10;5M"):   # medio, derecho
            self.assertEqual(self._pulsar(data), "mouse-otro")

    def test_modo_x10_por_si_el_terminal_ignora_sgr(self):
        """
        ESC [ M + tres bytes (+32 cada uno). Sin decodificarlo, un terminal que ignore
        1006 metia los clics como basura en el filtro.
        """
        self.assertEqual(self._pulsar(b"\x1b[M" + bytes([32, 32 + 42, 32 + 7])), "click:7")
        self.assertEqual(self._pulsar(b"\x1b[M" + bytes([32 + 3, 32 + 5, 32 + 5])),
                         "mouse-release")
        self.assertEqual(self._pulsar(b"\x1b[M" + bytes([32 + 64, 32 + 5, 32 + 5])), "wheelup")

    def test_secuencia_de_raton_rota_no_ensucia_el_filtro(self):
        """Basura entre '<' y 'M' debe caer en 'esc', nunca convertirse en texto."""
        self.assertEqual(self._pulsar(b"\x1b[<sarasa;;M"), "esc")

    def test_ctrl_r_y_digitos(self):
        self.assertEqual(self._pulsar(b"\x12"), "refresh")
        self.assertEqual(self._pulsar(b"3"), "3")
        self.assertEqual(self._pulsar(b"\r"), "enter")


# ────────────────────────── ayuda y teclas reservadas ──────────────────────────


class TestAyuda(unittest.TestCase):
    def test_estructura(self):
        self.assertTrue(ccl.HELP)
        for titulo, filas in ccl.HELP:
            self.assertTrue(titulo)
            self.assertTrue(filas)
            for tecla, desc in filas:
                self.assertTrue(desc, f"toda fila necesita descripcion: {titulo}/{tecla}")

    def _texto_completo(self, cols=110, term_rows=40):
        """Todas las paginas juntas: la ayuda ya no cabe en una sola pantalla."""
        n = len(ccl.help_pages(cols, term_rows))
        return ccl.ANSI_RE.sub("", "".join(ccl.render_help(cols, term_rows, p)
                                           for p in range(n)))

    def test_render_incluye_todas_las_secciones(self):
        plano = self._texto_completo()
        for titulo, _ in ccl.HELP:
            self.assertIn(titulo, plano)

    def test_render_documenta_las_teclas_de_accion(self):
        plano = self._texto_completo()
        for tecla in ("Ctrl-R", "?", "enter", "esc"):
            self.assertIn(tecla, plano, f"{tecla} deberia estar documentada")

    def test_documenta_como_copiar(self):
        """Con el raton activo la seleccion normal no funciona: hay que decir como."""
        plano = self._texto_completo()
        for pista in ("copiar", "⌥", "--list"):
            self.assertIn(pista, plano, f"falta {pista!r}: no se explica como copiar")

    def test_render_no_desborda_el_ancho(self):
        cols = 80
        for p in range(len(ccl.help_pages(cols, 40))):
            for linea in ccl.render_help(cols, 40, p).split("\r\n"):
                self.assertLessEqual(ccl.vis(linea), cols,
                                     f"linea mas ancha que la terminal: {linea!r}")

    def test_ninguna_pagina_desborda_la_altura(self):
        """
        Se pinta de arriba abajo: si una pagina es mas alta que la ventana, lo que sobra
        se va por el borde SUPERIOR y se pierde el principio sin avisar.
        """
        for term_rows in (10, 24, 30, 44, 60):
            for p, pag in enumerate(ccl.help_pages(110, term_rows)):
                # +1 del pie; debe caber con al menos una fila de margen
                self.assertLess(len(pag) + 1, term_rows + 1,
                                f"pagina {p} no cabe en {term_rows} filas")

    def test_una_ventana_alta_no_pagina(self):
        self.assertEqual(len(ccl.help_pages(110, 200)), 1)

    def test_una_ventana_baja_pagina(self):
        self.assertGreater(len(ccl.help_pages(110, 20)), 1)

    def test_las_paginas_cortan_al_final_de_una_seccion(self):
        """
        Partiendo a ciegas, la pagina siguiente empezaba por una linea de nota sin su
        tecla ni su titulo — se leia como texto colgando. Alturas donde toda seccion
        cabe: con una ventana diminuta hay que partir por dentro y no queda opcion.
        """
        for term_rows in (24, 30, 44):
            paginas = ccl.help_pages(110, term_rows)
            for i, pag in enumerate(paginas[:-1]):
                self.assertEqual(ccl.ANSI_RE.sub("", pag[-1]).strip(), "",
                                 f"{term_rows} filas: la página {i + 1} corta a medias")

    def test_la_ultima_pagina_no_ofrece_siguiente(self):
        """Decir «espacio sigue» en la ultima es mentira: ahi el espacio vuelve."""
        paginas = ccl.help_pages(110, 24)
        self.assertGreater(len(paginas), 1)
        ultima = ccl.ANSI_RE.sub("", ccl.render_help(110, 24, len(paginas) - 1))
        self.assertNotIn("sigue", ultima)
        primera = ccl.ANSI_RE.sub("", ccl.render_help(110, 24, 0))
        self.assertIn("sigue", primera)

    def test_una_sola_pagina_no_habla_de_paginas(self):
        plano = ccl.ANSI_RE.sub("", ccl.render_help(110, 200))
        # "página 1/" y no "página": PgUp/PgDn se documenta como "media página"
        self.assertNotIn("página 1/", plano)
        self.assertIn("cualquier tecla", plano)

    def test_no_se_pierde_ninguna_linea_al_paginar(self):
        enteras = ccl.help_lines(110)
        partidas = [l for pag in ccl.help_pages(110, 20) for l in pag]
        self.assertEqual(partidas, enteras)

    def test_ninguna_accion_es_una_letra_suelta(self):
        """
        Cualquier letra empieza a filtrar, asi que una accion en una letra suelta se
        come el filtrado de todo lo que empiece por ella. Paso con 'r' (impedia buscar
        'revisa') y habria pasado con 'h' para la ayuda ('honest-metrics-...').

        Excepcion consciente: 'q' para salir, que en el codigo va guardada por
        `not query` — con filtro activo es texto.
        """
        permitidas = {"q"}
        for titulo, filas in ccl.HELP:
            for tecla, _ in filas:
                for parte in tecla.replace("/", " ").split():
                    if len(parte) == 1 and parte.isalpha() and parte not in permitidas:
                        self.fail(f"'{parte}' ({titulo}) es una letra suelta: "
                                  f"usa una tecla de control o un simbolo")


# ────────────────────────── linea principal ──────────────────────────


class TestMainLine(unittest.TestCase):
    def r(self, **kw):
        base = row(7, "s7")
        base.update({"name": "mi-sesion", "repo": "mi-repo", "ts": iso(minutes=2)})
        base.update(kw)
        return base

    def test_incluye_numero_nombre_repo_y_antiguedad(self):
        plano = ccl.ANSI_RE.sub("", ccl.main_line(self.r()))
        self.assertIn("[ 7]", plano)
        self.assertIn("mi-sesion", plano)
        self.assertIn("mi-repo", plano)
        self.assertIn("hace 2m", plano)

    def test_marca_las_que_no_estan_en_iterm(self):
        con = ccl.ANSI_RE.sub("", ccl.main_line(self.r(iterm=("100", 1))))
        sin = ccl.ANSI_RE.sub("", ccl.main_line(self.r(iterm=None)))
        self.assertNotIn("⚠", con)
        self.assertIn("⚠", sin)

    def test_columna_de_cuenta_solo_con_show_account(self):
        sin = ccl.ANSI_RE.sub("", ccl.main_line(self.r(account="personal")))
        con = ccl.ANSI_RE.sub("", ccl.main_line(self.r(account="personal"), True))
        self.assertNotIn("personal", sin)
        self.assertIn("personal", con)

    def test_columnas_alineadas_pese_a_nombres_de_distinto_largo(self):
        corto = ccl.main_line(self.r(name="ab"))
        largo = ccl.main_line(self.r(name="un-nombre-bastante-mas-largo"))
        # la antiguedad debe empezar en la misma columna en ambos
        pos = lambda l: ccl.ANSI_RE.sub("", l).index("hace 2m")
        self.assertEqual(pos(corto), pos(largo))

    def test_nombre_muy_largo_se_recorta_sin_romper_columnas(self):
        linea = ccl.main_line(self.r(name="x" * 200))
        self.assertLess(ccl.vis(linea), 120)


if __name__ == "__main__":
    unittest.main(verbosity=2)
