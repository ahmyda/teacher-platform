# Teacher Platform (Flask + SQLite)

A lightweight local starter app for teacher accounts, student lists, Excel import, assessment records, and lecture uploads.

## Requirements

- Python 3.10 or newer
- VS Code
- Internet access for the initial package installation

## Setup on Windows

Open this folder in VS Code. In **Terminal → New Terminal**, run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

If PowerShell blocks environment activation, use Command Prompt terminal instead:

```bat
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 in your browser. Stop the server with `Ctrl+C`.

## Excel import format

Save the workbook as `.xlsx`. The first row must have headings. One name heading is required:
- `full_name`, `name`, `student name`, or `student_name`

Optional headings:
- `student_code`, `student id`, `code`, or `id`
- `class_name`, `class`, or `group`

Example:

| student_code | full_name | class_name |
|---|---|---|
| S001 | Example Student | Class 1 |
| S002 | Another Student | Class 1 |

The app imports the first worksheet. Review the student list after importing; this starter version does not automatically detect duplicate students.

## Important security notes

- Passwords are hashed, and forms use CSRF protection.
- Database queries use parameters and each data route filters by the logged-in teacher.
- This is a learning/development starter, not yet ready for public deployment.
- Before deploying publicly: set a strong random `FLASK_SECRET_KEY` environment variable, turn off debug mode, use HTTPS, add rate limiting and email verification, restrict teacher registration, back up the database, and consider malware scanning for uploads.
- Uploaded files are limited to 10 MB and a file extension allowlist, but extension checks alone do not prove that a file is safe.
- The local development server should not be exposed directly to the internet.
