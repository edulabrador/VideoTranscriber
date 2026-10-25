import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Optional

import typer

from backend.config import settings
from backend.core.errors import TranscriberError
from backend.core.history import history_store
from backend.core.pipeline import FileSource, URLSource, run_pipeline
from backend.core.transcriber import TranscriptionOptions
from backend.core.validators import is_supported_url

app = typer.Typer(add_completion=False, no_args_is_help=True)

_STAGE_LABELS = {
    "queued": "Esperando turno...",
    "loading_model": "Descargando o cargando el modelo...",
    "downloading": "Descargando vídeo...",
    "extracting_audio": "Preparando el audio...",
    "transcribing": "Transcribiendo audio...",
    "completed": "Transcripción completada.",
}


def _make_stage_printer():
    printed: set[str] = set()

    def on_stage(status: str, _message: str, _progress: int | None = None) -> None:
        label = _STAGE_LABELS.get(status)
        if label and status not in printed:
            typer.echo(label)
            printed.add(status)

    return on_stage


def _copy_to_clipboard(text: str) -> bool:
    try:
        import pyperclip

        pyperclip.copy(text)
        return True
    except Exception:
        pass
    if sys.platform == "darwin":
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
            return True
        except Exception:
            return False
    return False


def _clean_orphans(confirm: bool) -> None:
    orphans = history_store.orphan_outputs()
    if not orphans:
        typer.echo("No hay carpetas de resultados huérfanas.")
        return
    for path in orphans:
        typer.echo(f"  {path}")
    if not confirm:
        typer.echo(f"{len(orphans)} carpetas sin entrada en el historial. Añade --yes para borrarlas.")
        return
    for path in orphans:
        shutil.rmtree(path, ignore_errors=True)
    typer.echo(f"Se borraron {len(orphans)} carpetas.")


@app.command()
def main(
    source: Optional[str] = typer.Argument(
        None, help="Enlace de vídeo (YouTube, Instagram, TikTok, X u otro sitio) o un archivo local"
    ),
    model: str = typer.Option(None, "--model", help="Cambiar el tamaño del modelo Whisper"),
    profile: str = typer.Option(
        "balanced", "--profile", help="Perfil de transcripción: fast, balanced o precise"
    ),
    audio_quality: str = typer.Option(
        "balanced", "--audio-quality", help="Calidad de descarga: compact, balanced o best"
    ),
    language: str = typer.Option(
        None, "--language", help="Código de idioma, por ejemplo es o en. Por defecto se detecta"
    ),
    translate: bool = typer.Option(False, "--translate", help="Traducir el audio al inglés"),
    prompt: str = typer.Option(
        None, "--prompt", help="Vocabulario o contexto: nombres propios, siglas, jerga"
    ),
    word_timestamps: bool = typer.Option(
        False, "--word-timestamps", help="Marcas de tiempo por palabra para subtítulos más precisos"
    ),
    cookies: Path = typer.Option(
        None, "--cookies", help="Ruta de cookies.txt para contenido que requiere iniciar sesión"
    ),
    output_dir: Path = typer.Option(
        None, "--output-dir", help="Carpeta donde guardar los archivos de la transcripción"
    ),
    no_history: bool = typer.Option(
        False, "--no-history", help="No añadir la transcripción al historial de la aplicación"
    ),
    no_clipboard: bool = typer.Option(
        False, "--no-clipboard", help="No copiar la transcripción al portapapeles"
    ),
    clean_orphans: bool = typer.Option(
        False, "--clean-orphans",
        help="Listar las carpetas de output/ que ya no están en el historial",
    ),
    yes: bool = typer.Option(False, "--yes", help="Con --clean-orphans, borrarlas de verdad"),
) -> None:
    if clean_orphans:
        _clean_orphans(yes)
        return
    if not source:
        typer.echo("Error: indica un enlace o un archivo", err=True)
        raise typer.Exit(code=1)
    if profile not in {"fast", "balanced", "precise"}:
        typer.echo("Error: --profile debe ser fast, balanced o precise", err=True)
        raise typer.Exit(code=1)
    if audio_quality not in {"compact", "balanced", "best"}:
        typer.echo("Error: --audio-quality debe ser compact, balanced o best", err=True)
        raise typer.Exit(code=1)
    if model:
        settings.model_size = model
    if cookies:
        settings.cookies_file = cookies

    job_id = f"job_{uuid.uuid4().hex[:10]}"
    # A custom folder is outside the history's output/ tree, so it cannot be reopened there.
    record_history = not no_history and output_dir is None
    out_dir = output_dir or settings.output_dir / job_id
    job_source: URLSource | FileSource

    if Path(source).expanduser().is_file():
        path = Path(source).expanduser().resolve()
        job_source = FileSource(path=path, original_name=path.name)
    elif is_supported_url(source):
        job_source = URLSource(url=source)
    else:
        typer.echo(
            "Error: el enlace no es compatible y no se encontró ningún archivo local en esa ruta",
            err=True,
        )
        raise typer.Exit(code=1)

    cancel_event = threading.Event()
    on_stage = _make_stage_printer()
    options = TranscriptionOptions(
        language=language,
        task="translate" if translate else "transcribe",
        initial_prompt=prompt,
        word_timestamps=word_timestamps,
    )

    try:
        result = run_pipeline(
            job_id,
            job_source,
            cancel_event=cancel_event,
            on_stage=on_stage,
            output_dir=out_dir,
            profile=profile,  # type: ignore[arg-type]
            audio_quality=audio_quality,  # type: ignore[arg-type]
            options=options,
            record_history=record_history,
        )
    except KeyboardInterrupt:
        cancel_event.set()
        typer.echo("Cancelado.")
        raise typer.Exit(code=130) from None
    except TranscriberError as exc:
        if exc.code == "cancelled":
            typer.echo("Cancelado.")
            raise typer.Exit(code=0) from None
        typer.echo(f"Error: {exc.message}", err=True)
        raise typer.Exit(code=1) from None

    if not no_clipboard:
        _copy_to_clipboard(result.text)

    typer.echo(f"\nIdioma: {result.language} ({result.language_probability:.0%} de confianza)")
    typer.echo(f"Duración: {result.duration:.1f} s   Palabras: {result.word_count}")
    typer.echo(f"Guardado en: {out_dir}")


if __name__ == "__main__":
    app()
