"""
Tests for cyrrus CLI functionality.

Tests template matching, non-interactive mode, and TTY safety.
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cyrrus.templates import (
    match_template,
    get_template_config,
    list_templates,
    list_personalities,
    TEMPLATES,
    PERSONALITIES,
)
from cyrrus.cli import (
    is_interactive,
    non_interactive_mode,
)


class TestTemplateMatching:
    """Test template keyword matching functionality."""
    
    def test_match_coding_keywords(self):
        """Test that coding-related descriptions match coding template."""
        descriptions = [
            "I need help with Python programming",
            "Build me a web development assistant",
            "Debug my JavaScript code",
            "Write a function for data processing"
        ]
        for desc in descriptions:
            result = match_template(desc)
            assert result == "coding", f"Expected 'coding' for '{desc}', got '{result}'"
    
    def test_match_support_keywords(self):
        """Test that support-related descriptions match support template."""
        descriptions = [
            "Customer service bot for troubleshooting",
            "Help users with product issues",
            "Support agent for handling tickets"
        ]
        for desc in descriptions:
            result = match_template(desc)
            assert result == "support", f"Expected 'support' for '{desc}', got '{result}'"
    
    def test_match_casual_keywords(self):
        """Test that casual-related descriptions match casual template."""
        descriptions = [
            "Just a fun chat buddy",
            "Casual conversation companion",
            "Friendly bot for hanging out"
        ]
        for desc in descriptions:
            result = match_template(desc)
            assert result == "casual", f"Expected 'casual' for '{desc}', got '{result}'"
    
    def test_no_match_returns_none(self):
        """Test that descriptions with no matching keywords return None."""
        descriptions = [
            "xyz abc def",
            "",
            "random words with no meaning"
        ]
        for desc in descriptions:
            result = match_template(desc)
            assert result is None, f"Expected None for '{desc}', got '{result}'"
    
    def test_case_insensitive_matching(self):
        """Test that keyword matching is case-insensitive."""
        descriptions = [
            "I need CODE help",
            "Python PROGRAMMING assistant",
            "Web DEVELOPMENT bot"
        ]
        for desc in descriptions:
            result = match_template(desc)
            assert result == "coding", f"Expected 'coding' for '{desc}', got '{result}'"


class TestTemplateConfig:
    """Test template configuration generation."""
    
    def test_get_template_config_basic(self):
        """Test basic template config generation."""
        config = get_template_config("coding")
        assert "core_lamp" in config
        assert "content" in config["core_lamp"]
        assert "coding" in config["core_lamp"]["content"].lower()
    
    def test_get_template_config_with_personality(self):
        """Test template config with personality modifier."""
        config = get_template_config("coding", "professional")
        assert "core_lamp" in config
        assert "Tone:" in config["core_lamp"]["content"]
        assert "professional" in config["core_lamp"]["content"].lower()
    
    def test_get_template_config_invalid_template(self):
        """Test that invalid template raises ValueError."""
        with pytest.raises(ValueError, match="Unknown template"):
            get_template_config("nonexistent")
    
    def test_get_template_config_accepts_free_text_personality(self):
        """A free-text tone is preserved in the generated lamp."""
        config = get_template_config("coding", "nonexistent_personality")
        assert "Tone: nonexistent_personality" in config["core_lamp"]["content"]
    
    def test_list_templates(self):
        """Test that list_templates returns expected structure."""
        templates = list_templates()
        assert len(templates) > 0
        assert all(len(t) == 3 for t in templates)  # (key, name, description)
        assert all(t[0] in TEMPLATES for t in templates)
    
    def test_list_personalities(self):
        """Test that list_personalities returns expected values."""
        personalities = list_personalities()
        assert len(personalities) > 0
        assert all(p in PERSONALITIES for p in personalities)


class TestNonInteractiveMode:
    """Test non-interactive CLI mode."""
    
    def test_non_interactive_with_all_flags(self, tmp_path):
        """Test non-interactive mode with all required flags."""
        output_file = tmp_path / "test_config.json"
        
        # Mock is_interactive to return False
        with patch('cyrrus.cli.is_interactive', return_value=False):
            non_interactive_mode("coding", "professional", str(output_file))
        
        # Verify file was created
        assert output_file.exists()
        
        # Verify content
        with open(output_file) as f:
            config = json.load(f)
        
        assert "core_lamp" in config
        assert "coding" in config["core_lamp"]["content"].lower()
        assert "professional" in config["core_lamp"]["content"].lower()
    
    def test_non_interactive_without_personality_exits(self, tmp_path):
        """Non-interactive mode requires both template and tone."""
        output_file = tmp_path / "test_config.json"
        with pytest.raises(SystemExit) as exc_info:
            non_interactive_mode("coding", None, str(output_file))
        assert exc_info.value.code == 1
        assert not output_file.exists()
    
    def test_non_interactive_missing_template_exits(self, tmp_path):
        """Test that non-interactive mode without template exits with error."""
        output_file = tmp_path / "test_config.json"
        
        with patch('cyrrus.cli.is_interactive', return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                non_interactive_mode(None, None, str(output_file))
        
        assert exc_info.value.code == 1
    
    def test_file_write_error_handling(self, tmp_path):
        """Test that file write errors are handled gracefully."""
        # Use an invalid path
        invalid_path = "/nonexistent/directory/config.json"
        
        with patch('cyrrus.cli.is_interactive', return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                non_interactive_mode("coding", None, invalid_path)
        
        assert exc_info.value.code == 1


class TestTTYDetection:
    """Test TTY detection for interactive mode."""
    
    def test_is_interactive_with_tty(self):
        """Test that is_interactive returns True when both stdin and stdout are TTY."""
        with patch('sys.stdin.isatty', return_value=True):
            with patch('sys.stdout.isatty', return_value=True):
                assert is_interactive() is True
    
    def test_is_interactive_without_stdin_tty(self):
        """Test that is_interactive returns False when stdin is not TTY."""
        with patch('sys.stdin.isatty', return_value=False):
            with patch('sys.stdout.isatty', return_value=True):
                assert is_interactive() is False
    
    def test_is_interactive_without_stdout_tty(self):
        """Test that is_interactive returns False when stdout is not TTY."""
        with patch('sys.stdin.isatty', return_value=True):
            with patch('sys.stdout.isatty', return_value=False):
                assert is_interactive() is False
    
    def test_is_interactive_without_both_tty(self):
        """Test that is_interactive returns False when neither is TTY."""
        with patch('sys.stdin.isatty', return_value=False):
            with patch('sys.stdout.isatty', return_value=False):
                assert is_interactive() is False


class TestCLIIntegration:
    """Integration tests for CLI main function."""
    
    def test_cli_non_interactive_with_template(self, tmp_path):
        """Test CLI in non-interactive mode with --template flag."""
        output_file = tmp_path / "test_config.json"
        from cyrrus.cli import main
        with patch('cyrrus.cli.is_interactive', return_value=False):
            main(["init", "--template", "coding", "--tone", "professional",
                  "--yes", "--output", str(output_file)])
        
        assert output_file.exists()
    
    def test_cli_non_interactive_missing_template(self):
        """Test CLI in non-interactive mode without --template fails."""
        from cyrrus.cli import main
        with patch('cyrrus.cli.is_interactive', return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                main(["init", "--yes"])
        
        assert exc_info.value.code == 1
    
    def test_cli_with_no_input_flag(self, tmp_path):
        """Test --no-input flag forces non-interactive mode and writes file."""
        output_file = tmp_path / "test_config.json"
        
        from cyrrus.cli import main
        with patch('cyrrus.cli.is_interactive', return_value=True):
            main(["init", "--template", "coding", "--tone", "casual",
                  "--no-input", "--output", str(output_file)])
        
        assert output_file.exists()

    def test_cli_non_interactive_missing_tone_is_actionable(self, capsys):
        from cyrrus.cli import main
        with patch('cyrrus.cli.is_interactive', return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                main(["init", "--template", "coding"])
        assert exc_info.value.code == 1
        assert "--tone" in capsys.readouterr().err
