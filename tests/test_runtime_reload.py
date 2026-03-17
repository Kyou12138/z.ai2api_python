from app.core import openai as openai_module


def test_get_upstream_client_rebuilds_when_signature_changes(monkeypatch):
    created_clients = []

    class DummyUpstreamClient:
        def __init__(self):
            self.instance_id = len(created_clients) + 1
            created_clients.append(self)

    original_api_endpoint = openai_module.settings.API_ENDPOINT
    original_glm5_model = openai_module.settings.GLM5_MODEL
    openai_module._upstream_client = None
    openai_module._upstream_signature = None

    monkeypatch.setattr(openai_module, "UpstreamClient", DummyUpstreamClient)

    try:
        first_client = openai_module.get_upstream_client()
        second_client = openai_module.get_upstream_client()

        assert first_client is second_client
        assert len(created_clients) == 1

        monkeypatch.setattr(
            openai_module.settings,
            "API_ENDPOINT",
            "https://runtime.example/v1/chat/completions",
        )
        monkeypatch.setattr(openai_module.settings, "GLM5_MODEL", "GLM-5-RUNTIME")

        rebuilt_client = openai_module.get_upstream_client()

        assert rebuilt_client is not first_client
        assert len(created_clients) == 2
    finally:
        openai_module._upstream_client = None
        openai_module._upstream_signature = None
        openai_module.settings.API_ENDPOINT = original_api_endpoint
        openai_module.settings.GLM5_MODEL = original_glm5_model
