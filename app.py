import os
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (
    Flask, abort, flash, g, redirect, render_template, request,
    send_from_directory, session, url_for
)
from flask_wtf.csrf import CSRFProtect
from openpyxl import load_workbook
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = INSTANCE_DIR / "teacher_platform.db"

INSTANCE_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__, instance_path=str(INSTANCE_DIR))
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", "dev-only-change-this-before-deployment"),
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,  # 10 MB maximum request size
    UPLOAD_FOLDER=str(UPLOAD_DIR),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
csrf = CSRFProtect(app)

ALLOWED_LECTURE_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "txt", "png", "jpg", "jpeg"}
ALLOWED_EXCEL_EXTENSIONS = {"xlsx"}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            student_code TEXT,
            full_name TEXT NOT NULL,
            class_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            mark REAL NOT NULL,
            max_mark REAL NOT NULL,
            observation TEXT NOT NULL DEFAULT '',
            assessment_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS lectures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
        );
    """)
    db.commit()
    db.close()


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if "teacher_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(**kwargs)
    return wrapped_view


def current_teacher_id():
    teacher_id = session.get("teacher_id")
    if not teacher_id:
        abort(401)
    return int(teacher_id)


def allowed_file(filename, allowed_extensions):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions


@app.errorhandler(413)
def too_large(_error):
    flash("That file is too large. The maximum upload size is 10 MB.", "error")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/")
def index():
    if session.get("teacher_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not name or not email or not password:
            flash("Please complete every field.", "error")
        elif len(password) < 8:
            flash("Use a password with at least 8 characters.", "error")
        elif password != confirm:
            flash("The passwords do not match.", "error")
        else:
            db = get_db()
            try:
                cursor = db.execute(
                    "INSERT INTO teachers (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (name, email, generate_password_hash(password), datetime.now().isoformat(timespec="seconds"))
                )
                db.commit()
                session.clear()
                session["teacher_id"] = cursor.lastrowid
                session["teacher_name"] = name
                flash("Your teacher account has been created.", "success")
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                flash("An account with that email already exists.", "error")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        teacher = get_db().execute(
            "SELECT * FROM teachers WHERE email = ?", (email,)
        ).fetchone()

        if teacher and check_password_hash(teacher["password_hash"], password):
            session.clear()
            session["teacher_id"] = teacher["id"]
            session["teacher_name"] = teacher["name"]
            return redirect(url_for("dashboard"))
        flash("Email or password is incorrect.", "error")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have logged out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    teacher_id = current_teacher_id()
    student_count = db.execute(
        "SELECT COUNT(*) AS total FROM students WHERE teacher_id = ?", (teacher_id,)
    ).fetchone()["total"]
    assessment_count = db.execute(
        "SELECT COUNT(*) AS total FROM assessments WHERE teacher_id = ?", (teacher_id,)
    ).fetchone()["total"]
    lecture_count = db.execute(
        "SELECT COUNT(*) AS total FROM lectures WHERE teacher_id = ?", (teacher_id,)
    ).fetchone()["total"]
    recent_assessments = db.execute("""
        SELECT a.*, s.full_name, s.class_name
        FROM assessments a JOIN students s ON s.id = a.student_id
        WHERE a.teacher_id = ?
        ORDER BY a.assessment_date DESC, a.id DESC LIMIT 5
    """, (teacher_id,)).fetchall()
    return render_template(
        "dashboard.html",
        student_count=student_count,
        assessment_count=assessment_count,
        lecture_count=lecture_count,
        recent_assessments=recent_assessments
    )


@app.route("/students", methods=["GET", "POST"])
@login_required
def students():
    db = get_db()
    teacher_id = current_teacher_id()

    if request.method == "POST":
        code = request.form.get("student_code", "").strip()
        name = request.form.get("full_name", "").strip()
        class_name = request.form.get("class_name", "").strip()
        if not name:
            flash("Student name is required.", "error")
        else:
            db.execute(
                "INSERT INTO students (teacher_id, student_code, full_name, class_name, created_at) VALUES (?, ?, ?, ?, ?)",
                (teacher_id, code or None, name, class_name, datetime.now().isoformat(timespec="seconds"))
            )
            db.commit()
            flash("Student added.", "success")
            return redirect(url_for("students"))

    rows = db.execute(
        "SELECT * FROM students WHERE teacher_id = ? ORDER BY class_name, full_name",
        (teacher_id,)
    ).fetchall()
    return render_template("students.html", students=rows)


@app.route("/students/import", methods=["POST"])
@login_required
def import_students():
    teacher_id = current_teacher_id()
    uploaded = request.files.get("excel_file")

    if not uploaded or not uploaded.filename:
        flash("Choose an Excel .xlsx file first.", "error")
        return redirect(url_for("students"))
    if not allowed_file(uploaded.filename, ALLOWED_EXCEL_EXTENSIONS):
        flash("Please upload an .xlsx file. Older .xls files are not supported.", "error")
        return redirect(url_for("students"))

    try:
        workbook = load_workbook(uploaded, read_only=True, data_only=True)
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, None)
        if not header:
            flash("The spreadsheet is empty.", "error")
            return redirect(url_for("students"))

        normalized = [str(value).strip().lower() if value is not None else "" for value in header]
        # Accepted column names: name/full_name/student name; code/student_code/id; class/class_name
        name_keys = {"name", "full_name", "student name", "student_name"}
        code_keys = {"code", "student_code", "student id", "student_id", "id"}
        class_keys = {"class", "class_name", "group"}
        name_index = next((i for i, value in enumerate(normalized) if value in name_keys), None)
        code_index = next((i for i, value in enumerate(normalized) if value in code_keys), None)
        class_index = next((i for i, value in enumerate(normalized) if value in class_keys), None)

        if name_index is None:
            workbook.close()
            flash("A header column named Name, Full Name, or Student Name is required.", "error")
            return redirect(url_for("students"))

        imported = 0
        db = get_db()
        for row in rows:
            if name_index >= len(row) or row[name_index] is None:
                continue
            name = str(row[name_index]).strip()
            if not name:
                continue
            code = str(row[code_index]).strip() if code_index is not None and code_index < len(row) and row[code_index] is not None else ""
            class_name = str(row[class_index]).strip() if class_index is not None and class_index < len(row) and row[class_index] is not None else ""
            db.execute(
                "INSERT INTO students (teacher_id, student_code, full_name, class_name, created_at) VALUES (?, ?, ?, ?, ?)",
                (teacher_id, code or None, name, class_name, datetime.now().isoformat(timespec="seconds"))
            )
            imported += 1
        db.commit()
        workbook.close()
        flash(f"Imported {imported} student(s). Check the list for duplicates.", "success")
    except Exception:
        flash("The file could not be read. Check that it is a valid .xlsx workbook.", "error")

    return redirect(url_for("students"))


@app.route("/students/<int:student_id>/delete", methods=["POST"])
@login_required
def delete_student(student_id):
    db = get_db()
    result = db.execute(
        "DELETE FROM students WHERE id = ? AND teacher_id = ?",
        (student_id, current_teacher_id())
    )
    db.commit()
    if result.rowcount:
        flash("Student and their assessment records deleted.", "success")
    else:
        flash("Student not found.", "error")
    return redirect(url_for("students"))


@app.route("/assessments", methods=["GET", "POST"])
@login_required
def assessments():
    db = get_db()
    teacher_id = current_teacher_id()

    if request.method == "POST":
        student_id = request.form.get("student_id", type=int)
        title = request.form.get("title", "").strip()
        mark = request.form.get("mark", type=float)
        max_mark = request.form.get("max_mark", type=float)
        observation = request.form.get("observation", "").strip()
        assessment_date = request.form.get("assessment_date", "").strip() or datetime.now().date().isoformat()

        student = db.execute(
            "SELECT id FROM students WHERE id = ? AND teacher_id = ?",
            (student_id, teacher_id)
        ).fetchone() if student_id else None

        if not student:
            flash("Choose one of your students.", "error")
        elif not title:
            flash("Assessment title is required.", "error")
        elif mark is None or max_mark is None or max_mark <= 0 or mark < 0 or mark > max_mark:
            flash("Enter a valid mark between 0 and the maximum mark.", "error")
        else:
            db.execute("""
                INSERT INTO assessments
                (teacher_id, student_id, title, mark, max_mark, observation, assessment_date, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (teacher_id, student_id, title, mark, max_mark, observation,
                  assessment_date, datetime.now().isoformat(timespec="seconds")))
            db.commit()
            flash("Assessment saved.", "success")
            return redirect(url_for("assessments"))

    student_rows = db.execute(
        "SELECT id, full_name, class_name FROM students WHERE teacher_id = ? ORDER BY full_name",
        (teacher_id,)
    ).fetchall()
    assessment_rows = db.execute("""
        SELECT a.*, s.full_name, s.class_name
        FROM assessments a JOIN students s ON s.id = a.student_id
        WHERE a.teacher_id = ?
        ORDER BY a.assessment_date DESC, a.id DESC
    """, (teacher_id,)).fetchall()
    return render_template("assessments.html", students=student_rows, assessments=assessment_rows,
                           today=datetime.now().date().isoformat())


@app.route("/assessments/<int:assessment_id>/delete", methods=["POST"])
@login_required
def delete_assessment(assessment_id):
    db = get_db()
    result = db.execute(
        "DELETE FROM assessments WHERE id = ? AND teacher_id = ?",
        (assessment_id, current_teacher_id())
    )
    db.commit()
    flash("Assessment deleted." if result.rowcount else "Assessment not found.",
          "success" if result.rowcount else "error")
    return redirect(url_for("assessments"))


@app.route("/lectures", methods=["GET", "POST"])
@login_required
def lectures():
    db = get_db()
    teacher_id = current_teacher_id()
    teacher_folder = UPLOAD_DIR / str(teacher_id)
    teacher_folder.mkdir(parents=True, exist_ok=True)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        uploaded = request.files.get("lecture_file")
        if not title:
            flash("Lecture title is required.", "error")
        elif not uploaded or not uploaded.filename:
            flash("Choose a file to upload.", "error")
        elif not allowed_file(uploaded.filename, ALLOWED_LECTURE_EXTENSIONS):
            flash("Unsupported file type. Allowed: PDF, DOC/DOCX, PPT/PPTX, TXT, PNG, JPG.", "error")
        else:
            original = secure_filename(uploaded.filename)
            stored = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{original}"
            uploaded.save(teacher_folder / stored)
            db.execute(
                "INSERT INTO lectures (teacher_id, title, original_filename, stored_filename, uploaded_at) VALUES (?, ?, ?, ?, ?)",
                (teacher_id, title, original, stored, datetime.now().isoformat(timespec="seconds"))
            )
            db.commit()
            flash("Lecture uploaded.", "success")
            return redirect(url_for("lectures"))

    rows = db.execute(
        "SELECT * FROM lectures WHERE teacher_id = ? ORDER BY uploaded_at DESC",
        (teacher_id,)
    ).fetchall()
    return render_template("lectures.html", lectures=rows)


@app.route("/lectures/<int:lecture_id>/download")
@login_required
def download_lecture(lecture_id):
    lecture = get_db().execute(
        "SELECT * FROM lectures WHERE id = ? AND teacher_id = ?",
        (lecture_id, current_teacher_id())
    ).fetchone()
    if not lecture:
        abort(404)
    return send_from_directory(
        str(UPLOAD_DIR / str(current_teacher_id())),
        lecture["stored_filename"],
        as_attachment=True,
        download_name=lecture["original_filename"]
    )


@app.route("/lectures/<int:lecture_id>/delete", methods=["POST"])
@login_required
def delete_lecture(lecture_id):
    db = get_db()
    lecture = db.execute(
        "SELECT * FROM lectures WHERE id = ? AND teacher_id = ?",
        (lecture_id, current_teacher_id())
    ).fetchone()
    if lecture:
        file_path = UPLOAD_DIR / str(current_teacher_id()) / lecture["stored_filename"]
        if file_path.exists():
            file_path.unlink()
        db.execute("DELETE FROM lectures WHERE id = ? AND teacher_id = ?",
                   (lecture_id, current_teacher_id()))
        db.commit()
        flash("Lecture deleted.", "success")
    else:
        flash("Lecture not found.", "error")
    return redirect(url_for("lectures"))


@app.route("/students-template")
@login_required
def students_template():
    # Download a small CSV template, which Excel can open and save as .xlsx.
    from flask import Response
    content = "student_code,full_name,class_name\nS001,Example Student,Class 1\n"
    return Response(
        content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=students-template.csv"}
    )


with app.app_context():
    init_db()


if __name__ == "__main__":
    # Local development only. Do not use Flask's development server for public deployment.
    app.run(debug=True)
