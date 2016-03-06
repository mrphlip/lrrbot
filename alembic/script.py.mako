revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}

import alembic
import sqlalchemy
${imports if imports else ""}
def upgrade():
	${upgrades if upgrades else "pass"}

def downgrade():
	${downgrades if downgrades else "pass"}
