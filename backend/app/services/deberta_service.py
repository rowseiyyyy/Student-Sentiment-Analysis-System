from app.core.config import settings
from app.services.transformer_service import TransformerSentimentService


class mDeBERTaService(TransformerSentimentService):
    def __init__(self) -> None:
        super().__init__(settings.MDEBERTA_MODEL_NAME, settings.MDEBERTA_MODEL_PATH, settings.TRANSFORMER_DEVICE)


mdeberta_service = mDeBERTaService()
# Compatibility alias for integrations importing the former service name.
deberta_service = mdeberta_service
