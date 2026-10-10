"""Versioned project evidence and explicitly saved assistant outputs.

Frozen SQLite DDL; all existing historical tables remain in place.
"""
from alembic import op
import sqlalchemy as sa
revision = '0007_project_material_assistant'
down_revision = '0006_phase3_review_schedule'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE TABLE project (\n\tid INTEGER NOT NULL, \n\tname VARCHAR(240) NOT NULL, \n\tsummary TEXT DEFAULT '' NOT NULL, \n\ttech_stack TEXT DEFAULT '' NOT NULL, \n\tpersonal_role TEXT DEFAULT '' NOT NULL, \n\tchallenges TEXT DEFAULT '' NOT NULL, \n\toutcomes TEXT DEFAULT '' NOT NULL, \n\thighlights TEXT DEFAULT '' NOT NULL, \n\tnotes TEXT DEFAULT '' NOT NULL, \n\tis_active BOOLEAN DEFAULT 1 NOT NULL, \n\tarchived_at DATETIME, \n\tcreated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tupdated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tPRIMARY KEY (id)\n)")
    op.execute("CREATE TABLE material (\n\tid INTEGER NOT NULL, \n\tkind VARCHAR(32) NOT NULL, \n\tproject_id INTEGER, \n\ttitle VARCHAR(240) NOT NULL, \n\toriginal_filename VARCHAR(512), \n\tis_active BOOLEAN DEFAULT 1 NOT NULL, \n\tinclude_in_context BOOLEAN DEFAULT 1 NOT NULL, \n\tis_system_managed BOOLEAN DEFAULT 0 NOT NULL, \n\tarchived_at DATETIME, \n\tcreated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tupdated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_material_kind CHECK (kind IN ('resume','project_profile','project_brief','readme','architecture_doc','other')), \n\tCONSTRAINT ck_material_profile_owner CHECK ((kind = 'project_profile' AND is_system_managed = 1 AND project_id IS NOT NULL) OR (kind != 'project_profile' AND is_system_managed = 0)), \n\tFOREIGN KEY(project_id) REFERENCES project (id) ON DELETE RESTRICT\n)")
    op.execute("CREATE UNIQUE INDEX uq_material_project_profile ON material (project_id) WHERE kind = 'project_profile' AND is_system_managed = 1")
    op.execute('CREATE INDEX ix_material_project_id ON material (project_id)')
    op.execute('CREATE TABLE material_version (\n\tid INTEGER NOT NULL, \n\tmaterial_id INTEGER NOT NULL, \n\tversion_no INTEGER NOT NULL, \n\tpath VARCHAR(512) NOT NULL, \n\toriginal_filename VARCHAR(512) NOT NULL, \n\tsha256 VARCHAR(64) NOT NULL, \n\tbyte_size INTEGER NOT NULL, \n\tparsed_at DATETIME NOT NULL, \n\tcreated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_material_version_no UNIQUE (material_id, version_no), \n\tCONSTRAINT ck_material_version_no CHECK (version_no > 0), \n\tFOREIGN KEY(material_id) REFERENCES material (id) ON DELETE RESTRICT\n)')
    op.execute('CREATE INDEX ix_material_version_material_id ON material_version (material_id)')
    op.execute('CREATE TABLE material_chunk (\n\tid INTEGER NOT NULL, \n\tmaterial_version_id INTEGER NOT NULL, \n\tproject_id INTEGER, \n\tordinal INTEGER NOT NULL, \n\tpage_number INTEGER, \n\theading VARCHAR(240), \n\ttext TEXT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_material_chunk_ordinal UNIQUE (material_version_id, ordinal), \n\tFOREIGN KEY(material_version_id) REFERENCES material_version (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(project_id) REFERENCES project (id) ON DELETE RESTRICT\n)')
    op.execute('CREATE INDEX ix_material_chunk_material_version_id ON material_chunk (material_version_id)')
    op.execute("CREATE TABLE assistant_output (\n\tid INTEGER NOT NULL, \n\tpreview_key VARCHAR(36) NOT NULL, \n\tquestion_id INTEGER NOT NULL, \n\tsource_saved_answer_version_id INTEGER, \n\toutput_type VARCHAR(32) NOT NULL, \n\torigin_kind VARCHAR(24) NOT NULL, \n\tselected_context_json JSON NOT NULL, \n\tcontent_text TEXT NOT NULL, \n\tprovider VARCHAR(80) NOT NULL, \n\tmodel VARCHAR(120) NOT NULL, \n\tprompt_version VARCHAR(40) NOT NULL, \n\tcreated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_assistant_output_type CHECK (output_type IN ('polish','reference_answer','analyze')), \n\tUNIQUE (preview_key), \n\tFOREIGN KEY(question_id) REFERENCES question (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(source_saved_answer_version_id) REFERENCES saved_answer_version (id) ON DELETE RESTRICT\n)")
    op.execute('CREATE INDEX ix_assistant_output_question_id ON assistant_output (question_id)')
    op.execute('CREATE TABLE assistant_output_source (\n\tid INTEGER NOT NULL, \n\tassistant_output_id INTEGER NOT NULL, \n\tmaterial_version_id INTEGER, \n\tmaterial_id_snapshot INTEGER NOT NULL, \n\tmaterial_version_id_snapshot INTEGER NOT NULL, \n\tproject_id_snapshot INTEGER, \n\tchunk_ids_json JSON, \n\tsource_title_snapshot VARCHAR(240) NOT NULL, \n\tversion_no_snapshot INTEGER NOT NULL, \n\tsha256_snapshot VARCHAR(64) NOT NULL, \n\tsource_deleted_at DATETIME, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(assistant_output_id) REFERENCES assistant_output (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(material_version_id) REFERENCES material_version (id) ON DELETE SET NULL\n)')
    op.execute('CREATE INDEX ix_assistant_output_source_assistant_output_id ON assistant_output_source (assistant_output_id)')
    op.execute("CREATE VIRTUAL TABLE material_chunk_fts USING fts5(text, content='material_chunk', content_rowid='id', tokenize='unicode61')")
    op.execute('CREATE TRIGGER material_chunk_fts_insert AFTER INSERT ON material_chunk BEGIN INSERT INTO material_chunk_fts(rowid,text) VALUES(new.id,new.text); END')
    op.execute("CREATE TRIGGER material_chunk_fts_delete AFTER DELETE ON material_chunk BEGIN INSERT INTO material_chunk_fts(material_chunk_fts,rowid,text) VALUES('delete',old.id,old.text); END")
    op.execute("CREATE TRIGGER material_chunk_fts_update AFTER UPDATE OF text ON material_chunk BEGIN INSERT INTO material_chunk_fts(material_chunk_fts,rowid,text) VALUES('delete',old.id,old.text); INSERT INTO material_chunk_fts(rowid,text) VALUES(new.id,new.text); END")
    op.execute("CREATE TRIGGER saved_answer_assistant_reference_insert BEFORE INSERT ON saved_answer_version WHEN NEW.assistant_output_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM assistant_output WHERE id=NEW.assistant_output_id) BEGIN SELECT RAISE(ABORT,'Assistant output reference does not exist'); END")
    op.execute("CREATE TRIGGER saved_answer_assistant_reference_update BEFORE UPDATE ON saved_answer_version WHEN NEW.assistant_output_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM assistant_output WHERE id=NEW.assistant_output_id) BEGIN SELECT RAISE(ABORT,'Assistant output reference does not exist'); END")
    op.execute("CREATE TRIGGER assistant_output_answer_restrict BEFORE DELETE ON assistant_output WHEN EXISTS(SELECT 1 FROM saved_answer_version WHERE assistant_output_id=OLD.id) BEGIN SELECT RAISE(ABORT,'Assistant output is referenced by an answer'); END")
    op.execute("CREATE TRIGGER material_version_immutable BEFORE UPDATE ON material_version WHEN NEW.material_id IS NOT OLD.material_id OR NEW.version_no IS NOT OLD.version_no OR NEW.path IS NOT OLD.path OR NEW.original_filename IS NOT OLD.original_filename OR NEW.sha256 IS NOT OLD.sha256 OR NEW.byte_size IS NOT OLD.byte_size OR NEW.parsed_at IS NOT OLD.parsed_at OR NEW.created_at IS NOT OLD.created_at BEGIN SELECT RAISE(ABORT,'Material evidence versions are immutable'); END")
    op.execute("CREATE TRIGGER material_chunk_immutable BEFORE UPDATE ON material_chunk WHEN NEW.material_version_id IS NOT OLD.material_version_id OR NEW.project_id IS NOT OLD.project_id OR NEW.ordinal IS NOT OLD.ordinal OR NEW.page_number IS NOT OLD.page_number OR NEW.heading IS NOT OLD.heading OR NEW.text IS NOT OLD.text BEGIN SELECT RAISE(ABORT,'Material evidence versions are immutable'); END")


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM material')) or op.get_bind().scalar(sa.text('SELECT count(*) FROM assistant_output')):
        raise RuntimeError('Cannot downgrade while Phase 4 history exists')
    for name in ('saved_answer_assistant_reference_insert','saved_answer_assistant_reference_update','assistant_output_answer_restrict','material_version_immutable','material_chunk_immutable','material_chunk_fts_insert','material_chunk_fts_delete','material_chunk_fts_update'):
        op.execute(f'DROP TRIGGER {name}')
    op.execute('DROP TABLE material_chunk_fts')
    for name in ('assistant_output_source','assistant_output','material_chunk','material_version','material','project'):
        op.drop_table(name)
