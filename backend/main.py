
import json
import os
import shutil
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv(override=True)

import database as db
from ocr import extract_text
from grader import grade

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOADS = os.path.join(BASE, "uploads")
os.makedirs(UPLOADS, exist_ok=True)

db.init_db()

app = FastAPI(title="AI Answer Sheet Checker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ---------------- MODELS ----------------

class Question(BaseModel):
    q: str
    answer: str
    marks: float = Field(gt=0)

class ExamIn(BaseModel):
    title: str
    questions: list[Question]

class RecheckIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

class OverrideIn(BaseModel):
    total: float = Field(ge=0)
    reason: str = Field(
        default="Teacher marks correction",
        min_length=1,
        max_length=1000
    )
    teacher_id: str | None = None

# ---------------- HELPER FUNCTIONS ----------------

def read_result(value):
    """Safely convert saved JSON into a Python dictionary."""
    if not value:
        return None

    if isinstance(value, dict):
        return value

    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None

def get_ai_total(result):
    """Get marks from an AI result, not teacher final marks."""
    result_data = read_result(result)

    if not result_data:
        return 0.0

    return float(result_data.get("total", 0))

def get_final_total(ai_total, teacher_total):
    """Teacher marks take priority when they are not NULL."""
    if teacher_total is not None:
        return float(teacher_total)

    return float(ai_total)

# ---------------- CREATE EXAM ----------------

@app.post("/api/exams")
def create_exam(e: ExamIn):

    if not e.title.strip():
        raise HTTPException(400, "Exam title is required")

    if not e.questions:
        raise HTTPException(400, "At least one question is required")

    with db.conn() as c:
        cur = c.execute(
            """
            INSERT INTO exams(title, questions)
            VALUES(?,?)
            """,
            (
                e.title.strip(),
                json.dumps(
                    [q.model_dump() for q in e.questions],
                    ensure_ascii=False
                )
            )
        )

        return {"id": cur.lastrowid}

# ---------------- LIST EXAMS ----------------

@app.get("/api/exams")
def list_exams():

    with db.conn() as c:
        rows = c.execute(
            "SELECT * FROM exams ORDER BY id DESC"
        ).fetchall()

        return [db.row(r) for r in rows]

# ---------------- SUBMIT ANSWER SHEET ----------------

@app.post("/api/submit")
async def submit(
    exam_id: int = Form(...),
    student_name: str = Form(...),
    file: UploadFile = File(...)
):

    if not student_name.strip():
        raise HTTPException(400, "Student name is required")

    with db.conn() as c:
        exam = c.execute(
            "SELECT * FROM exams WHERE id=?",
            (exam_id,)
        ).fetchone()

    if not exam:
        raise HTTPException(404, "Exam not found")

    ext = os.path.splitext(file.filename or "")[1] or ".jpg"

    path = os.path.join(
        UPLOADS,
        f"{uuid.uuid4().hex}{ext}"
    )

    try:
        with open(path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        extracted = extract_text(path)

        result = grade(
            json.loads(exam["questions"]),
            extracted
        )

        ai_json = json.dumps(result, ensure_ascii=False)

        with db.conn() as c:
            cur = c.execute(
                """
                INSERT INTO submissions(
                    exam_id,
                    student_name,
                    image_path,
                    extracted_text,
                    result,
                    ai_result,
                    total,
                    max_total,
                    status
                )
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    exam_id,
                    student_name.strip(),
                    path,
                    extracted,
                    ai_json,
                    ai_json,
                    result["total"],
                    result["max_total"],
                    "graded"
                )
            )

            sid = cur.lastrowid

    except Exception as ex:
        if os.path.exists(path):
            os.remove(path)

        raise HTTPException(
            500,
            f"Answer sheet checking failed: {ex}"
        )

    return {
        "id": sid,
        "extracted_text": extracted,
        "ai_result": result,
        "teacher_total": None,
        **result
    }

# ---------------- LIST ALL SUBMISSIONS ----------------

@app.get("/api/submissions")
def submissions():

    with db.conn() as c:
        rows = c.execute(
            """
            SELECT s.*, e.title AS exam_title
            FROM submissions s
            JOIN exams e ON e.id = s.exam_id
            ORDER BY s.id DESC
            """
        ).fetchall()

        return [db.row(r) for r in rows]

# ---------------- AI RECHECK ----------------

@app.post("/api/recheck/{sid}")
def recheck(sid: int, body: RecheckIn):

    reason = body.reason.strip()

    if not reason:
        raise HTTPException(
            400,
            "Rechecking reason is required"
        )

    with db.conn() as c:

        s = c.execute(
            "SELECT * FROM submissions WHERE id=?",
            (sid,)
        ).fetchone()

        if not s:
            raise HTTPException(404, "Answer sheet not found")

        exam = c.execute(
            "SELECT * FROM exams WHERE id=?",
            (s["exam_id"],)
        ).fetchone()

        if not exam:
            raise HTTPException(404, "Exam not found")

        # Previous latest AI result
        old_ai_result = read_result(s["result"])

        if not old_ai_result:
            raise HTTPException(
                400,
                "Previous AI result is missing. Rechecking cannot continue."
            )

        old_ai_total = float(old_ai_result.get("total", 0))

        # Preserve teacher marks
        teacher_total = s["teacher_total"]

        try:
            new_result = grade(
                json.loads(exam["questions"]),
                s["extracted_text"],
                reason
            )

        except Exception as ex:
            raise HTTPException(
                503,
                f"AI rechecking failed: {ex}"
            )

        new_ai_total = float(new_result["total"])

        # Teacher marks take priority
        final_total = get_final_total(
            new_ai_total,
            teacher_total
        )

        new_status = (
            "teacher_override"
            if teacher_total is not None
            else "rechecked"
        )

        new_json = json.dumps(
            new_result,
            ensure_ascii=False
        )

        old_json = json.dumps(
            old_ai_result,
            ensure_ascii=False
        )

        # Save history and update submission together
        c.execute(
            """
            INSERT INTO rechecks(
                submission_id,
                reason,
                old_total,
                new_total,
                result,
                old_result,
                action_type,
                teacher_id
            )
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                sid,
                reason,
                old_ai_total,
                new_ai_total,
                new_json,
                old_json,
                "ai_recheck",
                None
            )
        )

        # Original ai_result is NEVER modified
        c.execute(
            """
            UPDATE submissions
            SET result=?,
                total=?,
                status=?
            WHERE id=?
            """,
            (
                new_json,
                final_total,
                new_status,
                sid
            )
        )

    return {
        "ok": True,
        "submission_id": sid,
        "old_total": old_ai_total,
        "new_total": new_ai_total,
        "teacher_total": teacher_total,
        "final_total": final_total,
        "ai_result": new_result,
        "status": new_status
    }

# ---------------- TEACHER OVERRIDE ----------------

@app.put("/api/submissions/{sid}/override")
def override(sid: int, body: OverrideIn):

    reason = body.reason.strip()

    if not reason:
        raise HTTPException(
            400,
            "Teacher override reason is required"
        )

    with db.conn() as c:

        s = c.execute(
            "SELECT * FROM submissions WHERE id=?",
            (sid,)
        ).fetchone()

        if not s:
            raise HTTPException(
                404,
                "Submission not found"
            )

        max_marks = float(s["max_total"])

        if body.total > max_marks:
            raise HTTPException(
                400,
                f"Marks cannot exceed {max_marks}"
            )

        # Current latest AI result remains unchanged
        current_ai_result = read_result(s["result"])

        if not current_ai_result:
            raise HTTPException(
                400,
                "AI result is missing"
            )

        # Previous final marks
        old_final_total = float(s["total"])

        # New teacher final marks
        new_teacher_total = float(body.total)

        current_ai_json = json.dumps(
            current_ai_result,
            ensure_ascii=False
        )

        # Save teacher action in history
        c.execute(
            """
            INSERT INTO rechecks(
                submission_id,
                reason,
                old_total,
                new_total,
                result,
                old_result,
                action_type,
                teacher_id
            )
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                sid,
                reason,
                old_final_total,
                new_teacher_total,
                current_ai_json,
                current_ai_json,
                "teacher_override",
                body.teacher_id
            )
        )

        # Change teacher/final marks only
        # Do not modify original or latest AI result
        c.execute(
            """
            UPDATE submissions
            SET total=?,
                teacher_total=?,
                status='teacher_override'
            WHERE id=?
            """,
            (
                new_teacher_total,
                new_teacher_total,
                sid
            )
        )

    return {
        "ok": True,
        "submission_id": sid,
        "ai_result": current_ai_result,
        "old_total": old_final_total,
        "teacher_total": new_teacher_total,
        "final_total": new_teacher_total,
        "status": "teacher_override"
    }

# ---------------- COMPLETE CHECKING HISTORY ----------------

@app.get("/api/submissions/{sid}/history")
def submission_history(sid: int):

    with db.conn() as c:

        s = c.execute(
            "SELECT * FROM submissions WHERE id=?",
            (sid,)
        ).fetchone()

        if not s:
            raise HTTPException(
                404,
                "Submission not found"
            )

        history = c.execute(
            """
            SELECT *
            FROM rechecks
            WHERE submission_id=?
            ORDER BY id ASC
            """,
            (sid,)
        ).fetchall()

        original_result = read_result(s["ai_result"])
        latest_result = read_result(s["result"])

        teacher_total = s["teacher_total"]

        latest_ai_total = get_ai_total(latest_result)

        final_total = get_final_total(
            latest_ai_total,
            teacher_total
        )

        return {
            "submission_id": sid,
            "student_name": s["student_name"],
            "original_ai_result": original_result,
            "latest_ai_result": latest_result,
            "original_ai_total": get_ai_total(original_result),
            "latest_ai_total": latest_ai_total,
            "teacher_total": teacher_total,
            "final_total": final_total,
            "max_total": s["max_total"],
            "status": s["status"],
            "history": [db.row(r) for r in history]
        }

# ---------------- FRONTEND ----------------

app.mount(
    "/",
    StaticFiles(
        directory=os.path.join(BASE, "..", "frontend"),
        html=True
    ),
    name="frontend"
)