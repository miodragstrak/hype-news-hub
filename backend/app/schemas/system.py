from pydantic import BaseModel


class SystemStatusResponse(BaseModel):
    name: str
    status: str
