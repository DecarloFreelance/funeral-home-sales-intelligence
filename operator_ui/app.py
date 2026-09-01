from pathlib import Path
import csv
import io
import secrets
import json
from datetime import datetime, timedelta
import threading
import os
import sqlite3
from urllib.parse import urlsplit

from flask import Flask, Response, abort, flash, redirect, render_template, request, session, url_for

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
        if not app.config["AUTH_REQUIRED"] or request.endpoint in {"login", "static", "healthz", "review_drafts_api", "approve_review_draft_api"}:
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

    def review_db():
        path = (Path(app.config["DATA_ROOT"]).resolve() / "generated/manual_imports/review_queue.sqlite").resolve()
        root = Path(app.config["DATA_ROOT"]).resolve()
        if root not in path.parents:
            abort(500, "Invalid review database path")
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS drafts (draft_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            legacy = root / "generated/manual_imports/review_queue.json"
            if connection.execute("SELECT 1 FROM drafts LIMIT 1").fetchone() is None and legacy.is_file():
                try:
                    items = json.loads(legacy.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    items = []
                if isinstance(items, list):
                    connection.executemany("INSERT OR IGNORE INTO drafts (draft_id, payload) VALUES (?, ?)", [(item.get("draft_id", secrets.token_urlsafe(16)), json.dumps(item, ensure_ascii=False)) for item in items if isinstance(item, dict)])
        return path

    def review_drafts():
        path = review_db()
        with sqlite3.connect(path) as connection:
            rows = connection.execute("SELECT payload FROM drafts ORDER BY rowid").fetchall()
            drafts = [json.loads(row[0]) for row in rows]
            known = {item.get("draft_id") for item in drafts if isinstance(item, dict)}
            legacy = path.with_suffix(".json")
            if legacy.is_file():
                try:
                    items = json.loads(legacy.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    items = []
                if isinstance(items, list):
                    missing = [item for item in items if isinstance(item, dict) and item.get("draft_id") not in known]
                    if missing:
                        connection.executemany("INSERT OR IGNORE INTO drafts (draft_id, payload) VALUES (?, ?)", [(item.get("draft_id", secrets.token_urlsafe(16)), json.dumps(item, ensure_ascii=False)) for item in missing])
                        drafts.extend(missing)
        return drafts

    def display_website(row):
        value = str(row.get("website") or "").strip()
        try:
            parts = urlsplit(value)
        except ValueError:
            return ""
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return ""
        return value

    def display_findings(records):
        output = []
        for row in records:
            website = display_website(row)
            host = (urlsplit(website).hostname or "").removeprefix("www.") if website else ""
            output.append({**row, "display_website": website, "display_website_host": host})
        return output

    def filtered_findings(records):
        query = request.args.get("q", "").strip().casefold()[:200]
        province = request.args.get("province", "").strip().upper()
        contact = request.args.get("contact", "").strip().lower()
        website = request.args.get("website", "").strip().lower()
        decision_maker = request.args.get("decision_maker", "").strip().lower()
        if contact not in {"", "yes", "no"} or website not in {"", "yes", "no"} or decision_maker not in {"", "yes", "no"}:
            abort(400, "Unsupported findings filter")
        provinces = sorted({str(row.get("province") or "").upper() for row in records if row.get("province")})
        if province and province not in provinces:
            abort(400, "Unsupported province filter")
        filtered = []
        for row in records:
            has_safe_contact = bool(row.get("emails") or row.get("phones") or row.get("staff"))
            searchable = " ".join(str(row.get(key) or "") for key in ("directory_record_id", "company", "city", "province", "display_website")).casefold()
            matches = (
                (not query or query in searchable)
                and (not province or str(row.get("province") or "").upper() == province)
                and (not contact or has_safe_contact == (contact == "yes"))
                and (not website or bool(row.get("display_website")) == (website == "yes"))
                and (not decision_maker or bool(row.get("decision_makers")) == (decision_maker == "yes"))
            )
            if matches:
                filtered.append(row)
        filters = {"q": query, "province": province, "contact": contact,
                   "website": website, "decision_maker": decision_maker}
        return filtered, provinces, filters

    def findings_metrics(records):
        return {
            "canonical_businesses": len(records),
            "businesses_with_any_safe_contact": sum(
                bool(row.get("emails") or row.get("phones") or row.get("staff")) for row in records
            ),
            "businesses_with_staff": sum(bool(row.get("staff")) for row in records),
            "businesses_with_decision_maker": sum(bool(row.get("decision_makers")) for row in records),
            "named_staff": sum(len(row.get("staff") or []) for row in records),
            "named_decision_makers": sum(len(row.get("decision_makers") or []) for row in records),
            "businesses_with_website": sum(bool(row.get("display_website")) for row in records),
        }

    def csv_cell(value):
        text = str(value or "")
        return "'" + text if text.startswith(("=", "+", "-", "@")) else text

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
        records = display_findings(records)
        filtered, provinces, filters = filtered_findings(records)
        export_url = url_for("export_findings", **{key: value for key, value in filters.items() if value})
        return render_template("findings.html", records=filtered, total_records=len(records), summary=summary,
                               metrics=findings_metrics(records),
                               provinces=provinces, filters=filters, export_url=export_url)

    @app.get("/findings/export.csv")
    def export_findings():
        records, _summary = repository().findings()
        records = display_findings(records)
        filtered, _provinces, _filters = filtered_findings(records)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["Directory ID", "Company", "City", "Province", "Website", "Emails",
                         "Phones", "Staff", "Decision Makers"])
        for row in filtered:
            writer.writerow([csv_cell(row.get("directory_record_id")), csv_cell(row.get("company")),
                             csv_cell(row.get("city")), csv_cell(row.get("province")), csv_cell(row.get("display_website")),
                             csv_cell("; ".join(str(item.get("value") or "") for item in row.get("emails") or [])),
                             csv_cell("; ".join(str(item.get("value") or "") for item in row.get("phones") or [])),
                             csv_cell("; ".join(str(item.get("name") or "") for item in row.get("staff") or [])),
                             csv_cell("; ".join(str(item.get("name") or "") for item in row.get("decision_makers") or []))])
        return Response("\ufeff" + stream.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=funeral-home-findings.csv"})

    @app.get("/findings/<record_id>")
    def finding_detail(record_id):
        record = repository().finding(record_id)
        if record is None:
            abort(404)
        website = display_website(record)
        return render_template("finding_detail.html", record={**record, "display_website": website,
                               "display_website_host": (urlsplit(website).hostname or "").removeprefix("www.") if website else ""})

    @app.get("/queues")
    def queues():
        repo = repository()
        return render_template("queues.html", records=repo.queue(), report=repo.crawl_report())

    @app.get("/imports")
    def imports():
        records, _summary = repository().findings()
        businesses = sorted(records, key=lambda row: (str(row.get("company") or "").casefold(), str(row.get("directory_record_id") or "")))
        return render_template("imports.html", preview=None, businesses=businesses)

    @app.post("/imports/manual")
    def manual_import():
        require_confirmed_post()
        record_id = request.form.get("directory_record_id", "").strip()
        record = repository().finding(record_id)
        if not record:
            abort(400, "Select a valid canonical business")
        website = request.form.get("website", "").strip()
        address = request.form.get("address", "").strip()
        if website:
            website = _canonical_page_url(website)
            if not website:
                abort(400, "Website must be a valid HTTP or HTTPS URL")
        def rows(prefix, fields):
            values = [request.form.getlist(f"{prefix}_{field}") for field in fields]
            return [dict(zip(fields, item)) for item in zip(*values) if any(item)]
        phones = rows("phone", ("value", "person", "source_url", "notes"))
        emails = rows("email", ("value", "person", "source_url", "notes"))
        staff = rows("staff", ("name", "role", "source_url", "notes"))
        if not website and not address and not phones and not emails and not staff:
            abort(400, "Enter at least one enrichment value")
        draft = {
            "draft_id": secrets.token_urlsafe(16), "status": "REVIEW",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "directory_record_id": record_id, "company": record.get("company"),
            "city": record.get("city"), "province": record.get("province"),
            "website": website, "address": address, "phones": phones, "emails": emails, "staff": staff,
        }
        path = review_db()
        with sqlite3.connect(path) as connection:
            connection.execute("INSERT INTO drafts (draft_id, payload) VALUES (?, ?)", (draft["draft_id"], json.dumps(draft, ensure_ascii=False)))
        legacy = path.with_suffix(".json")
        legacy.write_text(json.dumps(review_drafts(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        flash(f"Saved manual enrichment for {record.get('company')} for review.")
        return redirect(url_for("imports"))

    @app.get("/api/review-drafts")
    def review_drafts_api():
        expected = os.environ.get("REVIEW_DRAFTS_TOKEN", "").strip()
        supplied = request.headers.get("Authorization", "")
        if not expected or supplied != f"Bearer {expected}":
            return {"error": "review drafts token required"}, 401
        drafts = review_drafts()
        return {"drafts": drafts, "count": len(drafts)}

    @app.post("/api/review-drafts/approve")
    def approve_review_draft_api():
        expected = os.environ.get("REVIEW_DRAFTS_TOKEN", "").strip()
        if not expected or request.headers.get("Authorization") != f"Bearer {expected}":
            return {"error": "review drafts token required"}, 401
        body = request.get_json(silent=True) or {}
        ids = [str(value) for value in [body.get("draft_id"), body.get("merge_with")] if value]
        drafts = [item for item in review_drafts() if item.get("draft_id") in ids]
        if len(drafts) != len(ids) or len({item.get("directory_record_id") for item in drafts}) != 1 or len(drafts) not in {1, 2}:
            return {"error": "one or two drafts for the same business are required"}, 400
        merged = dict(drafts[0]); other = drafts[1] if len(drafts) == 2 else {}
        for key in ("phones", "emails", "staff"):
            merged[key] = drafts[0].get(key, []) + other.get(key, [])
        if not merged.get("website"): merged["website"] = other.get("website", "")
        merged["status"] = "APPROVED"; merged["merged_draft_ids"] = ids
        path = review_db()
        with sqlite3.connect(path) as connection:
            connection.executemany("UPDATE drafts SET payload=? WHERE draft_id=?", [(json.dumps({**item, "status": "SUPERSEDED", "superseded_by": merged["draft_id"]}, ensure_ascii=False), item["draft_id"]) for item in drafts])
            connection.execute("INSERT OR REPLACE INTO drafts (draft_id, payload) VALUES (?, ?)", (merged["draft_id"], json.dumps(merged, ensure_ascii=False)))
        return {"approved": merged}

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
