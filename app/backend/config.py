from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    database_url: str = 'postgresql+psycopg://compass:compass@127.0.0.1:5440/compass'
    public_url: str = 'http://localhost:5174'
    allowed_origins: str = 'http://localhost:5174,http://127.0.0.1:5174,http://localhost:8010,http://127.0.0.1:8010'
    cookie_secure: bool = False
    session_days: int = 7
    upload_dir: Path = ROOT / 'var' / 'uploads'
    max_upload_mb: int = 15
    ollama_url: str = 'http://127.0.0.1:11434'
    llm_model: str = 'qwen3:4b-q4_K_M'
    embedding_model: str = 'qwen3-embedding:0.6b'
    ai_max_retries: int = 3
    pubmed_email: str = ''
    pubmed_api_key: str = ''
    pubmed_query: str = '(depression OR anxiety) AND (treatment OR adverse effects)'
    knowledge_sync_hours: int = 24
    vapid_public_key: str = ''
    vapid_private_key: str = ''
    vapid_contact: str = 'mailto:developer@example.com'
    demo_rules: bool = True
    frontend_dist: Path = ROOT / 'app' / 'frontend' / 'dist'
    @property
    def origins(self):
        return [x.strip().rstrip('/') for x in self.allowed_origins.split(',') if x.strip()]

settings = Settings()
