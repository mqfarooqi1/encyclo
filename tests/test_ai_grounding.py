"""AI safety properties.

These are the tests that matter most for trustworthiness: the assistant must
never produce a factual answer that the encyclopaedia cannot support, and must
never be able to fabricate a citation without that being detected.
"""

from __future__ import annotations

from encarta.ai.assistant import EncyclopaediaAssistant
from encarta.ai.provider import Completion, NullProvider, get_provider
from encarta.config import Config


class FakeProvider(NullProvider):
    """A stand-in model that returns whatever text a test gives it."""

    name = "fake"

    def __init__(self, text: str) -> None:
        self.text = text

    @property
    def available(self) -> bool:
        return True

    def complete(self, system: str, prompt: str, *, max_tokens: int = 900) -> Completion:
        self.system = system
        self.prompt = prompt
        return Completion(self.text, "fake-model")


def assistant(conn, config, provider=None):
    instance = EncyclopaediaAssistant(conn, config)
    if provider is not None:
        instance.provider = provider
    return instance


def test_default_provider_is_none(config):
    assert isinstance(get_provider(Config(data_dir=config.data_dir,
                                          content_dir=config.content_dir)), NullProvider)


def test_no_provider_still_returns_real_articles(conn, config):
    """Degrading honestly: no prose, but genuine cited material."""
    result = assistant(conn, config).answer("Why did the dinosaurs die out?")
    assert result["answered"] is False
    assert result["grounded"] is True
    assert result["passages"]
    assert result["sources"]
    assert "not available" in result["reason"].lower()


def test_unknown_topic_is_refused_rather_than_guessed(conn, config):
    """With no retrieval hits the model is never called at all."""
    provider = FakeProvider("I would happily invent something here.")
    result = assistant(conn, config, provider).answer(
        "What is the capital of the planet Zog in the Fnord system?"
    )
    assert result["answered"] is False
    assert result["grounded"] is False
    assert result["passages"] == []
    assert not hasattr(provider, "prompt"), "the model must not be called without grounding"


def test_grounded_question_reaches_the_model_with_passages(conn, config):
    provider = FakeProvider("The impact happened about 66 million years ago [P1].")
    result = assistant(conn, config, provider).answer("Why did the dinosaurs die out?")
    assert result["answered"] is True
    assert "PASSAGES:" in provider.prompt
    assert "[P1]" in provider.prompt
    assert result["cited_passages"] == [1]
    assert result["invalid_citations"] == []


def test_fabricated_citation_is_detected_and_surfaced(conn, config):
    """A marker pointing at a passage that does not exist is a hallucination signal."""
    provider = FakeProvider("This is well established [P1] and also proven [P97].")
    result = assistant(conn, config, provider).answer("Why did the dinosaurs die out?")
    assert result["invalid_citations"] == [97]


def test_system_prompt_forbids_invention(conn, config):
    provider = FakeProvider("ok [P1]")
    assistant(conn, config, provider).answer("What is a black hole?")
    system = provider.system.lower()
    assert "only using the numbered passages provided" in system
    assert "never invent a citation" in system
    assert "do not fill the gap from your own knowledge" in system


def test_answer_always_carries_a_disclaimer(conn, config):
    provider = FakeProvider("An answer [P1].")
    result = assistant(conn, config, provider).answer("What is a black hole?")
    assert result["disclaimer"]
    assert result["ai"]["model"] == "fake-model"


def test_kids_mode_never_uses_adult_reading_level(conn, config):
    provider = FakeProvider("Simple answer [P1].")
    result = assistant(conn, config, provider).answer(
        "What is a black hole?", reading_level="adult", kids_mode=True
    )
    assert result["reading_level"] in {"age6_8", "age9_12"}
    for passage in result["passages"]:
        assert passage["reading_level"] in {"age6_8", "age9_12", "teen", "adult"}


def test_provider_failure_degrades_to_articles(conn, config):
    class Broken(FakeProvider):
        def complete(self, system, prompt, *, max_tokens=900):
            return Completion("", "fake-model", False, "Provider unreachable.")

    result = assistant(conn, config, Broken("")).answer("What is a black hole?")
    assert result["answered"] is False
    assert result["grounded"] is True
    assert result["passages"]


def test_network_is_refused_when_disabled(config):
    """An offline deployment must not make outbound calls by accident."""
    from encarta.ai.provider import AnthropicProvider

    offline = Config(data_dir=config.data_dir, content_dir=config.content_dir,
                     ai_provider="anthropic", allow_network=False)
    completion = AnthropicProvider(offline).complete("s", "p")
    assert completion.available is False
    assert "network" in (completion.reason or "").lower()
