import datetime
import google.auth
from google.auth.transport.requests import Request as AuthRequest
from google.api_core.exceptions import NotFound
from google.cloud import storage

class StorageService:
    def __init__(self, bucket_name: str, signer_email: str):
        self.credentials, project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        self.client = storage.Client(credentials=self.credentials, project=project)
        self.bucket_name = bucket_name
        self.bucket = self.client.bucket(bucket_name)
        self.signer_email = signer_email

    def gcs_uri(self, object_name: str) -> str:
        return f"gs://{self.bucket_name}/{object_name}"

    def object_name(self, gcs_uri: str) -> str:
        return gcs_uri.removeprefix(f"gs://{self.bucket_name}/")

    def upload(self, fileobj, object_name: str, content_type: str) -> None:
        self.bucket.blob(object_name).upload_from_file(
            fileobj, content_type=content_type, rewind=True
        )

    def delete(self, object_name: str) -> None:
        try:
            self.bucket.blob(object_name).delete()
        except NotFound:
            pass  # already gone: deleting twice is safe

    def signed_download_url(self, object_name: str, filename: str, minutes: int) -> str:
        if not self.credentials.valid:
            self.credentials.refresh(AuthRequest())
        return self.bucket.blob(object_name).generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=minutes),
            method="GET",
            service_account_email=self.signer_email,   # sign via IAM signBlob
            access_token=self.credentials.token,       # no private key needed
            response_disposition=f'attachment; filename="{filename}"',
        )
