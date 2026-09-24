"""Response schema for Ask the bot. Passed to Gemini and re-validated here; Python then checks the content."""
from pydantic import BaseModel, field_validator


class BotAnswer(BaseModel):
    answerable: bool                  # false when the passages do not answer the question
    answer: str                       # short, plain answer written only from the passages
    citations: list[str]              # passage labels such as "P1", "P3"

    @field_validator("citations")
    @classmethod
    def clean(cls, value):
        return [v.strip().strip("[]").upper() for v in value if v and v.strip()]
