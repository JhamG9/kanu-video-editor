#!/bin/bash
# Compila la ventana nativa de Kanu dentro de Kanu.app (icono propio en el Dock).
set -e
cd "$(dirname "$0")"
swiftc -O Kanu.swift -o ../../Kanu.app/Contents/MacOS/Kanu -framework Cocoa -framework WebKit
codesign --force -s - ../../Kanu.app
touch ../../Kanu.app
echo "Kanu.app listo"
