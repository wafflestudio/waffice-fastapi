import os
from urllib.parse import quote, unquote, urlparse
from uuid import uuid4

from fastapi import UploadFile

from app.exceptions import ObjectStorageError

PROFILE_IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class OCIObjectStorageService:
    def __init__(self):
        try:
            import oci
        except ImportError:
            raise ObjectStorageError("oci package is not installed")

        self.oci = oci
        self.namespace = os.getenv("OCI_NAMESPACE", "")
        self.bucket = os.getenv("OCI_BUCKET", "")
        self.region = os.getenv("OCI_REGION", "")
        if not all((self.namespace, self.bucket, self.region)):
            raise ObjectStorageError("OCI object storage is not configured")

        config_file = os.getenv("OCI_CONFIG_FILE")
        profile = os.getenv("OCI_CONFIG_PROFILE", "DEFAULT")
        try:
            config = (
                oci.config.from_file(config_file, profile)
                if config_file
                else oci.config.from_file(profile_name=profile)
            )
            self.client = oci.object_storage.ObjectStorageClient(config)
        except Exception as exc:
            raise ObjectStorageError("OCI object storage is not configured") from exc

    def upload_profile_image(self, user_id: int, file: UploadFile, body: bytes) -> str:
        object_name = (
            f"profiles/{user_id}/{uuid4()}{PROFILE_IMAGE_EXTENSIONS[file.content_type]}"
        )
        try:
            self.client.put_object(
                self.namespace,
                self.bucket,
                object_name,
                body,
                content_type=file.content_type,
            )
        except Exception as exc:
            raise ObjectStorageError("Failed to upload profile image") from exc
        return self.public_url(object_name)

    def delete_profile_image(self, user_id: int, url: str | None) -> None:
        object_name = self.object_name_from_url(url)
        if not object_name or not object_name.startswith(f"profiles/{user_id}/"):
            return
        try:
            self.client.delete_object(self.namespace, self.bucket, object_name)
        except Exception:
            pass

    def public_url(self, object_name: str) -> str:
        base_url = (
            os.getenv("OCI_PUBLIC_BASE_URL")
            or f"https://objectstorage.{self.region}.oraclecloud.com/n/{self.namespace}/b/{self.bucket}/o"
        ).rstrip("/")
        return f"{base_url}/{quote(object_name, safe='')}"

    def object_name_from_url(self, url: str | None) -> str | None:
        if not url:
            return None
        path = urlparse(url).path
        marker = f"/n/{self.namespace}/b/{self.bucket}/o/"
        if marker in path:
            return unquote(path.split(marker, 1)[1])
        base_url = os.getenv("OCI_PUBLIC_BASE_URL", "").rstrip("/")
        if base_url and url.startswith(f"{base_url}/"):
            return unquote(url[len(base_url) + 1 :])
        return None
