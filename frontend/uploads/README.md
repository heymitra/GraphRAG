# frontend/uploads/

Temporary holding directory for PDFs uploaded via the GraphRAG Explorer web UI.

When a user uploads a PDF, Flask saves it here before `extract_pdf.py` converts
it to `.txt` and moves the text to `input/`. The original PDF remains here for
reference but is not used by subsequent pipeline steps.

> **Generated — do not commit.** Contents are user-uploaded files.
