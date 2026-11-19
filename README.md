# Kanu

Editor de video para stock: corrección de color automática (y con tu estilo), estabilización con Gyroflow,
enderezado, manchas del sensor, cortes de 12–14 s y exportación 4K. Ver `LEEME.md` para el uso.

## Estructura

```
backend/            motor en Python (FastAPI)
  kanu/config.py    rutas de datos y programas (KANU_DATA, KANU_FFMPEG, KANU_GYROFLOW…)
  kanu/core/        algoritmos puros: color (grade), análisis, cortes, manchas, estilo
  kanu/infra/       ffmpeg y Gyroflow
  kanu/services/    biblioteca de clips, vistas previas, exportación, tandas
  kanu/api/         FastAPI: app + routes por dominio
  kanu/cli.py       uso desde terminal (python -m kanu.cli stock)
  tests/            pytest (usan una carpeta de datos temporal)
apps/legacy-ui/     interfaz actual (HTML + JS), servida por el backend
tools/icono/        generador del icono (tucán)
```

Próximas fases: `apps/ui` (React + TypeScript + Vite) y `apps/desktop` (Electron, arranca el backend).

## Desarrollo

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m kanu            # http://localhost:8765  (API en /docs)
.venv/bin/python -m pytest -q       # tests
.venv/bin/ruff check kanu           # linter
```

Requiere ffmpeg (Homebrew) y Gyroflow (en Aplicaciones). Los datos del usuario (`Videos/`, `ajustes/`,
`videos subir/`, `estilo/`…) no van al repositorio.
