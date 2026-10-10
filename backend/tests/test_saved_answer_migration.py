"""Upgrade a populated 0004 database in place, including FTS and OCR evidence."""
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app import create_app
from app.models.question import Question
from app.models.practice import PracticeSession, SessionItem
from app.models.ingestion import SourceAsset, IngestionJob, OCRBlock, QuestionSource, QuestionSourceOCRBlock
from app.services.questions import prepare_question_text


def test_0004_upgrade_preserves_all_history_and_fts(tmp_path):
    path=tmp_path/'upgrade.sqlite3';url=f'sqlite:///{path}'
    cfg=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    cfg.set_main_option('sqlalchemy.url',url)
    command.upgrade(cfg,'0004_question_relations')
    app=create_app({'DATABASE_URL':url,'APP_DATA_DIR':tmp_path,'SEED_TOPICS_ON_STARTUP':False})
    with app.extensions['sqlalchemy_session_factory'].begin() as s:
        raw,normalized,digest=prepare_question_text('MCP 历史问题')
        q=Question(text=raw,normalized_text=normalized,search_text=normalized,normalized_hash=digest,status='active')
        ps=PracticeSession(mode='random',filters_json={})
        asset=SourceAsset(original_filename='synthetic.png',mime_type='image/png',byte_size=10,
            original_width=100,original_height=80,display_width=100,display_height=80,
            original_path='synthetic.png',display_preview_path='synthetic.png',sha256='a'*64)
        s.add_all([q,ps,asset]);s.flush()
        job=IngestionJob(source_asset_id=asset.id,status='succeeded',stage='completed');s.add(job);s.flush()
        block=OCRBlock(ingestion_job_id=job.id,text='原始 OCR',bbox_json={'x':10,'y':20,'width':50,'height':10},reading_order=0)
        source=QuestionSource(question_id=q.id,source_asset_id=asset.id,locator_json=block.bbox_json,
            source_text_snapshot='原始证据',raw_ocr_text_snapshot='原始 OCR')
        item=SessionItem(session_id=ps.id,question_id=q.id,ordinal=1,status='completed')
        s.add_all([block,source,item]);s.flush()
        s.add(QuestionSourceOCRBlock(question_source_id=source.id,ocr_block_id=block.id))
        s.connection().exec_driver_sql("INSERT INTO practice_review(question_id,session_item_id,review_rating) VALUES (?,?,'basic')",(q.id,item.id))
    engine=app.extensions['sqlalchemy_engine']
    names=['question','question_fts','source_asset','ingestion_job','ocr_block','question_source',
           'question_source_ocr_block','practice_session','session_item','practice_review']
    with engine.connect() as c:
        old_columns={n:[r[1] for r in c.exec_driver_sql(f'PRAGMA table_info({n})')] for n in names}
        snapshots={n:c.exec_driver_sql(f'SELECT * FROM {n} ORDER BY 1').all() for n in names}
    engine.dispose()
    command.upgrade(cfg,'head')
    with create_engine(url).connect() as c:
        for name in names:
            columns=','.join(old_columns[name])
            assert c.exec_driver_sql(f'SELECT {columns} FROM {name} ORDER BY 1').all()==snapshots[name]
        assert c.exec_driver_sql("SELECT rowid FROM question_fts WHERE question_fts MATCH 'MCP'").all()
        assert c.exec_driver_sql('PRAGMA integrity_check').scalar()=='ok'
        assert c.exec_driver_sql('PRAGMA foreign_key_check').all()==[]
        assert c.exec_driver_sql('SELECT saved_answer_version_id FROM practice_review').scalar() is None
