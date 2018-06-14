import os
import sys
from flask import Flask, jsonify, render_template, request, g
from datetime import datetime, timedelta
import json
from porc import Client

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
            creds = services['orchestrate'][0]['credentials']
        except KeyError, ke:
            print >> sys.stderr, "VCAP_SERVICES = %s" % str(services)
            raise ke
        # api_url = creds['ORCHESTRATE_API_URL']
        api_key = creds['ORCHESTRATE_API_KEY']
        api_host = creds['ORCHESTRATE_API_HOST']

    else:
        # Try heroku / localhost
        api_key = os.environ.get('ORCHESTRATE_API_KEY')
        api_host = os.environ.get('ORCHESTRATE_API_HOST')
        # uri = database_uri
        # database = database_url.path[1:]
        # username = database_url.username
        # password = database_url.password
        # hostname = database_url.hostname
        # port = database_url.port

    print >> sys.stderr, "Connecting to database: %s" % api_host

    try:
        client = Client(api_key)
        return client
    except Exception, ex:
        print >> sys.stderr, "%s: %s" % (type(ex).__name__, str(ex))
        raise ex


def get_connection():
    db = getattr(g, '_db', None)
    if db is None:
        db = g._db = connect_db()
    return db


@app.teardown_request
def teardown_request(exception):
    pass
    # if hasattr(g, '_db'):
    #     g._db.close()


def query_wind_data(station, start_time, end_time):
    "Returns a generator of wind data tuples"
    client = get_connection()
    pages = client.list_events(
        'obs', station, 'obs', startEvent=start_time, endEvent=end_time)
    return pages
    # c = db.cursor()
    # c.execute("SELECT update_time, direction, speed_kts, gust_kts "
    #           "FROM obs WHERE station = %s AND update_time > %s AND update_time < %s "
    #           "ORDER BY update_time;",
    #           (station, start_time, end_time))
    # row = c.fetchone()
    # while row is not None:
    #     yield row
    #     row = c.fetchone()


def store_observation(obs):
    "Write an observation to the database"
    db = get_connection()
    c = db.cursor()
    c.execute("""INSERT INTO obs (station, direction, speed_kts, gust_kts, update_time)
        VALUES (%s, %s, %s, %s, %s)
        """, (obs['station'], obs['direction'], obs['speed_kts'], obs['gust_kts'],
              obs['update_time']))
    db.commit()
    return c.rowcount


def safe_int(d):
    try:
        i = int(d)
    except TypeError:
        i = None
    return i


@app.route(wind_url, methods=['GET', 'POST'])
def wind_api():
    if request.method == 'POST':
        return create_wind_observation()
    elif request.method == 'GET':
        return wind_data_as_json()


def create_wind_observation():
    obs = request.get_json()
    if obs is not None:
        try:
            if store_observation(obs) > 0:
                return jsonify(obs), 201
            else:
                return jsonify(message="Invalid request"), 403
        except KeyError as ke:
            return jsonify(message="Invalid request: missing key: {}".format(ke)), 403
        except Exception as ex:
            return jsonify(message=str(ex)), 403
    else:
        return jsonify(message="No data"), 403


def wind_data_as_json():
    station = request.args.get('stn', default_station)
    start_time = request.args.get('from', datetime.utcnow() - timedelta(0, 3600 * 24),
                                  type=lambda x: datetime.strptime(x, iso_format))
    end_time = request.args.get('to', datetime.utcnow(),
                                type=lambda x: datetime.strptime(x, iso_format))
    winddatagen = query_wind_data(station, start_time, end_time)
    # This is a kludge to make the data jasonifiable, since it contains
    # datetime and Decimal classes
    jsonfriendly = [
        (x[0]/1000,
            safe_int(x[1][u'direction']),
            safe_int(x[1][u'speed_kts']),
            safe_int(x[1][u'gust_kts']))
        for x in reversed([
            (event[u'timestamp'], event[u'value']) for event in winddatagen.all()])]
    return jsonify(station=station, winddata=jsonfriendly)


@app.route('/')
def hello():
    station = request.args.get('stn', default_station)
    minutes = request.args.get('minutes', 0, int)
    hours = request.args.get('hours', 3 if minutes == 0 else 0, int)
    return render_template(
        current_template,
        wind=wind_url,
        station=station,
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
                               station=station,
                               start_time=[start_date.year, start_date.month - 1, start_date.day],
                               end_time=[end_date.year, end_date.month - 1, end_date.day])
    else:
        return render_template(day_template, wind=wind_url, station=station)


if __name__ == '__main__':
    # Bind to PORT if defined, otherwise default to 5000.
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=not services)
