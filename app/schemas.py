from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class JobCreate(BaseModel):
    job_type: Literal["sum_numbers", "word_count"]
    payload: dict[str, Any]
    max_attempts: int = Field(default=3, ge=1, le=10)

class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    job_type: str
    payload: dict[str, Any]
    status: str
    attempts: int
    max_attempts: int
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    next_run_at: datetime
