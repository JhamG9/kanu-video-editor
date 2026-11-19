#!/bin/bash
# Arma el instalador de Kanu: Kanu-<versión>.dmg en la raíz del proyecto.
# La app trae dentro Python, las librerías, ffmpeg/ffprobe y el motor; los datos van a ~/Movies/Kanu.
# Gyroflow no se incluye: la app avisa si falta.
#
# Uso: tools/app/empaquetar.sh        (descarga Python y ffmpeg la primera vez, en build/descargas)
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT="$PWD"

PY_TAG="20261110"
PY_FILE="cpython-3.13.18+${PY_TAG}-aarch64-apple-darwin-install_only_stripped.tar.gz"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_TAG}/${PY_FILE//+/%2B}"
FF_URL="https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release"

VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' backend/pyproject.toml)
DL="$ROOT/build/descargas"
APP="$ROOT/build/Kanu.app"
RES="$APP/Contents/Resources"
DMG="$ROOT/Kanu-$VERSION.dmg"

echo "▸ Kanu $VERSION"

# 1. Descargas (una sola vez)
mkdir -p "$DL/python" "$DL/ffmpeg"
if [ ! -f "$DL/python/python.tar.gz" ]; then
  echo "▸ Descargando Python…"
  curl -fsSL -o "$DL/python/python.tar.gz" "$PY_URL"
fi
EXPECTED=$(curl -fsSL "https://github.com/astral-sh/python-build-standalone/releases/download/${PY_TAG}/SHA256SUMS" \
  | awk -v f="$PY_FILE" '$2==f {print $1}')
ACTUAL=$(shasum -a 256 "$DL/python/python.tar.gz" | awk '{print $1}')
[ "$EXPECTED" = "$ACTUAL" ] || { echo "✗ El Python descargado no coincide con su suma SHA-256"; exit 1; }
for t in ffmpeg ffprobe; do
  if [ ! -f "$DL/ffmpeg/$t.zip" ]; then
    echo "▸ Descargando $t…"
    curl -fsSL -o "$DL/ffmpeg/$t.zip" "$FF_URL/$t.zip"
  fi
done

# 2. Esqueleto de la app
echo "▸ Armando Kanu.app…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RES/bin" "$RES/kanu/backend" "$RES/kanu/apps" "$RES/licencias"
cp Kanu.app/Contents/Info.plist "$APP/Contents/"
cp Kanu.app/Contents/Resources/Kanu.icns "$RES/"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$APP/Contents/Info.plist"
plutil -replace CFBundleVersion -string "$VERSION" "$APP/Contents/Info.plist"
swiftc -O tools/app/Kanu.swift -o "$APP/Contents/MacOS/Kanu" -framework Cocoa -framework WebKit

# 3. Python + librerías del motor
tar -xzf "$DL/python/python.tar.gz" -C "$RES"          # crea Resources/python
PY="$RES/python/bin/python3"
DEPS=$("$PY" -c 'import tomllib; print("\n".join(tomllib.load(open("backend/pyproject.toml","rb"))["project"]["dependencies"]))')
echo "$DEPS" | tr '\n' '\0' | xargs -0 "$PY" -m pip install -q --no-compile --disable-pip-version-check
rm -rf "$RES/python/share" "$RES/python/include"
find "$RES/python" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$RES/python" -type d \( -name "test" -o -name "tests" -o -name "idlelib" -o -name "tkinter" -o -name "turtledemo" \) \
  -path "*/lib/python3*" -prune -exec rm -rf {} +

# 4. Motor e interfaz
rsync -a --exclude "__pycache__" backend/kanu "$RES/kanu/backend/"
cp backend/pyproject.toml "$RES/kanu/backend/"
rsync -a apps/legacy-ui "$RES/kanu/apps/"

# 5. ffmpeg / ffprobe
for t in ffmpeg ffprobe; do unzip -oq "$DL/ffmpeg/$t.zip" -d "$RES/bin"; done
chmod +x "$RES/bin/ffmpeg" "$RES/bin/ffprobe"

# 6. Licencias
cp LICENSE "$RES/licencias/Kanu-MIT.txt"
cat > "$RES/licencias/ffmpeg.txt" <<'EOF'
Kanu incluye ffmpeg y ffprobe (https://ffmpeg.org), compilados con licencia GPL v3
por Martin Riedl (https://ffmpeg.martin-riedl.de), que publica las fuentes y las
opciones de compilación. Código fuente de FFmpeg: https://ffmpeg.org/download.html
EOF
cp "$RES/python/LICENSE.txt" "$RES/licencias/Python.txt" 2>/dev/null || true

# 7. Firma local (sin cuenta de Apple: macOS pedirá «Abrir» la primera vez)
echo "▸ Firmando…"
codesign --force --deep -s - "$APP"

# 8. .dmg con atajo a Aplicaciones
echo "▸ Creando el .dmg…"
STAGE="$ROOT/build/dmg"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Aplicaciones"
hdiutil create -quiet -volname "Kanu $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"

echo "✓ $(basename "$DMG") ($(du -h "$DMG" | cut -f1)) en la raíz del proyecto"
