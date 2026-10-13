"""Installed checker can address any Agent Shuttle profile by URL."""

import os
import unittest
from unittest.mock import patch

from agent_code_checker.providers import agent_shuttle_provider_from_name


class ProviderResolutionTests(unittest.TestCase):
    def test_agent_shuttle_prefix_resolves_builtin_and_custom_profiles(self):
        builtin = agent_shuttle_provider_from_name(
            "agent-shuttle:codex", peer_url="http://127.0.0.1:8765",
        )
        custom = agent_shuttle_provider_from_name(
            "agent-shuttle:my-agent", peer_url="http://127.0.0.1:8999",
        )
        self.assertEqual((builtin.agent, custom.agent), ("codex", "my-agent"))
        self.assertEqual(builtin.descriptor().id, "agent_shuttle")

    def test_generic_profile_accepts_explicit_url_and_policy(self):
        provider = agent_shuttle_provider_from_name(
            "agent-shuttle:opencode-local",
            peer_url="http://127.0.0.1:8767",
            tool_policy="no_tools",
        )
        self.assertEqual(provider.agent, "opencode-local")
        self.assertEqual(provider.peer_url, "http://127.0.0.1:8767")
        self.assertTrue(provider.capabilities.read_only)

    def test_generic_profile_requires_url(self):
        with self.assertRaisesRegex(ValueError, "agent_url"):
            agent_shuttle_provider_from_name("agent-shuttle:claude-local")

    def test_shuttle_env_url_is_used(self):
        with patch.dict(os.environ, {"AGENT_SHUTTLE_CODEX_URL": "http://127.0.0.1:8765"}):
            provider = agent_shuttle_provider_from_name("agent-shuttle:codex")
        self.assertEqual(provider.peer_url, "http://127.0.0.1:8765")
        self.assertTrue(provider.capabilities.read_only)

    def test_unrecognized_provider_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown provider"):
            agent_shuttle_provider_from_name("unknown", peer_url="http://127.0.0.1:8767")
