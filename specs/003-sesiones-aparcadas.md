---
capacidad: parked-sessions
estado: implementada
modo: retroactivo
rutas:
  - ccl
  - test_ccl.py
  - CLAUDE.md
  - README.md
  - README.es.md
ultima_verificacion_commit: ddcfac4
ultima_verificacion_fecha: 2026-11-09
---

# 003 · Sesiones aparcadas en un job de fondo

> **Implementada** el 2026-11-09, sin versión publicada todavía. Se escribió antes del código, con
> el diseño aprobado por el usuario («si arregla»), y se reconcilió al terminar: salió como se
> diseñó, sin desviaciones.

## Qué pasa

> «¿Por qué dice BACKGROUND?» … «Pero sí existe un iTerm2 para esa sesión.»

Claude Code puede **aparcar** una sesión interactiva: su conversación sigue en un *job* de
fondo, un proceso nuevo con otro `sessionId`, y la pestaña de iTerm se queda con el proceso
original. Verificado el 2026-11-09 con Claude Code 2.1.319, en la máquina del usuario:

| | La pestaña | El job |
|---|---|---|
| Proceso | pid 2323, `claude --resume …` en `ttys117` (iTerm, ventana 483892, pestaña 10) | pid 58841, `claude bg-spare` en `ttys000`, que **no** es de iTerm: cuelga de `claude bg-pty-host` |
| `sessionId` | `a5bcbbaf-…` | `5a59d1f0-…` |
| `claude agents --json` | **No sale** | `kind: "background"`, `id: "5a59d1f0"`, `state: "blocked"` |
| `~/.claude/sessions/<pid>.json` | `"parkedJobId": "5a59d1f0"`, `kind: "interactive"`, versión 2.1.292 | `"jobId": "5a59d1f0"`, `kind: "bg"`, versión 2.1.319 |
| Transcript | 22 MB, escrito por última vez a las 19:11 | Nace a las 18:10 con un **resumen compactado** de la otra (`isCompactSummary`, `logicalParentUuid`): es su continuación |

El job lo lanzó la propia pestaña (`daemon run --spawned-by {"pid": 2323}`). Por qué se aparcó
no se sabe; no hace falta para arreglar lo que sigue.

## Qué se rompe en `ccl`

1. **La fila del job dice BACKGROUND y `Enter` no lleva a ningún sitio:** su tty es del proceso
   de fondo, no de iTerm.
2. **La conversación de la pestaña sale como muerta.** No está en el registro, así que:
   - `--saved` la pinta en gris, como «aún no ha vuelto»;
   - `Enter` sobre esa fila gris, `--restore` y `--recent` la **reanudarían en otra pestaña**:
     un segundo proceso sobre una conversación que sigue abierta en la pestaña 10.

## Comportamiento

| # | Requisito |
|---|---|
| R1 | La fila del job se queda como está (su estado, su número, su grupo BACKGROUND), pero **su terminal es la de la pestaña aparcada**: `Enter` y el doble clic llevan a la pestaña de iTerm, y desaparece el ⚠. |
| R2 | La conversación aparcada cuenta como **viva** en todo lo que decide eso: `--saved` no la pinta en gris, `--restore` no la reabre, `--recent` no la lista. |
| R3 | No se enseña una segunda fila para la pestaña: el job **es** esa conversación (la continúa). |
| R4 | Sin jobs de fondo en el registro no se lee nada nuevo: coste cero en el caso normal. |
| R5 | Si el formato de `sessions/<pid>.json` cambia o no se puede leer, `ccl` se comporta como antes de esta spec, sin errores. |

## Cómo

- **`_enlazar_aparcadas(sesiones, cfg)`**, en `get_sessions` por cada cuenta. Si hay sesiones
  con `kind == "background"` e `id`, lista `<cfg>/sessions/`, y lee **solo** los `<pid>.json`
  cuyo pid no está en el registro (las aparcadas son justo las que faltan) y sigue vivo
  (`os.kill(pid, 0)`, sin subproceso). Si uno lleva `parkedJobId` igual al `id` de un job, el
  job se queda con `aparcada` (el `sessionId` de la pestaña) y `_pid_terminal` (su pid).
- **`build`** toma el tty de `_pid_terminal` cuando lo hay, y de ahí salen `ventana` y `tmux`
  como siempre. Los comandos en vuelo (`$N`) siguen contándose en el pid del job, que es quien
  los ejecuta.
- **`ids_vivos(filas)`**: los `sessionId` más los `aparcada`. Lo usan `faltantes`, `--restore` y
  `recent_rows`, que hoy calculan cada uno su conjunto a mano.
- **`--save` no cambia:** guarda la fila del job, con su `sessionId`, en la ventana de la
  pestaña. Es la continuación, así que es lo que hay que reanudar tras un reset.

## Invariantes

- El texto de fuera sigue pasando por `sin_control` (lo hace `build`).
- Cero subprocesos nuevos (`stdin=DEVNULL` sigue cubriendo todos).
- Lo de la conversación (nota, pausa, escritorio) sigue yendo por el `sessionId` de la fila.

## Criterios de aceptación

| # | Criterio | Cómo se verifica |
|---|---|---|
| CA1 | Un job con su `<pid>.json` aparcado y vivo queda enlazado; con el pid muerto, con el pid presente en el registro, sin `parkedJobId`, con JSON roto o sin carpeta `sessions/`, no. | `test_ccl.py`, con un directorio temporal y el pid del propio test como «vivo». |
| CA2 | Sin jobs de fondo no se lista `sessions/`. | `test_ccl.py`. |
| CA3 | `build` da a la fila del job el tty y la ventana de la pestaña; `$N`, del job. | `test_ccl.py`. |
| CA4 | `faltantes`, `--restore` (vía `ids_vivos`) y `recent_rows` no tratan como muerta la conversación aparcada. | `test_ccl.py`. |
| CA5 | Con los datos reales del 2026-11-09: la fila del job lleva a la pestaña 10 y `--saved` deja de enseñar la gris. | A mano, sin pulsar `Enter` (consultando la fila). |

**Verificación** (2026-11-09): CA1-CA4 en verde, 400 tests en `test_ccl.py`; los de CA3 y CA4
fallan si `build` vuelve a usar el tty del job o `faltantes` los `sessionId` a secas (comprobado
mutándolos). CA5 con los datos reales: la fila del job (número 5) quedó con `tty: ttys117` y
`ventana: ('iTerm2', '483892', 10)`, y la gris «Coordinador de Depliegues NewCariAI» dejó de salir
entre las 18 que faltan de la foto.

## Dónde quedó

| Pieza | Qué |
|---|---|
| `_enlazar_aparcadas`, `_proceso_vivo` | El enlace, llamado desde `get_sessions` para cada cuenta. |
| `ids_vivos` | El conjunto de «vivas» que usan `faltantes`, `--restore` y `recent_rows`. |
| `build` | `tty` de `_pid_terminal`; la fila lleva `aparcada`. |
| `TestSesionesAparcadas` y un caso en `TestRecuperables` | 10 tests. |
| `CLAUDE.md` | Una fila en la tabla de contratos externos y el párrafo de las aparcadas. |
| README (los dos) | Una entrada en *Known limitations*: por qué dice BACKGROUND. |

## Fuera de alcance

- **Que el job cuente como ESPERANDO.** Trae `state: "blocked"`, pero no se sabe si significa
  «te espera»; hasta saberlo sigue en BACKGROUND, fuera de `-w`/`⌥N`.
- **Saber por qué se aparcó** una sesión.
- **Jobs de fondo sin pestaña** (lanzados directamente en segundo plano): siguen como hoy.

## Riesgos

- **`sessions/<pid>.json` es un formato interno sin documentar.** Va a la tabla de contratos
  externos de `CLAUDE.md`; si cambia, R5.
- **Un pid reutilizado.** Si la pestaña muere sin borrar su `<pid>.json` y otro proceso hereda el
  pid, el job apuntaría a una pestaña ajena. Hace falta que además el job siga vivo con ese
  mismo `id`; se acepta.
- **No está verificado que `claude --resume` acepte el `sessionId` de un job** (`--save` lo
  guardaría así). No se puede probar sin abrir una segunda copia de la conversación.
