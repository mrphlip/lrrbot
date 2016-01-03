from flask import Flask
from flaskext.csrf import csrf
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy
import warnings
import asyncio
import functools

from common.config import config
from common import space

class Application(Flask):
	def __init__(self, *args, **kwargs):
		self.__wrapped_view_funcs = {}
		super().__init__(*args, **kwargs)

	def add_url_rule(self, rule, endpoint, view_func, **options):
		# Cache the wrapper functions so Flask doesn't complain.
		if asyncio.iscoroutinefunction(view_func) and view_func not in self.__wrapped_view_funcs:
			@functools.wraps(view_func)
			def inner(*args, **kwargs):
				return asyncio.get_event_loop().run_until_complete(view_func(*args, **kwargs))
			self.__wrapped_view_funcs[view_func] = inner
			func = inner
		else:
			func = view_func

		return super().add_url_rule(rule, endpoint, func, **options)

app = Application(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = config["postgres"]
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
db.engine.update_execution_options(autocommit=False)
with warnings.catch_warnings():
    # Yes, I know you can't understand FTS indexes.
    warnings.simplefilter("ignore", category=sqlalchemy.exc.SAWarning)
    db.reflect()
csrf(app)
space.monkey_patch_urlize()

__all__ = ['app', 'db']
csrf(app)
