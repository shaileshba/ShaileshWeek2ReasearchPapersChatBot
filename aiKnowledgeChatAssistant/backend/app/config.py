from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE = Path(__file__).resolve().parents[1]
class Settings(BaseSettings):
    openai_api_key: str = ''
    answer_model: str = 'gpt-5.4'
    embedding_model: str = 'text-embedding-3-large'
    rag_data_dir: Path = BASE.parents[1] / 'RAG data'
    storage_dir: Path = BASE / 'storage'
    model_config = SettingsConfigDict(env_file=BASE / '.env', extra='ignore')

settings = Settings()
