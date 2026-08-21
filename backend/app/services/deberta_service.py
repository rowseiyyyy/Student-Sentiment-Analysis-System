from app.core.config import settings
from app.services.transformer_service import TransformerSentimentService


class DeBERTaService(TransformerSentimentService):
    def __init__(self) -> None:
        super().__init__(settings.DEBERTA_MODEL_NAME, settings.DEBERTA_MODEL_PATH, settings.TRANSFORMER_DEVICE)


deberta_service = DeBERTaService()
