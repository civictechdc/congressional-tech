"""Identity: fixture people, the decision graph (C6), and mention linking."""
from news_lake.identity.decisions import apply_decisions
from news_lake.identity.linking import link_mentions
from news_lake.identity.people import PEOPLE, PEOPLE_BY_ID

__all__ = [
    'PEOPLE',
    'PEOPLE_BY_ID',
    'apply_decisions',
    'link_mentions',
]
