from coding_agent_harness.llm.base import LLMClient, Message
from coding_agent_harness.models import AssistantTurn, Stop


class FakeClient:
    def complete(self, messages, tools, state):
        return AssistantTurn(action=Stop("done"), intent="完成", raw="x")


def test_protocol_is_structural():
    c = FakeClient()
    t = c.complete([], [], None)
    assert isinstance(t, AssistantTurn)
    assert isinstance(t.action, Stop)
    assert Message(role="user", content="hi").content == "hi"
