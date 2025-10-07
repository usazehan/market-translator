# A tiny DSPy program that 'polishes' mapped fields with learned few-shots.
# You can later plug in actual HF models inside DSPy modules.

from typing import Dict, Any
import dspy as dspy_ai  # <-- external dspy-ai library
from pipeline.state import Item
from models.hf_models import normalize_title_desc

class NormalizeSignature(dspy_ai.Signature):
    """
    Clean and normalize marketplace listing fields.
    item_title: str
    item_description: str
    mapped_payload: dict
    -> improved_payload: dict
    """

class NormalizerProgram(dspy_ai.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy_ai.Predict(NormalizeSignature)

    def forward(self, item_title: str, item_description: str, mapped_payload: dict):
        # For MVP we simply echo; later, train with examples to shape outputs.
        improved = mapped_payload.copy()
        # Example lightweight normalization via HF wrappers
        tmp_item = Item(id="tmp", title=item_title, description=item_description, attributes={})
        improved = normalize_title_desc(tmp_item, improved)
        return { "improved_payload": improved }

_program = NormalizerProgram()

def normalize_fields(item: Item, payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _program(item_title=item.title, item_description=item.description, mapped_payload=payload)
    return out["improved_payload"]
