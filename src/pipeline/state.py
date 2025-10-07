from pydantic import BaseModel, Field
from typing import List, Dict, Any

class Item(BaseModel):
    id: str
    title: str
    description: str
    attributes: Dict[str, Any] = Field(default_factory=dict)

class TranslatedItem(BaseModel):
    id: str
    channel_payload: Dict[str, Any]

class PipelineState(BaseModel):
    channel: str
    catalog_path: str
    dry_run: bool = True
    batch_size: int = 50
    items: List[Item] = Field(default_factory=list)
    mapped: List[TranslatedItem] = Field(default_factory=list)
    valid: List[TranslatedItem] = Field(default_factory=list)
    batches: List[List[TranslatedItem]] = Field(default_factory=list)
    upserted_ids: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
