from flask import Flask
from flask_seasurf import SeaSurf
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy
import warnings

from common.config import config
from common import postgres

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = config["postgres"]
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = config["debugsql"]
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
	'isolation_level': 'READ COMMITTED',
	'pool_pre_ping': True,
}
db = SQLAlchemy(app)
with app.app_context():
	with warnings.catch_warnings():
		# Yes, I know you can't understand FTS indexes.
		warnings.simplefilter("ignore", category=sqlalchemy.exc.SAWarning)
		db.reflect()
	postgres.set_engine_and_metadata(db.engine, db.metadata)
csrf = SeaSurf(app)

__all__ = ['app', 'db', 'csrf']
