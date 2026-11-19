#!/bin/bash
# Abre Kanu en el navegador (el motor corre en esta ventana de Terminal; ciérrala para apagarlo).
cd "$(dirname "$0")/backend"
echo "Abriendo Kanu…"
exec .venv/bin/python -m kanu
