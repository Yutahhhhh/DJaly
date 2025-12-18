from pydantic import BaseModel

class GenreAnalyzeAllRequest(BaseModel):
    mode: str = "keep" # "keep" or "overwrite"
