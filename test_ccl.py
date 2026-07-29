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
        self.assertTrue(ccl.ago(iso(hours=3)).startswith("hace "))

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
        orig = ccl.subprocess.run
        ccl.subprocess.run = fake
        try:
            return ccl.get_sessions()
        finally:
            ccl.subprocess.run = orig

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
