import datetime
import sqlalchemy

from common.config import config
from common.sqlalchemy_pg95_upsert impot DoUpdate

def increment(engine, metadata, counter):
    storm = metadata.tables['storm']
    with engine.begin() as conn:
        do_update = DoUpdate([storm.c.date]).set(**{counter: storm.c[counter] + sqlalchemy.literal_column("EXCLUDED.count")})
        count, = conn.execute(storm.insert(postgresql_on_conflict=do_update).returning(storm.c[counter]), {
            'date': datetime.datetime.now(config['timezone']).date(),
            counter: 1,
        })
    return count

def get(engine, metadata, counter):
    storm = metadata.tables['storm']
    with engine.begin() as conn:
        row = conn.execute(sqlalchemy.select([storm.c[counter]])
            .where(storm.c.date == datetime.datetime.now(config['timezone']).date())) \
            .first()
    if row is not None:
        return row[0]
    return 0
