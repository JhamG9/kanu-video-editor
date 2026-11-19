# Kanu · editor de videos para stock

Editor local para corregir el color, quitar el ruido, cortar y exportar videos para stock.

## Abrir
Doble clic en **Abrir editor.command**. Se abre en el navegador (http://localhost:8765).
Para cerrarlo, cierra la ventana de Terminal.

## Carpetas
- `Videos/`: pon aquí los originales. Nunca se modifican.
- `ajustes/`: un `.json` por clip con su color, ruido y cortes. Claude y el editor usan el mismo archivo.
- `videos subir/`: los finales listos para subir al banco de stock (C0253.mp4…). Es la opción marcada por defecto al exportar.
- `Exportados/<formato>/`: pruebas y otros formatos.
- `.cache/`: fotogramas y LUTs temporales. Se puede borrar.

## Subir videos (desde el editor)
1. Pulsa **⇪ Subir** (o suelta los videos en cualquier parte del editor).
2. Arrastra los videos. Ponle un nombre a la tanda si quieres.
3. Marca lo que aplique: **ya viene estable** (trípode, dron, gimbal: no se estabiliza), **conservar colores cálidos**
   (amanecer o atardecer), **sin ralentizar**, y la duración de los clips.
4. **Nota para Claude** (opcional): lo que no cabe en las opciones ("el tercero tiene un golpe en el segundo 8").
   Queda guardada en `tandas/` y aparece en la corrección de cada clip.
5. **Subir y procesar**: Kanu corrige y exporta todo a `videos subir/`. Lo ves avanzar en **Cola**.
   **Solo subir** copia los videos sin procesarlos.

## Tanda nueva para stock (lo hace Claude)
1. Copia los videos nuevos a `Videos/`.
2. Dile a Claude: "procesa los videos nuevos para stock".
3. Claude ejecuta `cd backend && .venv/bin/python -m kanu.cli stock`, que hace todo en un paso con cada clip que aún no tiene su final:
   color natural, ruido, estabilización (la que pida cada toma, normalmente Media o Fuerte), enderezado,
   cortes de 12 a 14 s y exportación 4K H.264 sin audio a `videos subir/`.
4. Tú revisas los finales. Si alguno no te gusta, ábrelo en el editor, ajústalo y vuelve a exportarlo.
   Los clips que ajustaste a mano no se vuelven a corregir automáticamente.

Los temporales de estabilización (~3.5 GB por clip) se borran solos al terminar cada clip.

1. **✦ Corregir todo**: Claude analiza cada clip y aplica una corrección natural para stock.
2. Revisa con **Dividido** (antes y después). Si algo no te gusta, mueve los controles. Doble clic en un control lo pone en 0.
   - Debajo de la línea de tiempo están los botones para reproducir: ⏮ inicio, ↺ 5 s atrás, ▶/⏸, 5 s ↻ adelante, 🔁 repetir y 🔇 sonido. El color se aplica mientras corre el video.
   - Teclas: **Espacio** o **K** reproduce/pausa, **J**/**L** 5 s atrás/adelante, **Inicio** vuelve al principio, ← → 1 s.
   - La primera vez que reproduces un clip tarda unos 10 s en prepararlo (se guarda en `.cache/proxy`).
3. **✓ Aprobar** los que estén bien.
4. **Exportar…**: elige los clips y los formatos.

### Estabilización
Se hace con Gyroflow (gratis, instalado en Aplicaciones). La corrección automática mide la vibración de todo el clip (el temblor rápido y el vaivén lento de grabar a mano) y elige el nivel: Apagada, Suave, Media o Fuerte. Para stock la toma debe parecer de trípode, así que a mano lo normal es Media o Fuerte. Subir el nivel casi no recorta más (Gyroflow ajusta el zoom solo).
- **Automático**: usa el giroscopio que graba la cámara (Sony) y, si el archivo no lo trae (dron, celular), analiza la imagen como el Warp Stabilizer de Premiere.
- La estabilización recorta alrededor de un 10 % para no mostrar bordes.
- **▶ Comparar antes / después** (panel derecho): reproduce el original y el estabilizado lado a lado y sincronizados, con cuadrícula y opción a 0.5× para notar la vibración. La primera vez tarda ~1 min por clip.
- Cada clip estabilizado genera un intermedio de unos 2.5 GB en `.cache/`. Usa **Cola → Liberar espacio** cuando termines.

### Enderezar
En **Enderezar** (panel derecho):
- **✦ Auto** (al lado del título): Claude mide la inclinación con las líneas rectas de la imagen (edificios, postes) y corrige la perspectiva de grabar mirando hacia abajo. En paisajes sin líneas rectas no toca nada. **✦ Corregir todo** también lo hace.
- **📐 Trazar línea recta**: dibuja una línea sobre algo que debería estar recto (horizonte, edificio, poste) y el clip se gira solo. Sirve con líneas horizontales o verticales.
- O mueve **Ángulo** (doble clic lo pone en 0) y afina con los botones de 0.1°.
- Al girar se recorta un poco para que no aparezcan bordes (con 2° alrededor de un 6 %). El visor muestra exactamente el encuadre que se exporta.

### Manchas del sensor (polvo)
Si una mancha difusa aparece en el mismo lugar en todo el video:
1. En **Manchas del sensor** (panel derecho) pulsa **◎ Marcar mancha**. El visor muestra el original sin girar.
2. Haz **clic justo encima** de la mancha. Kanu encuentra su centro y su tamaño (tarda unos segundos).
   Si quieres, arrastra el círculo para moverlo o su punto para agrandarlo: Kanu la vuelve a medir.
3. Pulsa **✓ Listo**. En ~1 min el visor muestra el clip sin manchas; la exportación también sale limpia.

Cómo funciona: el polvo no tapa la imagen, la oscurece un poco. Kanu mide cuánto y le devuelve esa luz,
sin inventar píxeles. Se hace antes de estabilizar (la mancha está fija en el sensor) y la estabilización
sigue usando el giroscopio y el lente del original. No sirve para objetos opacos (un pájaro, un logo).

### Cielo (superblancos)
La Sony graba por encima del blanco normal. El editor recupera ese detalle en el cielo automáticamente.

### Cortes para stock: sacar el máximo de clips
- Clips de **12 a 14 s**.
- Si ralentizar un poco permite sacar un clip más, se ralentiza lo mínimo necesario. Por defecto el máximo es 1.2×.
- Lo que sobra se reparte en partes iguales.
- Se ralentiza **sin inventar fotogramas**: el material de 59.94p se exporta a 50p (1.2×) o a 29.97p (2×), con los mismos fotogramas reales.

| Original | Resultado (máx. 1.2×) |
|---|---|
| 10 s | 1 × 12 s a 50p |
| 16 s | 1 × 16 s a 59.94p |
| 22 s | 2 × 13.2 s a 50p |
| 32 s | 3 × 12.8 s a 50p |
| 40 s | 4 × 12 s a 50p |

### Cortador por tramos
Para quitar algo de en medio del clip (un golpe, alguien que pasa, un movimiento brusco):
1. Ve al punto y pulsa **✂ Cortar aquí** (tecla **C**). Aparece una barra con los tramos encima de la línea de tiempo.
2. **Clic en un tramo** lo descarta (rayado) o lo vuelve a usar. **Clic derecho** lo une con el siguiente.
3. Cada tramo que uses sale como su propio clip. Si es largo, se divide en clips de 12 a 14 s como siempre;
   si quieres el tramo exacto, desmarca "Sacar el máximo de clips".
**Quitar cortes** vuelve al clip entero.

Todo se cambia por clip en "Cortes para stock": la duración mínima y máxima, y si ralentizar nunca, hasta 1.2× o hasta 2×.

## Mi estilo de color (⚙ Ajustes)
Kanu puede aprender cómo editas tú:
1. Abre **⚙** (arriba a la derecha) → **Mi estilo de color**.
2. Suelta tus videos **Originales** (sin editar) y tus **Editados** con el **mismo nombre**. Se guardan en `estilo/`.
   Kanu muestra qué pares están completos. Con 20–30 pares variados (sol, neblina, ciudad, dron…) ya aprende bien.
3. **✦ Aprender mi estilo** (unos 20 s por video, en segundo plano).
4. Con **Usar mi estilo** encendido, la corrección automática toma los colores de cómo editaste tus videos
   más parecidos (lo dice en «Corrección automática»). Los editados pueden estar recortados: Kanu los ubica solo.
- **Sin originales**: sube solo tus editados. Kanu toma lo que se repite en todos (negros, contraste, saturación);
  aprende menos que con pares, pero nunca empeora la corrección.
- **Tus ajustes en Kanu cuentan solos**: cada clip que ajustas a mano o apruebas es un ejemplo perfecto (Kanu tiene
  el original y sabe qué moviste). Pulsa «Volver a aprender» de vez en cuando. Con pocos ejemplos Kanu se acerca
  a tu estilo con prudencia; cuantos más, más se parece.
- **Mi LUT** (opcional): sube tu preset como `.cube` y Kanu lo aplica después de su corrección, en el visor y al exportar.
- **Borrar todo mi estilo**: deja Kanu limpio (para empezar de nuevo o regalarlo). Tus videos y finales no se tocan.

## Desde la terminal
```
cd backend && .venv/bin/python -m kanu.cli stock                # tanda completa → videos subir/ (solo los nuevos)
cd backend && .venv/bin/python -m kanu.cli stock --probar       # muestra qué haría sin exportar
.venv/bin/python -m kanu.cli auto                 # corrige todos
.venv/bin/python -m kanu.cli export 4k_h264       # exporta todos (4k_hevc10, 4k_prores, 1080_h264, vertical_h264)
.venv/bin/python -m kanu.cli estado
.venv/bin/python -m kanu.cli limpiar              # libera el espacio de .cache
```
