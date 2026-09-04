"""
Template definitions and keyword matching for cyrrus init CLI.

Provides pre-built configuration templates for common bot use cases
and simple keyword-based template matching without external dependencies.
"""

import copy
from typing import Dict, List, Optional


# Template definitions
TEMPLATES: Dict[str, Dict] = {
    "coding": {
        "name": "Coding Assistant",
        "description": "Helps with programming tasks, code review, debugging",
        "config": {
            "core_lamp": {
                "content": "You are a helpful coding assistant. Provide clear, well-commented code solutions. Explain your reasoning when appropriate."
            },
            "code_lens": {
                "content": "Output only code unless explicitly asked for explanation.",
                "triggers": ["code", "script", "function", "class", "implement", "write"]
            }
        }
    },
    "support": {
        "name": "Customer Support",
        "description": "Handles customer inquiries, troubleshooting, and product support",
        "config": {
            "core_lamp": {
                "content": "You are a helpful customer support agent. Be patient, empathetic, and solution-oriented. Escalate issues when appropriate."
            },
            "product_info": {
                "content": "Product information and documentation available.",
                "triggers": ["product", "feature", "documentation", "help", "support"]
            }
        }
    },
    "casual": {
        "name": "Casual Chat Companion",
        "description": "Friendly conversational bot for casual interactions",
        "config": {
            "core_lamp": {
                "content": "You are a friendly conversational companion. Be engaging, ask follow-up questions, and keep the conversation flowing naturally."
            }
        }
    },
    "general": {
        "name": "General Assistant",
        "description": "Versatile assistant for a wide range of tasks",
        "config": {
            "core_lamp": {
                "content": "You are a helpful assistant. Be concise, accurate, and adapt your response style to the user's needs."
            }
        }
    }
}


# Personality/tone modifiers
PERSONALITIES: Dict[str, str] = {
    "professional": "Maintain a professional, courteous tone. Use formal language and avoid slang.",
    "casual": "Use a friendly, conversational tone. Feel free to use casual language and emojis when appropriate.",
    "sarcastic": "Use wit and sarcasm in your responses. Keep it playful but not mean-spirited.",
    "formal": "Use formal, academic language. Be precise and avoid contractions.",
    "friendly": "Be warm and approachable. Use encouraging language and show enthusiasm."
}


# Keyword matching dictionary for intent detection
KEYWORD_MAPPINGS: Dict[str, List[str]] = {
    "coding": [
        "code", "program", "develop", "software", "programming", "developer",
        "debug", "function", "class", "script", "algorithm", "api", "web",
        "python", "javascript", "java", "rust", "go", "typescript"
    ],
    "support": [
        "support", "help", "customer", "service", "troubleshoot", "issue",
        "problem", "ticket", "assistance", "product", "documentation", "faq"
    ],
    "casual": [
        "chat", "conversation", "friend", "buddy", "casual", "talk",
        "hangout", "social", "fun", "relaxed", "informal"
    ],
    "general": [
        "assistant", "help", "task", "general", "versatile", "anything",
        "everything", "various", "multiple", "assistant"
    ]
}


def match_template(description: str) -> Optional[str]:
    """
    Match a free-text description to the closest template using keyword matching.
    
    Args:
        description: User's description of what their bot should do
        
    Returns:
        Template key (e.g., "coding") or None if no match
    """
    if not description:
        return None
    
    description_lower = description.lower()
    scores = {}
    
    for template_key, keywords in KEYWORD_MAPPINGS.items():
        score = sum(1 for keyword in keywords if keyword in description_lower)
        if score > 0:
            scores[template_key] = score
    
    if not scores:
        return None
    
    # Return the template with the highest keyword match
    return max(scores, key=scores.get)


def get_template_config(template_key: str, personality: Optional[str] = None) -> Dict:
    """
    Get the full configuration for a template, optionally with personality modifier.
    
    Args:
        template_key: Template identifier (e.g., "coding")
        personality: Optional personality modifier (e.g., "professional")
        
    Returns:
        Complete configuration dictionary
    """
    if template_key not in TEMPLATES:
        raise ValueError(f"Unknown template: {template_key}")
    
    config = copy.deepcopy(TEMPLATES[template_key]["config"])
    
    # Apply a named or user-supplied personality modifier to core_lamp.
    if personality:
        base_content = config["core_lamp"]["content"]
        tone = PERSONALITIES.get(personality, personality)
        config["core_lamp"]["content"] = f"{base_content}\n\nTone: {tone}"
    
    return config


def list_templates() -> List[tuple]:
    """
    Get a list of available templates with their names and descriptions.
    
    Returns:
        List of (key, name, description) tuples
    """
    return [
        (key, template["name"], template["description"])
        for key, template in TEMPLATES.items()
    ]


def list_personalities() -> List[str]:
    """
    Get a list of available personality options.
    
    Returns:
        List of personality keys
    """
    return list(PERSONALITIES.keys())
