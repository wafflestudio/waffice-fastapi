from uuid import uuid4


class S3Service:
    def __init__(self, bucket: str = "waffice-uploads", region: str = "ap-northeast-2"):
        """
        Mock S3 Service for generating presigned URLs.

        TODO: Replace with actual boto3 implementation when S3 is ready.
        """
        self.bucket = bucket
        self.region = region

    def generate_presigned_url(
        self, filename: str, content_type: str
    ) -> dict[str, str]:
        """
        Mock implementation for presigned URL generation.

        Returns:
            dict with 'upload_url' and 'file_url'

        Note: The upload_url is a placeholder and won't actually work.
        Actual S3 integration will require boto3 and proper AWS credentials.
        """
        mock_key = f"profiles/{uuid4()}/{filename}"
        return {
            "upload_url": f"https://mock-s3-upload.example.com/{mock_key}",
            "file_url": f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{mock_key}",
        }
