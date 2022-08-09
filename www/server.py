from flask import Flask
from flask_seasurf import SeaSurf
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy
import warnings
import asyncio
import functools

from common.config import config
from common import space, postgres

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = config["postgres"]
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = config["debugsql"]
db = SQLAlchemy(app)
db.engine.update_execution_options(autocommit=False)
with warnings.catch_warnings():
    # Yes, I know you can't understand FTS indexes.
    warnings.simplefilter("ignore", category=sqlalchemy.exc.SAWarning)
    db.reflect()
postgres.set_engine_and_metadata(db.engine, db.metadata)
csrf = SeaSurf(app)
space.monkey_patch_urlize()

__all__ = ['app', 'db', 'csrf']
