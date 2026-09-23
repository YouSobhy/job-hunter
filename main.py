import flask
import traceback
from firebase_functions import https_fn, scheduler_fn, options
from firebase_admin import initialize_app
import run
from gcs_sync import pull_files, push_files, is_cloud
from jobhunter.config import BASE_DIR

initialize_app()

flask_app = flask.Flask(__name__)

from flask_cors import CORS
CORS(flask_app)

@flask_app.before_request
def before_req():
    if is_cloud():
        try:
            pull_files(BASE_DIR)
        except Exception as e:
            print("Pull failed:", e)

@flask_app.after_request
def after_req(response):
    if is_cloud():
        try:
            push_files(BASE_DIR)
        except Exception as e:
            print("Push failed:", e)
    return response

@flask_app.route("/api/jobs", methods=["GET"])
def route_get_jobs():
    from api import get_jobs
    return flask.jsonify(get_jobs())

@flask_app.route("/api/status", methods=["GET"])
def route_get_status():
    from api import get_status
    return flask.jsonify(get_status())

@flask_app.route("/api/feedback", methods=["POST"])
def route_feedback():
    from jobhunter.feedback import save_feedback
    req = flask.request.json or {}
    save_feedback(req.get("url"), req.get("category"))
    return flask.jsonify({"status": "ok"})

@flask_app.route("/api/run_search", methods=["POST"])
def route_run_search():
    return flask.jsonify({"status": "started"})

@flask_app.route("/")
def route_index():
    resp = flask.send_file("ui/index.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@https_fn.on_request(
    cors=options.CorsOptions(cors_origins=["*"], cors_methods=["*"]),
    memory=options.MemoryOption.GB_1,
    timeout_sec=120
)
def api(request: https_fn.Request) -> https_fn.Response:
    with flask_app.request_context(request.environ):
        return flask_app.full_dispatch_request()

@scheduler_fn.on_schedule(
    schedule="0 18 * * *", 
    timezone="UTC",
    memory=options.MemoryOption.GB_2,
    timeout_sec=1800
)
def daily_job_fetch(event: scheduler_fn.ScheduledEvent) -> None:
    pull_files(BASE_DIR)
    run.main()
    push_files(BASE_DIR)
