import os
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import Flask, Response, flash, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from npv_dcf import run_analysis


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "storage" / "uploads"
RESULT_DIR = BASE_DIR / "storage" / "results"
SKILL_DIR = BASE_DIR / "storage" / "skills"
SKILL_INDEX = SKILL_DIR / "skills.json"
DATA_DIR = BASE_DIR / "data"
SUBMITTED_SKILLS_INDEX = DATA_DIR / "submitted_skills.json"
SUBMITTED_SKILLS_UPLOAD_DIR = BASE_DIR / "uploads" / "submitted_skills"

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

SAMPLE_SKILLS = [
    {
        "id": "npv-dcf",
        "name": "NPV-DCF Analysis",
        "research_type": "Empirical / Financial Analysis",
        "description": "Calculates NPV, IRR, and investment decision from cash-flow inputs.",
        "input_type": "CSV + assumptions file",
        "output_type": "results CSV + validation report",
        "validation_status": "Validated",
        "author": "Open Research Skills Team",
        "version": "1.0",
        "purpose": "Evaluate investment value from discounted cash-flow data.",
        "procedure": "Upload cash flows, parse assumptions, calculate net cash flow, NPV, IRR, and compare expected results.",
        "validation_standard": "Validated against expected NPV and IRR values when expected_results.csv is provided.",
        "example_files": ["cash_flows.csv", "assumptions.md", "expected_results.csv"],
        "executable": True,
    },
    {
        "id": "bidding-collusion-coding",
        "name": "Bidding Collusion Document Coding",
        "research_type": "Qualitative Analysis",
        "description": "Extracts and codes collusion behavior from court judgment documents.",
        "input_type": "legal text document",
        "output_type": "structured coding table",
        "validation_status": "Tested",
        "author": "Open Research Skills Team",
        "version": "0.1",
        "purpose": "Support structured qualitative coding of collusion evidence.",
        "procedure": "Upload legal text, identify actors and behaviors, assign codes, and export a coding table.",
        "validation_standard": "Tested on sample judgment excerpts with manual review.",
        "example_files": ["judgment.txt", "coding_schema.md"],
        "executable": False,
    },
    {
        "id": "literature-screening-theme-coding",
        "name": "Literature Screening and Theme Coding",
        "research_type": "Literature Review",
        "description": "Screens papers and extracts research themes using predefined criteria.",
        "input_type": "paper list / abstracts",
        "output_type": "screening table + theme summary",
        "validation_status": "Draft",
        "author": "Open Research Skills Team",
        "version": "0.1",
        "purpose": "Make literature screening criteria explicit and reusable.",
        "procedure": "Load paper records, apply inclusion criteria, code themes, and summarize findings.",
        "validation_standard": "Draft workflow pending inter-coder agreement testing.",
        "example_files": ["abstracts.csv", "screening_criteria.md"],
        "executable": False,
    },
    {
        "id": "case-study-evidence-extraction",
        "name": "Case Study Evidence Extraction",
        "research_type": "Case Study",
        "description": "Extracts timeline, actors, decisions, and evidence from case documents.",
        "input_type": "case documents",
        "output_type": "evidence table + case summary",
        "validation_status": "Draft",
        "author": "Open Research Skills Team",
        "version": "0.1",
        "purpose": "Organize case evidence into a transparent analytical record.",
        "procedure": "Review documents, extract timeline events, identify actors, and compile evidence.",
        "validation_standard": "Draft workflow pending case-level replication tests.",
        "example_files": ["case_documents.zip", "extraction_template.csv"],
        "executable": False,
    },
    {
        "id": "optimization-model-formulation",
        "name": "Optimization Model Formulation",
        "research_type": "Optimization",
        "description": "Converts a planning problem into decision variables, objective function, and constraints.",
        "input_type": "problem description",
        "output_type": "model formulation",
        "validation_status": "Draft",
        "author": "Open Research Skills Team",
        "version": "0.1",
        "purpose": "Translate planning problems into formal optimization models.",
        "procedure": "Identify decisions, define objective, list constraints, and produce a structured formulation.",
        "validation_standard": "Draft workflow pending benchmark problem review.",
        "example_files": ["problem_statement.md", "formulation_template.md"],
        "executable": False,
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


def safe_folder_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "submitted-skill"


def load_submitted_skills() -> list[dict[str, str]]:
    if not SUBMITTED_SKILLS_INDEX.exists():
        return []
    try:
        return json.loads(SUBMITTED_SKILLS_INDEX.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def save_submitted_skills(skills: list[dict[str, str]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SUBMITTED_SKILLS_INDEX.write_text(json.dumps(skills, indent=2), encoding="utf-8")


def submitted_skill_folder(skill_name: str) -> tuple[str, Path]:
    base_name = safe_folder_name(skill_name)
    folder_name = base_name
    counter = 2
    while (SUBMITTED_SKILLS_UPLOAD_DIR / folder_name).exists():
        folder_name = f"{base_name}-{counter}"
        counter += 1
    folder = SUBMITTED_SKILLS_UPLOAD_DIR / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    return folder_name, folder


def save_publish_files(folder: Path) -> list[dict[str, str]]:
    saved_files: list[dict[str, str]] = []
    upload_fields = [
        "skill_md",
        "sample_input_files",
        "expected_output_files",
        "reference_files",
        "validation_report",
    ]
    for field in upload_fields:
        for uploaded in request.files.getlist(field):
            if uploaded.filename == "":
                continue
            filename = secure_filename(uploaded.filename)
            if not filename:
                continue
            uploaded.save(folder / filename)
            saved_files.append({"field": field, "filename": filename})
    return saved_files


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


def normalize_skill(skill: dict[str, str], contributed: bool = False) -> dict[str, str]:
    normalized = {
        "id": skill["id"],
        "name": skill["name"],
        "research_type": skill.get("research_type") or "Contributed Skill",
        "description": skill.get("description", ""),
        "input_type": skill.get("input_type") or skill.get("inputs") or "User-defined inputs",
        "output_type": skill.get("output_type") or skill.get("outputs") or "User-defined outputs",
        "validation_status": skill.get("validation_status") or skill.get("status") or "Draft",
        "author": skill.get("author", "Anonymous"),
        "version": skill.get("version", "0.1"),
        "purpose": skill.get("purpose") or skill.get("description", ""),
        "procedure": skill.get("procedure") or "Procedure summary will be added by the contributor.",
        "validation_standard": skill.get("validation_standard") or "Validation standard not yet specified.",
        "example_files": skill.get("example_files", []),
        "files": skill.get("files", []),
        "folder": skill.get("folder", ""),
        "created_at": skill.get("created_at", "Sample"),
        "contributed": contributed,
        "executable": skill.get("executable", False),
    }
    normalized["detail_href"] = url_for("library_skill_detail", skill_id=normalized["id"])
    normalized["use_href"] = url_for("use_skill", skill_id=normalized["id"])
    normalized["comment_href"] = f"{normalized['detail_href']}#comments"
    normalized["package_href"] = url_for("download_skill_package", skill_id=normalized["id"])
    normalized["status_class"] = normalized["validation_status"].lower().replace(" ", "-").replace("/", "-")
    return normalized


def all_library_skills() -> list[dict[str, str]]:
    sample_skills = [normalize_skill(skill) for skill in SAMPLE_SKILLS]
    contributed = [normalize_skill(skill, contributed=True) for skill in load_contributed_skills()]
    submitted = [normalize_skill(skill, contributed=True) for skill in load_submitted_skills()]
    return sample_skills + contributed + submitted


def find_library_skill(skill_id: str) -> dict[str, str] | None:
    return next((skill for skill in all_library_skills() if skill["id"] == skill_id), None)


@app.context_processor
def inject_globals():
    return {"modules": MODULES}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/library")
def library():
    skills = all_library_skills()
    featured_ids = {"npv-dcf", "bidding-collusion-coding", "literature-screening-theme-coding"}
    featured_skills = [skill for skill in skills if skill["id"] in featured_ids]
    research_types = sorted({skill["research_type"] for skill in skills})
    validation_statuses = sorted({skill["validation_status"] for skill in skills})
    input_types = sorted({skill["input_type"] for skill in skills})
    output_types = sorted({skill["output_type"] for skill in skills})
    return render_template(
        "library.html",
        skills=skills,
        featured_skills=featured_skills,
        research_types=research_types,
        validation_statuses=validation_statuses,
        input_types=input_types,
        output_types=output_types,
    )


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
        form_data = request.form.to_dict()
        name = form_data.get("name", "").strip()
        description = form_data.get("description", "").strip()
        skill_md = request.files.get("skill_md")
        errors: dict[str, str] = {}

        if not name:
            errors["name"] = "Skill Name is required."
        if not description:
            errors["description"] = "Short Description is required."
        if skill_md is None or skill_md.filename == "":
            errors["skill_md"] = "SKILL.md upload is required."
        elif secure_filename(skill_md.filename).lower() != "skill.md":
            errors["skill_md"] = "Upload a file named SKILL.md."

        if errors:
            return render_template("publish.html", errors=errors, form_data=form_data), 400

        folder_name, folder = submitted_skill_folder(name)
        files = save_publish_files(folder)
        submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        skill = {
            "id": folder_name,
            "name": name,
            "description": description,
            "short_description": description,
            "author": form_data.get("author", "").strip() or "Anonymous",
            "institution": form_data.get("institution", "").strip(),
            "contact_email": form_data.get("contact_email", "").strip(),
            "related_paper_title": form_data.get("related_paper_title", "").strip(),
            "doi_url": form_data.get("doi_url", "").strip(),
            "research_type": form_data.get("research_type", "").strip() or "Contributed Skill",
            "purpose": form_data.get("purpose", "").strip(),
            "input_type": form_data.get("required_inputs", "").strip() or "User-defined inputs",
            "output_type": form_data.get("expected_outputs", "").strip() or "User-defined outputs",
            "procedure": form_data.get("procedure_summary", "").strip(),
            "decision_rules": form_data.get("decision_rules", "").strip(),
            "validation_standard": form_data.get("validation_standard", "").strip(),
            "known_limitations": form_data.get("known_limitations", "").strip(),
            "validation_status": form_data.get("skill_status", "Draft"),
            "visibility": form_data.get("visibility", "Private Draft"),
            "status": form_data.get("skill_status", "Draft"),
            "version": "0.1",
            "created_at": submitted_at,
            "submitted_at": submitted_at,
            "folder": folder_name,
            "files": files,
        }
        skills = load_submitted_skills()
        skills.insert(0, skill)
        save_submitted_skills(skills)
        return redirect(url_for("submission_confirmation", skill_id=folder_name))

    return render_template("publish.html", errors={}, form_data={})


@app.route("/publish/confirmation/<skill_id>")
def submission_confirmation(skill_id: str):
    skill = next((item for item in load_submitted_skills() if item["id"] == skill_id), None)
    if skill is None:
        flash("Submission not found.", "error")
        return redirect(url_for("publish"))
    return render_template("submission_confirmation.html", skill=skill)


@app.route("/my-submitted-skills")
def my_submitted_skills():
    return render_template("my_submitted_skills.html", skills=load_submitted_skills())


@app.route("/library/skills/<skill_id>")
def library_skill_detail(skill_id: str):
    skill = find_library_skill(skill_id)
    if skill is None:
        flash("Skill not found.", "error")
        return redirect(url_for("library"))
    return render_template("skill_detail.html", skill=skill)


@app.route("/skills/contributed/<skill_id>")
def skill_detail(skill_id: str):
    return redirect(url_for("library_skill_detail", skill_id=skill_id))


@app.route("/skills/use/<skill_id>")
def use_skill(skill_id: str):
    skill = find_library_skill(skill_id)
    if skill is None:
        flash("Skill not found.", "error")
        return redirect(url_for("library"))
    if skill_id == "npv-dcf":
        return redirect(url_for("npv_dcf_skill"))
    flash("This skill is listed for review. Execution will be added in a later MVP iteration.", "success")
    return redirect(url_for("library_skill_detail", skill_id=skill_id))


@app.route("/skills/package/<skill_id>")
def download_skill_package(skill_id: str):
    skill = find_library_skill(skill_id)
    if skill is None:
        flash("Skill not found.", "error")
        return redirect(url_for("library"))
    lines = [
        f"# {skill['name']}",
        "",
        f"- Research type: {skill['research_type']}",
        f"- Validation status: {skill['validation_status']}",
        f"- Author: {skill['author']}",
        f"- Version: {skill['version']}",
        "",
        "## Purpose",
        skill["purpose"],
        "",
        "## Required Inputs",
        skill["input_type"],
        "",
        "## Expected Outputs",
        skill["output_type"],
        "",
        "## Procedure Summary",
        skill["procedure"],
        "",
        "## Validation Standard",
        skill["validation_standard"],
        "",
    ]
    content = "\n".join(lines)
    filename = secure_filename(f"{skill['name'].lower().replace(' ', '-')}-package.md")
    return Response(
        content,
        mimetype="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/skills/contributed/<skill_id>/files/<filename>")
def skill_file(skill_id: str, filename: str):
    safe_skill_id = secure_filename(skill_id)
    safe_filename = secure_filename(filename)
    return send_from_directory(SKILL_DIR / safe_skill_id / "files", safe_filename, as_attachment=True)


@app.route("/uploads/submitted_skills/<skill_id>/<filename>")
def submitted_skill_file(skill_id: str, filename: str):
    safe_skill_id = secure_filename(skill_id)
    safe_filename = secure_filename(filename)
    return send_from_directory(SUBMITTED_SKILLS_UPLOAD_DIR / safe_skill_id, safe_filename, as_attachment=True)


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
