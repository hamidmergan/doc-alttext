# PLAN

Status: phase 1 done 2026-10-23. Phase 2 (PDF) is open.

## 1. Intent

`doc-alttext` writes missing alt text for images in DOCX and PPTX files, using any
OpenAI-compatible vision model. Since June 2025 the European Accessibility Act (BFSG in
Germany) requires accessible documents in many places, also at universities and public
bodies. Open-source tools for Office files do not exist yet. Commercial ones do
(Nutrient, PDFix, SlideSpeak).

```
doc-alttext report.docx  ->  report.alt.docx  (+ optional report.json / .csv)
```

Goals
- Library as core, thin CLI. Same conventions as doc-extract, office-translate, invoice-extract.
- DOCX and PPTX first. Tagged PDF second (phase 2).
- Alt text fits the document: context (surrounding text, slide title, caption) goes into the prompt.
- Alt text in the document language (`--lang` or detected).
- Short (about 150 characters). Charts and diagrams: state the key message.
- Decorative images are marked decorative, not described.
- Review report (JSON/CSV) with image, location, old and new alt text.

Non-goals
- No other accessibility fixes (reading order, contrast, tables, headings).
- No editing of chart objects (`c:chart`), SmartArt, equations, VBA.
- No images in slide layouts or masters (template material, usually decorative).
- No OCR of whole documents (that is doc-extract).

Anti-goals (failure even if it "works")
- The output does not open cleanly in Word or PowerPoint, or the formatting changes.
- The input file gets overwritten without `--in-place`.
- Existing human-written alt text gets replaced without `--overwrite`.
- Images get sent to a fixed provider, or a server URL is hard-coded.

## 2. Constraints

- `base_url` and `model` have no default. Missing -> clear error naming flag and env variable.
- `api_key` optional, placeholder `not-needed` if missing. Then `OPENAI_API_KEY`.
- Settings: argument, then env `DOC_ALTTEXT_*`, then default.
- Everything in the repo in English. MIT. Lab server URL never in the repo.
- README after `doc-extract/README.md`: vision model needed, privacy with self-hosted models.

## 3. How Office stores alt text (verified)

PowerPoint, taken from PowerPoint's own theme files (`Bjorn.thmx`):

```xml
<p:cNvPr id="7" name="Straight Connector 6">
  <a:extLst>
    <a:ext uri="{C183D7F6-B498-43B3-948B-1728B52AA6E4}">
      <adec:decorative xmlns:adec="http://schemas.microsoft.com/office/drawing/2017/decorative" val="1"/>
    </a:ext>
  </a:extLst>
</p:cNvPr>
```

- Alt text: attribute `descr` on `p:cNvPr` (PPTX) or `wp:docPr` (DOCX).
- Decorative: extension above, no `descr`. Element and `val` (boolean) confirmed in [MS-ODRAWXML] 2.34.
- `a:extLst` is the last child of `cNvPr`/`docPr` (after `a:hlinkClick`, `a:hlinkHover`). Other `a:ext`
  entries (for example `a16:creationId`) stay untouched.
- DOCX uses the same type (`CT_NonVisualDrawingProps`) for `wp:docPr`. Not yet seen in a file saved by
  Word. Task 4 checks it against a reference file saved by Word (see open question).
- DOCX: write `descr` on `wp:docPr` and also on `pic:cNvPr` inside the same drawing, if present.
  Keep `title` as it is.

## 4. Behaviour

What is an image
- DOCX: every `w:drawing` with a `pic:pic` in body, tables, text boxes, headers, footers,
  footnotes, endnotes. Pictures inside groups (`wpg:wgp`) get their own `pic:cNvPr`.
- PPTX: every `p:pic` on slides, also inside groups (`p:grpSp`), and shapes with a picture fill
  (`p:sp` with `a:blipFill`).
- Legacy VML images (`w:pict`) and linked images (`r:link`): reported as `unsupported`, not changed.
- Image formats: PNG, JPEG, GIF, BMP, TIFF, WEBP. SVG uses its PNG fallback. EMF/WMF: `unsupported`.

Existing alt text
- Kept if `descr` is non-empty, or the image is already decorative.
- Treated as missing: empty, whitespace, a file name (`image1.png`, `IMG_2034.JPG`), or Word's
  auto-generated text ("... Automatically generated description" / "Automatisch generierte Beschreibung").
- `--overwrite` replaces everything, including decorative flags.

Context for the prompt (trimmed, about 1500 characters in total)
- DOCX: nearest heading before the image, about 400 characters before and after, the caption
  (adjacent paragraph with style `caption` or a `SEQ` field, language independent), or
  "page header/footer" for header and footer images.
- PPTX: slide number, slide title (placeholder `title`/`ctrTitle`), other text on the slide, the start
  of the speaker notes.
- Both: how often the same image appears in the document (repeated logos are a strong decorative hint).

Language
- `--lang` wins. Otherwise one short text-only model call on a sample of the document text.
  If the document has no text: most common `lang` attribute in the runs, else English.

Model answer
- One request per unique image (same bytes = one call, result reused).
- Answer as JSON: `{"decorative": true|false, "alt": "..."}`. Tolerant parsing (code fences,
  `<think>` blocks), as in invoice-extract.
- Prompt rules: target length `max_chars` (150), no "image of", charts and diagrams with the key
  message, important text in the image, do not repeat the caption, decorative for lines,
  borders, backgrounds, ornaments and repeated branding logos.
- Longer answers are kept, not cut, and flagged `too_long` in the report.
- Pre-check without the model: very thin or tiny images (short side under 16 px, or aspect
  ratio over 15:1 with short side under 30 px) count as decorative.

Output
- Default `report.alt.docx` next to the input. If it exists: `report.alt-1.docx`.
- `-o FILE` (one input) or `-o FOLDER` (several inputs). `--in-place` writes over the input.
- Write to a temp file, then `os.replace`. All untouched zip parts are copied byte for byte.
- `--dry-run`: no document written, only the report.

Report
- `--report FILE.json` or `FILE.csv`. With `--dry-run` and no `--report`: JSON on stdout.
- CSV in UTF-8 with BOM, so Excel shows umlauts correctly.
- Always a one-line summary on stderr.
- Fields: `file`, `image` (zip part, e.g. `ppt/media/image3.png`), `location` (e.g. `slide 3`,
  `body, paragraph 12`, `header1`), `shape`, `status` (`added`, `decorative`, `kept`,
  `unsupported`, `error`), `old_alt`, `new_alt`, `chars`, `language`, `note`.
- Exit code: 0 ok, 1 if any file or image failed (the file is still written), 2 config error.

Settings

| Argument / flag | Env | Default |
| --- | --- | --- |
| `base_url` / `--base-url` | `DOC_ALTTEXT_BASE_URL` | none, required |
| `model` / `--model` | `DOC_ALTTEXT_MODEL` | none, required |
| `api_key` / `--api-key` | `DOC_ALTTEXT_API_KEY`, then `OPENAI_API_KEY` | optional |
| `lang` / `--lang` | `DOC_ALTTEXT_LANG` | detected |
| `max_chars` / `--max-chars` | `DOC_ALTTEXT_MAX_CHARS` | 150 |
| `max_file_mb` / `--max-file-mb` | `DOC_ALTTEXT_MAX_FILE_MB` | 100 |
| `max_images` / `--max-images` | `DOC_ALTTEXT_MAX_IMAGES` | 300 |
| `max_image_side` / `--max-image-side` | `DOC_ALTTEXT_MAX_IMAGE_SIDE` | 1024 |
| `concurrency` / `--concurrency` | `DOC_ALTTEXT_CONCURRENCY` | 4 |
| `timeout` / `--timeout` | `DOC_ALTTEXT_TIMEOUT` | 120 |
| `prompt` / `--prompt` | `DOC_ALTTEXT_PROMPT` | built-in |

Flags without env: `--overwrite`, `--dry-run`, `--in-place`, `-o`, `--report`.

Limits
- More than `max_images` images or a file over `max_file_mb`: the file is rejected with a message
  naming the limit and the setting. Nothing is silently skipped (same rule as doc-extract).

Python API

```python
from doc_alttext import add_alt_text

result = add_alt_text("report.docx", base_url=..., model=..., lang=None,
                      overwrite=False, dry_run=False, output=None, in_place=False)
result.output   # Path or None (dry run)
result.items    # list of ImageItem, same fields as the report
```

## 5. Package layout

```
doc-alttext/
  pyproject.toml   (name doc-alttext, deps openai, lxml, Pillow, extra [ui], no PyPI release)
  README.md  CHANGELOG.md  LICENSE  .gitignore  .github/workflows/ci.yml
  src/doc_alttext/
    __init__.py  py.typed
    errors.py    AltTextError, ConfigError, LimitError, UnsupportedFileError, ModelError
    config.py    Settings, resolve()
    client.py    prompt, describe_image(), detect_language(), JSON parsing
    images.py    load, size check, downscale, convert to PNG, tiny/line pre-check
    package.py   zip read/write, rels, content types, read/write alt + decorative
    word.py      DOCX: find images and context
    slides.py    PPTX: find images and context
    report.py    ImageItem, JSON/CSV writer
    core.py      pipeline, add_alt_text()
    cli.py
  tests/  conftest.py (fake server, fixture builders with python-docx/python-pptx), test_*.py
```

No publish.yml: the package is not released on PyPI. Install from GitHub.

## 6. Phase 2: tagged PDF (own short design before coding)

- Extra `doc-alttext[pdf]` with pikepdf and pypdfium2.
- Tagged (`/MarkInfo /Marked true` and `/StructTreeRoot`): walk `/Figure` elements, keep those with
  `/Alt`, find the image via `/BBox` attribute or the MCIDs in the content stream, render that area,
  write `/Alt`.
- Decorative in PDF would mean retagging as artifact. Phase 2 only reports it.
- Untagged PDF: only report ("untagged, N images, alt text needs tags"), no output file.

## 7. Plan (phase 1)

Each task: tests first, then code, `pytest` green before the next task.

- [x] 1 Scaffold: pyproject, LICENSE, .gitignore, CI, errors, config + tests
- [x] 2 Model client: prompt, JSON parsing, language detection, fake server + tests
- [x] 3 Images: load, formats, downscale, tiny/line pre-check + tests
- [x] 4 Package layer: zip, rels, read/write `descr` and decorative + tests (verified in Word and PowerPoint, see 10b)
- [x] 5 DOCX: find images (body, tables, text boxes, header/footer, groups), context, captions + tests
- [x] 6 PPTX: find images (groups, picture fills), title, slide text, notes + tests
- [x] 7 Report: items, JSON, CSV + tests
- [x] 8 Pipeline and Python API: dedupe, concurrency, language, dry-run, in-place, atomic write + tests
- [x] 9 CLI + tests
- [x] 10 README, CHANGELOG, grep for lab URL, real run with local Ollama (gemma4:12b)
- [x] 10b Manual check in Word and PowerPoint (accessibility checker)
  - [x] PowerPoint (Mac): output opens without repair, accessibility checker "no issues" (2026-10-23)
  - [x] Word (Mac): output opens without repair, Word reads the alt text (AppleScript)
  - [x] Word (Mac): accessibility checker reports 1 missing alt text of 3 images (only the header logo from the timeout run), so the decorative line is accepted
- [x] 11 Review improvements (keep it simple)
  - [x] Report shows the alt text as found (also file names and generated texts that were replaced)
  - [x] HTML report via `--report x.html`: thumbnail, location, status, before/after, notes. One file, no JavaScript, no external resources
  - [x] Progress lines on stderr (language detection, image n/N)
  - [x] Timeout error suggests `--timeout`
  - [x] README: review workflow (check, write, fill gaps, fix single texts in Word/PowerPoint)
- [x] 12 Web page: `doc-alttext serve`, extra `ui`, FastAPI and one static HTML page like invoice-extract
  - [x] `apply_alt_texts(path, decisions)`: write reviewed texts without a model call
  - [x] Upload, background job with progress, thumbnails, edit text or decorative, download
  - [x] Host and origin guard, upload size limit, one file at a time
  - [x] Real run through the API with a hosted vision model (chat-vl-fast): 3 images in about 2 seconds, edited text and decorative flags land in the downloaded file
  - [ ] Real run in the browser
- [x] 13 Docker: Dockerfile and .dockerignore like invoice-extract, container starts the web page
  - [x] Image built, runs as user `app`, no tests or PLAN.md inside. DOCX and PPTX through the page in the container
  - [x] File type comes from the content, not the name
  - [x] Prompt: when unsure, write alt text. Photos, illustrations, charts and diagrams are never decorative
- [x] 14 Real presentation (29 objects): PowerPoint still reported 16 missing alt texts, all drawn shapes without text
  - [x] Shapes without text (PPTX `p:sp`, `p:cxnSp`, DOCX `wps`/`wpg`) are marked decorative without a model call. Placeholders, text boxes and shapes with text are left out. They do not count against `max_images`
  - [x] One request per image and part, so an icon on two slides gets the context of each slide
- [ ] 15 Phase 2 PDF

## 8. Notes from the real run (2026-10-23, gemma4:12b via Ollama)

- German DOCX: chart got its key message in German (126 chars), thin line marked decorative without a model call.
- English PPTX: slide picture described in English, with the slide title as context.
- Header logo was first described, not marked decorative. Header/footer context now says they repeat on every page. Rerun: logo marked decorative.
- A request timeout shows up as `error` in the report, exit code 1, file still written. Rerun on the output only asks the missing image.

## 9. Word markup

- Word reads the same decorative extension on `wp:docPr`. Checked with Word's accessibility checker
  on Mac: the decorative line was not reported as missing alt text (see 10b).
