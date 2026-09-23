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
    import threading
    req = flask.request.json or {}
    terms = req.get("terms")
    
    def background_run():
        if is_cloud():
            pull_files(BASE_DIR)
        run.main(terms=terms)
        if is_cloud():
            push_files(BASE_DIR)
            
    threading.Thread(target=background_run).start()
    return flask.jsonify({"status": "started"})

@flask_app.route("/api/telegram_webhook", methods=["POST"])
def route_telegram_webhook():
    import threading
    from jobhunter.telegram import load_telegram, api_call, format_job
    from jobhunter.results import load_jobs
    
    cfg = load_telegram()
    token = cfg.get("bot_token")
    if not token:
        return flask.jsonify({"status": "ok"})
        
    req = flask.request.json or {}
    msg = req.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip()
    
    if not chat_id or not text:
        return flask.jsonify({"status": "ok"})
        
    owner = cfg.get("chat_id")
    if chat_id != owner:
        return flask.jsonify({"status": "ok"})
        
    def send(t):
        try:
            api_call(token, "sendMessage", {"chat_id": chat_id, "text": t, "disable_web_page_preview": "true"})
        except Exception:
            pass

    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    
    def background_run(terms=None):
        if is_cloud():
            pull_files(BASE_DIR)
        run.main(terms=terms)
        if is_cloud():
            push_files(BASE_DIR)
            
    if cmd == "/run":
        send("Run started - I'll report when it finishes.")
        threading.Thread(target=background_run).start()
    elif cmd == "/search":
        arg = arg.strip()
        if not arg:
            send("Usage: /search hr analyst; payroll lead")
            return flask.jsonify({"status": "ok"})
        from jobhunter.searches import parse_terms
        terms = parse_terms(arg)
        if not terms:
            send("Couldn't parse any titles from that.")
            return flask.jsonify({"status": "ok"})
        send(f"Custom search for: {', '.join(terms)} started - I'll report when it finishes.")
        threading.Thread(target=lambda: background_run(terms)).start()
    elif cmd == "/status":
        from jobhunter.notify import read_status
        s = read_status()
        lines = [
            f"Last run    : {(s.get('last_run') or 'never')[:16].replace('T', ' ')}",
            f"New jobs    : {s.get('new_jobs', '-')}",
        ]
        send("\n".join(lines))
    elif cmd == "/last":
        jobs = load_jobs()
        if not jobs:
            send("No jobs in the store yet.")
        else:
            for e in jobs[-3:]:
                send(format_job(e))
    else:
        send("/run - fire search now\n/search t1; t2 - custom search\n/status - run info\n/last - recent jobs")
        
    return flask.jsonify({"status": "ok"})

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
