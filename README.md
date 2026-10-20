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

- Enlaces de YouTube, Instagram, TikTok, X y Twitter.
- Archivos locales de audio y vídeo.
- Aceleración mediante GPU NVIDIA CUDA, con retorno a CPU cuando corresponda.
- Perfiles Rápido, Equilibrado y Preciso para elegir entre velocidad y exactitud.
- Calidad de descarga configurable para reducir tiempo y consumo de red.
- Ajuste automático y conservador del tamaño de lote según la VRAM disponible.
- Cola de una sola transcripción GPU para evitar saturar la memoria gráfica.
- Reutilización inmediata de transcripciones anteriores para el mismo enlace y perfil.
- Progreso basado en bytes descargados y segundos de audio procesados.
- Estimación del tiempo restante y cancelación de trabajos.
- Exportación a TXT, SRT y JSON.
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
| `COBALT_API_URL` | `http://127.0.0.1:9187` | Descargador local para TikTok y rutas alternativas |
| `MODEL_SIZE` | `auto` | Modelo de faster-whisper |
| `DEVICE` | `auto` | Selección entre `cuda` y `cpu` |
| `COMPUTE_TYPE` | `auto` | Precisión de cálculo |
| `BATCH_SIZE` | `0` | `0` ajusta los lotes automáticamente según la VRAM |
| `BEAM_SIZE` | `1` | Prioriza velocidad. `5` puede mejorar precisión y tarda más |

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

La documentación técnica adicional está en [docs/DEV_GUIDE.md](docs/DEV_GUIDE.md).

## Tecnologías y licencias

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper), reconocimiento de voz.
- [CTranslate2](https://github.com/OpenNMT/CTranslate2), ejecución optimizada en CPU y CUDA.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp), descarga de medios.
- [Cobalt](https://github.com/imputnet/cobalt), descarga local de TikTok y rutas alternativas. Se instala como proyecto separado y conserva su licencia AGPL-3.0.
- [PyAV](https://github.com/PyAV-Org/PyAV), lectura de audio y vídeo.

El código propio de VideoTranscriber utiliza la licencia [MIT](LICENSE).
