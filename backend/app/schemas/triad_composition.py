"""Response contract of a standard triad composition version."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class TriadComponent(BaseModel):
    id_modelo: int
    catalogue_id: str
    weight: float


class TriadCompositionResponse(BaseModel):
    id: int
    model_id: str
    dataset_id: int
    partition_version: Optional[str] = None
    job_id: str
    version: int
    previous_id: Optional[int] = None
    latest: bool
    active: bool
    components: List[TriadComponent]
    author_id: Optional[int] = None
    created_at: datetime
