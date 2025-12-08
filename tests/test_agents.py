"""Tests for v3 agents module."""

import pytest
from pathlib import Path
import tempfile

from rilai.contracts.agent import AgentManifest, AgentPriority, AgentOutput
from rilai.agents.manifest import load_manifest, load_prompt, discover_agents
from rilai.agents.base_v3 import BaseAgent
from rilai.agents.registry import AgentRegistry, get_registry, reset_registry
from rilai.runtime.workspace import Workspace


class TestManifestLoading:
    def test_load_manifest(self, tmp_path):
        yaml_content = """
id: test.agent
display_name: Test Agent
description: A test agent
inputs:
  - user_message
outputs:
  - observation
cost_estimate: 500
cooldown: 30
priority: normal
safety_profile: read_only
prompt_template: test.md
version: 1
"""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(yaml_content)

        manifest = load_manifest(yaml_file)
        assert manifest.id == "test.agent"
        assert manifest.display_name == "Test Agent"
        assert manifest.priority == AgentPriority.NORMAL

    def test_load_prompt(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test Prompt\n\nThis is a test.")

        prompt = load_prompt(md_file)
        assert "Test Prompt" in prompt

    def test_load_missing_prompt(self, tmp_path):
        missing = tmp_path / "missing.md"
        prompt = load_prompt(missing)
        assert "agent" in prompt.lower()  # Default prompt

    def test_discover_agents(self, tmp_path):
        # Create agents directory structure
        agents_dir = tmp_path / "agents" / "emotion"
        agents_dir.mkdir(parents=True)

        yaml_content = """
id: emotion.test
display_name: Test Emotion Agent
description: Test
inputs:
  - user_message
outputs:
  - observation
prompt_template: test.md
"""
        (agents_dir / "test.yaml").write_text(yaml_content)
        (agents_dir / "test.md").write_text("# Test")

        agents = discover_agents(tmp_path)
        assert len(agents) == 1
        assert agents[0][0].id == "emotion.test"


class TestBaseAgent:
    def test_agent_creation(self):
        manifest = AgentManifest(
            id="test.agent",
            display_name="Test Agent",
            inputs=["user_message"],
            outputs=["observation"],
            prompt_template="test.md",
        )
        agent = BaseAgent(manifest, "# Test prompt")
        assert agent.agent_id == "test.agent"

    @pytest.mark.asyncio
    async def test_agent_quiet_output(self):
        manifest = AgentManifest(
            id="test.agent",
            display_name="Test Agent",
            inputs=["user_message"],
            outputs=["observation"],
            prompt_template="test.md",
        )
        agent = BaseAgent(manifest, "# Test prompt")
        workspace = Workspace()
        workspace.set_user_message("Hello")

        # Without provider, should return quiet
        output = await agent.assess(workspace)
        assert output.agent_id == "test.agent"
        assert output.observation == "Quiet"

    def test_parse_response_json(self):
        manifest = AgentManifest(
            id="test.agent",
            display_name="Test",
            inputs=["user_message"],
            outputs=["observation"],
            prompt_template="test.md",
        )
        agent = BaseAgent(manifest, "")

        response = '{"observation": "Test observation", "urgency": 2, "confidence": 2, "claims": []}'
        output = agent._parse_response(response)

        assert output.observation == "Test observation"
        assert output.urgency == 2
        assert output.confidence == 2

    def test_parse_response_with_claims(self):
        manifest = AgentManifest(
            id="test.agent",
            display_name="Test",
            inputs=["user_message"],
            outputs=["observation"],
            prompt_template="test.md",
        )
        agent = BaseAgent(manifest, "")

        response = '''
{
  "observation": "User stressed",
  "urgency": 2,
  "confidence": 2,
  "claims": [
    {"text": "User shows stress", "type": "observation"}
  ]
}
'''
        output = agent._parse_response(response)

        assert len(output.claims) == 1
        assert output.claims[0].text == "User shows stress"

    def test_extract_json_from_code_block(self):
        manifest = AgentManifest(
            id="test.agent",
            display_name="Test",
            inputs=["user_message"],
            outputs=["observation"],
            prompt_template="test.md",
        )
        agent = BaseAgent(manifest, "")

        content = '''Here is my analysis:
```json
{"observation": "Test", "urgency": 1, "confidence": 1, "claims": []}
```
'''
        data = agent._extract_json(content)
        assert data["observation"] == "Test"


class TestAgentRegistry:
    def test_registry_creation(self):
        registry = AgentRegistry()
        assert len(registry.manifests) == 0

    def test_register_agent(self):
        registry = AgentRegistry()
        manifest = AgentManifest(
            id="test.agent",
            display_name="Test",
            inputs=["user_message"],
            outputs=["observation"],
            prompt_template="test.md",
        )
        registry.register_agent(manifest, "# Test")

        assert "test.agent" in registry.manifests
        assert registry.get_agent("test.agent") is not None

    def test_get_agents_by_agency(self):
        registry = AgentRegistry()

        for name in ["stress", "wellbeing"]:
            manifest = AgentManifest(
                id=f"emotion.{name}",
                display_name=name,
                inputs=["user_message"],
                outputs=["observation"],
                prompt_template=f"{name}.md",
            )
            registry.register_agent(manifest, "# Test")

        manifest = AgentManifest(
            id="planning.short_term",
            display_name="Short Term",
            inputs=["user_message"],
            outputs=["observation"],
            prompt_template="short_term.md",
        )
        registry.register_agent(manifest, "# Test")

        emotion_agents = registry.get_agents_by_agency("emotion")
        assert len(emotion_agents) == 2

    def test_get_always_on_agents(self):
        registry = AgentRegistry()

        manifest1 = AgentManifest(
            id="test.always",
            display_name="Always On",
            inputs=["user_message"],
            outputs=["observation"],
            prompt_template="test.md",
            priority=AgentPriority.ALWAYS_ON,
        )
        manifest2 = AgentManifest(
            id="test.normal",
            display_name="Normal",
            inputs=["user_message"],
            outputs=["observation"],
            prompt_template="test.md",
            priority=AgentPriority.NORMAL,
        )
        registry.register_agent(manifest1, "# Test")
        registry.register_agent(manifest2, "# Test")

        always_on = registry.get_always_on_agents()
        assert "test.always" in always_on
        assert "test.normal" not in always_on

    def test_load_from_directory(self, tmp_path):
        # Create agents directory structure
        agents_dir = tmp_path / "agents" / "emotion"
        agents_dir.mkdir(parents=True)

        yaml_content = """
id: emotion.test
display_name: Test Emotion Agent
description: Test
inputs:
  - user_message
outputs:
  - observation
prompt_template: test.md
"""
        (agents_dir / "test.yaml").write_text(yaml_content)
        (agents_dir / "test.md").write_text("# Test")

        registry = AgentRegistry()
        registry.load_from_directory(tmp_path)

        assert "emotion.test" in registry.manifests


class TestGlobalRegistry:
    def test_get_registry(self):
        reset_registry()
        registry = get_registry()
        assert isinstance(registry, AgentRegistry)

    def test_registry_singleton(self):
        reset_registry()
        registry1 = get_registry()
        registry2 = get_registry()
        assert registry1 is registry2
