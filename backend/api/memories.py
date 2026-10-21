from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.deps import CurrentUser, MemoriesDep
from backend.schemas.memory import MemoryOut, UpdateMemoryRequest

router = APIRouter()


@router.get("/memories", response_model=list[MemoryOut])
async def list_memories(user: CurrentUser, memories: MemoriesDep):
    return await memories.list_for_user(user.id)


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
async def update_memory(
    memory_id: str, body: UpdateMemoryRequest, user: CurrentUser, memories: MemoriesDep
):
    row = await memories.update_content(user.id, memory_id, body.content)
    if row is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return row


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, user: CurrentUser, memories: MemoriesDep):
    if not await memories.delete_by_id(user.id, memory_id):
        raise HTTPException(status_code=404, detail="memory not found")
    return {"deleted": memory_id}
