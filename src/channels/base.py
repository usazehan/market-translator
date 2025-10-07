from typing import Dict, Any

class ChannelClient:
    def upsert_listing(self, payload: Dict[str, Any]) -> bool:
        # Stub: pretend success if required fields exist
        required = ["title", "price"]
        return all(payload.get(k) for k in required)

class AmazonClient(ChannelClient):
    pass

class EbayClient(ChannelClient):
    pass

def get_client(channel: str) -> ChannelClient:
    if channel.lower() == "amazon":
        return AmazonClient()
    if channel.lower() == "ebay":
        return EbayClient()
    return ChannelClient()
