import os
import sys
from flask import Flask, jsonify, render_template, request, g
from datetime import datetime, timedelta
import time
import psycopg2
import json

application = app = Flask(__name__)

services = json.loads(os.environ.get("VCAP_SERVICES", "{}"))
if not services:
    import urlparse
    urlparse.uses_netloc.append("postgres")
    database_uri = os.environ.get('DATABASE_URL', 'postgres://localhost') 
    database_url = urlparse.urlparse(database_uri)

current_template = 'current.html'
day_template = 'day.html'
default_station = 'CYTZ'
wind_url = '/wind'
iso_format = '%Y-%m-%dT%H:%M:%S.%fZ'

epoch = datetime.utcfromtimestamp(0)
def epoch_time(dt):
    delta = dt - epoch
    return delta.total_seconds()

def connect_db():
    if services:
# Try appfog
        try:
            creds = services['postgresql-9.1'][0]['credentials']
        except KeyError, ke:
            print >> sys.stderr, "VCAP_SERVICES = %s" % str(services)
            raise ke
        database = creds['name']
        username = creds['username']
        password = creds['password']
        hostname = creds['hostname']
        port     = creds['port']

        uri = "postgres://%s:%s@%s:%d/%s" % (
            creds['username'],
            creds['password'],
            creds['hostname'],
            creds['port'],
            creds['name'])
    else:
# Try heroku / localhost
        uri = database_uri
        database = database_url.path[1:]
        username = database_url.username
        password = database_url.password
        hostname = database_url.hostname
        port     = database_url.port

    print >> sys.stderr, "Connecting to database: %s" % uri

    return psycopg2.connect(
        database=database,
        user=username,
        password=password,
        host=hostname,
        port=port
    )

def get_connection():
    db = getattr(g, '_db', None)
    if db is None:
        db = g._db = connect_db()
    return db

@app.teardown_request
def teardown_request(exception):
    if hasattr(g, '_db'):
        g._db.close()

def queryWindData(station, start_time, end_time):
    db = get_connection()
    c = db.cursor()
    c.execute("SELECT update_time, direction, speed_kts, gust_kts " \
              "FROM obs WHERE station = %s AND update_time > %s AND update_time < %s " \
              "ORDER BY update_time;",
              (station, start_time, end_time))
    return c.fetchall() 

def safe_int(d):
    try:
        i = int(d)
    except TypeError:
        i = None
    return i

@app.route(wind_url)
def getWindData():
    station = request.args.get('stn', default_station)
    start_time = request.args.get('from', datetime.utcnow()-timedelta(0,3600*24),
                    type=lambda x : datetime.strptime(x, iso_format))
    end_time = request.args.get('to', datetime.utcnow(),
                    type=lambda x : datetime.strptime(x, iso_format))
    data = queryWindData(station, start_time, end_time)
    # This is a kludge to make the data jasonifiable, since it contains
    # datetime and Decimal classes
    serialized = [(epoch_time(x[0]), safe_int(x[1]), safe_int(x[2]), safe_int(x[3])) 
                    for x in data]
    return jsonify(station=station, winddata=serialized)

@app.route('/')
def hello():
    station = request.args.get('stn', default_station)
    minutes = request.args.get('minutes', 0, int)
    hours = request.args.get('hours', 3 if minutes == 0 else 0, int)
    return render_template(
        current_template, 
        wind=wind_url,
        station=default_station,
        hours=hours,
        minutes=minutes)

@app.route('/day')
@app.route('/day/<date>')
def day(date=None):
    station = request.args.get('stn', default_station)
    if date:
        start_date = datetime.strptime(date, '%Y-%m-%d')
        end_date = start_date + timedelta(1)
        return render_template(day_template, 
            wind=wind_url,
            station=default_station,
            start_time=[start_date.year, start_date.month-1, start_date.day],
            end_time=[end_date.year, end_date.month-1, end_date.day])
    else:
        return render_template(day_template, wind=wind_url, station=default_station)


if __name__ == '__main__':
    # Bind to PORT if defined, otherwise default to 5000.
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

