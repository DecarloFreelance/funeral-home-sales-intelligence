from pathlib import Path
import secrets
import json
from datetime import datetime, timedelta
import threading
import os
from urllib.parse import urlsplit

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

from crm.action_queue import create_action
from crm.execution import complete_action, start_action
from discovery.ingestion import build_crawl_queue
from discovery.source_adapters import load_source_text
from website_crawler import crawl_queue
from operator_ui.research_actions import apply_reviewed_resolution, preview_resolution
from discovery.crawler import _canonical_page_url
from operator_ui.outreach_actions import approve_draft
from operator_ui.repository import OperatorRepository
from operator_ui.auth import AuthStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATA_ROOT=PROJECT_ROOT / "data",
        CRM_DB=None,
        SECRET_KEY=secrets.token_hex(32),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        CRAWL_RUNNER=crawl_queue,
        AUTH_REQUIRED=True,
        AUTH_DB=PROJECT_ROOT / "instance/operator_auth.sqlite",
        FINDINGS_PATH=None,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("OPERATOR_UI_SECURE_COOKIE", "").lower() == "true",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    if config:
        app.config.update(config)
    if app.config["TESTING"] and (not config or "AUTH_REQUIRED" not in config):
        app.config["AUTH_REQUIRED"] = False
    app.extensions["import_previews"] = {}
    app.extensions["crawl_jobs"] = {}
    app.extensions["crawl_lock"] = threading.Lock()
    app.extensions["resolution_previews"] = {}
    app.extensions["resolution_lock"] = threading.Lock()
    app.extensions["outreach_lock"] = threading.Lock()
    app.extensions["login_failures"] = {}
    app.extensions["login_lock"] = threading.Lock()

    def auth_store():
        return AuthStore(app.config["AUTH_DB"])

    def safe_next(value):
        parts = urlsplit(value or "")
        return value if value and not parts.scheme and not parts.netloc and value.startswith("/") else None

    @app.before_request
    def require_login():
        if not app.config["AUTH_REQUIRED"] or request.endpoint in {"login", "static", "healthz"}:
            return None
        if session.get("authenticated_user"):
            return None
        return redirect(url_for("login", next=request.full_path.rstrip("?")))

    @app.context_processor
    def authenticated_user():
        return {"authenticated_user": session.get("authenticated_user")}

    def repository():
        return OperatorRepository(
            app.config["DATA_ROOT"], app.config.get("CRM_DB"), app.config.get("FINDINGS_PATH")
        )

    def csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            supplied = request.form.get("csrf_token", "")
            if not supplied or not secrets.compare_digest(supplied, session.get("csrf_token", "")):
                abort(400, "Invalid CSRF token")
            now = datetime.utcnow()
            client_key = request.remote_addr or "unknown"
            with app.extensions["login_lock"]:
                failures = [
                    value for value in app.extensions["login_failures"].get(client_key, [])
                    if value > now - timedelta(minutes=5)
                ]
                app.extensions["login_failures"][client_key] = failures
            if len(failures) >= 5:
                abort(429, "Too many login attempts; try again later")
            user = auth_store().authenticate(
                request.form.get("username", ""), request.form.get("password", "")
            )
            if user:
                with app.extensions["login_lock"]:
                    app.extensions["login_failures"].pop(client_key, None)
                token = secrets.token_urlsafe(32)
                session.clear()
                session["authenticated_user"] = user
                session["csrf_token"] = token
                session.permanent = True
                return redirect(safe_next(request.form.get("next")) or url_for("findings"))
            with app.extensions["login_lock"]:
                app.extensions["login_failures"].setdefault(client_key, []).append(now)
            flash("Invalid username or password.")
        return render_template("login.html", next=safe_next(request.args.get("next")) or "")

    @app.post("/logout")
    def logout():
        supplied = request.form.get("csrf_token", "")
        if not supplied or not secrets.compare_digest(supplied, session.get("csrf_token", "")):
            abort(400, "Invalid CSRF token")
        session.clear()
        return redirect(url_for("login"))

    def require_confirmed_post():
        supplied = request.form.get("csrf_token", "")
        if not supplied or not secrets.compare_digest(supplied, session.get("csrf_token", "")):
            abort(400, "Invalid CSRF token")
        if request.form.get("confirm") != "yes":
            abort(400, "Confirmation is required")

    @app.get("/")
    def dashboard():
        return render_template("dashboard.html", summary=repository().summary())

    @app.get("/findings")
    def findings():
        records, summary = repository().findings()
        return render_template("findings.html", records=records, summary=summary)

    @app.get("/findings/<record_id>")
    def finding_detail(record_id):
        record = repository().finding(record_id)
        if record is None:
            abort(404)
        return render_template("finding_detail.html", record=record)

    @app.get("/queues")
    def queues():
        repo = repository()
        return render_template("queues.html", records=repo.queue(), report=repo.crawl_report())

    @app.get("/imports")
    def imports():
        return render_template("imports.html", preview=None)

    @app.post("/imports/preview")
    def import_preview():
        require_confirmed_post()
        source_type = request.form.get("source_type", "").strip().lower()
        allowed_sources = {"manual", "maps", "search", "association", "directory"}
        if source_type not in allowed_sources:
            abort(400, "Unsupported source type")
        upload = request.files.get("source_file")
        if upload is None or not upload.filename:
            abort(400, "A CSV or JSON source file is required")
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in {".csv", ".json"}:
            abort(400, "Only CSV and JSON source files are supported")
        try:
            text = upload.read().decode("utf-8-sig")
            leads = load_source_text(text, suffix, source_type)
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
            abort(400, f"Could not parse source: {error}")
        queue = build_crawl_queue(leads)
        if not queue:
            abort(400, "The source contains no valid business websites")
        token = secrets.token_urlsafe(24)
        app.extensions["import_previews"][token] = {
            "expires": datetime.utcnow() + timedelta(minutes=15),
            "queue": queue,
            "source_type": source_type,
            "filename": Path(upload.filename).name,
            "input_records": len(leads),
        }
        preview = {
            "token": token, "records": queue, "source_type": source_type,
            "filename": Path(upload.filename).name, "input_records": len(leads),
            "rejected": sum(not lead.domain for lead in leads),
        }
        return render_template("imports.html", preview=preview)

    @app.post("/imports/confirm")
    def import_confirm():
        require_confirmed_post()
        token = request.form.get("preview_token", "")
        preview = app.extensions["import_previews"].pop(token, None)
        if not preview or preview["expires"] < datetime.utcnow():
            abort(409, "Import preview is missing, expired, or already used")
        output = (Path(app.config["DATA_ROOT"]).resolve() / "crawl_queue.json").resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(preview["queue"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output)
        flash(f"Imported {len(preview['queue'])} unique domains from {preview['filename']}.")
        return redirect(url_for("queues"))

    @app.get("/research")
    def research():
        return render_template("research.html", records=repository().research(), preview=None)

    @app.post("/research/preview")
    def research_preview():
        require_confirmed_post()
        old_domain = request.form.get("old_domain", "").strip().lower()
        new_website = _canonical_page_url(request.form.get("new_website", "").strip())
        evidence_url = _canonical_page_url(request.form.get("evidence_url", "").strip())
        confidence = request.form.get("confidence", "").strip().upper()
        notes = request.form.get("notes", "").strip()
        if not old_domain or not new_website or not evidence_url or not notes:
            abort(400, "Domain, replacement website, evidence URL, and rationale are required")
        if confidence not in {"HIGH", "MEDIUM"}:
            abort(400, "Reviewed confidence must be HIGH or MEDIUM")
        resolution = {
            "old_domain": old_domain, "new_website": new_website,
            "confidence": confidence, "evidence_url": evidence_url, "notes": notes,
        }
        try:
            preview = preview_resolution(app.config["DATA_ROOT"], resolution)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            abort(400, str(error))
        token = secrets.token_urlsafe(24)
        app.extensions["resolution_previews"][token] = {
            "expires": datetime.utcnow() + timedelta(minutes=15),
            "resolution": resolution,
        }
        preview["token"] = token
        return render_template("research.html", records=repository().research(), preview=preview)

    @app.post("/research/confirm")
    def research_confirm():
        require_confirmed_post()
        token = request.form.get("preview_token", "")
        stored = app.extensions["resolution_previews"].pop(token, None)
        if not stored or stored["expires"] < datetime.utcnow():
            abort(409, "Resolution preview is missing, expired, or already used")
        try:
            with app.extensions["resolution_lock"]:
                retry, summary = apply_reviewed_resolution(
                    app.config["DATA_ROOT"], stored["resolution"]
                )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            abort(409, str(error))
        flash(
            f"Reviewed resolution applied; {len(retry)} retry domains and "
            f"{summary['remaining_domains']} research records remain."
        )
        return redirect(url_for("research"))

    @app.get("/crawl")
    def crawl_status():
        jobs = sorted(
            app.extensions["crawl_jobs"].values(),
            key=lambda job: job["created_at"], reverse=True,
        )
        return render_template("crawl.html", jobs=jobs)

    @app.post("/crawl/start")
    def crawl_start():
        require_confirmed_post()
        mode = request.form.get("mode", "")
        if mode not in {"replace", "resume"}:
            abort(400, "Crawl mode must be replace or resume")
        try:
            options = {
                "limit": int(request.form.get("limit", "10")),
                "offset": int(request.form.get("offset", "0")),
                "max_pages": int(request.form.get("max_pages", "5")),
                "max_attempts": int(request.form.get("max_attempts", "5")),
                "timeout": float(request.form.get("timeout", "10")),
                "delay": float(request.form.get("delay", "0.25")),
            }
        except ValueError:
            abort(400, "Crawl options must be numeric")
        if not (1 <= options["limit"] <= 250 and 0 <= options["offset"] <= 100000):
            abort(400, "Limit or offset is outside the allowed range")
        if not (1 <= options["max_pages"] <= 25 and 1 <= options["max_attempts"] <= 50):
            abort(400, "Page or attempt limit is outside the allowed range")
        if not (1 <= options["timeout"] <= 60 and 0 <= options["delay"] <= 10):
            abort(400, "Timeout or delay is outside the allowed range")

        data_root = Path(app.config["DATA_ROOT"]).resolve()
        input_path = data_root / "crawl_queue.json"
        if not input_path.is_file():
            abort(409, "No crawl queue is available")
        output_path = data_root / "discovered_leads.json"
        report_path = data_root / "discovered_leads_report.json"

        with app.extensions["crawl_lock"]:
            if any(job["status"] in {"QUEUED", "RUNNING"} for job in app.extensions["crawl_jobs"].values()):
                abort(409, "Another crawl is already running")
            job_id = secrets.token_urlsafe(12)
            job = {
                "id": job_id, "status": "QUEUED", "mode": mode,
                "created_at": datetime.utcnow().isoformat(), "completed_at": None,
                "processed": 0, "total": options["limit"], "domain": None,
                "pages": 0, "error": None, "options": options,
            }
            app.extensions["crawl_jobs"][job_id] = job

        def run_job():
            job["status"] = "RUNNING"

            def update(index, total, domain, pages):
                job.update(processed=index, total=total, domain=domain, pages=job["pages"] + pages)

            try:
                report = app.config["CRAWL_RUNNER"](
                    input_path, output_path, report_path=report_path,
                    append=mode == "resume", progress_callback=update, **options,
                )
                job["status"] = "COMPLETED"
                job["report"] = report
                job["processed"] = report.get("queued_domains", job["processed"])
                job["pages"] = report.get("pages", job["pages"])
            except Exception as error:
                job["status"] = "FAILED"
                job["error"] = str(error)
            finally:
                job["completed_at"] = datetime.utcnow().isoformat()

        threading.Thread(target=run_job, name=f"crawl-{job_id}", daemon=True).start()
        flash(f"Crawl {job_id} started in {mode} mode.")
        return redirect(url_for("crawl_status", job=job_id))

    @app.get("/leads")
    def leads():
        return render_template("leads.html", records=repository().leads())

    @app.get("/leads/<path:domain>")
    def lead_detail(domain):
        lead = repository().lead(domain)
        if lead is None:
            abort(404)
        return render_template("lead_detail.html", lead=lead)

    @app.get("/quality")
    def quality_review():
        return render_template("quality.html", records=repository().quality_review())

    @app.get("/candidates")
    def candidates():
        return render_template("candidates.html", records=repository().candidates())

    @app.get("/drafts")
    def drafts():
        return render_template("drafts.html", records=repository().drafts())

    @app.post("/drafts/<draft_id>/approve")
    def draft_approve(draft_id):
        require_confirmed_post()
        try:
            with app.extensions["outreach_lock"]:
                approval, created = approve_draft(app.config["DATA_ROOT"], draft_id)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            abort(409, str(error))
        if created:
            flash(f"Approved unsent draft for {approval['to']}.")
        else:
            flash(f"Draft for {approval['to']} was already approved.")
        return redirect(url_for("drafts"))

    @app.get("/crm/actions")
    def crm_actions():
        return render_template("crm_actions.html", records=repository().crm_actions())

    @app.post("/crm/actions")
    def crm_action_create():
        require_confirmed_post()
        domain = request.form.get("domain", "").strip().lower()
        action_type = request.form.get("action_type", "").strip()
        priority = request.form.get("priority", "").strip()
        if not domain or not action_type or not priority:
            abort(400, "Domain, action type, and priority are required")
        allowed_priorities = {
            "A1 - Immediate Outreach", "A2 - Priority Outreach",
            "B1 - Nurture", "Research Required",
        }
        if priority not in allowed_priorities:
            abort(400, "Unsupported priority")
        if not repository().crm_has_lead(domain):
            abort(400, "The action domain must match an existing CRM lead")
        action_id = create_action(
            domain, action_type, priority, request.form.get("notes", "").strip(),
            db_path=app.config.get("CRM_DB"),
        )
        flash(f"Action {action_id} is queued for {domain}.")
        return redirect(url_for("crm_actions"))

    @app.post("/crm/actions/<int:action_id>/start")
    def crm_action_start(action_id):
        require_confirmed_post()
        result = start_action(action_id, app.config.get("CRM_DB"))
        if result is None:
            abort(409, "Action is not open or its lead is unavailable")
        flash(f"Started {result['action']} for {result['domain']}.")
        return redirect(url_for("crm_actions"))

    @app.post("/crm/actions/<int:action_id>/complete")
    def crm_action_complete(action_id):
        require_confirmed_post()
        domain = request.form.get("domain", "").strip().lower()
        result_note = request.form.get("result", "").strip()
        if not domain or not result_note:
            abort(400, "Domain and result note are required")
        if not complete_action(domain, result_note, app.config.get("CRM_DB"), action_id):
            abort(409, "Action is not in progress")
        flash(f"Completed action for {domain}.")
        return redirect(url_for("crm_actions"))

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
