"""On-demand evidence endpoint (05-api-spec section 9)."""

from fastapi import APIRouter, Request

from app.api.schemas import EvidenceOut

router = APIRouter(tags=["answers"])


@router.get("/answers/{answer_id}/evidence", response_model=EvidenceOut)
async def get_evidence(answer_id: str, request: Request) -> EvidenceOut:
    result = await request.app.state.query_service.get_answer_evidence(answer_id)
    return EvidenceOut(**result)
