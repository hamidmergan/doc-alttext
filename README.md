# doc-alttext

A lightweight Python utility that adds missing alt text to images in Word and PowerPoint files. Each image is sent to a vision model of your choice, together with the text around it, and the answer is written straight into the file. Screen reader users then hear what the image shows and why it matters.

Since June 2025 the European Accessibility Act requires accessible documents in many places, including universities and public bodies. doc-alttext helps with one of the most common gaps: images without a text alternative.

doc-alttext currently supports:

- DOCX (also DOCM, DOTX)
- PPTX (also PPTM, POTX)

What it does:

- Writes alt text in the language of the document, or in the language you choose
- Keeps alt text short (about 150 characters). Charts and diagrams get their key message
- Uses the context: nearest heading, caption, text before and after, slide title, speaker notes
- Marks decorative images (lines, borders, backgrounds, repeated logos) as decorative, the same way Word and PowerPoint do
- Marks drawn shapes without text (cards, circles, lines) as decorative, without asking the model
- Leaves existing alt text alone, unless you ask it to overwrite
- Writes a review report with every image, where it is and the new alt text: as an HTML page with the images, or as JSON or CSV

## Prerequisites

- Python 3.9 or newer
- A server with an OpenAI-compatible API and a **vision-capable model** (for example Ollama, vLLM, LM Studio, a university server or a cloud provider). A text-only model is not enough.
- An API key is optional. Many self-hosted servers do not need one.

If you run your own model, your documents stay on your own network. Nothing leaves your machine or data center.

## Installation

doc-alttext is installed from GitHub:

```bash
pip install git+https://github.com/hamidmergan/doc-alttext.git
```

With the web page:

```bash
pip install "doc-alttext[ui] @ git+https://github.com/hamidmergan/doc-alttext.git"
```

Alternatively, you can install it from a local copy (`pip install ".[ui]"` for the web page):

```bash
git clone https://github.com/hamidmergan/doc-alttext.git
cd doc-alttext
pip install .
```

## Usage

### Web page

```bash
doc-alttext serve --base-url http://localhost:11434/v1 --model your-vision-model
```

Open http://127.0.0.1:8000 and choose a Word or PowerPoint file.

- **Start** sends the images to the model. The page shows the progress.
- **Each image** appears next to its alt text. Edit the text, or tick "Decorative" so screen readers skip the image. A counter shows the length against the target.
- **Download** writes your texts into a copy of the file, named `<name>.alt.docx` or `<name>.alt.pptx`. Only the texts on the page are written. The model is not asked again.

The page handles one file at a time. Your file stays on your computer and is only sent to your model server. The page has no login. It listens on 127.0.0.1 by default and only answers requests for localhost, so other websites cannot reach it. Only use `--host 0.0.0.0` on a trusted network.

### Docker

```bash
docker build -t doc-alttext .
docker run -d --name doc-alttext -p 127.0.0.1:8000:8000 \
  -e DOC_ALTTEXT_BASE_URL=http://host.docker.internal:11434/v1 \
  -e DOC_ALTTEXT_MODEL=your-vision-model \
  doc-alttext
```

Then open http://127.0.0.1:8000. If port 8000 is taken, change the first number, for example `-p 127.0.0.1:8020:8000` and http://127.0.0.1:8020.

The container starts the web page and reads its settings from the `DOC_ALTTEXT_*` environment variables. `host.docker.internal` reaches a model server on your own machine, for example Ollama. Add `-e DOC_ALTTEXT_API_KEY=...` if your server needs a key.

`127.0.0.1:` makes the page reachable from your own computer only. The page has no login, so do not expose the port to the internet.

Stop, start again or remove the container:

```bash
docker stop doc-alttext
docker start doc-alttext
docker rm -f doc-alttext
```

### Command-Line

Add alt text to a document:

```bash
doc-alttext report.docx --base-url http://localhost:11434/v1 --model your-vision-model
```

This writes `report.alt.docx` next to `report.docx`. The original is never changed. If the target already exists, a number is added (`report.alt-1.docx`).

Check the result first, without writing a document. The report is printed as JSON:

```bash
doc-alttext slides.pptx --dry-run --base-url http://localhost:11434/v1 --model your-vision-model
```

Write a report for review. As HTML it shows each image next to its alt text:

```bash
doc-alttext report.docx --report review.html --base-url http://localhost:11434/v1 --model your-vision-model
```

Use `review.csv` for Excel or `review.json` for scripts instead.

Several files work the same way. Use `-o` to choose the output. For one file it is a file, for several files it is a folder:

```bash
doc-alttext a.docx b.pptx -o accessible/ --base-url http://localhost:11434/v1 --model your-vision-model
```

More options:

- `--lang German` sets the language of the alt text. Without it, the language of the document is used.
- `--overwrite` replaces existing alt text and decorative flags too.
- `--in-place` changes the input file instead of writing a new one.
- `--max-chars 120` changes the target length.

Progress and errors appear on stderr. The exit code is 1 if a file or an image failed, and 2 for a usage or configuration error.

### Review workflow

A model can be wrong. Check the result before you publish:

1. Check first, without changing anything: `doc-alttext slides.pptx --dry-run --report check.html`, then open `check.html` in a browser.
2. Write the file: `doc-alttext slides.pptx --report check.html`. This creates `slides.alt.pptx`.
3. Fill gaps: if some images failed (for example a timeout), run it again on the output: `doc-alttext slides.alt.pptx --in-place`. Images that already have alt text are kept, only the missing ones are sent.
4. Fix single texts by hand in Word or PowerPoint, at the place the report shows (right-click the image, then alt text).

If requests time out with a slow or busy model, raise `--timeout` (seconds).

### Python API

```python
from doc_alttext import add_alt_text

result = add_alt_text(
    "report.docx",
    base_url="http://localhost:11434/v1",
    model="your-vision-model",
)
print(result.output)
for item in result.items:
    print(item.location, item.status, item.new_alt)
```

To write texts you reviewed yourself, without asking a model again, pass one decision per image in the order of the report: `apply_alt_texts("report.docx", [{"alt": "..."}, {"decorative": True}, None])`. `None` leaves an image as it is.

`add_alt_text` accepts the same options as the command line: `output`, `overwrite`, `dry_run`, `in_place`, `lang` and the settings below. Pass `progress=print` to see progress messages. To process several files with the same settings, create an `AltTexter` once and call `process` for each file. `write_report(items, "review.html")` writes the report as HTML, CSV or JSON, chosen by the extension.

### Report

Each image becomes one entry. The HTML report shows the same fields next to a small copy of the image. It is a single file without scripts or external resources, so you can pass it on or archive it.

| Field | Meaning |
| --- | --- |
| `file` | Input file |
| `image` | Image inside the file, e.g. `ppt/media/image3.png` |
| `location` | Where it is, e.g. `slide 3`, `body, paragraph 12`, `header (header1)` |
| `shape` | Name of the picture in Word or PowerPoint |
| `status` | `added`, `decorative`, `kept` (had alt text), `unsupported` or `error` |
| `old_alt` | Alt text before, as found in the file (also file names and generated texts that count as missing) |
| `new_alt` | New alt text |
| `chars` | Length of the new alt text |
| `language` | Language used for the alt text |
| `note` | Details, e.g. `too_long`, the reason for `unsupported`, or the error |

Alt text that is longer than the target is kept as it is and marked `too_long`, so you can shorten it by hand.

### What counts as existing alt text

Alt text is kept if it is filled in and the image is not already marked decorative. Empty text, a file name such as `IMG_2034.JPG` and descriptions generated automatically by Word or PowerPoint ("Description automatically generated") count as missing.

### Settings

Order: argument, then environment variable, then default.

| Argument / flag | Environment variable | Default |
| --- | --- | --- |
| `base_url` / `--base-url` | `DOC_ALTTEXT_BASE_URL` | none, required |
| `model` / `--model` | `DOC_ALTTEXT_MODEL` | none, required |
| `api_key` / `--api-key` | `DOC_ALTTEXT_API_KEY` (then `OPENAI_API_KEY`) | optional |
| `lang` / `--lang` | `DOC_ALTTEXT_LANG` | language of the document |
| `max_chars` / `--max-chars` | `DOC_ALTTEXT_MAX_CHARS` | 150 |
| `max_file_mb` / `--max-file-mb` | `DOC_ALTTEXT_MAX_FILE_MB` | 100 |
| `max_images` / `--max-images` | `DOC_ALTTEXT_MAX_IMAGES` | 300 |
| `max_image_side` / `--max-image-side` | `DOC_ALTTEXT_MAX_IMAGE_SIDE` | 1024 pixels |
| `concurrency` / `--concurrency` | `DOC_ALTTEXT_CONCURRENCY` | 4 |
| `timeout` / `--timeout` | `DOC_ALTTEXT_TIMEOUT` | 120 seconds |
| `prompt` / `--prompt` | `DOC_ALTTEXT_PROMPT` | default prompt |

If a limit is exceeded, the file is rejected with a message naming the limit and the setting. Nothing is silently skipped. Images are downscaled before sending (longest side `max_image_side`). An image used several times on the same slide or page part is sent only once.

## Limitations

- Quality depends on the chosen model. Check the report before you publish, especially for charts and images with text.
- Not handled: EMF/WMF and other vector images, linked (not embedded) images, old VML images in Word, charts and SmartArt built in Office, video and audio. They appear in the report as `unsupported` or are skipped.
- Images in slide layouts and masters are not changed.
- PDF is not supported yet.

## Running Tests

```bash
pip install -e ".[test]"
pytest
```

The tests run against a local fake server and need no real model.

## License

MIT
