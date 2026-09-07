from app.core.config import settings
from app.services.transformer_service import TransformerSentimentService


class XLMRoBERTaService(TransformerSentimentService):
    def __init__(self) -> None:
        super().__init__(settings.XLM_ROBERTA_MODEL_NAME, settings.XLM_ROBERTA_MODEL_PATH, settings.TRANSFORMER_DEVICE)


xlm_roberta_service = XLMRoBERTaService()
# Compatibility alias for integrations importing the former service name.
roberta_service = xlm_roberta_service
