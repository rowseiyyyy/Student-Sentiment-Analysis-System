from app.core.config import settings
from app.services.transformer_service import TransformerSentimentService


class RoBERTaService(TransformerSentimentService):
    def __init__(self) -> None:
        super().__init__(settings.ROBERTA_MODEL_NAME, settings.ROBERTA_MODEL_PATH, settings.TRANSFORMER_DEVICE)


roberta_service = RoBERTaService()
