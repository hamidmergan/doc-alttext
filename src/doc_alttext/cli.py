import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .config import resolve
from .core import AltTexter, default_output
from .errors import AltTextError
from .report import REPORT_SUFFIXES, ImageItem, summary, to_json, write_report

LOOPBACK = ("127.0.0.1", "localhost", "::1")
UI_HINT = 'The web page needs extra packages: pip install "doc-alttext[ui] @ git+https://github.com/hamidmergan/doc-alttext.git"'
NO_LOGIN = "Warning: the page has no login. Anyone who can reach this address can use it and your model server."


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="doc-alttext",
        description="Add missing alt text to images in DOCX and PPTX files with any OpenAI-compatible vision model.",
    )
    p.add_argument("files", nargs="+", help="Files to process (.docx, .pptx)")
    p.add_argument(
        "-o",
        "--output",
        help="Output file (one input) or output folder (several inputs). Default: <name>.alt.<ext> next to each input",
    )
    p.add_argument("--in-place", action="store_true", help="Change the input files instead of writing new ones")
    p.add_argument("--dry-run", action="store_true", help="Write no documents, only the report")
    p.add_argument("--overwrite", action="store_true", help="Replace existing alt text and decorative flags too")
    p.add_argument(
        "--report",
        help="Write a review report: .html to check images and texts side by side, or .json/.csv. "
        "With --dry-run and no --report, JSON goes to stdout",
    )
    _model_options(p)
    p.add_argument("--version", action="version", version=f"doc-alttext {__version__}")
    return p


def _model_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--lang", help="Language of the alt text, e.g. German or de. Default: language of the document")
    p.add_argument("--max-chars", type=int, help="Target length of the alt text in characters (default 150)")
    p.add_argument("--base-url", help="URL of the OpenAI-compatible server, e.g. http://localhost:11434/v1")
    p.add_argument("--model", help="Name of a vision model")
    p.add_argument("--api-key", help="API key, if the server requires one")
    p.add_argument("--max-file-mb", type=float)
    p.add_argument("--max-images", type=int, help="Maximum number of images per file")
    p.add_argument("--max-image-side", type=int, help="Longer images are downscaled to this side length")
    p.add_argument("--concurrency", type=int, help="Requests sent in parallel")
    p.add_argument("--timeout", type=float, help="Seconds per request")
    p.add_argument("--prompt", help="Replace the built-in prompt. {language} and {max_chars} are filled in")


def _settings_options(args) -> dict:
    return dict(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        lang=args.lang,
        max_chars=args.max_chars,
        max_file_mb=args.max_file_mb,
        max_images=args.max_images,
        max_image_side=args.max_image_side,
        concurrency=args.concurrency,
        timeout=args.timeout,
        prompt=args.prompt,
    )


def _serve_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="doc-alttext serve",
        description="Start a local web page: upload a Word or PowerPoint file, check and edit the alt texts, download.",
    )
    p.add_argument("--host", default="127.0.0.1", help="Address to listen on (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="Port (default 8000)")
    _model_options(p)
    return p


def _serve(argv: List[str]) -> int:
    args = _serve_parser().parse_args(argv)
    try:
        import uvicorn

        from .web.app import create_app
    except ImportError:
        print(UI_HINT, file=sys.stderr)
        return 2
    try:
        settings = resolve(**_settings_options(args))
    except AltTextError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.host not in LOOPBACK:
        print(NO_LOGIN, file=sys.stderr)
    # on loopback, only accept our own host names, so other web pages cannot reach the page via DNS rebinding
    allowed = list(LOOPBACK) if args.host in LOOPBACK else None
    host = f"[{args.host}]" if ":" in args.host else args.host
    if args.host in LOOPBACK:
        print(f"Open http://{host}:{args.port} in your browser. Stop with Ctrl+C.", file=sys.stderr)
    else:
        print(f"Listening on {host}:{args.port}. Stop with Ctrl+C.", file=sys.stderr)
    uvicorn.run(create_app(settings, allowed_hosts=allowed), host=args.host, port=args.port, log_level="warning")
    return 0


def _target(src: Path, out: Optional[Path], many: bool) -> Optional[Path]:
    if out is None:
        return None  # default name, chosen by the library
    if many or out.is_dir():
        return default_output(out / src.name)
    return out  # an explicitly named output file is overwritten


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "serve":
        return _serve(argv[1:])
    args = _parser().parse_args(argv)
    many = len(args.files) > 1
    out = Path(args.output) if args.output else None

    if args.in_place and out is not None:
        print("Error: use either -o or --in-place, not both.", file=sys.stderr)
        return 2
    if many and out is not None and out.exists() and not out.is_dir():
        print("Error: with several files, -o must be a folder.", file=sys.stderr)
        return 2
    if args.report and Path(args.report).suffix.lower() not in REPORT_SUFFIXES:
        print("Error: --report must end in .html, .json or .csv.", file=sys.stderr)
        return 2

    current = {"name": ""}

    def progress(message: str) -> None:
        print(f"{current['name']}: {message}", file=sys.stderr, flush=True)

    try:
        texter = AltTexter(progress, **_settings_options(args))
    except AltTextError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    failed = 0
    items: List[ImageItem] = []
    for name in args.files:
        src = Path(name)
        current["name"] = name
        try:
            target = None if args.dry_run else _target(src, out, many)
            result = texter.process(
                src, target, overwrite=args.overwrite, dry_run=args.dry_run, in_place=args.in_place
            )
        except (AltTextError, OSError) as exc:
            failed += 1
            print(f"Error: {name}: {exc}", file=sys.stderr)
            continue
        items.extend(result.items)
        if not result.ok:
            failed += 1
        written = f" -> {result.output}" if result.output else ""
        print(f"{name}: {summary(result.items)}{written}", file=sys.stderr)
        for item in result.items:
            if item.status == "error":
                print(f"  Error: {item.location}: {item.note}", file=sys.stderr)

    if args.report:
        try:
            write_report(items, args.report)
        except (AltTextError, OSError) as exc:
            print(f"Error: report: {exc}", file=sys.stderr)
            return 1
        print(f"Report: {args.report}", file=sys.stderr)
    elif args.dry_run:
        sys.stdout.write(to_json(items))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
