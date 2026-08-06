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

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import signal
import stat
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("ccl_mod", os.path.join(_HERE, "ccl"))
_spec = importlib.util.spec_from_loader("ccl_mod", _loader)
ccl = importlib.util.module_from_spec(_spec)
_loader.exec_module(ccl)

ccl._TTY = True  # forzar colores: es lo que hace interesantes los tests de ancho

# El idioma se FIJA: si no, los tests heredan el locale de quien los ejecute y las
# cadenas cambian — pasaban en una maquina con LANG=es_ES y fallaban en el CI, que corre
# sin locale. Se fija ingles porque es el defecto del proyecto; el español lo cubre
# `TestIdioma`, y los asserts que dependen de un texto usan `ccl.t(...)` en vez de
# escribirlo a mano.
ccl.LANG = "en"


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

    # Los textos se comparan contra `ccl.t(...)` y no escritos a mano: asi los tests
    # valen en los dos idiomas y no hay que duplicarlos.

    def test_ago_reciente(self):
        self.assertEqual(ccl.ago(iso(seconds=10)), ccl.t("ahora"))
        self.assertEqual(ccl.ago(iso(minutes=5)), ccl.t("hace_min", n=5))

    def test_ago_horas(self):
        self.assertEqual(ccl.ago(iso(hours=3)), ccl.t("hace_hora", n=3))
        self.assertEqual(ccl.ago(iso(hours=23)), ccl.t("hace_hora", n=23))

    def test_ago_no_depende_de_la_hora_del_dia(self):
        # el bug que cazo el CI: cruzar medianoche cambiaba "hace 3h" por "ayer 23:00"
        # para el mismo tiempo transcurrido
        self.assertEqual(ccl.ago(iso(hours=3)), ccl.t("hace_hora", n=3))

    def test_ago_ayer_y_mas_atras(self):
        ayer = ccl.t("ayer", hora="").strip()
        self.assertIn(ayer, ccl.ago(iso(hours=30)))
        viejo = ccl.ago(iso(days=5))
        self.assertNotIn(ayer, viejo)
        self.assertRegex(viejo, r"\d{2}-\w+ \d{2}:\d{2}")   # "24-jul 21:52"

    def test_ago_futuro_no_muestra_negativos(self):
        futuro = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        self.assertEqual(ccl.ago(futuro), ccl.t("ahora"))

    def test_el_color_de_la_antiguedad_no_depende_del_idioma(self):
        """
        `color_age` decidia mirando el TEXTO ("empieza por 'hace '"). Con la interfaz en
        ingles eso dejaba de casar y TODO salia en gris, sin que nada fallara.
        """
        original = ccl.LANG
        try:
            colores = {}
            for idioma in ("en", "es"):
                ccl.LANG = idioma
                colores[idioma] = [ccl.ANSI_RE.findall(ccl.color_age(ts))
                                   for ts in (iso(minutes=5), iso(hours=3), iso(days=5))]
            self.assertEqual(colores["en"], colores["es"])
            # y de verdad son tres colores distintos, no todo gris
            self.assertEqual(len({tuple(c) for c in colores["en"]}), 3)
        finally:
            ccl.LANG = original

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


def row(num, sid, status="idle", ts=None, kind="interactive", paused=False):
    return {"num": num, "name": f"s{num}", "repo": "r", "cwd": "/x", "kind": kind,
            "status": status, "sessionId": sid, "pid": num, "tty": "", "iterm": None,
            "ts": ts, "branch": None, "model": None, "effort": None,
            "title": None, "prompt": None, "note": "", "paused": paused,
            "startedAt": num}


class TestAgrupacion(unittest.TestCase):
    def test_separa_activas_de_esperando(self):
        g = ccl.grouped([row(1, "a", "busy"), row(2, "b", "idle")])
        self.assertEqual([lbl for lbl, _, _ in g],
                         [ccl.t("grupo_busy"), ccl.t("grupo_idle")])

    def test_omite_grupos_vacios(self):
        g = ccl.grouped([row(1, "a", "idle")])
        self.assertEqual([lbl for lbl, _, _ in g], [ccl.t("grupo_idle")])

    def test_background_solo_aparece_si_existe(self):
        sin_bg = ccl.grouped([row(1, "a", "idle")])
        self.assertNotIn(ccl.t("grupo_bg"), [lbl for lbl, _, _ in sin_bg])
        con_bg = ccl.grouped([row(1, "a", "idle"), row(2, "b", "idle", kind="background")])
        self.assertIn(ccl.t("grupo_bg"), [lbl for lbl, _, _ in con_bg])

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
        _, _, del_grupo = next(g for g in ccl.grouped(rows)
                               if g[0] == ccl.t("grupo_idle"))
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
        self.assertEqual(aviso, ccl.t("ninguna_esperando"))

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
        self.assertEqual(opts, {"list": False, "num": None, "waiting": None,
                                "help": False, "version": False, "table": False,
                                "notify": None})

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

    def test_version(self):
        self.assertTrue(ccl.parse_args(["--version"])[0]["version"])
        self.assertTrue(ccl.parse_args(["-V"])[0]["version"])
        # y es una version semantica de verdad, no un placeholder
        self.assertRegex(ccl.__version__, r"^\d+\.\d+\.\d+$")

    def test_table(self):
        self.assertTrue(ccl.parse_args(["--table"])[0]["table"])
        self.assertTrue(ccl.parse_args(["-t"])[0]["table"])
        opts, err = ccl.parse_args(["--list", "--table"])
        self.assertIsNone(err)
        self.assertTrue(opts["list"] and opts["table"])

    def test_notify(self):
        self.assertEqual(ccl.parse_args(["--notify"])[0]["notify"], ccl.WATCH_SECONDS)
        self.assertEqual(ccl.parse_args(["--notify", "30"])[0]["notify"], 30)
        # sin forma corta a proposito: `-n` se confundiria con `-w`
        self.assertTrue(ccl.parse_args(["-n"])[1])
        self.assertTrue(ccl.parse_args(["--notify", "0"])[1])

    def test_el_intervalo_de_notify_no_se_confunde_con_una_sesion(self):
        """`--notify 30` son 30 segundos, no la sesion [30]."""
        opts, err = ccl.parse_args(["--notify", "30"])
        self.assertIsNone(err)
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


# ────────────────────────── pausadas ──────────────────────────


class TestPausadas(unittest.TestCase):
    """
    Pausada = espera algo que no eres tu. Es una marca del usuario porque
    `claude agents --json` no la puede dar: solo distingue busy/idle.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = ccl.NOTES_FILE
        ccl.NOTES_FILE = os.path.join(self.tmp.name, "ccl-notes.json")

    def tearDown(self):
        ccl.NOTES_FILE = self.orig
        self.tmp.cleanup()

    def test_marca_y_desmarca(self):
        self.assertTrue(ccl.toggle_paused("sid-a"))
        self.assertEqual(ccl.load_state()[2], {"sid-a"})
        self.assertFalse(ccl.toggle_paused("sid-a"))
        self.assertEqual(ccl.load_state()[2], set())

    def test_guardar_una_nota_no_borra_las_pausadas(self):
        """
        El fallo que obligo a que haya un solo escritor: `save_note` se escribia el JSON
        entero con dos claves, asi que la primera nota se llevaba por delante la lista.
        """
        ccl.toggle_paused("sid-a")
        ccl.save_note("sid-b", "una nota cualquiera")
        self.assertEqual(ccl.load_state()[2], {"sid-a"})

    def test_pausar_no_toca_las_notas(self):
        ccl.save_note("sid-a", "esperando a Felipe")
        ccl.toggle_paused("sid-a")
        sesion, _, pausadas = ccl.load_state()
        self.assertEqual(sesion["sid-a"], "esperando a Felipe")
        self.assertEqual(pausadas, {"sid-a"})

    def test_sale_de_esperando_y_no_la_elige_w(self):
        """El sentido entero de la pausa: `-w`/⌥N no puede mandarte a la que no puedes
        desatascar."""
        rows = [row(1, "pausada", "idle", ts=iso(minutes=1), paused=True),
                row(2, "la-buena", "idle", ts=iso(hours=2))]
        self.assertEqual([r["sessionId"] for r in ccl.waiting_rows(rows)], ["la-buena"])
        elegida, _ = ccl.pick_waiting(rows, 1)
        self.assertEqual(elegida["sessionId"], "la-buena")

    def test_tiene_su_propio_grupo_despues_de_esperando(self):
        rows = [row(1, "a", "idle", ts=iso(minutes=1)),
                row(2, "b", "idle", ts=iso(minutes=2), paused=True)]
        self.assertEqual([lbl for lbl, _, _ in ccl.grouped(rows)],
                         [ccl.t("grupo_idle"), ccl.t("grupo_pausa")])

    def test_una_pausada_que_vuelve_a_trabajar_se_ve_arriba(self):
        """Si esta corriendo no espera a nadie: esconderla abajo seria mentir."""
        g = ccl.grouped([row(1, "a", "busy", ts=iso(minutes=1), paused=True)])
        self.assertEqual([lbl for lbl, _, _ in g], [ccl.t("grupo_busy")])

    def test_una_de_background_pausada_no_sale_dos_veces(self):
        rows = [row(1, "bg", "idle", kind="background", paused=True, ts=iso(minutes=1))]
        etiquetas = [lbl for lbl, _, _ in ccl.grouped(rows)]
        self.assertEqual(etiquetas, [ccl.t("grupo_pausa")])

    def test_build_marca_las_pausadas_del_archivo(self):
        ccl.toggle_paused("sid-a")
        sesiones = [{"sessionId": "sid-a", "name": "a", "cwd": "/x", "pid": 1},
                    {"sessionId": "sid-b", "name": "b", "cwd": "/x", "pid": 2}]
        filas = ccl.build(sesiones, {}, {}, {"sid-a": 1, "sid-b": 2})
        self.assertEqual({f["sessionId"]: f["paused"] for f in filas},
                         {"sid-a": True, "sid-b": False})

    def test_una_lista_de_pausadas_con_basura_no_revienta(self):
        ccl.escribir_json(ccl.NOTES_FILE, {"por_repo": {}, "pausadas": "no-es-lista"})
        self.assertEqual(ccl.load_state()[2], set())
        ccl.escribir_json(ccl.NOTES_FILE, {"pausadas": ["sid-a", 7, None]})
        self.assertEqual(ccl.load_state()[2], {"sid-a"})

    def test_el_formato_viejo_sigue_leyendose_y_no_tiene_pausadas(self):
        ccl.escribir_json(ccl.NOTES_FILE, {"/repos/web": "escrita con el formato viejo"})
        sesion, repo, pausadas = ccl.load_state()
        self.assertEqual(repo, {"/repos/web": "escrita con el formato viejo"})
        self.assertEqual((sesion, pausadas), ({}, set()))

    def test_un_archivo_corrupto_no_impide_pausar(self):
        """Mismo criterio que las notas: un archivo roto no puede tumbar el panel."""
        os.makedirs(os.path.dirname(ccl.NOTES_FILE), exist_ok=True)
        with open(ccl.NOTES_FILE, "w") as fh:
            fh.write("{ esto no es json")
        self.assertTrue(ccl.toggle_paused("sid-a"))
        self.assertEqual(ccl.load_state()[2], {"sid-a"})

    def test_el_archivo_no_queda_legible_por_otros(self):
        """Pausar puede CREAR el fichero: tiene que nacer con los mismos permisos."""
        ccl.toggle_paused("sid-a")
        modo = stat.S_IMODE(os.stat(ccl.NOTES_FILE).st_mode)
        self.assertEqual(modo & 0o077, 0, f"permisos {oct(modo)}: legible por otros")

    def test_una_fila_sin_el_campo_no_revienta(self):
        """
        `test_panel.py` y cualquier código que fabrique filas a mano se saltan `build`,
        que es quien pone `paused`. Por eso se lee con `.get`, y esto lo fija.
        """
        cruda = row(1, "a", "idle", ts=iso(minutes=1))
        del cruda["paused"]
        self.assertTrue(ccl.waiting_rows([cruda]))
        self.assertTrue(ccl.grouped([cruda]))
        self.assertEqual(ccl.estado_de(cruda)[0], ccl.t("grupo_idle"))

    def test_estado_de_coincide_con_el_grupo_que_le_toca(self):
        """La columna de estado de la tabla y la cabecera de grupo no pueden discrepar."""
        rows = [row(1, "a", "busy", ts=iso(minutes=1)),
                row(2, "b", "idle", ts=iso(minutes=2)),
                row(3, "c", "idle", ts=iso(minutes=3), paused=True),
                row(4, "d", "idle", ts=iso(minutes=4), kind="background")]
        for etiqueta, _, items in ccl.grouped(rows):
            for r in items:
                self.assertEqual(ccl.estado_de(r)[0], etiqueta, r["sessionId"])

    def test_un_archivo_que_solo_tiene_pausadas_no_las_lee_como_notas(self):
        """Sin la clave en la deteccion del formato, {"pausadas": [...]} se leia como el
        formato viejo y la lista acababa de nota de un repo llamado "pausadas"."""
        ccl.escribir_json(ccl.NOTES_FILE, {"pausadas": ["sid-a"]})
        sesion, repo, pausadas = ccl.load_state()
        self.assertEqual((sesion, repo), ({}, {}))
        self.assertEqual(pausadas, {"sid-a"})


# ────────────────────────── vista de tabla ──────────────────────────


class TestTabla(unittest.TestCase):
    def filas(self):
        return [row(1, "a", "busy", ts=iso(minutes=1)),
                row(2, "b", "idle", ts=iso(minutes=2)),
                row(3, "c", "idle", ts=iso(minutes=3), paused=True)]

    def test_una_linea_por_sesion_y_una_cabecera(self):
        lines = ccl.build_table_display(self.filas(), width=120)
        self.assertEqual([r for r, _, _ in lines], ["head", "main", "main", "main"])
        self.assertIsNone(lines[0][2])

    def test_el_orden_es_el_mismo_que_el_de_los_grupos(self):
        rows = self.filas()
        esperado = [r["sessionId"] for _, _, items in ccl.grouped(rows) for r in items]
        lines = ccl.build_table_display(rows, width=120)
        self.assertEqual([f["sessionId"] for _, _, f in lines if f], esperado)

    def test_cada_fila_dice_su_estado(self):
        lines = ccl.build_table_display(self.filas(), width=120)
        plano = {f["sessionId"]: ccl.ANSI_RE.sub("", txt)
                 for _, txt, f in lines if f}
        self.assertIn(ccl.t("grupo_busy"), plano["a"])
        self.assertIn(ccl.t("grupo_idle"), plano["b"])
        self.assertIn(ccl.t("grupo_pausa"), plano["c"])

    def test_ninguna_linea_desborda_el_ancho(self):
        """Una fila mas ancha que la ventana se envuelve y descuadra el panel entero."""
        for ancho in (80, 100, 120, 160):
            for _, texto, _ in ccl.build_table_display(self.filas(), width=ancho):
                self.assertLessEqual(ccl.vis(texto), ancho, f"ancho={ancho}: {texto!r}")

    def test_la_marca_de_sin_iterm_tampoco_desborda(self):
        r = row(1, "a", "idle", ts=iso(minutes=1))
        r["prompt"] = "x" * 400
        self.assertLessEqual(ccl.vis(ccl.table_line(r, width=100)), 100)

    def test_las_columnas_se_alinean_con_la_cabecera(self):
        """Las dos salen de `_tabla_columnas`: si divergen, la tabla deja de ser tabla."""
        r = row(1, "a", "idle", ts=iso(minutes=1))
        r["name"], r["repo"] = "un-nombre-larguisimo-de-verdad-si", "repo-largo-tambien"
        anchos = [a for _, a in ccl._tabla_columnas(120, False)]
        corte = sum(anchos)
        cabecera = ccl.ANSI_RE.sub("", ccl.table_head(120, False))
        fila = ccl.ANSI_RE.sub("", ccl.table_line(r, 120, False))
        # el ultimo campo (nota/prompt) empieza en la misma columna en las dos
        self.assertEqual(cabecera[:corte].rstrip(), cabecera[:corte].rstrip())
        self.assertTrue(fila[corte - 1] == " ", "falta el espacio entre columnas")
        self.assertIn(ccl.t("col_nota"), cabecera[corte:])

    def test_en_una_ventana_estrecha_caen_las_columnas_prescindibles(self):
        estrecha = [k for k, _ in ccl._tabla_columnas(80, False)]
        ancha = [k for k, _ in ccl._tabla_columnas(140, False)]
        self.assertNotIn("branch", estrecha)
        self.assertNotIn("model", estrecha)
        self.assertIn("branch", ancha)
        self.assertIn("model", ancha)
        # lo imprescindible esta en las dos
        for k in ("num", "estado", "name", "repo", "ts"):
            self.assertIn(k, estrecha)

    def test_la_cuenta_solo_ocupa_columna_si_hay_varias(self):
        self.assertNotIn("account", [k for k, _ in ccl._tabla_columnas(120, False)])
        self.assertIn("account", [k for k, _ in ccl._tabla_columnas(120, True)])

    def test_con_varias_cuentas_tampoco_desborda(self):
        """La cuenta son once columnas mas: corre los umbrales de las prescindibles."""
        r = row(1, "a", "idle", ts=iso(minutes=1))
        r["account"] = "trabajo"
        for ancho in (80, 100, 120, 160):
            self.assertLessEqual(ccl.vis(ccl.table_line(r, ancho, True)), ancho,
                                 f"ancho={ancho}")

    def test_vista_elige_el_constructor(self):
        """Las dos vistas devuelven los MISMOS roles: es lo que hace que el cursor, el
        clic y el scroll no se enteren de cuál está puesta."""
        rows = self.filas()
        self.assertEqual(ccl.vista(rows, 120, True),
                         ccl.build_table_display(rows, 120))
        self.assertEqual(ccl.vista(rows, 120, False), ccl.build_display(rows, 120))
        for lineas in (ccl.vista(rows, 120, True), ccl.vista(rows, 120, False)):
            self.assertLessEqual({rol for rol, _, _ in lineas},
                                 {"head", "main", "sub", "blank"})

    def test_se_construye_mas_estrecha_que_la_ventana(self):
        """
        El panel pinta cada fila como `clip(texto, cols - 4)` y las cabeceras NO las
        recorta: construyendo al ancho entero, el recorte se comía la última columna y
        la cabecera se salía una posición.
        """
        for ancho in (80, 100, 128):
            for _, texto, _ in ccl.build_table_display(self.filas(), width=ancho):
                self.assertLessEqual(ccl.vis(texto), ancho - 4, f"ancho={ancho}")


class TestVigilante(unittest.TestCase):
    """
    `--notify`. Toda la decision es pura: `Vigilante` no manda ninguna notificacion, asi
    que se puede probar entera sin llenar de avisos la pantalla de quien corra los tests.
    """

    def test_la_primera_foto_no_avisa_de_nada(self):
        """
        Arrancar con doce sesiones ociosas y soltar doce notificaciones es la forma mas
        rapida de que alguien apague los avisos para siempre.
        """
        v = ccl.Vigilante()
        rows = [row(n, f"sid-{n}", "idle", ts=iso(minutes=n)) for n in range(1, 13)]
        self.assertEqual(v.nuevas(rows), [])

    def test_avisa_de_la_que_acaba_de_ponerse_a_esperar(self):
        trabajando = row(1, "sid-a", "busy", ts=iso(minutes=1))
        v = ccl.Vigilante()
        v.nuevas([trabajando])
        libre = dict(trabajando, status="idle")
        self.assertEqual([r["sessionId"] for r in v.nuevas([libre])], ["sid-a"])

    def test_no_repite_el_aviso_mientras_siga_esperando(self):
        """Avisa del FLANCO, no del estado: si no, repetiria cada 15 s."""
        v = ccl.Vigilante()
        v.nuevas([row(1, "sid-a", "busy", ts=iso(minutes=1))])
        libre = [row(1, "sid-a", "idle", ts=iso(minutes=1))]
        self.assertEqual(len(v.nuevas(libre)), 1)
        for _ in range(3):
            self.assertEqual(v.nuevas(libre), [])

    def test_si_vuelve_a_trabajar_y_termina_avisa_otra_vez(self):
        v = ccl.Vigilante()
        v.nuevas([row(1, "sid-a", "idle", ts=iso(minutes=1))])
        v.nuevas([row(1, "sid-a", "busy", ts=iso(minutes=1))])
        self.assertEqual(len(v.nuevas([row(1, "sid-a", "idle", ts=iso(minutes=1))])), 1)

    def test_una_pausada_no_avisa_nunca(self):
        """Marcaste que espera a otro: avisarte de ella es lo contrario de lo que pediste."""
        v = ccl.Vigilante()
        v.nuevas([row(1, "sid-a", "busy", ts=iso(minutes=1))])
        libre_pausada = [row(1, "sid-a", "idle", ts=iso(minutes=1), paused=True)]
        self.assertEqual(v.nuevas(libre_pausada), [])

    def test_las_de_background_tampoco(self):
        v = ccl.Vigilante()
        v.nuevas([row(1, "sid-a", "busy", ts=iso(minutes=1), kind="background")])
        self.assertEqual(
            v.nuevas([row(1, "sid-a", "idle", ts=iso(minutes=1), kind="background")]), [])

    def test_una_sesion_que_muere_no_avisa(self):
        v = ccl.Vigilante()
        v.nuevas([row(1, "sid-a", "busy", ts=iso(minutes=1))])
        self.assertEqual(v.nuevas([]), [])

    def test_una_sesion_nueva_que_nace_esperando_avisa(self):
        """Es el caso de `claude --resume`: no estaba, y ya te espera."""
        v = ccl.Vigilante()
        v.nuevas([row(1, "sid-a", "busy", ts=iso(minutes=1))])
        nuevas = v.nuevas([row(1, "sid-a", "busy", ts=iso(minutes=1)),
                           row(2, "sid-b", "idle", ts=iso(minutes=2))])
        self.assertEqual([r["sessionId"] for r in nuevas], ["sid-b"])

    def test_el_orden_es_el_mismo_que_el_del_panel(self):
        v = ccl.Vigilante()
        v.nuevas([])
        rows = [row(1, "vieja", "idle", ts=iso(hours=3)),
                row(2, "nueva", "idle", ts=iso(minutes=1))]
        self.assertEqual([r["sessionId"] for r in v.nuevas(rows)],
                         [r["sessionId"] for r in ccl.waiting_rows(rows)])


class TestBucleDeVigilancia(unittest.TestCase):
    """
    `watch()` de punta a punta, con `collect` y `notificar` parcheados: ni se ejecuta
    `claude` ni se manda ninguna notificacion de verdad.
    """

    def setUp(self):
        self.avisos = []
        self.originales = (ccl.collect, ccl.notificar, ccl.time.sleep)
        ccl.notificar = lambda *a: self.avisos.append(a) or True
        ccl.time.sleep = lambda _: None      # el intervalo no se espera de verdad

    def tearDown(self):
        ccl.collect, ccl.notificar, ccl.time.sleep = self.originales

    def _guion(self, fotos):
        """`collect` va devolviendo una foto distinta en cada llamada."""
        it = iter(fotos)
        ultima = [fotos[-1]]
        ccl.collect = lambda: next(it, ultima[0])

    def test_avisa_una_vez_por_sesion_que_termina(self):
        ocupada = [row(1, "sid-a", "busy", ts=iso(minutes=1))]
        libre = [row(1, "sid-a", "idle", ts=iso(minutes=1))]
        self._guion([ocupada, libre, libre, libre])
        ccl.watch(intervalo=0, vueltas=3)
        self.assertEqual(len(self.avisos), 1, "una sola vez, aunque siga esperando")
        titulo, _, _ = self.avisos[0]
        self.assertEqual(titulo, "[1] s1")   # `row()` nombra las sesiones s<num>

    def test_muchas_a_la_vez_son_un_solo_aviso_resumido(self):
        """Doce notificaciones de golpe no se leen, se descartan."""
        ocupadas = [row(n, f"sid-{n}", "busy", ts=iso(minutes=n)) for n in range(1, 7)]
        libres = [dict(r, status="idle") for r in ocupadas]
        self._guion([ocupadas, libres])
        ccl.watch(intervalo=0, vueltas=1)
        self.assertEqual(len(self.avisos), 1, "deberia resumir, no mandar seis")
        self.assertIn("6", self.avisos[0][0])

    def test_justo_en_el_limite_avisa_una_por_una(self):
        n = ccl.NOTIFY_MAX
        ocupadas = [row(i, f"sid-{i}", "busy", ts=iso(minutes=i)) for i in range(1, n + 1)]
        libres = [dict(r, status="idle") for r in ocupadas]
        self._guion([ocupadas, libres])
        ccl.watch(intervalo=0, vueltas=1)
        self.assertEqual(len(self.avisos), n)

    def test_un_fallo_puntual_de_collect_no_mata_al_vigilante(self):
        """Que Claude Code se reinicie no puede dejarte sin avisos el resto del dia."""
        ocupada = [row(1, "sid-a", "busy", ts=iso(minutes=1))]
        libre = [row(1, "sid-a", "idle", ts=iso(minutes=1))]
        llamadas = [ocupada, "boom", libre]
        it = iter(llamadas)

        def collect_con_fallo():
            v = next(it, libre)
            if v == "boom":
                raise ccl.SessionsUnavailable("claude se cayo")
            return v

        ccl.collect = collect_con_fallo
        ccl.watch(intervalo=0, vueltas=2)
        self.assertEqual(len(self.avisos), 1, "no avisó tras recuperarse del fallo")

    def test_si_claude_no_esta_al_arrancar_falla_en_vez_de_callarse(self):
        """
        Un demonio silencioso que nunca avisará es indistinguible de uno que funciona.
        El primer `collect()` va fuera del try justamente para esto.
        """
        def collect_roto():
            raise ccl.SessionsUnavailable("no encuentro claude")

        ccl.collect = collect_roto
        with self.assertRaises(ccl.SessionsUnavailable):
            ccl.watch(intervalo=0, vueltas=1)


class TestSalirDelVigilante(unittest.TestCase):
    """
    Se puede parar. Suena obvio; no lo fue: `ccl --notify` se quedó sin morir con Ctrl-C
    en una terminal de verdad, y no hay nada peor en un proceso de fondo que uno del que
    no te puedes bajar.
    """

    def setUp(self):
        self.originales = (ccl.collect, ccl.notificar, ccl.time.sleep)
        ccl.notificar = lambda *a: True
        ccl.time.sleep = lambda _: None

    def tearDown(self):
        ccl.collect, ccl.notificar, ccl.time.sleep = self.originales

    def test_una_señal_corta_el_bucle(self):
        """SIGINT en mitad de una vuelta: la siguiente ya no ocurre."""
        vueltas = []

        def collect_que_avisa():
            vueltas.append(1)
            if len(vueltas) == 2:
                os.kill(os.getpid(), signal.SIGINT)
            return [row(1, "sid-a", "idle", ts=iso(minutes=1))]

        ccl.collect = collect_que_avisa
        self.assertEqual(ccl.watch(intervalo=0, vueltas=50), 0)
        self.assertLessEqual(len(vueltas), 3, "siguió dando vueltas tras la señal")

    def test_sigterm_tambien(self):
        """Es lo que manda `kill`, y lo que usará launchd al cerrar sesión."""
        vueltas = []

        def collect_que_avisa():
            vueltas.append(1)
            if len(vueltas) == 2:
                os.kill(os.getpid(), signal.SIGTERM)
            return []

        ccl.collect = collect_que_avisa
        self.assertEqual(ccl.watch(intervalo=0, vueltas=50), 0)
        self.assertLessEqual(len(vueltas), 3)

    def test_deja_los_manejadores_como_estaban(self):
        """Los instala para sí, no para siempre: `watch()` también se importa."""
        antes = signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)
        ccl.collect = lambda: []
        ccl.watch(intervalo=0, vueltas=1)
        self.assertEqual((signal.getsignal(signal.SIGINT),
                          signal.getsignal(signal.SIGTERM)), antes)

    def test_dormir_se_corta_en_cuanto_hay_bandera(self):
        """
        Desde PEP 475 `time.sleep()` REANUDA lo que le queda si la señal no lanza
        excepción. De una sola vez, un `--notify 60` tardaría un minuto en reaccionar al
        Ctrl-C, que por fuera es idéntico a estar colgado. Por eso duerme a rodajas.
        """
        ccl.time.sleep = self.originales[2]      # aquí el sleep tiene que ser el de verdad
        parar = []
        import threading
        threading.Timer(0.2, lambda: parar.append(True)).start()
        t0 = time.monotonic()
        ccl._dormir(30, parar)
        self.assertLess(time.monotonic() - t0, 3, "no miró la bandera mientras dormía")


class TestSubprocesosSinTerminal(unittest.TestCase):
    """
    **Ningún hijo puede ver el terminal.** `capture_output=True` redirige la salida pero
    NO stdin: el hijo hereda el tty y puede reconfigurarlo. `claude` es una TUI de Node y
    pone stdin en modo raw; si muere a mitad por una señal, no lo deshace y te quedas con
    la terminal en raw — sin Ctrl-C ni Ctrl-Z, que es justo lo que pasó. Con `DEVNULL` en
    fd 0 no hay nada que tocar.
    """

    def _capturar(self, fn):
        llamadas = []
        original = ccl.subprocess.run

        def falso(cmd, **kw):
            llamadas.append(kw)
            class R:
                returncode, stdout, stderr = 0, "", ""
            return R()

        ccl.subprocess.run = falso
        try:
            fn()
        except Exception:
            pass
        finally:
            ccl.subprocess.run = original
        return llamadas

    def test_ninguna_llamada_hereda_el_stdin(self):
        casos = {
            "get_ttys": lambda: ccl.get_ttys([1, 2]),
            "get_iterm_map": ccl.get_iterm_map,
            "notificar": lambda: ccl.notificar("a", "b", "c"),
            "focus": lambda: ccl.focus({"iterm": ("1", 2), "num": 1, "name": "x",
                                        "tty": "", "cwd": "/x"}, quiet=True),
        }
        for nombre, fn in casos.items():
            for kw in self._capturar(fn):
                self.assertEqual(kw.get("stdin"), ccl.subprocess.DEVNULL,
                                 f"{nombre} deja que el hijo vea el terminal")

    def test_tambien_al_consultar_a_claude(self):
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "projects"), exist_ok=True)
        for kw in self._capturar(lambda: ccl._sessions_from(tmp)):
            self.assertEqual(kw.get("stdin"), ccl.subprocess.DEVNULL,
                             "`claude` es una TUI: no puede heredar el terminal")

    def test_no_queda_ninguna_suelta_en_el_codigo(self):
        """
        Guardarraíl sobre el fuente: una llamada nueva sin `stdin` vuelve a abrir el
        agujero, y el sintoma —una terminal que se queda sin Ctrl-C -- aparece lejos.
        """
        with open(os.path.join(_HERE, "ccl")) as fh:
            fuente = fh.read()
        llamadas = fuente.count("subprocess.run(")
        con_devnull = fuente.count("stdin=subprocess.DEVNULL")
        self.assertEqual(llamadas, con_devnull,
                         f"{llamadas} llamadas a subprocess.run y solo "
                         f"{con_devnull} con stdin=DEVNULL")


class TestTextoDelAviso(unittest.TestCase):
    def test_lleva_numero_nombre_repo_y_rama(self):
        r = row(3, "sid-a", "idle", ts=iso(minutes=1))
        r["name"], r["repo"], r["branch"] = "arreglar-login", "web-app", "fix/login"
        titulo, subtitulo, _ = ccl.aviso_de(r)
        self.assertEqual(titulo, "[3] arreglar-login")
        self.assertEqual(subtitulo, "web-app · fix/login")

    def test_tu_nota_manda_sobre_el_prompt(self):
        r = row(1, "sid-a", "idle", ts=iso(minutes=1))
        r["prompt"], r["note"] = "el ultimo prompt", "esperando a Felipe"
        self.assertEqual(ccl.aviso_de(r)[2], "esperando a Felipe")

    def test_sin_nota_cae_al_prompt_y_luego_al_titulo(self):
        r = row(1, "sid-a", "idle", ts=iso(minutes=1))
        r["prompt"] = "revisa el flujo de pago"
        self.assertEqual(ccl.aviso_de(r)[2], "revisa el flujo de pago")
        r["prompt"], r["title"] = None, "un titulo"
        self.assertEqual(ccl.aviso_de(r)[2], "un titulo")

    def test_sin_nada_no_revienta(self):
        self.assertEqual(ccl.aviso_de(row(1, "sid-a"))[2], "")

    def test_el_cuerpo_se_recorta_y_va_en_una_linea(self):
        r = row(1, "sid-a", "idle", ts=iso(minutes=1))
        r["prompt"] = "linea uno\n\nlinea dos   con    espacios " + "x" * 400
        cuerpo = ccl.aviso_de(r)[2]
        self.assertNotIn("\n", cuerpo)
        self.assertIn("linea uno linea dos con espacios", cuerpo)
        self.assertLessEqual(len(cuerpo), 200)

    def test_el_texto_va_por_argv_y_no_dentro_del_applescript(self):
        """
        Aqui entra por primera vez texto de FUERA en un script que se ejecuta. Interpolarlo
        convierte una comilla en un error de sintaxis, y algo peor que una comilla en
        AppleScript arbitrario. Con `on run argv` el texto es un dato.
        """
        capturado = {}

        def falso_run(cmd, **kw):
            capturado["cmd"] = cmd
            class R:
                returncode = 0
            return R()

        original = ccl.subprocess.run
        ccl.subprocess.run = falso_run
        try:
            malicioso = '" & (do shell script "touch /tmp/ccl-pwned") & "'
            ccl.notificar("titulo", "sub", malicioso)
        finally:
            ccl.subprocess.run = original

        cmd = capturado["cmd"]
        self.assertIn("--", cmd, "el texto tiene que ir despues de -- , como argumento")
        script = " ".join(cmd[:cmd.index("--")])
        self.assertNotIn(malicioso, script, "el texto acabó DENTRO del AppleScript")
        self.assertIn(malicioso, cmd[cmd.index("--") + 1:], "el texto deberia ir en argv")
        self.assertIn("item 1 of argv", script)


class TestListadoEstatico(unittest.TestCase):
    """`--list`, con y sin `--table`. Es la salida que la gente mete en una tubería."""

    def _render(self, tabla):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ccl.render([row(1, "a", "busy", ts=iso(minutes=1)),
                        row(2, "b", "idle", ts=iso(minutes=2)),
                        row(3, "c", "idle", ts=iso(minutes=3), paused=True)], tabla)
        return ccl.ANSI_RE.sub("", buf.getvalue())

    def test_la_tabla_lleva_cabecera_y_una_linea_por_sesion(self):
        lineas = [l for l in self._render(True).split("\n") if l.strip()]
        self.assertIn(ccl.t("col_estado"), lineas[0])
        self.assertEqual(len(lineas), 4, "cabecera + tres sesiones")

    def test_la_tabla_no_repite_las_cabeceras_de_grupo(self):
        salida = self._render(True)
        self.assertNotIn(f"{ccl.t('grupo_idle')} (", salida)
        # pero el estado sigue estando, ahora en su columna
        for clave in ("grupo_busy", "grupo_idle", "grupo_pausa"):
            self.assertIn(ccl.t(clave), salida)

    def test_la_vista_normal_sigue_siendo_de_dos_lineas_por_grupo(self):
        salida = self._render(False)
        self.assertIn(f"{ccl.t('grupo_pausa')} (1)", salida)

    def test_las_dos_vistas_enseñan_las_mismas_sesiones(self):
        for vista in (self._render(True), self._render(False)):
            for n in ("[ 1]", "[ 2]", "[ 3]"):
                self.assertIn(n, vista)


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
            # el mensaje entero, en el idioma que toque
            self.assertIn(ccl.t("sin_comando").split("\n")[0], str(cm.exception))
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


class TestIdioma(unittest.TestCase):
    """
    La interfaz va en ingles por defecto y en español si el entorno lo pide. Estos tests
    son el guardarrail contra el "a medias": una traduccion incompleta desconcierta mas
    que una interfaz entera en un idioma que no es el tuyo.
    """

    def setUp(self):
        self.orig_lang = ccl.LANG
        self.orig_env = {k: os.environ.get(k)
                         for k in ("CCL_LANG", "LC_ALL", "LC_MESSAGES", "LANG")}
        for k in self.orig_env:
            os.environ.pop(k, None)

    def tearDown(self):
        ccl.LANG = self.orig_lang
        for k, v in self.orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_los_dos_idiomas_tienen_las_mismas_claves(self):
        """Si falta una clave, `t()` cae al ingles y sale una linea descolgada."""
        self.assertEqual(set(ccl.TEXTOS["en"]), set(ccl.TEXTOS["es"]))

    def test_ninguna_traduccion_esta_vacia(self):
        for idioma, tabla in ccl.TEXTOS.items():
            for clave, valor in tabla.items():
                self.assertTrue(valor.strip(), f"{idioma}/{clave} está vacío")

    def test_los_huecos_coinciden_entre_idiomas(self):
        """
        Un `{n}` que exista en un idioma y no en el otro revienta con KeyError en
        cuanto alguien cambie de locale — o peor, deja el dato fuera del mensaje.
        """
        for clave, en in ccl.TEXTOS["en"].items():
            huecos = lambda s: set(re.findall(r"\{(\w+)\}", s))
            self.assertEqual(huecos(en), huecos(ccl.TEXTOS["es"][clave]),
                             f"los huecos de {clave!r} no coinciden")

    def test_las_dos_ayudas_van_en_paralelo(self):
        """Misma estructura y las MISMAS teclas: lo que cambia es la descripcion."""
        self.assertEqual(len(ccl.HELP_EN), len(ccl.HELP_ES))
        for (t_en, filas_en), (t_es, filas_es) in zip(ccl.HELP_EN, ccl.HELP_ES):
            self.assertTrue(t_en and t_es)
            self.assertEqual(len(filas_en), len(filas_es),
                             f"la seccion {t_en!r}/{t_es!r} no tiene las mismas filas")
            for (k_en, d_en), (k_es, d_es) in zip(filas_en, filas_es):
                self.assertTrue(d_en and d_es, f"falta descripcion en {t_en!r}")
                # las teclas son las mismas salvo cuando la propia tecla se nombra en
                # palabras ("clic"/"click", "rueda"/"wheel")
                if k_en.isascii() and not k_en.isalpha() and " " not in k_en:
                    self.assertEqual(k_en, k_es, f"la tecla cambia entre idiomas")

    def test_CCL_LANG_manda_sobre_el_locale(self):
        os.environ["LANG"] = "es_ES.UTF-8"
        os.environ["CCL_LANG"] = "en"
        self.assertEqual(ccl.detect_lang(), "en")

    def test_sigue_el_locale_si_no_hay_CCL_LANG(self):
        os.environ["LANG"] = "es_MX.UTF-8"
        self.assertEqual(ccl.detect_lang(), "es")
        os.environ["LANG"] = "en_US.UTF-8"
        self.assertEqual(ccl.detect_lang(), "en")

    def test_LC_ALL_gana_a_LANG(self):
        """Es el orden de POSIX: quien exporta LC_ALL=C espera que mande."""
        os.environ["LANG"] = "es_ES.UTF-8"
        os.environ["LC_ALL"] = "C"
        self.assertEqual(ccl.detect_lang(), "en")

    def test_sin_nada_en_el_entorno_es_ingles(self):
        self.assertEqual(ccl.detect_lang(), "en")

    def test_un_locale_raro_no_revienta(self):
        for valor in ("", "POSIX", "zh_CN.UTF-8", "esperanto"):
            os.environ["LANG"] = valor
            self.assertIn(ccl.detect_lang(), ("en", "es"))

    def test_una_clave_que_falte_cae_al_ingles_sin_reventar(self):
        ccl.LANG = "es"
        original = ccl.TEXTOS["es"].pop("sin_sesiones")
        try:
            self.assertEqual(ccl.t("sin_sesiones"), ccl.TEXTOS["en"]["sin_sesiones"])
        finally:
            ccl.TEXTOS["es"]["sin_sesiones"] = original

    def test_los_dos_idiomas_rellenan_los_huecos(self):
        for idioma in ("en", "es"):
            ccl.LANG = idioma
            self.assertIn("7", ccl.t("solo_hay_esperando", n=7))
            self.assertIn("mi-repo", ccl.t("nota_prompt", repo="mi-repo"))

    def test_el_uso_de_help_existe_en_los_dos(self):
        for texto in (ccl.USO_EN, ccl.USO_ES):
            self.assertIn("ccl", texto)
            self.assertIn("-w", texto)
            self.assertIn("CCL_LANG", texto, "hay que documentar como cambiar de idioma")


class TestNotas(unittest.TestCase):
    """
    Las notas van por **directorio**, no por sessionId: los sessionId cambian al
    reiniciar Claude Code y la nota se quedaria huerfana justo cuando mas hace falta.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = ccl.NOTES_FILE
        ccl.NOTES_FILE = os.path.join(self.tmp.name, "sub", "ccl-notes.json")

    def tearDown(self):
        ccl.NOTES_FILE = self.orig
        self.tmp.cleanup()

    def test_guarda_y_recupera(self):
        ccl.save_note("sid-1", "backend de facturación")
        sesion, repo = ccl.load_notes()
        self.assertEqual(sesion, {"sid-1": "backend de facturación"})
        self.assertEqual(repo, {})

    def test_una_nota_no_se_pega_a_las_otras_sesiones_del_mismo_repo(self):
        """
        EL BUG que hizo cambiar el diseño: con la nota atada al `cwd`, escribir
        "esperando que felipe haga algo" en una sesion la pintaba en las otras tres del
        mismo directorio. Con 16 sesiones en 11 directorios, el 43% no podia tener nota
        propia.
        """
        filas = [row(1, "sid-a"), row(2, "sid-b"), row(3, "sid-c")]
        for f in filas:
            f["cwd"] = "/repos/support_agent"        # las tres en el MISMO directorio
        ccl.save_note("sid-b", "esperando que felipe haga algo")
        sesion, repo = ccl.load_notes()
        vistas = [ccl.note_for(f, sesion, repo) for f in filas]
        self.assertEqual(vistas, ["", "esperando que felipe haga algo", ""])

    def test_la_del_repo_es_el_respaldo_de_las_que_no_tienen_propia(self):
        filas = [row(1, "sid-a"), row(2, "sid-b")]
        for f in filas:
            f["cwd"] = "/repos/web"
        ccl.escribir_json(ccl.NOTES_FILE, {"por_repo": {"/repos/web": "el backend"}})
        ccl.save_note("sid-b", "yo tengo la mia")
        sesion, repo = ccl.load_notes()
        self.assertEqual([ccl.note_for(f, sesion, repo) for f in filas],
                         ["el backend", "yo tengo la mia"])

    def test_borrar_la_propia_devuelve_la_del_repo(self):
        """Es la forma de "quitar lo mio" sin tener que editar el JSON a mano."""
        fila = row(1, "sid-a")
        fila["cwd"] = "/repos/web"
        ccl.escribir_json(ccl.NOTES_FILE, {"por_repo": {"/repos/web": "el backend"}})
        ccl.save_note("sid-a", "temporal")
        sesion, repo = ccl.load_notes()
        self.assertEqual(ccl.note_for(fila, sesion, repo), "temporal")
        ccl.save_note("sid-a", "")
        sesion, repo = ccl.load_notes()
        self.assertEqual(ccl.note_for(fila, sesion, repo), "el backend")

    def test_lee_el_formato_viejo_sin_perder_nada(self):
        """
        Las notas del formato anterior eran un dict plano {cwd: nota}. Quien ya las tenia
        escritas no puede perderlas por un cambio de formato: se leen como notas de repo.
        """
        ccl.escribir_json(ccl.NOTES_FILE, {"/repos/web": "escrita con el formato viejo"})
        sesion, repo = ccl.load_notes()
        self.assertEqual(sesion, {})
        self.assertEqual(repo, {"/repos/web": "escrita con el formato viejo"})

    def test_guardar_una_de_sesion_no_pisa_las_de_repo(self):
        """La migracion tiene que sobrevivir al primer guardado, no solo a la lectura."""
        ccl.escribir_json(ccl.NOTES_FILE, {"/repos/web": "la del repo"})
        ccl.save_note("sid-a", "la mia")
        sesion, repo = ccl.load_notes()
        self.assertEqual(repo, {"/repos/web": "la del repo"})
        self.assertEqual(sesion, {"sid-a": "la mia"})

    def test_crea_el_directorio_si_no_existe(self):
        """NOTES_FILE puede caer en un ~/.claude que aun no exista."""
        ccl.save_note("sid-1", "algo")
        self.assertTrue(os.path.exists(ccl.NOTES_FILE))

    def test_sin_archivo_no_hay_notas_y_no_revienta(self):
        self.assertEqual(ccl.load_notes(), ({}, {}))

    def test_una_nota_vacia_la_borra(self):
        ccl.save_note("sid-1", "algo")
        ccl.save_note("sid-1", "   ")
        self.assertEqual(ccl.load_notes(), ({}, {}))

    def test_borrar_una_que_no_existe_no_revienta(self):
        self.assertEqual(ccl.save_note("sid-que-no-existe", ""), "")

    def test_normaliza_espacios_y_saltos(self):
        """Es una linea en un panel: un salto de linea descuadraria el layout."""
        self.assertEqual(ccl.save_note("sid-1", "  hola \n\t mundo  "), "hola mundo")

    def test_recorta_las_larguisimas(self):
        guardada = ccl.save_note("sid-1", "a" * (ccl.NOTE_MAX + 500))
        self.assertEqual(len(guardada), ccl.NOTE_MAX)
        self.assertEqual(len(ccl.load_notes()[0]["sid-1"]), ccl.NOTE_MAX)

    def test_no_pierde_las_demas_al_guardar_una(self):
        ccl.save_note("sid-a", "uno")
        ccl.save_note("sid-b", "dos")
        self.assertEqual(ccl.load_notes()[0], {"sid-a": "uno", "sid-b": "dos"})

    def test_archivo_corrupto_no_revienta(self):
        os.makedirs(os.path.dirname(ccl.NOTES_FILE), exist_ok=True)
        with open(ccl.NOTES_FILE, "w") as fh:
            fh.write("{esto no es json")
        self.assertEqual(ccl.load_notes(), ({}, {}))

    def test_json_valido_pero_con_la_forma_equivocada(self):
        """Una lista, o valores que no son texto: se ignoran en vez de reventar."""
        os.makedirs(os.path.dirname(ccl.NOTES_FILE), exist_ok=True)
        for basura in ('["a", "b"]', '{"/x": 42, "/y": "vale"}', '"solo un string"'):
            with open(ccl.NOTES_FILE, "w") as fh:
                fh.write(basura)
            sesion, repo = ccl.load_notes()
            self.assertIsInstance(sesion, dict)
            self.assertIsInstance(repo, dict)
            self.assertNotIn("/x", repo)

    def test_los_acentos_se_guardan_legibles(self):
        """ensure_ascii=False: el archivo lo puede editar el usuario a mano."""
        ccl.save_note("sid-1", "migración")
        with open(ccl.NOTES_FILE) as fh:
            self.assertIn("migración", fh.read())

    def test_la_nota_sale_en_la_linea_de_detalle_y_va_primera(self):
        r = row(1, "a")
        r.update({"note": "backend de facturación", "branch": "main", "model": "opus-5"})
        plano = ccl.ANSI_RE.sub("", ccl.detail_line(r))
        self.assertIn("✎ backend de facturación", plano)
        self.assertLess(plano.index("backend"), plano.index("main"),
                        "la nota va primera: al final se la come el recorte")

    def test_la_nota_va_resaltada(self):
        """
        La linea de detalle es casi toda DIM y grises: sin resaltarla, la nota se pierde
        entre la rama y el modelo, que es justo lo contrario de para lo que sirve.

        Se comprueba contra `NOTE`, no contra un codigo concreto: el color se puede
        cambiar de opinion sin tocar el test, pero que la nota se resalte, no.
        """
        r = row(1, "a")
        r.update({"note": "mi nota", "branch": "main", "model": "opus-5"})
        linea = ccl.detail_line(r)
        self.assertIn(ccl.NOTE("✎ mi nota"), linea, "la nota debe pintarse con NOTE")
        # y el resto de la linea NO debe quedarse con el atributo abierto
        self.assertIn("\033[0m", linea[linea.index("nota"):])

    def test_el_resalte_de_la_nota_es_negrita_con_color(self):
        """Ni DIM (seria invisible) ni color a secas (se pierde entre los demas)."""
        codigos = ccl.ANSI_RE.findall(ccl.NOTE("x"))
        self.assertTrue(codigos, "NOTE tiene que emitir algun codigo")
        apertura = codigos[0]
        self.assertIn("1;", apertura, "debe llevar negrita")
        self.assertNotIn("2;", apertura, "DIM haria justo lo contrario de resaltar")
        # Y un color de texto de verdad, no solo el atributo de negrita. Se acepta la
        # paleta de 256 (`38;5;N`) porque el rojo desaturado que se quiere para la nota
        # no existe entre los 16 basicos.
        self.assertRegex(apertura, r"38;5;\d+|3[0-7]\b|9[0-7]\b")

    def test_el_color_de_la_nota_no_choca_con_los_demas(self):
        """
        Cada cosa de la fila tiene que distinguirse de las otras. Ya paso: la nota se
        puso en magenta, que es el color del repo, y quedaba duplicado.
        """
        nota = ccl.ANSI_RE.findall(ccl.NOTE("x"))[0]
        otros = {
            "repo/fable": ccl.ANSI_RE.findall(ccl.MAGENTA("x"))[0],
            "rama/haiku": ccl.ANSI_RE.findall(ccl.GREY("x"))[0],
            "sonnet": ccl.ANSI_RE.findall(ccl.GREEN("x"))[0],
            "opus": ccl.ANSI_RE.findall(ccl.BLUE("x"))[0],
            "effort": ccl.ANSI_RE.findall(ccl.YELLOW("x"))[0],
            "⚠ y errores": ccl.ANSI_RE.findall(ccl.RED("x"))[0],
            "numero y UI": ccl.ANSI_RE.findall(ccl.CYAN("x"))[0],
        }
        for quien, codigo in otros.items():
            # comparar el numero de color, ignorando el ';1' de la negrita
            self.assertNotEqual(nota.replace("1;", ""), codigo,
                                f"la nota usa el mismo color que {quien}")

    def test_sin_nota_la_linea_no_cambia(self):
        r = row(1, "a")
        r.update({"branch": "main", "model": "opus-5"})
        self.assertNotIn("✎", ccl.detail_line(r))

    def test_se_puede_filtrar_por_la_nota(self):
        r = row(1, "a")
        r["note"] = "backend de facturación"
        self.assertTrue(ccl.matches(r, "factur"))
        self.assertTrue(ccl.matches(r, "facturacion"))   # sin acento tambien
        self.assertFalse(ccl.matches(r, "frontend"))


class TestSaneado(unittest.TestCase):
    """
    El panel PINTA campos que vienen de fuera: el ultimo prompt sale del transcript de
    Claude Code, o sea de lo que se teclea Y SE PEGA ahi. Un `\033[2A` colado ahi mueve el
    cursor y reescribe la fila de OTRA sesion: en una herramienta cuyo trabajo es "llevame
    a la sesion correcta", falsear una fila es el peor fallo posible.
    """

    def test_quita_las_secuencias_de_escape(self):
        for entrada in ("a\033[2Ab", "a\033]1337;SetUserVar=x=y\007b",
                        "a\033]0;titulo\033\\b", "a\033b", "a\007b", "a\x00b"):
            salida = ccl.sin_control(entrada)
            self.assertEqual(salida, "ab", f"con {entrada!r}")

    def test_se_come_la_carga_del_OSC_entera(self):
        """
        El orden de las alternativas del regex importa: si la generica de dos bytes va
        antes, casa solo `ESC ]` y el payload se queda como texto visible en la fila.
        """
        self.assertNotIn("1337", ccl.sin_control("\033]1337;File=algo\007"))
        self.assertNotIn("SetUserVar", ccl.sin_control("\033]1337;SetUserVar=a=b\007"))

    def test_no_toca_el_texto_normal(self):
        for entrada in ("hola mundo", "migración 会话 ñ", "listo 🎉",
                        "feature/ABC-123_v2", "a · b"):
            self.assertEqual(ccl.sin_control(entrada), entrada)

    def test_los_campos_pintables_se_sanean_al_construir_la_fila(self):
        """Se hace en `build`, una vez, y no en cada sitio que pinta."""
        sesiones = [{"sessionId": "s1", "name": "malo\033[2A", "cwd": "/x/repo\007",
                     "pid": 1, "kind": "interactive", "status": "idle", "startedAt": 0}]
        orig = ccl.read_transcript
        ccl.read_transcript = lambda *a, **k: {"branch": "main\033]0;x\007",
                                               "prompt": "pega\033[2Ado"}
        try:
            fila = ccl.build(sesiones, {}, {}, {"s1": 1})[0]
        finally:
            ccl.read_transcript = orig
        for campo in ("name", "repo", "branch", "prompt"):
            self.assertNotIn("\033", fila[campo] or "", f"{campo} sin sanear")

    def test_una_nota_editada_a_mano_en_el_json_tambien_se_sanea(self):
        """Por el editor no entran escapes (isprintable los filtra), pero el JSON es tuyo."""
        tmp = tempfile.mkdtemp()
        orig = ccl.NOTES_FILE
        ccl.NOTES_FILE = os.path.join(tmp, "notas.json")
        try:
            guardada = ccl.save_note("sid-1", "nota\033[2Amaliciosa")
            self.assertNotIn("\033", guardada)
        finally:
            ccl.NOTES_FILE = orig

    def test_el_fichero_de_notas_no_queda_legible_por_otros(self):
        """Son datos personales: nombres de gente y en qué estás esperando."""
        tmp = tempfile.mkdtemp()
        orig = ccl.NOTES_FILE
        ccl.NOTES_FILE = os.path.join(tmp, "notas.json")
        try:
            ccl.save_note("sid-1", "algo privado")
            modo = stat.S_IMODE(os.stat(ccl.NOTES_FILE).st_mode)
            self.assertEqual(modo & 0o077, 0, f"permisos {oct(modo)}: legible por otros")
        finally:
            ccl.NOTES_FILE = orig


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

    def _pulsar(self, data, n=1, ultimo_timeout=3.0):
        """
        Lo que `read_key()` decodifica al recibir `data`. Con `n>1`, la lista de las n
        lecturas seguidas — que es lo que hace falta para comprobar que nada se pierde
        en el camino, o que un doble clic llega entero.

        Escribir DESPUES de que read_key entre en modo raw: tty.setraw usa TCSAFLUSH,
        que descarta la entrada pendiente, asi que lo escrito antes se perderia. Esta
        plomeria estaba copiada en cuatro sitios; ya se toco una vez y mas vale tenerla
        en uno.

        `ultimo_timeout` acorta la espera de la ULTIMA lectura, para los tests que
        comprueban que ya no queda nada por leer sin esperar tres segundos.
        """
        maestro, esclavo = os.openpty()
        hilo = threading.Timer(0.05, lambda: os.write(maestro, data))
        stdin_real = ccl.sys.stdin
        try:
            ccl.sys.stdin = open(esclavo, "rb", buffering=0, closefd=False)
            hilo.start()
            leidas = [ccl.read_key(timeout=3.0 if i < n - 1 else ultimo_timeout)
                      for i in range(n)]
        finally:
            hilo.cancel()
            ccl.sys.stdin.close()
            ccl.sys.stdin = stdin_real
            os.close(esclavo)
            os.close(maestro)
        return leidas if n > 1 else leidas[0]

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
            tecla, sobra = self._pulsar(data, n=2, ultimo_timeout=0.3)
            self.assertEqual(tecla, esperado)
            self.assertIsNone(sobra, f"quedo basura tras {esperado}")

    def test_esc_suelto_sigue_siendo_esc(self):
        self.assertEqual(self._pulsar(b"\x1b"), "esc")

    def test_no_se_pierden_las_teclas_que_llegan_juntas(self):
        """
        `tty.setraw` usa TCSAFLUSH por defecto, que DESCARTA la entrada recibida y no
        leida. Como se entra en modo raw en cada lectura, de 5 teclas seguidas llegaba 1:
        se comia letras al escribir rapido y el doble clic (press,release,press,release
        de golpe) no llegaba nunca a verse como doble.
        """
        self.assertEqual(self._pulsar(b"abcde", n=5), ["a", "b", "c", "d", "e"])

    def test_dos_clics_seguidos_llegan_los_dos(self):
        """El doble clic depende de esto: los 4 eventos vienen en una sola rafaga."""
        rafaga = b"\x1b[<0;5;9M\x1b[<0;5;9m\x1b[<0;5;9M\x1b[<0;5;9m"
        self.assertEqual(self._pulsar(rafaga, n=4),
                         ["click:9", "mouse-release", "click:9", "mouse-release"])

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

    def test_los_acentos_y_la_ene_llegan_enteros(self):
        """
        UTF-8 multibyte: leyendo de a un byte, `decode(errors="ignore")` tiraba el
        caracter y no se podian escribir acentos ni ñ, ni al filtrar ni en una nota.
        En un proyecto en español eso no es un detalle.
        """
        for texto in ("ó", "ñ", "ü", "é"):
            self.assertEqual(self._pulsar(texto.encode()), texto)

    def test_los_caracteres_de_cuatro_bytes_tambien(self):
        """Un emoji son 4 bytes; nadie lo escribira en un filtro, pero no debe colgarse."""
        self.assertEqual(self._pulsar("🎉".encode()), "🎉")

    def test_las_teclas_de_accion_llegan_con_su_nombre(self):
        """
        Ctrl-N, Ctrl-P y Ctrl-T. Van en teclas de control y no en letras porque
        cualquier letra empieza a filtrar; que `read_key` las traduzca es lo que hace
        que el bucle del panel no tenga que saber de bytes.
        """
        for data, esperado in ((b"\x0e", "note"), (b"\x10", "pause"),
                               (b"\x14", "table")):
            self.assertEqual(self._pulsar(data), esperado, repr(data))

    def test_ctrl_r_y_digitos(self):
        self.assertEqual(self._pulsar(b"\x12"), "refresh")
        self.assertEqual(self._pulsar(b"3"), "3")
        self.assertEqual(self._pulsar(b"\r"), "enter")


# ────────────────────────── ayuda y teclas reservadas ──────────────────────────


class TestAyuda(unittest.TestCase):
    def test_estructura(self):
        self.assertTrue(ccl.help_secciones())
        for titulo, filas in ccl.help_secciones():
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
        for titulo, _ in ccl.help_secciones():
            self.assertIn(titulo, plano)

    def test_render_documenta_las_teclas_de_accion(self):
        plano = self._texto_completo()
        for tecla in ("Ctrl-R", "Ctrl-N", "Ctrl-P", "Ctrl-T", "?", "enter", "esc"):
            self.assertIn(tecla, plano, f"{tecla} deberia estar documentada")

    def test_documenta_como_copiar(self):
        """Con el raton activo la seleccion normal no funciona: hay que decir como."""
        plano = self._texto_completo()
        for pista in ("⌘C", "⌥", "--list"):
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
        sigue = ccl.t("ayuda_sigue").split()[0]      # "sigue" / "next"
        ultima = ccl.ANSI_RE.sub("", ccl.render_help(110, 24, len(paginas) - 1))
        self.assertNotIn(sigue, ultima)
        primera = ccl.ANSI_RE.sub("", ccl.render_help(110, 24, 0))
        self.assertIn(sigue, primera)

    def test_una_sola_pagina_no_habla_de_paginas(self):
        plano = ccl.ANSI_RE.sub("", ccl.render_help(110, 200))
        # con el numero: en español "media página" contiene la palabra suelta
        self.assertNotIn(ccl.t("ayuda_pagina", i=1, n=2), plano)
        self.assertIn(ccl.t("ayuda_volver"), plano)

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
        # en LOS DOS idiomas: una accion en una letra suelta es un fallo de diseño
        # independientemente de como se llame la tecla en la ayuda
        for titulo, filas in ccl.HELP_EN + ccl.HELP_ES:
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
        self.assertIn(ccl.t("hace_min", n=2), plano)

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
        pos = lambda l: ccl.ANSI_RE.sub("", l).index(ccl.t("hace_min", n=2))
        self.assertEqual(pos(corto), pos(largo))

    def test_nombre_muy_largo_se_recorta_sin_romper_columnas(self):
        linea = ccl.main_line(self.r(name="x" * 200))
        self.assertLess(ccl.vis(linea), 120)


if __name__ == "__main__":
    unittest.main(verbosity=2)
