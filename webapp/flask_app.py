import os
from datetime import datetime, timedelta

import pymysql
from flask import Flask, g, jsonify, render_template, request

application = app = Flask(__name__)


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
    mysql_host = os.environ.get('MYSQL_HOST', 'martinh.mysql.pythonanywhere-services.com')
    mysql_user = os.environ.get('MYSQL_USER', 'martinh')
    mysql_db = os.environ.get('MYSQL_DB', 'martinh$windburglr')
    mysql_password = os.environ.get('MYSQL_PASSWORD')

    return pymysql.connect(host=mysql_host, user=mysql_user, db=mysql_db, password=mysql_password)


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
    db = get_connection()
    c = db.cursor()
    c.execute("""SELECT update_time, direction, speed_kts, gust_kts
        FROM station JOIN wind_obs ON station_id = station.id
        WHERE station.name = %s AND update_time BETWEEN %s AND %s
        ORDER BY update_time;
        """,
        (station, start_time, end_time))
    row = c.fetchone()
    while row is not None:
        yield row
        row = c.fetchone()


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
    jsonfriendly = [(epoch_time(x[0]), safe_int(x[1]), safe_int(x[2]), safe_int(x[3]))
        for x in winddatagen]
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
    app.run(host='0.0.0.0', port=port, debug=True)
