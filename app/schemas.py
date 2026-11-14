from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator

class DocumentCreate(BaseModel):
    owner: str = Field(min_length=2, max_length=100)
    filename: str = Field(min_length=1, max_length=255)
    gcs_path: str = Field(pattern=r"^gs://")
    size_bytes: int = Field(ge=0)
    content_type: str = "application/octet-stream"
    tags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, v: list[str]) -> list[str]:
        cleaned = {t.strip().lower() for t in v if t.strip()}
        if any(len(t) > 50 for t in cleaned):
            raise ValueError("each tag must be 50 characters or fewer")
        return sorted(cleaned)

class DocumentOut(DocumentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
