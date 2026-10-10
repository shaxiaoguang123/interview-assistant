"""0006 to 0007 leaves every existing table and historical trigger intact."""
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from app import create_app


def test_0006_upgrade_preserves_existing_rows_and_triggers(tmp_path):
    url=f"sqlite:///{tmp_path/'phase4-upgrade.sqlite3'}"
    cfg=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'));cfg.set_main_option('sqlalchemy.url',url)
    command.upgrade(cfg,'0006_phase3_review_schedule')
    app=create_app({'DATABASE_URL':url,'APP_DATA_DIR':tmp_path,'SEED_TOPICS_ON_STARTUP':False})
    c=app.test_client();q=c.post('/api/v1/questions',json={'text':'MCP migration history'}).get_json()['id']
    ps=c.post('/api/v1/practice-sessions',json={'mode':'random','limit':1}).get_json()
    item=ps['items'][0];r=c.post(f"/api/v1/session-items/{item['id']}/review",json={'review_rating':'basic'}).get_json()
    a=c.post(f'/api/v1/questions/{q}/saved-answers',json={'content':'Original saved answer','source_session_item_id':item['id'],'source_practice_review_id':r['id']})
    assert a.status_code==201
    engine=app.extensions['sqlalchemy_engine']
    with engine.connect() as conn:
        names=[row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='alembic_version'")]
        snapshots={n:conn.exec_driver_sql(f'SELECT * FROM {n} ORDER BY 1').all() for n in names}
        triggers=conn.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").all()
    engine.dispose();command.upgrade(cfg,'head')
    engine=create_engine(url)
    with engine.connect() as conn:
        for n in names:assert conn.exec_driver_sql(f'SELECT * FROM {n} ORDER BY 1').all()==snapshots[n]
        assert set(triggers).issubset(set(conn.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").all()))
        assert conn.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
        assert conn.exec_driver_sql('PRAGMA integrity_check').scalar()=='ok'
        assert conn.exec_driver_sql("SELECT rowid FROM question_fts WHERE question_fts MATCH 'MCP'").all()
    engine.dispose()
