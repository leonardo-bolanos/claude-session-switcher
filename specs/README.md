# Specs

Especificaciones de los cambios de `ccl` que merecen diseño antes de tocar código. Lo que ya está
construido y sus trampas viven en `CLAUDE.md` y en los skills de `.claude/skills/`; aquí va lo que
**se va a construir**, y por qué.

## Convención

- Un archivo por spec, plano: `specs/<nnn>-<slug>.md`, numeración de tres cifras que no se
  reutiliza. Antes de numerar, mira `git worktree list` y `git branch -a`: una rama puede tener
  ya ese número sin commitear.
- Prosa en español, identificadores en su forma original — mismo criterio que `CLAUDE.md`.
- Frontmatter con `estado`, las `rutas` que toca y el commit contra el que se verificó. Las anclas
  van como `archivo` + nombre de función, no como número de línea: `ccl` cambia a diario y las
  líneas envejecen en una semana.
- Toda afirmación sobre el código o sobre datos reales está verificada; lo que no se pudo
  comprobar va a *Decisiones abiertas*.
- **Al fusionar, la spec se reescribe en modo retroactivo**: se corrige lo que se construyó
  distinto y se anota lo descartado y por qué. Si no, queda afirmando un diseño que no existe.

## Estados

| Estado | Significa |
|---|---|
| `borrador` | Escrita, con decisiones abiertas pendientes |
| `aprobada` | Decisiones cerradas; se puede implementar |
| `implementada` | Fusionada y reconciliada con el código |
| `descartada` | No se hizo; se conserva por el razonamiento |

## Índice

| # | Spec | Estado |
|---|---|---|
| 001 | [Vista por proyecto](001-vista-por-proyecto.md) | implementada (1.4.0) |
| 002 | [Orden de las pestañas a mano](002-orden-de-pestañas.md) | implementada (1.5.0) |
| 003 | [Sesiones aparcadas en un job de fondo](003-sesiones-aparcadas.md) | implementada (sin publicar) |
