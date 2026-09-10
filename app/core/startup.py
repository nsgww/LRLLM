"""Startup consistency checks shared by the API and the ingestion worker.

06-retrieval-spec section 4: queries must use the same embedding model as the
index. A mismatch must be a configuration error, never a silent recall of
vectors produced by a different model.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError, QueryStage
from app.storage.postgres.repositories import DocumentRepository


async def validate_embedding_consistency(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    async with session_factory() as session:
        indexed = await DocumentRepository(session).distinct_embedding_versions()
    if indexed and settings.embedding_model_version not in indexed:
        raise AppError(
            code="EMBEDDING_MODEL_VERSION_MISMATCH",
            message=(
                f"configured embedding_model_version "
                f"'{settings.embedding_model_version}' does not match indexed "
                f"version(s) {sorted(indexed)}; reindex with a matching model"
            ),
            stage=QueryStage.VECTOR_RETRIEVAL,
        )
