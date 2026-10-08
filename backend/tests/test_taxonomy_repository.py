from app.models.taxonomy import Tag, Topic
from app.repositories import taxonomy


def test_load_taxonomy_by_ids_preserves_requested_order(db_session):
    first_topic = Topic(track_key="agent_development", slug="repo-topic-first", name="First")
    second_topic = Topic(track_key="agent_development", slug="repo-topic-second", name="Second")
    first_tag = Tag(name="Repository First")
    second_tag = Tag(name="Repository Second")
    db_session.add_all([first_topic, second_topic, first_tag, second_tag])
    db_session.flush()

    assert taxonomy.get_topics_by_ids(db_session, [second_topic.id, first_topic.id]) == [second_topic, first_topic]
    assert taxonomy.get_tags_by_ids(db_session, [second_tag.id, first_tag.id]) == [second_tag, first_tag]
