from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Document Vault API"
    app_env: str = "local"
    instance_connection_name: str          # required: app fails fast if missing
    db_user: str = "vault_app"
    db_pass: str                            # required
    db_name: str = "vault"
    gcs_bucket: str
    signer_sa_email: str
    max_upload_mb: int = 25
    signed_url_minutes: int = 15
settings = Settings()
