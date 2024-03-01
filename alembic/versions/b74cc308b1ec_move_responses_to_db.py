revision = 'b74cc308b1ec'
down_revision = '66d78d1a29ee'
branch_labels = None
depends_on = None

import alembic
import sqlalchemy
import json
from collections import defaultdict

def upgrade():
	commands = alembic.op.create_table("commands",
		sqlalchemy.Column("id", sqlalchemy.Integer, sqlalchemy.Identity(), primary_key=True),
		sqlalchemy.Column("access", sqlalchemy.Integer, nullable=False),
	)

	aliases = alembic.op.create_table("commands_aliases",
		sqlalchemy.Column("id", sqlalchemy.Integer, sqlalchemy.Identity(), primary_key=True),
		sqlalchemy.Column("command_id", sqlalchemy.Integer,
			sqlalchemy.ForeignKey("commands.id", ondelete="CASCADE"), nullable=False),
		sqlalchemy.Column("alias", sqlalchemy.String, nullable=False, unique=True),
	)

	responses = alembic.op.create_table("commands_responses",
		sqlalchemy.Column("id", sqlalchemy.Integer, sqlalchemy.Identity(), primary_key=True),
		sqlalchemy.Column("command_id", sqlalchemy.Integer,
			sqlalchemy.ForeignKey("commands.id", ondelete="CASCADE"), nullable=False),
		sqlalchemy.Column("response", sqlalchemy.String, nullable=False),
	)

	datafile = alembic.context.config.get_section_option("lrrbot", "datafile", "data.json")
	try:
		with open(datafile) as f:
			data = json.load(f)
	except FileNotFoundError:
		data = {}

	command_data = defaultdict(list)
	for cmd, val in data.get("responses", {}).items():
		resp = tuple(val["response"]) if isinstance(val["response"], list) else (val["response"],)
		access = {"any": 0, "sub": 1, "mod": 2}[val["access"]]
		command_data[resp, access].append(cmd)

	command_records = []
	alias_records = []
	response_records = []

	for (resp, access), cmds in command_data.items():
		command_records.append({"access": access})
		command_id = len(command_records)
		for i in cmds:
			alias_records.append({"command_id": command_id, "alias": i})
		for i in resp:
			response_records.append({"command_id": command_id, "response": i})

	alembic.op.bulk_insert(commands, command_records)
	alembic.op.bulk_insert(aliases, alias_records)
	alembic.op.bulk_insert(responses, response_records)

	data.pop("responses", None)
	with open(datafile, "w") as f:
		json.dump(data, f, indent=2, sort_keys=True)

def downgrade():
	conn = alembic.context.get_context().bind
	meta = sqlalchemy.MetaData()
	meta.reflect(conn)

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

	datafile = alembic.context.config.get_section_option("lrrbot", "datafile", "data.json")
	try:
		with open(datafile) as f:
			data = json.load(f)
	except FileNotFoundError:
		data = {}
	data["responses"] = responses
	with open(datafile, "w") as f:
		json.dump(data, f, indent=2, sort_keys=True)

	alembic.op.drop_table("commands_aliases")
	alembic.op.drop_table("commands_responses")
	alembic.op.drop_table("commands")
