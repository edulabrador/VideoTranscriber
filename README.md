<div align="center">

# VideoTranscriber

**Convierte vídeos de YouTube, Instagram, TikTok y Twitter (X) en texto desde tu ordenador.**

[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-TypeScript-149eca.svg)](https://react.dev/)

</div>

VideoTranscriber descarga únicamente el audio necesario y lo transcribe mediante
[faster-whisper](https://github.com/SYSTRAN/faster-whisper). El reconocimiento se
ejecuta localmente. No necesita claves de API ni una suscripción.

## Funciones

- Enlaces de YouTube, Instagram, TikTok, X y Twitter, y de cualquier otro sitio de
  vídeo admitido por yt-dlp (Vimeo, Twitch, Dailymotion, SoundCloud...).
- Varios enlaces o archivos a la vez: se procesan en una cola por orden de llegada
  que muestra cuántos trabajos hay por delante.
- Archivos locales de audio y vídeo.
- Aceleración mediante GPU NVIDIA CUDA, con retorno a CPU cuando corresponda.
- Perfiles Rápido, Equilibrado y Preciso para elegir entre velocidad y exactitud.
- Calidad de descarga configurable para reducir tiempo y consumo de red.
- Ajuste automático y conservador del tamaño de lote según la VRAM disponible.
- Cola de una sola transcripción GPU para evitar saturar la memoria gráfica.
- Los modelos recientes se mantienen cargados para cambiar de perfil sin esperar
  y se liberan tras 15 minutos sin uso.
- Opciones avanzadas: idioma del audio, vocabulario (nombres propios, siglas),
  traducción al inglés y marcas de tiempo por palabra.
- Identificación de hablantes («Hablante 1», «Hablante 2»...) para entrevistas,
  reuniones y pódcast, en local y sin cuentas ni tokens. Ver más abajo.
- Reutilización inmediata de transcripciones anteriores para el mismo enlace y perfil.
- Progreso basado en bytes descargados y segundos de audio procesados.
- Estimación del tiempo restante y cancelación de trabajos.
- Exportación a TXT por párrafos, Markdown con tiempos, subtítulos SRT y VTT
  legibles (máximo dos líneas de 42 caracteres y 6 segundos) y JSON.
- En vídeos de YouTube, cada marca de tiempo abre el vídeo en ese momento.
- Los trabajos fallidos quedan en el historial con su error y se pueden reintentar.
- Historial local. Las dos últimas entradas permiten desplegar el texto completo.
- Búsqueda en todos los textos del historial y apertura de resultados antiguos.
- Recuperación del último trabajo al recargar la página y avisos de desconexión.
- Opción para volver a transcribir sin reutilizar el resultado guardado.
- Interfaz en español, modo oscuro y diseño adaptable.
- Limpieza automática de los archivos temporales.

## Iniciar en Windows sin Codex

Codex no es necesario para usar el programa.

### En este ordenador

Haz doble clic en:

**`Iniciar VideoTranscriber.bat`**

El iniciador comprueba los requisitos, instala lo que falte dentro del proyecto,
arranca los tres servicios y abre automáticamente:

[http://127.0.0.1:5187](http://127.0.0.1:5187)

La ventana de terminal debe permanecer abierta. Para detener la aplicación, ciérrala
o pulsa `Ctrl+C`.

### En otro ordenador

Instala una sola vez:

- [Git](https://git-scm.com/download/win)
- [Node.js LTS](https://nodejs.org/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- El controlador NVIDIA actualizado si se va a utilizar una GPU NVIDIA.

El iniciador utiliza pnpm directamente si está instalado. Si no lo encuentra,
lo prepara automáticamente mediante Corepack, incluido con Node.js en este equipo.

Después descarga el proyecto:

```powershell
git clone https://github.com/edulabrador/VideoTranscriber.git
cd VideoTranscriber
```

Por último, haz doble clic en `Iniciar VideoTranscriber.bat`.

La primera preparación descarga las dependencias. La primera transcripción descarga
también el modelo de voz. Puede ocupar varios gigabytes y las siguientes ejecuciones
reutilizan todo lo descargado.

## Inicio manual

Si prefieres utilizar la terminal:

```powershell
pnpm dev
```

Servicios locales:

| Servicio | Dirección |
|---|---|
| Aplicación web | `http://127.0.0.1:5187` |
| API | `http://127.0.0.1:8187` |
| Descargador Cobalt | `http://localhost:9187` |

También existe una interfaz de terminal:

```powershell
uv run --project backend transcriber "https://www.instagram.com/reel/XXXXX/"
uv run --project backend transcriber video.mp4 --profile precise --language es --prompt "Kubernetes, OpenAI"
uv run --project backend transcriber entrevista.mp3 --diarize --speakers 2 --word-timestamps
uv run --project backend transcriber --clean-orphans        # lista carpetas de output/ sin historial
uv run --project backend transcriber --clean-orphans --yes  # y las borra
```

## ¿Se puede ejecutar directamente desde GitHub?

No puede ejecutarse la aplicación completa dentro de GitHub Pages. Pages solo sirve
archivos estáticos y no admite el backend Python, la descarga de vídeos ni el uso de
la GPU local.

GitHub Actions sí puede ejecutar pruebas automáticas, pero sus máquinas son temporales
y no están pensadas para mantener esta aplicación disponible como servicio web.

Para ofrecerla públicamente habría que alojar el backend en un servidor externo. Eso
añadiría coste, límites, gestión de privacidad y probablemente una GPU de pago. Para
uso personal, la ejecución local es más privada, barata y rápida.

## Configuración

La configuración local está en `.env`. Este archivo nunca se sube a GitHub.

| Variable | Valor habitual | Función |
|---|---|---|
| `COOKIES_FILE` | vacío | Archivo `cookies.txt` para publicaciones que exigen sesión |
| `COBALT_API_URL` | `http://127.0.0.1:9187` | Descargador local opcional. Solo se usa si yt-dlp falla con TikTok o X |
| `MODEL_SIZE` | `auto` | Modelo de faster-whisper |
| `DEVICE` | `auto` | Selección entre `cuda` y `cpu` |
| `COMPUTE_TYPE` | `auto` | Precisión de cálculo |
| `BATCH_SIZE` | `0` | `0` ajusta los lotes automáticamente según la VRAM |
| `BEAM_SIZE` | `1` | Prioriza velocidad. `5` puede mejorar precisión y tarda más |
| `MAX_CACHED_MODELS` | `2` | Modelos que se conservan entre trabajos. En CUDA solo el activo ocupa VRAM |
| `MODEL_IDLE_UNLOAD_SECONDS` | `900` | Libera los modelos tras ese tiempo sin uso. `0` los mantiene |
| `DIARIZATION_THRESHOLD` | `0.5` | Agrupación de voces cuando no se indica el número de hablantes. Más alto, menos hablantes |

La configuración optimizada de este ordenador está guardada únicamente en su `.env`
local. El repositorio mantiene valores automáticos compatibles con otros equipos.

### Perfiles y rendimiento

- **Rápido** usa el modelo `small` y prioriza terminar antes.
- **Equilibrado** usa la configuración local. Es la opción recomendada para uso normal.
- **Preciso** usa `large-v3`, una búsqueda más exhaustiva y un lote limitado para proteger la VRAM.

La calidad Compacta descarga audio de menor tamaño. Equilibrada ofrece un término
medio y Máxima conserva la mejor fuente disponible. Una transcripción ya guardada
se reutiliza cuando coinciden el enlace y el perfil, siempre que la calidad empleada
sea igual o superior a la solicitada.

La aplicación no modifica frecuencias, voltajes, ventiladores ni límites de potencia.
CUDA utiliza los mecanismos normales del controlador NVIDIA. Aun así, cualquier
tarea intensiva puede elevar temporalmente el uso y la temperatura del equipo.

### Identificación de hablantes

Activa **Identificar quién habla** en las opciones avanzadas, o usa `--diarize` en la
terminal. Cada fragmento del texto se etiqueta como «Hablante 1», «Hablante 2»...,
numerados por orden de aparición. Las etiquetas aparecen en la vista, al copiar y en
todas las exportaciones: párrafos con nombre en TXT y Markdown, `[Hablante 1]` al
cambiar de turno en SRT y etiquetas de voz `<v Hablante 1>` en VTT.

Se basa en [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) con el modelo de
segmentación de pyannote 3.0 (licencia MIT) y un modelo de huella de voz WeSpeaker
entrenado con VoxCeleb. Funciona con ONNX Runtime, sin PyTorch ni token de Hugging
Face. La primera vez descarga unos 33 MB en `models/diarization/` y comprueba su
huella SHA-256.

Consejos:

- **Indica el número de hablantes si lo sabes.** Es mucho más fiable. Sin él, el
  número se estima con `DIARIZATION_THRESHOLD`, y en una grabación de prueba con
  cuatro voces el valor por defecto detectó solo dos.
- Combínalo con **marcas por palabra** para que los cambios de turno dentro de una
  misma frase se separen correctamente.
- Se ejecuta en CPU: cuenta con unos 5 a 10 segundos por minuto de audio en un
  procesador de cuatro núcleos.
- Las voces que se solapan se asignan a quien más habla en ese tramo.

### Fiabilidad y recuperación

El progreso distingue consulta del vídeo, descarga del audio, preparación del archivo,
espera en cola, carga o descarga del modelo y transcripción. En YouTube se muestra
el idioma y formato de la pista original cuando se identifica con confianza; en caso
contrario se avisa de que se usa la pista por defecto.

La casilla **Volver a transcribir** ignora la caché. Los resultados anteriores a una
actualización del procesamiento, o creados con otro modelo o búsqueda, no se reutilizan
automáticamente. Siguen disponibles para abrir y exportar desde el historial.

Al recargar el navegador se recupera el último trabajo. Si se pierde la conexión,
la interfaz avisa y reintenta. Los resultados terminados se recuperan del disco
tras reiniciar el servidor. Los trabajos interrumpidos por el reinicio no se reanudan:
la interfaz indica que hay que volver a enviarlos.

En el historial puedes buscar por título, enlace o texto, abrir cualquier resultado,
copiarlo y exportarlo. Al eliminar una entrada puedes elegir si se borran también
sus archivos. La eliminación de archivos requiere confirmación.

Las subidas admiten hasta **512 MiB** por defecto, configurable con `MAX_UPLOAD_BYTES`
en `.env`. El servidor genera el nombre del archivo y elimina las subidas incompletas.

Los instaladores fijan Cobalt al commit de `scripts/cobalt-ref.txt`. Si una instalación
existente usa otro commit, se detienen para que puedas revisar los cambios antes de
actualizarla. No actualizan ese componente automáticamente.

## Privacidad y archivos

La transcripción se realiza en el ordenador. Los vídeos solo se solicitan a la
plataforma original o al descargador Cobalt que se ejecuta localmente.

Estos directorios no se suben a GitHub:

- `models/`: modelos de reconocimiento.
- `output/`: textos y subtítulos generados.
- `temp/`: audio temporal.
- `backend/data/`: historial.
- `.env`: configuración privada.

Los archivos temporales se eliminan al terminar o cancelar un trabajo.

## Contenido que requiere iniciar sesión

Algunas publicaciones pueden exigir una sesión válida. Exporta las cookies de tu
navegador en formato Netscape y configura su ruta:

```env
COOKIES_FILE=C:\ruta\a\cookies.txt
```

No compartas ni subas ese archivo.

## Estructura

```text
apps/web/          Interfaz React, TypeScript y Tailwind
backend/backend/   API FastAPI y motor de transcripción
backend/tests/     Pruebas del backend
scripts/           Preparación para macOS y Linux
services/cobalt/   Dependencia descargada localmente. No se copia al repositorio
models/            Modelos locales
output/            Transcripciones guardadas
temp/              Archivos temporales
```

## Desarrollo y comprobaciones

```powershell
pnpm --filter web build
uv run --project backend --extra dev ruff check backend/backend backend/tests
uv run --project backend --extra dev pytest backend/tests -q
uv run --project backend --extra dev mypy --config-file backend/pyproject.toml backend/backend
pnpm --dir apps/web test
pnpm --dir apps/web lint
```

GitHub Actions ejecuta estas comprobaciones y la compilación web en cada push y PR.
Las pruebas de red son opcionales y están desactivadas por defecto.

### Tiempos de procesamiento

En «Detalles de transcripción» se muestran los segundos de descarga o preparación
del archivo, espera en cola, carga del modelo, análisis y transcripción. Se guardan
también en el JSON exportado y en el registro del servidor. Los resultados antiguos
siguen funcionando, pero no tienen mediciones. Un resultado reutilizado conserva
los tiempos de su procesamiento original, no mide el acceso a la caché.

`audio_analysis` mide la llamada inicial al motor. `transcription` mide el consumo
de sus segmentos, incluida cualquier decodificación diferida por el motor.
`processing_total` va desde el inicio del procesamiento hasta antes de escribir los
archivos de exportación y el historial. No incluye la subida inicial ni la limpieza final.

La preparación de archivos admite cancelación y tiene un máximo de 600 segundos,
ajustable con `AUDIO_PREPARATION_TIMEOUT_SECONDS`. Se mantiene la normalización a
WAV mono de 16 kHz para preservar la compatibilidad con formatos de entrada.

Para comparar una primera ejecución con el modelo residente en memoria:

```powershell
uv run --project backend python scripts/benchmark.py "C:\ruta\audio.wav" --runs 2
```

El benchmark no añade entradas al historial personal y borra sus propios archivos
de salida al acabar. Usa la configuración y los modelos locales de la aplicación.

La documentación técnica adicional está en [docs/DEV_GUIDE.md](docs/DEV_GUIDE.md).

## Tecnologías y licencias

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper), reconocimiento de voz.
- [CTranslate2](https://github.com/OpenNMT/CTranslate2), ejecución optimizada en CPU y CUDA.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp), descarga de medios.
- [Cobalt](https://github.com/imputnet/cobalt), descarga local alternativa para TikTok y X cuando yt-dlp falla. Se instala como proyecto separado y conserva su licencia AGPL-3.0.
- [PyAV](https://github.com/PyAV-Org/PyAV), lectura de audio y vídeo.
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), identificación de hablantes con modelos de [pyannote](https://github.com/pyannote/pyannote-audio) y [WeSpeaker](https://github.com/wenet-e2e/wespeaker).

El código propio de VideoTranscriber utiliza la licencia [MIT](LICENSE).

## Dependencias revisadas de Cobalt

Usa Node 20.19 o posterior y pnpm 11.25.0. Los instaladores aplican `scripts/cobalt-security.patch` sobre el commit fijado, sin descargar una rama cambiante. El parche solo actualiza el bloqueo y la configuración de dependencias; conserva las versiones nativas existentes. Si hay cambios locales incompatibles, el proceso se detiene antes de sobrescribirlos.

En una instalación existente, con los procesos parados y tras actualizar el código, ejecuta en este orden `pnpm install --frozen-lockfile`, `node scripts/apply-cobalt-security.mjs`, `pnpm --dir services/cobalt install --frozen-lockfile` y `uv sync --project backend --locked`. Después puedes reiniciar la aplicación. No se cambian credenciales ni datos operativos.

El [aviso de `braces`](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) fue retirado el 23/10/2026 porque no se considera explotable en la práctica. Ya no se registra como vulnerabilidad pendiente.


### Acceso a los datos

El backend solo atiende a este ordenador. Comprueba la dirección del cliente, Host y Origin, y rechaza los encabezados de reenvío detectables. La interfaz y las llamadas locales habituales conservan su funcionamiento. Las peticiones remotas directas al historial, las transcripciones o las descargas se rechazan. Un túnel TCP que oculte el origen puede parecer un cliente local. Para compartir una instancia debe diseñarse una capa de autenticación explícita; no se debe ocultar el origen remoto detrás de un proxy local.
