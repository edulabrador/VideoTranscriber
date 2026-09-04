<div align="center">

# VideoTranscriber

**Convierte vídeos de Instagram, TikTok y Twitter (X) en texto desde tu ordenador.**

[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-TypeScript-149eca.svg)](https://react.dev/)

</div>

VideoTranscriber descarga únicamente el audio necesario y lo transcribe mediante
[faster-whisper](https://github.com/SYSTRAN/faster-whisper). El reconocimiento se
ejecuta localmente. No necesita claves de API ni una suscripción.

## Funciones

- Enlaces de Instagram, TikTok, X y Twitter.
- Archivos locales de audio y vídeo.
- Aceleración mediante GPU NVIDIA CUDA, con retorno a CPU cuando corresponda.
- Progreso basado en bytes descargados y segundos de audio procesados.
- Estimación del tiempo restante y cancelación de trabajos.
- Exportación a TXT, SRT y JSON.
- Historial local. Las dos últimas entradas permiten desplegar el texto completo.
- Interfaz en español, modo oscuro y diseño adaptable.
- Limpieza automática de los archivos temporales.

## Iniciar en Windows sin Codex

Codex no es necesario para usar el programa.

### En este ordenador

Haz doble clic en:

**`Iniciar VideoTranscriber.bat`**

El iniciador comprueba los requisitos, instala lo que falte dentro del proyecto,
arranca los tres servicios y abre automáticamente:

[http://localhost:5173](http://localhost:5173)

La ventana de terminal debe permanecer abierta. Para detener la aplicación, ciérrala
o pulsa `Ctrl+C`.

### En otro ordenador

Instala una sola vez:

- [Git](https://git-scm.com/download/win)
- [Node.js LTS](https://nodejs.org/)
- pnpm mediante `corepack enable pnpm`
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- El controlador NVIDIA actualizado si se va a utilizar una GPU NVIDIA.

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
| Aplicación web | `http://localhost:5173` |
| API | `http://localhost:8000` |
| Descargador Cobalt | `http://localhost:9000` |

También existe una interfaz de terminal:

```powershell
uv run --project backend transcriber "https://www.instagram.com/reel/XXXXX/"
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
| `COBALT_API_URL` | `http://127.0.0.1:9000` | Descargador local para TikTok y rutas alternativas |
| `MODEL_SIZE` | `auto` | Modelo de faster-whisper |
| `DEVICE` | `auto` | Selección entre `cuda` y `cpu` |
| `COMPUTE_TYPE` | `auto` | Precisión de cálculo |
| `BATCH_SIZE` | `4` | Lotes de GPU. Un valor mayor consume más VRAM |
| `BEAM_SIZE` | `1` | Prioriza velocidad. `5` puede mejorar precisión y tarda más |

La configuración optimizada de este ordenador está guardada únicamente en su `.env`
local. El repositorio mantiene valores automáticos compatibles con otros equipos.

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
uv run --project backend python -m unittest discover -s backend/tests -v
```

La documentación técnica adicional está en [docs/DEV_GUIDE.md](docs/DEV_GUIDE.md).

## Tecnologías y licencias

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper), reconocimiento de voz.
- [CTranslate2](https://github.com/OpenNMT/CTranslate2), ejecución optimizada en CPU y CUDA.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp), descarga de medios.
- [Cobalt](https://github.com/imputnet/cobalt), descarga local de TikTok y rutas alternativas. Se instala como proyecto separado y conserva su licencia AGPL-3.0.
- [PyAV](https://github.com/PyAV-Org/PyAV), lectura de audio y vídeo.

El código propio de VideoTranscriber utiliza la licencia [MIT](LICENSE).
