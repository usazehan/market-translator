import yaml
from pathlib import Path

# BEFORE:
# MAPPING_DIR = Path(__file__).parent / "mapping"

# AFTER:
MAPPING_DIR = Path(__file__).resolve().parent

def load_mapping(channel: str) -> dict:
    p = MAPPING_DIR / f"{channel.lower()}.yaml"
    if not p.exists():
        available = [x.name for x in MAPPING_DIR.glob("*.yaml")]
        raise FileNotFoundError(
            f"No mapping found for channel '{channel}' at {p}. "
            f"Available: {available}"
        )
    return yaml.safe_load(p.read_text()) or {}
