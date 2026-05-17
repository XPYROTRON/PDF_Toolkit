# PDF Toolkit

A lightweight, self-hosted web toolkit for common PDF workflows: merge, split, compress, protect, unlock, reorder, and convert PDFs in a single UI.

## Features

- Merge multiple PDFs into one document.
- Split a PDF by single pages or custom ranges.
- Smart PDF compression with text-quality preservation.
- Convert PDF pages to images.
- Password-protect PDFs.
- Unlock password-protected PDFs (with valid password).
- Remove selected pages.
- Reorder/organize page sequences.

## Smart Compression (Text-First Quality)

The compression pipeline is designed to preserve readable text quality:

- Keeps text/vector content intact whenever possible.
- Applies selective compression mainly to embedded images.
- Provides multiple compression levels (`low`, `medium`, `high`, `extreme`).
- Targets substantial file-size reduction while keeping output usable for documents and sharing.

## Tech Stack

- **Backend:** Flask
- **PDF processing:** PyMuPDF (`fitz`), PyPDF2
- **Images:** Pillow
- **Frontend:** HTML templates served by Flask

## Project Structure

- `app.py` — Flask app and PDF processing logic.
- `templates/index.html` — UI for upload and tool selection.
- `requirements.txt` — Python dependencies.

## Quick Start

### 1) Install dependencies

```bash
pip install -r requirements.txt
```

### 2) Run the app

```bash
python app.py
```

### 3) Open in browser

`http://localhost:5000`

## Notes

- Default upload size limit is 50 MB (`MAX_CONTENT_LENGTH`).
- Temporary and processed files are stored in `uploads/` and `processed/`.
- For best results, use modern versions of Python and libraries from `requirements.txt`.
