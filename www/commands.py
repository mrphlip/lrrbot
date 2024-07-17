import flask
import flask.json
import sqlalchemy
import itertools
from www import server
from www import login
from www import history
import common.rpc
from common import utils

blueprint = flask.Blueprint('commands', __name__)

RESPONSE_LIMIT = 3

@blueprint.route('/')
@login.require_mod
async def list(session):
	commands = server.db.metadata.tables["commands"]
	aliases = server.db.metadata.tables["commands_aliases"]
	responses = server.db.metadata.tables["commands_responses"]

	data = []

	with server.db.engine.connect() as conn:
		query = sqlalchemy.select(commands.c.id, commands.c.access, aliases.c.alias)
		query = query.select_from(commands.join(aliases, aliases.c.command_id == commands.c.id))
		query = query.order_by(commands.c.id, aliases.c.id)

		first = True
		for command_id, rows in itertools.groupby(conn.execute(query), key=lambda row:row[0]):
			command_data = {
				"command_id": command_id,
				"access": 0,
				"aliases": [],
				"responses": [],
			}
			for _, access, alias in rows:
				command_data["access"] = access
				command_data["aliases"].append(alias)

			query = sqlalchemy.select(responses.c.response).where(responses.c.command_id == command_id)
			query = query.order_by(responses.c.id).limit(RESPONSE_LIMIT)
			command_data["responses"] = conn.execute(query).scalars().all()

			query = sqlalchemy.select(sqlalchemy.func.count()).select_from(responses).where(responses.c.command_id == command_id)
			count = conn.execute(query).scalar()
			command_data["response_count"] = count
			command_data["response_more"] = (count > RESPONSE_LIMIT)

			data.append(command_data)
	data.sort(key=lambda command:command["aliases"][0].casefold())

	return flask.render_template("commands.html", commands=data, session=session)

@blueprint.route('/new')
@login.require_mod
async def new(session):
	return flask.render_template("commands_edit.html", command_id=-1, access=0, aliases=[''], responses=[''], session=session)

@blueprint.route('/edit/<int:command_id>')
@login.require_mod
async def edit(session, command_id):
	commands = server.db.metadata.tables["commands"]
	aliases = server.db.metadata.tables["commands_aliases"]
	responses = server.db.metadata.tables["commands_responses"]

	command_id = int(command_id)
	with server.db.engine.connect() as conn:
		query = sqlalchemy.select(commands.c.access).where(commands.c.id == command_id)
		access = conn.execute(query).scalar()
		query = sqlalchemy.select(aliases.c.alias).where(aliases.c.command_id == command_id).order_by(aliases.c.id)
		alias = conn.execute(query).scalars().all()
		query = sqlalchemy.select(responses.c.response).where(responses.c.command_id == command_id).order_by(responses.c.id)
		response = conn.execute(query).scalars().all()

	return flask.render_template("commands_edit.html", command_id=command_id, access=access, aliases=alias, responses=response, session=session)

@blueprint.route('/save', methods=['POST'])
@login.require_mod
async def save(session):
	command_id = int(flask.request.values['command_id'])
	access = int(flask.request.values["access"])
	alias = [" ".join(i.lower().split()) for i in flask.request.values.getlist("alias")]
	alias = [i for i in alias if i]
	response = [i for i in flask.request.values.getlist("response") if i.strip()]

	if access not in (0, 1, 2):
		return "Invalid access", 400
	if not alias:
		return "Missing aliases", 400
	if not response:
		return "Missing responses", 400

	commands = server.db.metadata.tables["commands"]
	aliases = server.db.metadata.tables["commands_aliases"]
	responses = server.db.metadata.tables["commands_responses"]
	with server.db.engine.connect() as conn:
		if command_id < 0:
			command_id = conn.execute(
				commands.insert().returning(commands.c.id),
				{"access": access}).scalar()
		else:
			conn.execute(commands.update().values(access=access).where(commands.c.id == command_id))

		conn.execute(aliases.delete().where(aliases.c.command_id == command_id))
		try:
			for a in alias:
				conn.execute(aliases.insert(), {"command_id": command_id, "alias": a})
		except sqlalchemy.exc.IntegrityError:
			conn.rollback()
			return "Duplicate command aliases", 400

		conn.execute(responses.delete().where(responses.c.command_id == command_id))
		for r in response:
			conn.execute(responses.insert(), {"command_id": command_id, "response": r})

		data = build_response_dict(conn, server.db.metadata)
		history.store('responses', session['active_account']['id'], data)
		conn.commit()
	await common.rpc.bot.static.modify_commands()
	return flask.redirect(f"{flask.url_for('.list')}#{command_id}")

@blueprint.route('/del', methods=['POST'])
@login.require_mod
async def delete(session):
	command_id = int(flask.request.values['command_id'])

	commands = server.db.metadata.tables["commands"]
	with server.db.engine.connect() as conn:
		conn.execute(commands.delete().where(commands.c.id == command_id))

		data = build_response_dict(conn, server.db.metadata)
		history.store('responses', session['active_account']['id'], data)
		conn.commit()
	await common.rpc.bot.static.modify_commands()
	return flask.redirect(flask.url_for('.list'))

def build_response_dict(conn, meta):
	commands = meta.tables["commands"]
	aliases = meta.tables["commands_aliases"]
	responses = meta.tables["commands_responses"]

	query = sqlalchemy.select(commands.c.access, aliases.c.alias, responses.c.response)
	query = query.select_from(
		commands.join(aliases, aliases.c.command_id == commands.c.id)
			.join(responses, responses.c.command_id == commands.c.id)
	)
	query = query.order_by(responses.c.id.asc())
	responses = {}
	for access, alias, response in conn.execute(query):
		if alias not in responses:
			responses[alias] = {"access": ["any", "sub", "mod"][access], "response": []}
		responses[alias]["response"].append(response)
	for val in responses.values():
		if len(val["response"]) == 1:
			val["response"] = val["response"][0]
	return responses
