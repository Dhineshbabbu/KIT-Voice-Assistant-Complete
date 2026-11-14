from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    college_api_url: str = "https://ht.knowvally.com"
    college_participant_key: str = ""
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    deepgram_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    elevenlabs_model_id: str = "eleven_flash_v2_5"
    elevenlabs_output_format: str = "mp3_44100_128"
    session_secret: str = "CHANGE_ME"
    database_path: str = "data/kit.db"
    session_cookie_secure: bool = False
    enable_document_rag: bool = True
    document_cache_dir: str = "data/documents"
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
