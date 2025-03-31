import datetime

import flask
import pytz
import sqlalchemy
from www import login, server


blueprint = flask.Blueprint('timers', __name__)

@blueprint.route('/')
@login.require_mod
def index(session):
	timers = server.db.metadata.tables["timers"]

	with server.db.engine.connect() as conn:
		data = [
			{
				"id": id,
				"name": name,
				"interval": interval,
				"mode": mode,
				"message": message,
				"next_run": next_run,
				"next_run_in": next_run_in,
			}
			for id, name, interval, mode, message, next_run, next_run_in in conn.execute(sqlalchemy.select(
				timers.c.id,
				timers.c.name,
				timers.c.interval,
				timers.c.mode,
				timers.c.message,
				timers.c.last_run + timers.c.interval,
				timers.c.last_run + timers.c.interval - sqlalchemy.func.current_timestamp(),
			).order_by(timers.c.name))
		]

	return flask.render_template("timers_list.html", timers=data, session=session)

@blueprint.route('/new')
@login.require_mod
def new(session):
	timer = {
		"id": None,
		"name": "",
		"interval": datetime.timedelta(minutes=15),
		"mode": "message",
		"message": "",
	}
	return flask.render_template("timers_edit.html", timer=timer, session=session)

@blueprint.route('/<int:id>')
@login.require_mod
def edit(session, id):
	timers = server.db.metadata.tables["timers"]

	with server.db.engine.connect() as conn:
		id, name, interval, mode, message = conn.execute(
			sqlalchemy.select(
				timers.c.id, timers.c.name, timers.c.interval, timers.c.mode, timers.c.message
			).where(timers.c.id == id)
		).one()

		timer = {
			"id": id,
			"name": name,
			"interval": interval,
			"mode": mode,
			"message": message,
		}

	return flask.render_template("timers_edit.html", timer=timer, session=session)

@blueprint.route('/save', methods=["POST"])
@login.require_mod
def save(session):
	timers = server.db.metadata.tables["timers"]

	timer_id = flask.request.form.get("id")
	timer = {
		"name": flask.request.form["name"].strip(),
		"interval": datetime.timedelta(minutes=float(flask.request.form["interval"].strip())),
		"mode": flask.request.form["mode"].strip(),
		"message": flask.request.form["message"].strip(),
	}

	if not timer['name']:
		return "Name missing", 400
	if timer['interval'] <= datetime.timedelta():
		return "Interval must be positive", 400
	if timer['mode'] not in ('command', 'message'):
		return "Invalid mode", 400
	if not timer['message']:
		return "Message missing", 400

	with server.db.engine.connect() as conn:
		if not timer_id:
			query = sqlalchemy.insert(timers)
		else:
			query = sqlalchemy.update(timers).where(timers.c.id == timer_id)
		conn.execute(query, timer)
		conn.commit()

	flask.flash("Saved.", "success")

	return flask.redirect(flask.url_for("timers.index"))

@blueprint.route('/<int:id>/delete', methods=["POST"])
@login.require_mod
def delete(session, id):
	timers = server.db.metadata.tables["timers"]

	with server.db.engine.connect() as conn:
		name = conn.execute(sqlalchemy.delete(timers).where(timers.c.id == id).returning(timers.c.name)).scalar()
		conn.commit()

	if name:
		flask.flash(f"Deleted {name!r}.", "success")
	else:
		flask.flash("Nothing to delete.")

	return flask.redirect(flask.url_for("timers.index"))
