"""生命周期收尾测试：后台任务不得在进程退出时被静默丢弃。"""

import asyncio

from app.core.config import Settings
from app.services.query_service import QueryService


def _service() -> QueryService:
    """只测 aclose，其余依赖不参与，传 None 即可。"""
    return QueryService(
        Settings(_env_file=None),
        None,  # llm
        None,  # prompts
        None,  # session_factory
        None,  # hybrid
        None,  # rerank
        None,  # evidence
        None,  # context
    )


def test_aclose_waits_for_background_task():
    async def scenario():
        service = _service()
        finished: list[str] = []

        async def quick():
            await asyncio.sleep(0.01)
            finished.append("quick")

        task = asyncio.create_task(quick())
        service._bg_tasks.add(task)

        await service.aclose(timeout=1.0)

        assert finished == ["quick"]
        assert task.done()

    asyncio.run(scenario())


def test_aclose_cancels_lingering_task_after_timeout():
    async def scenario():
        service = _service()
        cancelled = False

        async def hang():
            nonlocal cancelled
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled = True
                raise

        task = asyncio.create_task(hang())
        service._bg_tasks.add(task)

        await service.aclose(timeout=0.05)

        assert cancelled is True
        assert task.cancelled()

    asyncio.run(scenario())


def test_aclose_is_noop_without_pending_tasks():
    async def scenario():
        await _service().aclose(timeout=0.01)

    asyncio.run(scenario())
