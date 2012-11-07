import os
from flask import Flask, jsonify, render_template, request, g
from datetime import datetime, timedelta
import psycopg2
import urlparse

app = Flask(__name__)

urlparse.uses_netloc.append("postgres")
database = os.getenv('DATABASE_URL') or 'postgres://localhost'

basic_template = 'basic.html'
default_station = 'CYTZ'
wind_url = '/wind'
iso_format = '%Y-%m-%dT%H:%M:%S.%fZ'

def connect_db():
    url = urlparse.urlparse(database)

    return psycopg2.connect(
        database=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port
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
    serialized = [(str(x[0]), x[1] and int(x[1]), x[2] and int(x[2]), x[3] and int(x[3])) 
        for x in data]
    return jsonify(station=station, winddata=serialized)

@app.route('/')
def hello():
    return render_template('hello.html')

@app.route('/day')
@app.route('/day/<date>')
def day(date=None):
    station = request.args.get('stn', default_station)
    start_date = datetime.strptime(date, '%Y-%m-%d') if date is not None \
        else datetime.today().date()
    end_date = start_date + timedelta(1)
    return render_template(basic_template, 
        wind=wind_url,
        station=default_station,
        start_time=start_date.isoformat(),
        end_time=end_date.isoformat())

if __name__ == '__main__':
    # Bind to PORT if defined, otherwise default to 5000.
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

