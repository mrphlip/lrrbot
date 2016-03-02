from flask import Flask
from flaskext.csrf import csrf
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy
import warnings

from common.config import config

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = config["postgres"]
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
db.engine.update_execution_options(autocommit=False)
with warnings.catch_warnings():
    # Yes, I know you can't understand FTS indexes.
    warnings.simplefilter("ignore", category=sqlalchemy.exc.SAWarning)
    db.reflect()
csrf(app)

__all__ = ['app', 'db']
