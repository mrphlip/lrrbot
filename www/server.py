from flask import Flask
from flaskext.csrf import csrf

import asyncio
import functools

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
csrf(app)

__all__ = ['app']
