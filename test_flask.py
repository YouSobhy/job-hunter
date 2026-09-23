import sys
from firebase_functions import https_fn

class MockRequest:
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/api/jobs",
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8080",
    }

from main import flask_app
with flask_app.request_context(MockRequest.environ):
    resp = flask_app.full_dispatch_request()
    print(resp)
