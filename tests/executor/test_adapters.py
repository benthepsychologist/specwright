"""Tests for Agent Adapters."""

from __future__ import annotations

import pytest

from spec.executor.adapters import (
    AdapterError,
    AgentAdapter,
    ClaudeAdapter,
    EscalationRequired,
    ProtocolError,
    ToolNotFoundError,
    get_adapter,
    list_adapters,
)


class TestAdapterErrors:
    """Tests for adapter error classes."""

    def test_tool_not_found_error(self) -> None:
        """Test ToolNotFoundError."""
        err = ToolNotFoundError("claude")
        assert err.tool_name == "claude"
        assert "claude not found" in str(err)

    def test_tool_not_found_error_custom_message(self) -> None:
        """Test ToolNotFoundError with custom message."""
        err = ToolNotFoundError("claude", "custom message")
        assert err.tool_name == "claude"
        assert str(err) == "custom message"

    def test_protocol_error(self) -> None:
        """Test ProtocolError."""
        err = ProtocolError("something went wrong", failure_category="test_failure")
        assert err.failure_category == "test_failure"
        assert "something went wrong" in str(err)

    def test_protocol_error_no_category(self) -> None:
        """Test ProtocolError without category."""
        err = ProtocolError("error message")
        assert err.failure_category is None

    def test_adapter_error_is_exception(self) -> None:
        """Test AdapterError is an Exception."""
        err = AdapterError("test")
        assert isinstance(err, Exception)

    def test_tool_not_found_inherits_adapter_error(self) -> None:
        """Test ToolNotFoundError inherits from AdapterError."""
        err = ToolNotFoundError("claude")
        assert isinstance(err, AdapterError)

    def test_protocol_error_inherits_adapter_error(self) -> None:
        """Test ProtocolError inherits from AdapterError."""
        err = ProtocolError("error")
        assert isinstance(err, AdapterError)

    def test_escalation_required(self) -> None:
        """Test EscalationRequired exception."""
        err = EscalationRequired("need human review", violations=["scope_violation"])
        assert "need human review" in str(err)
        assert err.violations == ["scope_violation"]

    def test_escalation_required_no_violations(self) -> None:
        """Test EscalationRequired with no violations."""
        err = EscalationRequired("need review")
        assert err.violations == []

    def test_escalation_required_inherits_adapter_error(self) -> None:
        """Test EscalationRequired inherits from AdapterError."""
        err = EscalationRequired("test")
        assert isinstance(err, AdapterError)

    def test_escalation_required_not_protocol_error(self) -> None:
        """Test EscalationRequired is NOT a ProtocolError (distinct exception types)."""
        err = EscalationRequired("test")
        assert not isinstance(err, ProtocolError)


class TestAdapterRegistry:
    """Tests for adapter registry."""

    def test_get_claude_adapter(self) -> None:
        """Test getting claude adapter by name."""
        adapter = get_adapter("claude")
        assert isinstance(adapter, ClaudeAdapter)
        assert adapter.name == "claude"

    def test_get_adapter_case_insensitive(self) -> None:
        """Test adapter lookup is case-insensitive."""
        adapter = get_adapter("CLAUDE")
        assert isinstance(adapter, ClaudeAdapter)

    def test_get_unknown_adapter(self) -> None:
        """Test getting unknown adapter raises ValueError."""
        with pytest.raises(ValueError) as exc:
            get_adapter("unknown")

        assert "Unknown adapter" in str(exc.value)
        assert "claude" in str(exc.value)  # Should list available

    def test_list_adapters(self) -> None:
        """Test listing available adapters."""
        adapters = list_adapters()
        assert "claude" in adapters

    def test_codex_adapter_does_not_exist(self) -> None:
        """Test that codex adapter is no longer available."""
        adapters = list_adapters()
        assert "codex" not in adapters

        with pytest.raises(ValueError) as exc:
            get_adapter("codex")

        assert "Unknown adapter" in str(exc.value)


class TestClaudeAdapterProperties:
    """Tests for ClaudeAdapter properties."""

    def test_name_property(self) -> None:
        """Test name property returns 'claude'."""
        adapter = ClaudeAdapter()
        assert adapter.name == "claude"

    def test_adapter_is_agent_adapter(self) -> None:
        """Test ClaudeAdapter is an AgentAdapter."""
        adapter = ClaudeAdapter()
        assert isinstance(adapter, AgentAdapter)
