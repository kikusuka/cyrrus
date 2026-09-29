"""
Pure Python Porter stemmer and synonym matching for IntentRouter.

Public domain Porter stemmer implementation based on the original algorithm
by Martin Porter (1980). No external dependencies required.
"""

from typing import Dict, Set


# Porter Stemmer - Pure Python implementation
# Based on the original algorithm by Martin Porter (1980)
class PorterStemmer:
    """
    Pure Python Porter stemmer implementation.
    
    This is a simplified but functional implementation of the Porter stemming
    algorithm, suitable for English word normalization in keyword matching.
    """
    
    def __init__(self):
        self.vowels = {'a', 'e', 'i', 'o', 'u'}
    
    def _is_consonant(self, word: str, i: int) -> bool:
        """Check if character at index i is a consonant."""
        if word[i] in self.vowels:
            return False
        if word[i] == 'y':
            if i == 0:
                return True
            return not self._is_consonant(word, i - 1)
        return True
    
    def _measure(self, word: str) -> int:
        """Count the number of consonant sequences between vowels."""
        m = 0
        i = 0
        while i < len(word):
            if not self._is_consonant(word, i):
                i += 1
                while i < len(word) and self._is_consonant(word, i):
                    i += 1
                m += 1
            i += 1
        return m
    
    def _contains_vowel(self, stem: str) -> bool:
        """Check if stem contains a vowel."""
        for i, char in enumerate(stem):
            if not self._is_consonant(stem, i):
                return True
        return False
    
    def _ends_with_double_consonant(self, word: str) -> bool:
        """Check if word ends with double consonant (e.g., 'bb', 'tt')."""
        if len(word) < 2:
            return False
        return (self._is_consonant(word, -1) and 
                self._is_consonant(word, -2) and 
                word[-1] == word[-2])
    
    def _ends_with_cvc(self, word: str) -> bool:
        """Check if word ends with consonant-vowel-consonant pattern."""
        if len(word) < 3:
            return False
        return (self._is_consonant(word, -3) and 
                not self._is_consonant(word, -2) and 
                self._is_consonant(word, -1) and 
                word[-1] not in {'w', 'x', 'y'})
    
    def _replace(self, word: str, suffix: str, replacement: str) -> tuple:
        """Replace suffix if it exists and conditions are met."""
        if word.endswith(suffix):
            stem = word[:-len(suffix)]
            if self._measure(stem) > 0:
                return stem + replacement, True
        return word, False
    
    def stem(self, word: str) -> str:
        """
        Stem a word using the Porter algorithm.
        
        Args:
            word: The word to stem (lowercase)
            
        Returns:
            The stemmed word
        """
        if len(word) <= 2:
            return word
        
        word = word.lower()
        
        # Step 1a
        if word.endswith('sses'):
            word = word[:-2]
        elif word.endswith('ies'):
            word = word[:-2]
        elif word.endswith('s'):
            word = word[:-1]
        
        # Step 1b
        if word.endswith('eed'):
            stem = word[:-3]
            if self._measure(stem) > 0:
                word = stem + 'ee'
        elif word.endswith('ed'):
            stem = word[:-2]
            if self._contains_vowel(stem):
                word = stem
                if word.endswith('at') or word.endswith('bl') or word.endswith('iz'):
                    word += 'e'
                elif self._ends_with_double_consonant(word) and not self._ends_with_cvc(word):
                    word = word[:-1]
        elif word.endswith('ing'):
            stem = word[:-3]
            if self._contains_vowel(stem):
                word = stem
                if word.endswith('at') or word.endswith('bl') or word.endswith('iz'):
                    word += 'e'
                elif self._ends_with_double_consonant(word) and not self._ends_with_cvc(word):
                    word = word[:-1]
        
        # Step 2
        suffixes = [
            ('ational', 'ate'), ('tional', 'tion'), ('enci', 'ence'),
            ('anci', 'ance'), ('izer', 'ize'), ('abli', 'able'),
            ('alli', 'al'), ('entli', 'ent'), ('eli', 'e'),
            ('ousli', 'ous'), ('ization', 'ize'), ('ation', 'ate'),
            ('ator', 'ate'), ('alism', 'al'), ('iveness', 'ive'),
            ('fulness', 'ful'), ('ousness', 'ous'), ('aliti', 'al'),
            ('iviti', 'ive'), ('biliti', 'ble'), ('alli', 'al')
        ]
        for suffix, replacement in suffixes:
            word, replaced = self._replace(word, suffix, replacement)
            if replaced:
                break
        
        # Step 3
        suffixes = [
            ('icate', 'ic'), ('ative', ''), ('alize', 'al'),
            ('iciti', 'ic'), ('ical', 'ic'), ('ful', ''), ('ness', '')
        ]
        for suffix, replacement in suffixes:
            word, replaced = self._replace(word, suffix, replacement)
            if replaced:
                break
        
        # Step 4
        suffixes = [
            ('al', ''), ('ance', ''), ('ence', ''), ('er', ''),
            ('ic', ''), ('able', ''), ('ible', ''), ('ant', ''),
            ('ement', ''), ('ment', ''), ('ent', ''), ('ion', ''),
            ('ou', ''), ('ism', ''), ('ate', ''), ('iti', ''),
            ('ous', ''), ('ive', ''), ('ize', '')
        ]
        for suffix, replacement in suffixes:
            if word.endswith(suffix):
                stem = word[:-len(suffix)]
                if self._measure(stem) > 1:
                    word = stem + replacement
                break
        
        # Step 5a
        if word.endswith('e'):
            stem = word[:-1]
            if self._measure(stem) > 1 or (self._measure(stem) == 1 and not self._ends_with_cvc(stem)):
                word = stem
        
        # Step 5b
        if self._measure(word) > 1 and self._ends_with_double_consonant(word) and word.endswith('l'):
            word = word[:-1]
        
        return word


# Synonym table for common domains
SYNONYMS: Dict[str, Set[str]] = {
    # Coding/technical (18 entries)
    'bug': {'error', 'issue', 'problem', 'defect', 'glitch'},
    'error': {'bug', 'issue', 'problem', 'mistake', 'fault'},
    'issue': {'bug', 'error', 'problem', 'trouble', 'difficulty'},
    'script': {'code', 'program', 'function', 'routine'},
    'code': {'script', 'program', 'source', 'implementation'},
    'program': {'code', 'script', 'application', 'software'},
    'function': {'method', 'routine', 'procedure', 'subroutine'},
    'debug': {'fix', 'repair', 'troubleshoot', 'solve'},
    'implement': {'build', 'create', 'develop', 'write'},
    'develop': {'build', 'create', 'implement', 'write'},
    'build': {'develop', 'create', 'implement', 'construct'},
    'compile': {'build', 'assemble', 'translate'},
    'execute': {'run', 'launch', 'start', 'perform'},
    'run': {'execute', 'launch', 'start', 'perform'},
    'install': {'setup', 'configure', 'deploy'},
    'deploy': {'install', 'setup', 'launch', 'release'},
    'configure': {'setup', 'install', 'customize', 'adjust'},
    'test': {'verify', 'validate', 'check', 'examine'},
    'refactor': {'restructure', 'rewrite', 'reorganize', 'clean'},
    
    # Support/help (11 entries)
    'problem': {'issue', 'trouble', 'difficulty', 'challenge'},
    'trouble': {'problem', 'issue', 'difficulty', 'concern'},
    'help': {'assist', 'support', 'aid', 'guide'},
    'assist': {'help', 'support', 'aid'},
    'support': {'help', 'assist', 'aid'},
    'explain': {'clarify', 'describe', 'illustrate', 'demonstrate'},
    'clarify': {'explain', 'illuminate', 'simplify', 'clear'},
    'guide': {'direct', 'lead', 'instruct', 'show'},
    'advice': {'suggestion', 'recommendation', 'tip', 'counsel'},
    'resolve': {'fix', 'solve', 'settle', 'address'},
    'solve': {'resolve', 'fix', 'answer', 'workout'},
    
    # Casual conversation (7 entries)
    'hi': {'hey', 'hello', 'greetings', 'howdy'},
    'hey': {'hi', 'hello', 'greetings'},
    'hello': {'hi', 'hey', 'greetings'},
    'greetings': {'hi', 'hey', 'hello'},
    'thanks': {'thank', 'appreciate', 'cheers'},
    'thank': {'thanks', 'appreciate', 'grateful'},
    'bye': {'goodbye', 'seeya', 'farewell', 'later'},
    
    # Weather/scheduling (12 entries)
    'weather': {'forecast', 'conditions', 'temperature', 'climate'},
    'forecast': {'weather', 'prediction', 'outlook'},
    'schedule': {'calendar', 'agenda', 'plan', 'timetable'},
    'calendar': {'schedule', 'agenda', 'planner'},
    'appointment': {'meeting', 'engagement', 'slot'},
    'meeting': {'appointment', 'gathering', 'session'},
    'remind': {'reminder', 'prompt', 'nudge', 'alert'},
    'reminder': {'remind', 'alert', 'notification', 'prompt'},
    'event': {'occurrence', 'happening', 'gathering', 'activity'},
    'task': {'job', 'assignment', 'duty', 'chore'},
    'deadline': {'duedate', 'cutoff', 'timelimit', 'target'},
    'agenda': {'schedule', 'plan', 'itinerary', 'program'},
    
    # General utility (10 entries)
    'want': {'need', 'desire', 'require', 'wish'},
    'need': {'want', 'require', 'desire', 'must'},
    'use': {'utilize', 'employ', 'apply', 'leverage'},
    'get': {'obtain', 'acquire', 'retrieve', 'fetch'},
    'find': {'locate', 'discover', 'search', 'look'},
    'search': {'find', 'look', 'seek', 'query'},
    'show': {'display', 'present', 'demonstrate', 'reveal'},
    'display': {'show', 'present', 'exhibit', 'render'},
    'tell': {'inform', 'notify', 'communicate', 'say'},
    'check': {'verify', 'inspect', 'examine', 'review'},
}


def normalize_token(token: str, stemmer: PorterStemmer) -> Set[str]:
    """
    Normalize a token by stemming and expanding synonyms.
    
    Args:
        token: The token to normalize
        stemmer: PorterStemmer instance
        
    Returns:
        Set of normalized forms (stemmed + synonyms)
    """
    token = token.lower()
    stemmed = stemmer.stem(token)
    
    # Collect all equivalent forms
    normalized = {stemmed, token}
    
    # Add synonyms
    for word, synonyms in SYNONYMS.items():
        if token in synonyms or stemmed in synonyms:
            normalized.update(synonyms)
            normalized.add(word)
        if word == token or word == stemmed:
            normalized.update(synonyms)
    
    return normalized


# Global stemmer instance for reuse
_stemmer_instance = PorterStemmer()


def get_stemmer() -> PorterStemmer:
    """Get the global stemmer instance."""
    return _stemmer_instance
