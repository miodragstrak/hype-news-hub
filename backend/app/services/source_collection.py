"""Shared outcome classification without changing public response schemas."""
import logging

from app.connectors.errors import SourceFetchError
from app.services.article_normalizer import normalize_articles

logger = logging.getLogger(__name__)


def normalize_source_batch(connector_articles, source_url, connector="wordpress", source_name=None):
    if not isinstance(connector_articles, list) or any(not isinstance(item, dict) for item in connector_articles):
        raise SourceFetchError("malformed_structure")
    normalized = normalize_articles(connector_articles, source_url, connector, source_name)
    if not connector_articles:
        logger.info("source_outcome=upstream_empty source=%s", source_name or source_url)
    elif not normalized:
        raise SourceFetchError("normalization_filtered")
    elif len(normalized) != len(connector_articles):
        logger.warning("source_outcome=normalization_filtered source=%s fetched=%d accepted=%d", source_name or source_url, len(connector_articles), len(normalized))
    else:
        logger.info("source_outcome=collected source=%s accepted=%d", source_name or source_url, len(normalized))
    return normalized
