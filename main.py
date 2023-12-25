import sys
import os.path

from waitress import serve

project_home = 'webapp'
if project_home not in sys.path:
    sys.path = [project_home] + sys.path

#app.run(host='127.0.0.1', port=8181) # dev server
from flask_app import app # noqa
serve(app, host='127.0.0.1', port=8181, url_scheme='https') # production server
