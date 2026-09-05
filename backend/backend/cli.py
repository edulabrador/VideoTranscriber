import subprocess
import sys
import threading
from pathlib import Path

import typer

from backend.config import settings
from backend.core.errors import TranscriberError
from backend.core.pipeline import FileSource, URLSource, run_pipeline
from backend.core.validators import is_instagram_url

app = typer.Typer(add_completion=False, no_args_is_help=True)

_STAGE_LABELS = {
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


@app.command()
def main(
    source: str = typer.Argument(
        ..., help="Enlace de YouTube, Instagram, TikTok o Twitter (X), o un archivo local"
    ),
    model: str = typer.Option(None, "--model", help="Cambiar el tamaño del modelo Whisper"),
    cookies: Path = typer.Option(
        None, "--cookies", help="Ruta de cookies.txt para contenido que requiere iniciar sesión"
    ),
    output_dir: Path = typer.Option(
        None, "--output-dir", help="Carpeta donde guardar transcript.txt, subtitles.srt y transcript.json"
    ),
    no_clipboard: bool = typer.Option(
        False, "--no-clipboard", help="No copiar la transcripción al portapapeles"
    ),
) -> None:
    if model:
        settings.model_size = model
    if cookies:
        settings.cookies_file = cookies

    out_dir = output_dir or settings.output_dir
    job_source: URLSource | FileSource

    if is_instagram_url(source):
        job_source = URLSource(url=source)
    elif Path(source).expanduser().exists():
        path = Path(source).expanduser().resolve()
        job_source = FileSource(path=path, original_name=path.name)
    else:
        typer.echo(
            "Error: el enlace no es válido y no se encontró ningún archivo local en esa ruta",
            err=True,
        )
        raise typer.Exit(code=1)

    cancel_event = threading.Event()
    on_stage = _make_stage_printer()

    try:
        result = run_pipeline(
            "cli",
            job_source,
            cancel_event=cancel_event,
            on_stage=on_stage,
            output_dir=out_dir,
        )
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
    typer.echo(f"Guardado en: {out_dir}/transcript.txt, subtitles.srt, transcript.json")


if __name__ == "__main__":
    app()
