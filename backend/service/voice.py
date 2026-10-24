"""ElevenLabs conversation token for a private agent (WebRTC sessions from the app).

`GET https://api.elevenlabs.io/v1/convai/conversation/token?agent_id=...` returns
`{"token", "conversation_id"}` (docs: eleven-agents/api-reference/conversations/get-webrtc-token,
copy in runs/integ/docs/elevenlabs-conversation-token.md). The app passes `token` to
`ElevenLabs.startConversation(conversationToken:)`. The `xi-api-key` header is the standard
ElevenLabs API auth; that doc page does not show the header.
"""
from __future__ import annotations

import secrets

import httpx

ELEVENLABS_TOKEN_URL = "https://api.elevenlabs.io/v1/convai/conversation/token"


async def mint_conversation_token(settings, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    if settings.mock or not settings.elevenlabs_api_key or not settings.elevenlabs_agent_id:
        return {"conversation_token": "mock_" + secrets.token_hex(12),
                "agent_id": settings.elevenlabs_agent_id or "mock-agent"}
    async with httpx.AsyncClient(timeout=15, transport=transport) as http:
        r = await http.get(ELEVENLABS_TOKEN_URL, params={"agent_id": settings.elevenlabs_agent_id},
                           headers={"xi-api-key": settings.elevenlabs_api_key})
        r.raise_for_status()
        return {"conversation_token": r.json()["token"], "agent_id": settings.elevenlabs_agent_id}
