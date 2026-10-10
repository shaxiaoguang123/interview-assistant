"""Populated 0005 upgrades and interrupted parent-table copies remain atomic."""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app import create_app
from app.services.questions import prepare_question_text


def old_database(tmp_path):
    url=f"sqlite:///{tmp_path / 'upgrade.sqlite3'}"
    cfg=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    cfg.set_main_option('sqlalchemy.url',url)
    command.upgrade(cfg,'0005_saved_answers')
    engine=create_engine(url)
    with engine.begin() as c:
        c.exec_driver_sql('PRAGMA foreign_keys=ON')
        for qid,value,status,root in [(1,'MCP root','active',None),(2,'MCP child','merged',1),(3,'New question','active',None)]:
            raw,normalized,digest=prepare_question_text(value)
            c.exec_driver_sql('INSERT INTO question(id,text,normalized_text,search_text,normalized_hash,status,merged_into_question_id) VALUES (?,?,?,?,?,?,?)',
                (qid,raw,normalized,normalized,digest,status,root))
        c.exec_driver_sql("INSERT INTO question_state(question_id,is_favorite,is_wrong,user_note) VALUES(1,0,1,'keep note'),(2,1,0,'child note')")
        c.exec_driver_sql("INSERT INTO practice_session(id,mode,filters_json,selector_version) VALUES(10,'random','{}','v1'),(20,'topic','{}','v1')")
        c.exec_driver_sql("INSERT INTO session_item(id,session_id,question_id,ordinal,status) VALUES(11,10,1,1,'completed'),(12,10,2,2,'completed'),(21,20,3,1,'shown')")
        c.exec_driver_sql("INSERT INTO practice_review(id,question_id,session_item_id,review_rating,reviewed_at) VALUES(11,1,11,'basic','2026-10-08 08:00:00'),(12,2,12,'vague','2026-10-08 08:00:00')")
        c.exec_driver_sql("INSERT INTO saved_answer(id,question_id,source_session_item_id,is_pinned) VALUES(16,2,12,1)")
        c.exec_driver_sql("INSERT INTO saved_answer_version(id,saved_answer_id,version_no,content,source_session_item_id,source_practice_review_id,self_rating) VALUES(17,16,1,'Historical answer',12,12,5)")
        c.exec_driver_sql('UPDATE practice_review SET saved_answer_version_id=17 WHERE id=12')
    return cfg,engine,url


def snapshot(engine):
    names=['question','question_fts','question_state','practice_session','session_item','practice_review','saved_answer','saved_answer_version']
    with engine.connect() as c:
        columns={n:','.join(r[1] for r in c.exec_driver_sql(f'PRAGMA table_info({n})')) for n in names}
        data={n:c.exec_driver_sql(f'SELECT {columns[n]} FROM {n} ORDER BY 1').all() for n in names}
        triggers=c.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").all()
    return columns,data,triggers


def test_0005_upgrade_keeps_sessions_answers_reviews_flags_and_fts(tmp_path):
    cfg,engine,url=old_database(tmp_path)
    columns,before,triggers=snapshot(engine)
    command.upgrade(cfg,'0006_phase3_review_schedule')
    with engine.begin() as c:
        for table in columns:
            assert c.exec_driver_sql(f'SELECT {columns[table]} FROM {table} ORDER BY 1').all()==before[table]
        assert c.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name").all()==triggers
        row=c.exec_driver_sql('SELECT last_review_rating,next_review_at FROM question_state WHERE question_id=1').one()
        assert row[0]=='vague' and str(row[1]).startswith('2026-10-10 08:00:00')
        assert c.exec_driver_sql('SELECT next_review_at FROM question_state WHERE question_id=2').scalar() is None
        assert c.exec_driver_sql('SELECT count(*) FROM question_state WHERE question_id=3').scalar()==0
        assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
        assert c.exec_driver_sql('PRAGMA integrity_check').scalar()=='ok'
        c.exec_driver_sql("INSERT INTO practice_session(mode) VALUES ('due')")
        # All three FTS triggers still react to insert/update/delete.
        c.exec_driver_sql("UPDATE question SET search_text='Changedsearch' WHERE id=3")
        assert c.exec_driver_sql("SELECT rowid FROM question_fts WHERE question_fts MATCH 'Changedsearch'").all()
    app=create_app({'DATABASE_URL':url,'APP_DATA_DIR':tmp_path,'SEED_TOPICS_ON_STARTUP':False})
    response=app.test_client().post('/api/v1/session-items/21/review',json={'review_rating':'proficient'})
    assert response.status_code==201,response.get_json()
    assert response.get_json()['question_id']==3 and response.get_json()['session_item_id']==21
    engine.dispose();app.extensions['sqlalchemy_engine'].dispose()


def test_failed_backfill_rolls_back_check_change_columns_and_data(tmp_path):
    cfg,engine,_=old_database(tmp_path)
    with engine.begin() as c:
        c.exec_driver_sql("CREATE TRIGGER fail_backfill BEFORE UPDATE ON question_state BEGIN SELECT RAISE(ABORT,'test backfill failure'); END")
    columns,before,triggers=snapshot(engine)
    with pytest.raises(Exception,match='test backfill failure'):
        command.upgrade(cfg,'0006_phase3_review_schedule')
    assert snapshot(engine)==(columns,before,triggers)
    with engine.begin() as c:
        assert c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar()=='0005_saved_answers'
        assert c.exec_driver_sql("SELECT count(*) FROM sqlite_master WHERE name='_alembic_tmp_practice_session'").scalar()==0
        assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
        c.exec_driver_sql('DROP TRIGGER fail_backfill')
    command.upgrade(cfg,'0006_phase3_review_schedule')
    engine.dispose()
