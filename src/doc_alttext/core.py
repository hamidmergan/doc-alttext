"""Pipeline: find images, ask the model, write alt text, build the report."""

import hashlib
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Union

from . import slides, word
from .client import Answer, describe_image, detect_language, make_client
from .config import Settings, resolve
from .errors import AltTextError, LimitError, ModelError, UnsupportedFileError
from .images import looks_decorative, prepare
from .package import ImageRef, Package, Scan, set_alt
from .report import ADDED, DECORATIVE, ERROR, KEPT, UNSUPPORTED, ImageItem

WORD = {".docx", ".docm", ".dotx", ".dotm"}
SLIDES = {".pptx", ".pptm", ".potx", ".potm"}
SUPPORTED = WORD | SLIDES

FALLBACK_LANGUAGE = "English"


@dataclass
class Result:
    file: Path
    output: Optional[Path]  # None for a dry run
    language: str
    items: List[ImageItem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(i.status != ERROR for i in self.items)


def default_output(path: Union[str, Path]) -> Path:
    """report.docx -> report.alt.docx, or report.alt-1.docx if that exists."""
    path = Path(path)
    first = path.with_name(f"{path.stem}.alt{path.suffix}")
    candidate, n = first, 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}.alt-{n}{path.suffix}")
        n += 1
    return candidate


class AltTexter:
    """Holds settings and the client, so several files share them."""

    def __init__(self, progress: Optional[Callable[[str], None]] = None, settings: Optional[Settings] = None,
                 **options):
        """progress, if given, is called with short status messages while a file is processed.

        settings: ready settings (from config.resolve); otherwise options are resolved.
        """
        self.settings: Settings = settings if settings is not None else resolve(**options)
        self.progress = progress
        self._client = None

    def _say(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)

    @property
    def client(self):
        if self._client is None:
            self._client = make_client(self.settings)
        return self._client

    def process(
        self,
        path: Union[str, Path],
        output: Union[str, Path, None] = None,
        *,
        overwrite: bool = False,
        dry_run: bool = False,
        in_place: bool = False,
    ) -> Result:
        path = Path(path)
        _check_file(path, self.settings)
        if in_place and output is not None:
            raise AltTextError("Use either an output file or in_place, not both.")
        if not dry_run:
            output = _output_for(path, output, in_place)

        with Package(path) as pkg:
            found = _scan(pkg, path)
            pictures = sum(1 for ref in found.images if not ref.plain_shape)
            if pictures > self.settings.max_images:
                raise LimitError(
                    f"{path.name} has {pictures} images. The limit is {self.settings.max_images} "
                    "(--max-images or DOC_ALTTEXT_MAX_IMAGES)."
                )
            result = Result(file=path, output=None if dry_run else output, language="")
            self._run(pkg, path, found, overwrite, result)
            if not dry_run:
                _save(pkg, output)
        return result

    def _run(self, pkg: Package, path: Path, found: Scan, overwrite: bool, result: Result) -> None:
        items: List[ImageItem] = []
        # One request per image and part (slide, body, header), so each gets the context of its own place.
        todo: Dict[tuple, List[int]] = {}  # (image hash, part) -> indexes of refs that need it
        pngs: Dict[str, bytes] = {}
        uses: Dict[str, int] = {}  # image hash -> how often it appears in the document
        for ref in found.images:
            item = ImageItem(file=str(path), image=ref.media or "", location=ref.location, shape=ref.shape,
                             status="", old_alt=_found_alt(ref))
            items.append(item)
            if ref.problem:
                item.status, item.note = UNSUPPORTED, ref.problem
                continue
            if (ref.old_alt or ref.decorative) and not overwrite:
                item.status = KEPT
                item.note = "already decorative" if ref.decorative and not ref.old_alt else ""
                continue
            if ref.plain_shape:
                _apply(pkg, ref, item, Answer(decorative=True, alt=""), self.settings.max_chars)
                item.note = "shape without text"
                continue
            data = pkg.read(ref.media)
            key = hashlib.sha1(data).hexdigest()
            if key not in pngs:
                try:
                    image = prepare(data, ref.media, self.settings.max_image_side)
                except UnsupportedFileError as exc:
                    item.status, item.note = UNSUPPORTED, str(exc)
                    continue
                if looks_decorative(image.width, image.height):
                    _apply(pkg, ref, item, Answer(decorative=True, alt=""), self.settings.max_chars)
                    item.note = "tiny or thin image"
                    continue
                pngs[key] = image.png
            todo.setdefault((key, ref.part), []).append(len(items) - 1)
            uses[key] = uses.get(key, 0) + 1

        if todo:
            result.language = self._language(found)
            self._say(f"language: {result.language}")
            answers = self._ask(found, todo, pngs, uses, result.language)
            for key, indexes in todo.items():
                answer = answers[key]
                for i in indexes:
                    ref, item = found.images[i], items[i]
                    if isinstance(answer, ModelError):
                        item.status, item.note = ERROR, str(answer)
                    else:
                        _apply(pkg, ref, item, answer, self.settings.max_chars)
        else:
            result.language = self.settings.lang or ""
        for item in items:
            item.language = result.language if item.status in (ADDED, ERROR) else ""
        result.items = items

    def _language(self, found: Scan) -> str:
        if self.settings.lang:
            return self.settings.lang
        if found.text.strip():
            self._say("detecting the language")
            try:
                name = detect_language(self.client, self.settings, found.text)
            except ModelError:
                name = None
            if name:
                return name
        if found.langs:
            return found.langs.most_common(1)[0][0]
        return FALLBACK_LANGUAGE

    def _ask(self, found: Scan, todo: Dict[tuple, List[int]], pngs: Dict[str, bytes], uses: Dict[str, int],
             language: str) -> dict:
        def one(key: tuple):
            indexes = todo[key]
            context = found.images[indexes[0]].context
            if uses[key[0]] > 1:
                context += f"\nThe same image appears {uses[key[0]]} times in the document."
            try:
                return key, describe_image(self.client, self.settings, pngs[key[0]], context, language)
            except ModelError as exc:
                return key, exc

        answers = {}
        total = len(todo)
        self._say(f"asking the model about {total} image" + ("" if total == 1 else "s"))
        with ThreadPoolExecutor(max_workers=self.settings.concurrency) as pool:
            futures = [pool.submit(one, key) for key in todo]
            for done, future in enumerate(as_completed(futures), start=1):
                key, answer = future.result()
                answers[key] = answer
                self._say(f"image {done}/{total} done")
        return answers


def _scan(pkg: Package, path: Path) -> Scan:
    """Choose by the content, not the name, so a renamed file still works."""
    main = pkg.main_part()
    if main.startswith("ppt/"):
        return slides.scan(pkg)
    if main.startswith("word/"):
        return word.scan(pkg)
    raise UnsupportedFileError(f"{path.name} is neither a Word nor a PowerPoint file.")


def _output_for(path: Path, output: Union[str, Path, None], in_place: bool) -> Path:
    if in_place:
        if output is not None:
            raise AltTextError("Use either an output file or in_place, not both.")
        return path
    result = Path(output) if output is not None else default_output(path)
    if result.resolve() == path.resolve():
        raise AltTextError("The output file must not be the input file. Use in_place to change it.")
    if result.suffix.lower() != path.suffix.lower():
        raise AltTextError(f"The output file must end in {path.suffix} like the input.")
    return result


def apply_alt_texts(
    path: Union[str, Path],
    decisions: Sequence[Optional[dict]],
    output: Union[str, Path, None] = None,
    *,
    in_place: bool = False,
) -> Path:
    """Write reviewed alt texts into a file, without asking a model.

    decisions has one entry per image, in the order of the report items:
    {"alt": "..."} for alt text, {"decorative": True} for a decorative image, or None to leave it as it is.
    Returns the output path.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    if path.suffix.lower() not in SUPPORTED:
        raise UnsupportedFileError(f"Unsupported file type {path.suffix or '(none)'}.")
    output = _output_for(path, output, in_place)
    with Package(path) as pkg:
        found = _scan(pkg, path)
        if len(decisions) != len(found.images):
            raise AltTextError(
                f"{path.name} has {len(found.images)} images, but {len(decisions)} decisions were given. "
                "Was the file changed after the report was made?"
            )
        for ref, decision in zip(found.images, decisions):
            if decision is None or not ref.targets:
                continue
            decorative = bool(decision.get("decorative"))
            alt = " ".join(str(decision.get("alt") or "").split())
            set_alt(ref.targets, "" if decorative else alt, decorative)
            pkg.changed.add(ref.part)
        _save(pkg, output)
    return output


def _found_alt(ref: ImageRef) -> str:
    """The alt text as found in the file, also file names and generated texts that count as missing."""
    for target in ref.targets:
        descr = " ".join((target.get("descr") or "").split())
        if descr:
            return descr
    return ref.old_alt


def _apply(pkg: Package, ref: ImageRef, item: ImageItem, answer: Answer, max_chars: int) -> None:
    set_alt(ref.targets, answer.alt, answer.decorative)
    pkg.changed.add(ref.part)
    if answer.decorative:
        item.status = DECORATIVE
        return
    item.status, item.new_alt, item.chars = ADDED, answer.alt, len(answer.alt)
    if len(answer.alt) > max_chars:
        item.note = "too_long"


def _check_file(path: Path, settings: Settings) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    if path.suffix.lower() not in SUPPORTED:
        raise UnsupportedFileError(
            f"Unsupported file type {path.suffix or '(none)'}. Supported: {', '.join(sorted(SUPPORTED))}"
        )
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > settings.max_file_mb:
        raise LimitError(
            f"{path.name} is {size_mb:.1f} MB. The limit is {settings.max_file_mb:g} MB "
            "(--max-file-mb or DOC_ALTTEXT_MAX_FILE_MB)."
        )


def _save(pkg: Package, output: Path) -> None:
    """Write to a temp file next to the output, then move it into place."""
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(dir=output.parent, prefix=".tmp-", suffix=output.suffix, delete=False)
    tmp.close()
    tmp_path = Path(tmp.name)
    try:
        pkg.save(tmp_path)
        os.replace(tmp_path, output)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def add_alt_text(
    path: Union[str, Path],
    output: Union[str, Path, None] = None,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
    in_place: bool = False,
    progress: Optional[Callable[[str], None]] = None,
    **options,
) -> Result:
    """Add missing alt text to the images of a DOCX or PPTX file.

    options: base_url, model, api_key, lang, max_chars and the other settings.
    """
    return AltTexter(progress, **options).process(path, output, overwrite=overwrite, dry_run=dry_run, in_place=in_place)
