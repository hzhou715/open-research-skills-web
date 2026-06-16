import os
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import Flask, flash, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from npv_dcf import run_analysis


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "storage" / "uploads"
RESULT_DIR = BASE_DIR / "storage" / "results"
SKILL_DIR = BASE_DIR / "storage" / "skills"
SKILL_INDEX = SKILL_DIR / "skills.json"

app = Flask(__name__)
app.config["SECRET_KEY"] = "local-mvp-secret-key"
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024


MODULES = [
    {
        "name": "Publish / Contribute Skills",
        "slug": "publish",
        "label": "Publish",
        "summary": "Submit reusable research skill packages.",
    },
    {
        "name": "Skill Library",
        "slug": "library",
        "label": "Library",
        "summary": "Browse executable methods and examples.",
    },
    {
        "name": "Validation",
        "slug": "validation",
        "label": "Validation",
        "summary": "Check outputs against expected results.",
    },
    {
        "name": "Demo / Education Videos",
        "slug": "videos",
        "label": "Education",
        "summary": "Host short walkthroughs and teaching notes.",
    },
    {
        "name": "User Account Management",
        "slug": "account",
        "label": "Account",
        "summary": "Manage profiles, roles, and saved work.",
    },
]


def save_upload(field: str, run_dir: Path, required: bool = True) -> Path | None:
    uploaded = request.files.get(field)
    if uploaded is None or uploaded.filename == "":
        if required:
            raise ValueError(f"{field} is required.")
        return None
    filename = secure_filename(uploaded.filename)
    if not filename:
        raise ValueError(f"{field} has an invalid filename.")
    path = run_dir / filename
    uploaded.save(path)
    return path


def load_contributed_skills() -> list[dict[str, str]]:
    if not SKILL_INDEX.exists():
        return []
    try:
        return json.loads(SKILL_INDEX.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_contributed_skills(skills: list[dict[str, str]]) -> None:
    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    SKILL_INDEX.write_text(json.dumps(skills, indent=2), encoding="utf-8")


def save_skill_files(skill_id: str) -> list[dict[str, str]]:
    skill_file_dir = SKILL_DIR / skill_id / "files"
    skill_file_dir.mkdir(parents=True, exist_ok=True)
    saved_files: list[dict[str, str]] = []
    for uploaded in request.files.getlist("skill_files"):
        if uploaded.filename == "":
            continue
        filename = secure_filename(uploaded.filename)
        if not filename:
            continue
        uploaded.save(skill_file_dir / filename)
        saved_files.append({"filename": filename})
    return saved_files


def built_in_skills() -> list[dict[str, str]]:
    return [
        {
            "id": "npv-dcf",
            "name": "NPV-DCF Analysis",
            "status": "Executable MVP",
            "description": "Calculate NPV, IRR, and validation artifacts from uploaded cash flows.",
            "author": "Platform",
            "version": "1.0",
            "created_at": "Built-in",
            "href": url_for("npv_dcf_skill"),
            "files": [],
        }
    ]


@app.context_processor
def inject_globals():
    return {"modules": MODULES}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/library")
def library():
    contributed = load_contributed_skills()
    for skill in contributed:
        skill["href"] = url_for("skill_detail", skill_id=skill["id"])
    skills = built_in_skills() + contributed
    return render_template("library.html", skills=skills)


@app.route("/skills/npv-dcf", methods=["GET", "POST"])
def npv_dcf_skill():
    if request.method == "POST":
        run_id = datetime.utcnow().strftime("%Y%m%d%H%M%S") + "-" + uuid4().hex[:8]
        upload_dir = UPLOAD_DIR / run_id
        result_dir = RESULT_DIR / run_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        result_dir.mkdir(parents=True, exist_ok=True)

        try:
            cash_flows_path = save_upload("cash_flows", upload_dir)
            assumptions_path = save_upload("assumptions", upload_dir)
            expected_path = save_upload("expected_results", upload_dir, required=False)
            result = run_analysis(cash_flows_path, assumptions_path, expected_path, result_dir)
        except Exception as exc:
            flash(str(exc), "error")
            return redirect(url_for("npv_dcf_skill"))

        return render_template("results.html", result=result, run_id=run_id)

    return render_template("skill_npv.html")


@app.route("/validation")
def validation():
    return render_template("validation.html")


@app.route("/publish", methods=["GET", "POST"])
def publish():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        author = request.form.get("author", "").strip() or "Anonymous"
        version = request.form.get("version", "").strip() or "0.1"
        inputs = request.form.get("inputs", "").strip()
        outputs = request.form.get("outputs", "").strip()

        if not name or not description:
            flash("Skill name and description are required.", "error")
            return redirect(url_for("publish"))

        skill_id = datetime.utcnow().strftime("%Y%m%d%H%M%S") + "-" + uuid4().hex[:8]
        files = save_skill_files(skill_id)
        skill = {
            "id": skill_id,
            "name": name,
            "description": description,
            "author": author,
            "version": version,
            "inputs": inputs,
            "outputs": outputs,
            "status": "Submitted",
            "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "files": files,
        }
        skills = load_contributed_skills()
        skills.insert(0, skill)
        save_contributed_skills(skills)
        flash("Skill saved to the library.", "success")
        return redirect(url_for("skill_detail", skill_id=skill_id))

    return render_template("publish.html")


@app.route("/skills/contributed/<skill_id>")
def skill_detail(skill_id: str):
    skill = next((item for item in load_contributed_skills() if item["id"] == skill_id), None)
    if skill is None:
        flash("Skill not found.", "error")
        return redirect(url_for("library"))
    return render_template("skill_detail.html", skill=skill)


@app.route("/skills/contributed/<skill_id>/files/<filename>")
def skill_file(skill_id: str, filename: str):
    safe_skill_id = secure_filename(skill_id)
    safe_filename = secure_filename(filename)
    return send_from_directory(SKILL_DIR / safe_skill_id / "files", safe_filename, as_attachment=True)


@app.route("/videos")
def videos():
    return render_template("videos.html")


@app.route("/account")
def account():
    return render_template("account.html")


@app.route("/download/<run_id>/<filename>")
def download(run_id: str, filename: str):
    safe_run_id = secure_filename(run_id)
    safe_filename = secure_filename(filename)
    return send_from_directory(RESULT_DIR / safe_run_id, safe_filename, as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
