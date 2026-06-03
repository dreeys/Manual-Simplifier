import os
import json
import uuid
import sqlite3
import fitz  # PyMuPDF
from groq import Groq
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '..', '.env'))

GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
DB_PATH = os.path.join(BASE_DIR, 'guides.db')
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
MAX_CHARS = 6_000

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB
app.pending_jobs = {}


SYSTEM_PROMPT = """You are a technical documentation specialist who transforms complex product manuals into premium quick-start guides. Your output must be clear enough for a first-time user to succeed without referring to the original manual.

OUTPUT FORMAT: Respond with a single valid JSON object matching the schema below. Do not include any text outside the JSON. Do not use markdown code fences."""

USER_TASK = """---
TASK: Transform this manual into a simplified quick-start guide.

Rules:
1. Extract the 4-5 most important procedural steps (assembly, setup, first use)
2. Skip warranty pages, legal disclaimers, specifications tables, parts lists
3. Write at a Grade 8 reading level
4. Warnings must be genuine safety risks only — not generic advice like "read the manual first"

Return this exact JSON schema:
{
  "title": "string — product name from the manual",
  "summary": "string — one sentence describing what this product does",
  "total_steps": number,
  "steps": [
    {
      "step_number": number,
      "title": "string — 4-6 word action phrase, e.g. 'Attach the side panels'",
      "instructions": "string — 2-4 sentences of clear instructions",
      "why_it_matters": "string — one sentence explaining the purpose",
      "warnings": ["string"] or []
    }
  ]
}"""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS guides (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            filename    TEXT NOT NULL,
            title       TEXT,
            page_count  INTEGER,
            status      TEXT NOT NULL DEFAULT 'processing',
            guide_json  TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def extract_pdf_content(filepath):
    doc = fitz.open(filepath)
    pages = []
    for i, page in enumerate(doc):
        pages.append({
            "page": i + 1,
            "text": page.get_text("text").strip(),
            "has_images": len(page.get_images(full=True)) > 0
        })
    page_count = len(doc)
    doc.close()
    return pages, page_count


def build_manual_text(pages):
    parts = []
    for p in pages:
        if p["text"]:
            img_note = " [contains diagrams]" if p["has_images"] else ""
            parts.append(f"--- Page {p['page']}{img_note} ---\n{p['text']}")
    return "\n\n".join(parts)


def call_groq(manual_text, page_count):
    if len(manual_text) > MAX_CHARS:
        manual_text = (
            manual_text[:4_500]
            + f"\n\n[... content truncated — this is a {page_count}-page document. "
            "Focus on extracting the core assembly/setup procedure from what is shown above ...]\n\n"
            + manual_text[-1_500:]
        )

    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"MANUAL CONTENT:\n{manual_text}\n\n{USER_TASK}"}
        ],
        max_tokens=2000,
        temperature=0.3
    )

    raw = response.choices[0].message.content.strip()

    import sys
    print("=== RAW MODEL RESPONSE ===", file=sys.stderr)
    print(raw[:2000], file=sys.stderr)
    print("=== END ===", file=sys.stderr)

    # Strip accidental markdown fences
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:])
        if raw.startswith("json"):
            raw = raw[4:]
        if raw.endswith("```"):
            raw = raw[:-3].strip()

    return json.loads(raw)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    if "pdf" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["pdf"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted"}), 400

    filename = file.filename
    save_name = f"{uuid.uuid4().hex}.pdf"
    save_path = os.path.join(UPLOAD_DIR, save_name)
    file.save(save_path)

    try:
        pages, page_count = extract_pdf_content(save_path)
    except Exception as e:
        os.remove(save_path)
        return jsonify({"error": "Could not read PDF — it may be encrypted or corrupt"}), 500

    conn = get_db()
    cur = conn.execute(
        "INSERT INTO guides (filename, page_count, status) VALUES (?, ?, 'processing')",
        (filename, page_count)
    )
    conn.commit()
    job_id = cur.lastrowid
    conn.close()

    # Store the extracted text temporarily keyed by job_id using a simple in-memory dict
    # (sufficient for a single-user local tool; no persistence needed between server restarts)
    app.pending_jobs[job_id] = {
        "save_path": save_path,
        "pages": pages,
        "page_count": page_count
    }

    return jsonify({"job_id": job_id, "page_count": page_count, "filename": filename}), 200


@app.route("/api/process/<int:job_id>", methods=["GET"])
def process(job_id):
    job = app.pending_jobs.get(job_id)
    if not job:
        # Check if already processed
        conn = get_db()
        row = conn.execute("SELECT * FROM guides WHERE id=?", (job_id,)).fetchone()
        conn.close()
        if row and row["status"] == "done":
            return jsonify(json.loads(row["guide_json"])), 200
        return jsonify({"error": "Job not found or already expired"}), 404

    save_path = job["save_path"]
    pages = job["pages"]
    page_count = job["page_count"]

    try:
        manual_text = build_manual_text(pages)
        guide_data = call_groq(manual_text, page_count)

        conn = get_db()
        conn.execute(
            "UPDATE guides SET status='done', title=?, guide_json=? WHERE id=?",
            (guide_data.get("title", "Untitled Guide"), json.dumps(guide_data), job_id)
        )
        conn.commit()
        conn.close()

        del app.pending_jobs[job_id]
        return jsonify(guide_data), 200

    except json.JSONDecodeError:
        conn = get_db()
        conn.execute("UPDATE guides SET status='error' WHERE id=?", (job_id,))
        conn.commit()
        conn.close()
        return jsonify({"error": "AI returned malformed response — please try again"}), 500

    except Exception as e:
        conn = get_db()
        conn.execute("UPDATE guides SET status='error' WHERE id=?", (job_id,))
        conn.commit()
        conn.close()
        return jsonify({"error": f"AI processing failed: {str(e)}"}), 500

    finally:
        if os.path.exists(save_path):
            os.remove(save_path)
        app.pending_jobs.pop(job_id, None)


@app.route("/api/guides", methods=["GET"])
def list_guides():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, filename, title, page_count, created_at FROM guides WHERE status='done' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/guides/<int:guide_id>", methods=["GET"])
def get_guide(guide_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM guides WHERE id=? AND status='done'", (guide_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Guide not found"}), 404
    return jsonify(json.loads(row["guide_json"])), 200


@app.route("/api/guides/<int:guide_id>", methods=["DELETE"])
def delete_guide(guide_id):
    conn = get_db()
    row = conn.execute("SELECT id FROM guides WHERE id=?", (guide_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "not found"}), 404
    conn.execute("DELETE FROM guides WHERE id=?", (guide_id,))
    conn.commit()
    conn.close()
    return "", 204


if __name__ == "__main__":
    init_db()
    print("Guide Simplifier running at http://localhost:5001")
    app.run(debug=True, port=5001)
