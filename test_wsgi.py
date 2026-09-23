from main import wsgi_app
from flask import Flask, Request, Response

app = Flask(__name__)

def api(request):
    return Response.from_app(wsgi_app, request.environ)

with app.test_request_context('/api/jobs', method='GET'):
    req = Request(app.test_request_context('/api/jobs', method='GET').request.environ)
    try:
        response = api(req)
        print("Response:", response.status_code)
        print("Body:", b''.join(response.response)[:100])
    except Exception as e:
        print("Exception:", e)
