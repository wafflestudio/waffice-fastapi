from pydantic import BaseModel


class PresignedUrlRequest(BaseModel):
    filename: str
    content_type: str


class PresignedUrlResponse(BaseModel):
    upload_url: str
    file_url: str
