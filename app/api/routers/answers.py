"""On-demand evidence endpoint (05-api-spec section 9)."""

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_api_key, require_kb_id
from app.api.schemas import EvidenceOut

router = APIRouter(tags=["answers"], dependencies=[Depends(require_api_key)])


@router.get("/answers/{answer_id}/evidence", response_model=EvidenceOut)
async def get_evidence(
    answer_id: str,
    request: Request,
    kb_id: str = Depends(require_kb_id),
) -> EvidenceOut:
    result = await request.app.state.query_service.get_answer_evidence(answer_id, kb_id)
    return EvidenceOut(**result)
