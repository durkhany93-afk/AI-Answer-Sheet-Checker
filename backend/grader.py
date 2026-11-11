
import json
import re
import time

from google.genai import types
from ocr import client, model_name

SYSTEM = (
    "You are a fair, consistent examiner. Grade the student's answer "
    "sheet against the model answers. Give partial marks for partially "
    "correct answers. Reply with ONLY valid JSON, no markdown."
)


def grade(questions, student_text, recheck_reason=None):

    prompt = {
        "questions": questions,
        "student_answer_sheet": student_text,
        "output_format": {
            "results": [
                {
                    "q_no": 1,
                    "awarded": 0,
                    "max": 0,
                    "feedback": "short reason"
                }
            ],
            "total": 0,
            "max_total": 0,
        },
    }

    if recheck_reason:
        prompt["recheck_request"] = (
            f"The student asked for a recheck: '{recheck_reason}'. "
            "Re-evaluate carefully and independently. "
            "Only change marks if the original grading was truly wrong."
        )

    for attempt in range(3):

        try:
            resp = client().models.generate_content(
                model=model_name(),
                contents=json.dumps(prompt, ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM,
                    response_mime_type="application/json",
                ),
            )

            if not resp.text:
                raise ValueError("Gemini returned an empty response.")

            text = re.sub(
                r"^```(?:json)?|```$",
                "",
                resp.text.strip(),
                flags=re.M
            ).strip()

            data = json.loads(text)

            data["total"] = sum(
                r["awarded"] for r in data["results"]
            )

            data["max_total"] = sum(
                r["max"] for r in data["results"]
            )

            return data

        except Exception as ex:

            error = str(ex).upper()

            temporary = (
                "503" in error
                or "UNAVAILABLE" in error
            )

            if temporary and attempt < 2:
                wait = 2 ** (attempt + 1)
                print(
                    f"Gemini temporarily unavailable. "
                    f"Retrying in {wait} seconds..."
                )
                time.sleep(wait)
                continue

            raise

