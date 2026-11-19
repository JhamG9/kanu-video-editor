# Cómo contribuir a Kanu

¡Gracias por querer mejorar Kanu! Toda mejora entra al proyecto con un pull request (PR),
y el dueño del repositorio lo revisa y lo aprueba antes de unirlo a `main`.

## Pasos

1. Haz un **fork** del repositorio y clónalo en tu Mac.
2. Crea una rama para tu cambio: `git checkout -b mi-mejora`.
3. Prepara el entorno (ver «Desarrollo» en el [README](README.md)) y haz tus cambios.
4. Antes de enviar, comprueba que todo pasa:
   ```bash
   cd backend
   .venv/bin/python -m pytest -q
   .venv/bin/ruff check kanu
   ```
5. Sube tu rama y abre un **pull request** contra `main` explicando:
   - qué cambia y por qué;
   - cómo lo probaste (si toca la imagen, una captura de antes y después ayuda mucho).

## Reglas

- Un PR por mejora. Los PR pequeños se revisan antes.
- Nunca subas videos, LUT ni datos personales; el `.gitignore` ya los excluye.
- Si cambias `tools/app/Kanu.swift`, recompila con `tools/app/build.sh` e incluye el `Kanu.app` nuevo.
- Para ideas grandes o errores, abre primero un **issue** y lo conversamos.

Al enviar un PR aceptas que tu código se publique con la [licencia MIT](LICENSE) del proyecto.
