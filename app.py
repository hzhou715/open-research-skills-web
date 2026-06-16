import os
import json
import re
import zipfile
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


def unique_folder(folder: Path) -> Path:
    if not folder.exists():
        return folder
    counter = 2
    while True:
        candidate = folder.with_name(f"{folder.name}-{counter}")
        if not candidate.exists():
            return candidate
        counter += 1


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


def safe_extract_zip(zip_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            member_path = destination / member.filename
            if not member_path.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Uploaded zip contains an unsafe file path.")
        archive.extractall(destination)


def find_skill_md(folder: Path) -> Path | None:
    for path in folder.rglob("*"):
        if path.is_file() and path.name.lower() == "skill.md":
            return path
    return None


def parse_front_matter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    match = re.match(r"^---\s*\n(.*?)\n---\s*", text, flags=re.DOTALL)
    if not match:
        return {}
    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip().lower()] = value.strip().strip("\"'")
    return metadata


def extract_heading_section(text: str, heading: str) -> str:
    pattern = rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)"
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def extract_skill_metadata(text: str) -> dict[str, str]:
    front_matter = parse_front_matter(text)
    title_match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    purpose = extract_heading_section(text, "Purpose")
    inputs = extract_heading_section(text, "Inputs")
    outputs = extract_heading_section(text, "Outputs")
    validation = extract_heading_section(text, "Validation")

    metadata = {
        "name": front_matter.get("name") or (title_match.group(1).strip() if title_match else ""),
        "description": front_matter.get("description") or purpose,
        "research_type": front_matter.get("research_type", ""),
        "input_type": front_matter.get("required_inputs") or front_matter.get("inputs") or inputs,
        "output_type": front_matter.get("expected_outputs") or front_matter.get("outputs") or outputs,
        "validation_standard": front_matter.get("validation_standard") or validation,
        "author": front_matter.get("author", ""),
        "version": front_matter.get("version") or "0.1",
        "license": front_matter.get("license") or "Not specified",
        "purpose": purpose,
        "procedure": extract_heading_section(text, "Procedure") or extract_heading_section(text, "Procedure Summary"),
    }
    return metadata


def detect_package_files(folder: Path, skill_md_path: Path) -> dict[str, object]:
    paths = [path for path in folder.rglob("*") if path.is_file()]
    folder_names = {path.name.lower() for path in folder.rglob("*") if path.is_dir()}
    file_names = [str(path.relative_to(folder)) for path in paths]
    return {
        "has_skill_md": skill_md_path.exists(),
        "has_input": "input" in folder_names,
        "has_references": "references" in folder_names,
        "has_expected": "expected" in folder_names,
        "has_output": "output" in folder_names,
        "has_validation_report": any(path.name.lower() == "validation_report.md" for path in paths),
        "files": file_names,
    }


def prepare_skill_package(uploaded) -> dict[str, object]:
    if uploaded is None or uploaded.filename == "":
        raise ValueError("No file is uploaded.")

    original_filename = secure_filename(uploaded.filename)
    suffix = Path(original_filename).suffix.lower()
    if suffix not in {".zip", ".md"}:
        raise ValueError("Uploaded file must be .zip or .md.")
    if suffix == ".md" and original_filename.lower() != "skill.md":
        raise ValueError("For .md uploads, the file must be named SKILL.md.")

    staging_id = f"_staging-{uuid4().hex[:10]}"
    staging_folder = SUBMITTED_SKILLS_UPLOAD_DIR / staging_id
    staging_folder.mkdir(parents=True, exist_ok=True)
    uploaded_path = staging_folder / original_filename
    uploaded.save(uploaded_path)

    extract_folder = staging_folder / "package"
    extract_folder.mkdir(exist_ok=True)
    if suffix == ".zip":
        try:
            safe_extract_zip(uploaded_path, extract_folder)
        except zipfile.BadZipFile as exc:
            raise ValueError("Uploaded zip file cannot be read.") from exc
    else:
        (extract_folder / "SKILL.md").write_bytes(uploaded_path.read_bytes())

    skill_md_path = find_skill_md(extract_folder)
    if skill_md_path is None:
        raise ValueError("SKILL.md cannot be found in the uploaded package.")

    try:
        skill_text = skill_md_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("SKILL.md cannot be read as UTF-8 text.") from exc

    metadata = extract_skill_metadata(skill_text)
    detected = detect_package_files(extract_folder, skill_md_path)
    return {
        "staging_id": staging_id,
        "uploaded_file_name": original_filename,
        "metadata": metadata,
        "detected": detected,
    }


def finalize_staged_skill(staging_id: str, skill_name: str) -> tuple[str, Path]:
    if not re.fullmatch(r"_staging-[a-f0-9]{10}", staging_id):
        raise ValueError("Uploaded package could not be found. Please upload again.")
    staging_folder = SUBMITTED_SKILLS_UPLOAD_DIR / staging_id
    if not staging_folder.exists():
        raise ValueError("Uploaded package could not be found. Please upload again.")
    destination = unique_folder(SUBMITTED_SKILLS_UPLOAD_DIR / safe_folder_name(skill_name))
    staging_folder.rename(destination)
    return destination.name, destination


def files_for_skill(folder: Path) -> list[dict[str, str]]:
    package_folder = folder / "package"
    root = package_folder if package_folder.exists() else folder
    return [
        {"filename": str(path.relative_to(root))}
        for path in root.rglob("*")
        if path.is_file()
    ]


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
        action = request.form.get("action", "preview")
        if action == "preview":
            try:
                preview = prepare_skill_package(request.files.get("skill_package"))
            except ValueError as exc:
                return render_template("publish.html", error=str(exc), preview=None), 400
            return render_template("publish.html", error=None, preview=preview)

        staging_id = request.form.get("staging_id", "").strip()
        uploaded_file_name = request.form.get("uploaded_file_name", "").strip()
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        research_type = request.form.get("research_type", "").strip()
        input_type = request.form.get("input_type", "").strip()
        output_type = request.form.get("output_type", "").strip()
        validation_standard = request.form.get("validation_standard", "").strip()
        author = request.form.get("author", "").strip()
        version = request.form.get("version", "").strip() or "0.1"
        license_name = request.form.get("license", "").strip() or "Not specified"
        skill_status = request.form.get("skill_status", "Draft").strip() or "Draft"
        visibility = request.form.get("visibility", "Private Draft").strip() or "Private Draft"

        if not name:
            return render_template("publish.html", error="Skill name could not be detected. Please add it before submitting.", preview=None), 400

        folder_name, folder = finalize_staged_skill(staging_id, name)
        submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        skill = {
            "id": folder_name,
            "name": name,
            "description": description,
            "short_description": description,
            "author": author or "Anonymous",
            "research_type": research_type or "Contributed Skill",
            "purpose": request.form.get("purpose", "").strip() or description,
            "input_type": input_type or "User-defined inputs",
            "output_type": output_type or "User-defined outputs",
            "procedure": request.form.get("procedure", "").strip(),
            "validation_standard": validation_standard or "Not specified",
            "validation_status": skill_status,
            "visibility": visibility,
            "status": skill_status,
            "version": version,
            "license": license_name,
            "uploaded_file_name": uploaded_file_name,
            "created_at": submitted_at,
            "submitted_at": submitted_at,
            "folder": folder_name,
            "files": files_for_skill(folder),
        }
        skills = load_submitted_skills()
        skills.insert(0, skill)
        save_submitted_skills(skills)
        return redirect(url_for("submission_confirmation", skill_id=folder_name))

    return render_template("publish.html", error=None, preview=None)


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


@app.route("/skills/contributed/<skill_id>/files/<path:filename>")
def skill_file(skill_id: str, filename: str):
    safe_skill_id = secure_filename(skill_id)
    return send_from_directory(SKILL_DIR / safe_skill_id / "files", filename, as_attachment=True)


@app.route("/uploads/submitted_skills/<skill_id>/<path:filename>")
def submitted_skill_file(skill_id: str, filename: str):
    safe_skill_id = secure_filename(skill_id)
    folder = SUBMITTED_SKILLS_UPLOAD_DIR / safe_skill_id
    package_folder = folder / "package"
    base = package_folder if package_folder.exists() else folder
    return send_from_directory(base, filename, as_attachment=True)


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
