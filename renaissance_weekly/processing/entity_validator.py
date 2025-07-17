"""Advanced entity validation and correction system"""

import re
import json
from typing import Dict, List, Set, Tuple, Optional
from pathlib import Path
from collections import defaultdict

from ..utils.logging import get_logger
from ..utils.clients import openai_client

logger = get_logger(__name__)


class EntityValidator:
    """Validate and correct entities using multiple strategies"""
    
    def __init__(self):
        package_dir = Path(__file__).parent.parent
        self.knowledge_dir = package_dir / "data" / "knowledge"
        self.knowledge_dir.mkdir(exist_ok=True)
        
        # Load knowledge bases
        self.known_entities = self._load_known_entities()
        self.correction_patterns = self._load_correction_patterns()
        self.confidence_threshold = 0.8
        
    def _load_known_entities(self) -> Dict[str, Set[str]]:
        """Load verified entity lists by category"""
        entities = defaultdict(set)
        
        # Load from JSON files if they exist
        for category in ['people', 'companies', 'funds', 'terms']:
            file_path = self.knowledge_dir / f"{category}.json"
            if file_path.exists():
                try:
                    with open(file_path, 'r') as f:
                        entities[category] = set(json.load(f))
                except Exception as e:
                    logger.error(f"Failed to load {category}: {e}")
        
        # Hardcoded high-confidence entities
        entities['people'].update({
            # PayPal Mafia
            "Peter Thiel", "Elon Musk", "Reid Hoffman", "Max Levchin",
            "David Sacks", "Keith Rabois", "Roelof Botha", "Jeremy Stoppelman",
            
            # All-In Podcast
            "Jason Calacanis", "Chamath Palihapitiya", "David Friedberg",
            "Brad Gerstner", "Gavin Baker", "Bill Gurley",
            
            # Common guests/figures
            "Marc Andreessen", "Ben Horowitz", "Naval Ravikant",
            "Sam Altman", "Satya Nadella", "Jensen Huang",
            "Warren Buffett", "Charlie Munger", "Ray Dalio",
            "Stanley Druckenmiller", "Paul Tudor Jones",
            "Howard Marks", "Seth Klarman", "Dan Loeb"
        })
        
        entities['companies'].update({
            "OpenAI", "Anthropic", "DeepMind", "Perplexity",
            "Tesla", "SpaceX", "Neuralink", "The Boring Company",
            "Meta", "Google", "Microsoft", "Apple", "Amazon",
            "NVIDIA", "AMD", "Intel", "TSMC",
            "Palantir", "Snowflake", "Databricks", "Stripe"
        })
        
        entities['funds'].update({
            "Founders Fund", "Andreessen Horowitz", "Sequoia Capital",
            "Benchmark", "Accel", "Greylock Partners", "Kleiner Perkins",
            "Tiger Global", "Coatue", "Altimeter Capital",
            "Third Point", "Pershing Square", "Bridgewater Associates",
            "Renaissance Technologies", "Two Sigma", "Citadel"
        })
        
        return dict(entities)
    
    def _load_correction_patterns(self) -> List[Dict]:
        """Load phonetic correction patterns"""
        return [
            # Name patterns
            {"pattern": r"\b(Heath|Hieth)\s+(Raboy|Rabois|Raboys)\b", "replacement": "Keith Rabois", "confidence": 0.95},
            {"pattern": r"\b(Jason|Jayson)\s+(Kalkanis|Kalakanis|Calicanis)\b", "replacement": "Jason Calacanis", "confidence": 0.9},
            {"pattern": r"\bChamath\s+(Palihapatiya|Palihapitiya)\b", "replacement": "Chamath Palihapitiya", "confidence": 0.9},
            {"pattern": r"\bDavid\s+Sachs\b", "replacement": "David Sacks", "confidence": 0.95},
            {"pattern": r"\bPeter\s+(Teal|Theil)\b", "replacement": "Peter Thiel", "confidence": 0.9},
            {"pattern": r"\bElon\s+(Must|Musk)\b", "replacement": "Elon Musk", "confidence": 0.95},
            
            # Company patterns
            {"pattern": r"\bOpen\s*AI\b", "replacement": "OpenAI", "confidence": 0.95},
            {"pattern": r"\b(Founder's|Founders')\s+Fund\b", "replacement": "Founders Fund", "confidence": 0.9},
            {"pattern": r"\bAndreessen\s+(Horowitz|Horovitz)\b", "replacement": "Andreessen Horowitz", "confidence": 0.9},
            {"pattern": r"\b(N|n)vidia\b", "replacement": "NVIDIA", "confidence": 0.85},
            
            # Common terms
            {"pattern": r"\bL\.L\.M\.\b", "replacement": "LLM", "confidence": 0.9},
            {"pattern": r"\bA\.I\.\b", "replacement": "AI", "confidence": 0.9},
            {"pattern": r"\bI\.P\.O\.\b", "replacement": "IPO", "confidence": 0.9},
        ]
    
    async def validate_transcript_entities(self, transcript: str, podcast_name: str) -> Dict:
        """Validate entities in transcript using GPT-4"""
        
        # First, extract what we think are entities
        potential_entities = self._extract_potential_entities(transcript)
        
        if not potential_entities:
            return {"corrections": [], "confidence_scores": {}}
        
        # Build a focused prompt for GPT-4
        prompt = f"""Analyze these potential entities from a {podcast_name} transcript and identify likely transcription errors:

POTENTIAL ENTITIES:
{json.dumps(list(potential_entities), indent=2)}

CONTEXT: This is from a podcast about technology, investing, and business.

For each entity that seems like a transcription error, provide:
1. The incorrect transcription
2. The correct entity name
3. Confidence score (0-1)
4. Reasoning

Focus on:
- Names that sound similar but are misspelled
- Company names with incorrect formatting
- Technical terms with wrong abbreviations
- Known figures in tech/finance that are misspelled

Return as JSON: {{"corrections": [{{"incorrect": "", "correct": "", "confidence": 0.0, "reason": ""}}]}}"""

        try:
            response = await openai_client.chat.completions.create(
                model="gpt-4o-mini",  # Faster, cheaper for validation
                messages=[
                    {"role": "system", "content": "You are an expert at identifying transcription errors in podcast transcripts, especially for tech and finance personalities."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            return result
            
        except Exception as e:
            logger.error(f"Entity validation failed: {e}")
            return {"corrections": [], "confidence_scores": {}}
    
    def _extract_potential_entities(self, text: str) -> Set[str]:
        """Extract potential entity names from text"""
        entities = set()
        
        # Pattern for capitalized words (potential names)
        name_pattern = r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b'
        
        # Pattern for all-caps abbreviations
        abbrev_pattern = r'\b[A-Z]{2,}\b'
        
        # Find all matches
        for match in re.finditer(name_pattern, text):
            entity = match.group(0)
            # Filter out common words
            if len(entity) > 3 and entity not in {'This', 'That', 'When', 'Where', 'What', 'Which', 'There', 'These', 'Those'}:
                entities.add(entity)
        
        for match in re.finditer(abbrev_pattern, text):
            entities.add(match.group(0))
        
        return entities
    
    def apply_high_confidence_corrections(self, text: str) -> Tuple[str, List[str]]:
        """Apply only high-confidence corrections"""
        corrections = []
        
        for pattern_info in self.correction_patterns:
            if pattern_info['confidence'] >= self.confidence_threshold:
                pattern = pattern_info['pattern']
                replacement = pattern_info['replacement']
                
                # Check if pattern exists
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches:
                    # Apply correction
                    text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
                    corrections.append(f"Fixed '{matches[0]}' -> '{replacement}' (confidence: {pattern_info['confidence']})")
        
        return text, corrections
    
    def learn_from_correction(self, incorrect: str, correct: str, context: str = ""):
        """Add new correction pattern based on user feedback"""
        pattern = {
            "pattern": r"\b" + re.escape(incorrect) + r"\b",
            "replacement": correct,
            "confidence": 0.8,  # Start with moderate confidence
            "context": context
        }
        
        self.correction_patterns.append(pattern)
        
        # Save to file for persistence
        patterns_file = self.knowledge_dir / "learned_patterns.json"
        try:
            existing = []
            if patterns_file.exists():
                with open(patterns_file, 'r') as f:
                    existing = json.load(f)
            
            existing.append(pattern)
            
            with open(patterns_file, 'w') as f:
                json.dump(existing, f, indent=2)
                
            logger.info(f"Learned new correction: {incorrect} -> {correct}")
        except Exception as e:
            logger.error(f"Failed to save learned pattern: {e}")


# Singleton instance
entity_validator = EntityValidator()