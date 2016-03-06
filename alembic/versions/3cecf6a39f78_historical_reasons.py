revision = '3cecf6a39f78'
down_revision = None
branch_labels = None
depends_on = None

import alembic
import sqlalchemy
from sqlalchemy.dialects import postgresql

def upgrade():
	alembic.op.create_table("cards",
		sqlalchemy.Column("cardid", sqlalchemy.Integer, primary_key=True),
		sqlalchemy.Column("filteredname", sqlalchemy.String(255), nullable=False),
		sqlalchemy.Column("name", sqlalchemy.Text(collation="en_US.utf8"), nullable=False),
		sqlalchemy.Column("text", sqlalchemy.Text(collation="en_US.utf8"), nullable=False),
		sqlalchemy.Column("lastprinted", sqlalchemy.Date),
	)
	alembic.op.create_index("cards_name_idx", "cards", ["filteredname"], unique=True)

	alembic.op.create_table("card_multiverse",
		sqlalchemy.Column("multiverseid", sqlalchemy.Integer, primary_key=True, autoincrement=False),
		sqlalchemy.Column("cardid", sqlalchemy.Integer, sqlalchemy.ForeignKey("cards.cardid", ondelete="CASCADE"), nullable=False),
	)

	alembic.op.create_table("highlights",
		sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
		sqlalchemy.Column("title", sqlalchemy.Text, nullable=False),
	    sqlalchemy.Column("description", sqlalchemy.Text, nullable=False),
	    sqlalchemy.Column("time", sqlalchemy.DateTime(timezone=True), nullable=False),
	    sqlalchemy.Column("nick", sqlalchemy.Text, nullable=False),
	)

	alembic.op.create_table("history",
        sqlalchemy.Column("historykey", sqlalchemy.Integer, primary_key=True),
        sqlalchemy.Column("section", sqlalchemy.Text(collation="en_US.utf8"), nullable=False),
        sqlalchemy.Column("changetime", sqlalchemy.DateTime(timezone=True), nullable=False),
        sqlalchemy.Column("changeuser", sqlalchemy.Text(collation="en_US.utf8")),
        sqlalchemy.Column("jsondata", postgresql.JSONB),
	)
	alembic.op.create_index("history_idx1", "history", ["section", "changetime"])

	alembic.op.create_table("log",
		sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
	    sqlalchemy.Column("time", sqlalchemy.DateTime(timezone=True), nullable=False),
	    sqlalchemy.Column("source", sqlalchemy.Text(collation="en_US.utf8"), nullable=False),
	    sqlalchemy.Column("target", sqlalchemy.Text(collation="en_US.utf8"), nullable=False),
	    sqlalchemy.Column("message", sqlalchemy.Text(collation="en_US.utf8"), nullable=False),
	    sqlalchemy.Column("messagehtml", sqlalchemy.Text(collation="en_US.utf8"), nullable=False),
	    sqlalchemy.Column("specialuser", postgresql.ARRAY(sqlalchemy.Text)),
	    sqlalchemy.Column("usercolor", sqlalchemy.Text(collation="en_US.utf8")),
	    sqlalchemy.Column("emoteset", postgresql.ARRAY(sqlalchemy.Integer)),
	    sqlalchemy.Column("emotes", sqlalchemy.Text),
	    sqlalchemy.Column("displayname", sqlalchemy.Text),
	)
	alembic.op.create_index("log_idx1", "log", ["time"])

	alembic.op.create_table("notification",
        sqlalchemy.Column("notificationkey", sqlalchemy.Integer, primary_key=True),
        sqlalchemy.Column("message", sqlalchemy.Text(collation="en_US.utf8")),
        sqlalchemy.Column("channel", sqlalchemy.Text(collation="en_US.utf8")),
        sqlalchemy.Column("subuser", sqlalchemy.Text(collation="en_US.utf8")),
        sqlalchemy.Column("useravatar", sqlalchemy.Text(collation="en_US.utf8")),
        sqlalchemy.Column("eventtime", sqlalchemy.DateTime(timezone=True), nullable=True),
        sqlalchemy.Column("monthcount", sqlalchemy.Integer, nullable=True),
        sqlalchemy.Column("test", sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false()),
	)
	alembic.op.create_index("notification_idx1", "notification", ["eventtime"])

	alembic.op.create_table("quotes",
	    sqlalchemy.Column("qid", sqlalchemy.Integer, primary_key=True),
	    sqlalchemy.Column("quote", sqlalchemy.Text, nullable=False),
	    sqlalchemy.Column("attrib_name", sqlalchemy.Text),
	    sqlalchemy.Column("attrib_date", sqlalchemy.Date),
	    sqlalchemy.Column("deleted", sqlalchemy.Boolean, nullable=False, server_default=sqlalchemy.false()),
	)
	alembic.op.create_index("quotes_ftx_idx", "quotes", [sqlalchemy.text("TO_TSVECTOR('english', quote)")], postgresql_using="gin")

def downgrade():
	alembic.op.drop_table("card_multiverse")
	alembic.op.drop_table("cards")
	alembic.op.drop_table("highlights")
	alembic.op.drop_table("history")
	alembic.op.drop_table("log")
	alembic.op.drop_table("notification")
	alembic.op.drop_table("quotes")
