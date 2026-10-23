# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Alt text for images in DOCX and PPTX files with any OpenAI-compatible vision model
- Context from the document in the prompt: heading, caption, surrounding text, slide title, speaker notes
- Alt text in the document language, detected or set with `--lang`
- Decorative images marked with the same extension Word and PowerPoint use
- Existing alt text kept unless `--overwrite`
- Review report as JSON or CSV, `--dry-run` and `--in-place`
- HTML review report (`--report check.html`) with each image next to its alt text
- Progress messages on stderr, `progress` callback in the Python API
- Timeout errors name the `--timeout` setting
- Web page (`doc-alttext serve`, extra `ui`): upload a file, edit the alt texts next to the images, download the result
- `apply_alt_texts` writes reviewed texts into a file without asking a model
- Dockerfile that starts the web page
- The file type is read from the content, so a renamed file still works
- Drawn shapes without text are marked decorative, so the accessibility checker no longer reports them
- The same image on different slides gets its own context
