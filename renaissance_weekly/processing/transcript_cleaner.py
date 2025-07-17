"""Clean transcripts to fix common phonetic errors and misrecognitions"""

import re
import yaml
from pathlib import Path
from typing import Dict, List, Tuple

from ..utils.logging import get_logger
logger = get_logger(__name__)


class TranscriptCleaner:
    """Fix common transcription errors using known entity mappings"""
    
    def __init__(self):
        # Use package directory, not current working directory
        package_dir = Path(__file__).parent.parent
        self.entities_file = package_dir / "data" / "podcast_entities.yaml"
        self.entities = self._load_entities()
        self.replacements_made = []
        
    def _load_entities(self) -> Dict:
        """Load entity corrections from YAML file"""
        if not self.entities_file.exists():
            logger.warning(f"Entity file not found: {self.entities_file}")
            return {}
            
        try:
            with open(self.entities_file, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load entities: {e}")
            return {}
    
    def clean_transcript(self, transcript: str, podcast_name: str) -> Tuple[str, List[str]]:
        """Clean transcript for a specific podcast
        
        Returns:
            Tuple of (cleaned_transcript, list_of_corrections_made)
        """
        if not transcript:
            return transcript, []
            
        cleaned = transcript
        corrections = []
        
        # Get podcast-specific corrections
        podcast_entities = self.entities.get(podcast_name, {})
        
        # Apply host corrections
        for host in podcast_entities.get('hosts', []):
            cleaned, count = self._apply_corrections(cleaned, host)
            if count > 0:
                corrections.append(f"Fixed '{host['correct']}' ({count} times)")
        
        # Apply frequent guest corrections
        for guest in podcast_entities.get('frequent_guests', []):
            cleaned, count = self._apply_corrections(cleaned, guest)
            if count > 0:
                corrections.append(f"Fixed '{guest['correct']}' ({count} times)")
        
        # Apply company corrections
        for company in podcast_entities.get('companies', []):
            cleaned, count = self._apply_corrections(cleaned, company)
            if count > 0:
                corrections.append(f"Fixed '{company['correct']}' ({count} times)")
        
        # Apply common corrections across all podcasts
        common_entities = self.entities.get('common', {})
        for entity_type in ['companies', 'terms']:
            for item in common_entities.get(entity_type, []):
                cleaned, count = self._apply_corrections(cleaned, item)
                if count > 0:
                    corrections.append(f"Fixed '{item['correct']}' ({count} times)")
        
        if corrections:
            logger.info(f"📝 Transcript cleaned for {podcast_name}:")
            for correction in corrections:
                logger.info(f"   - {correction}")
        else:
            logger.debug(f"✓ No corrections needed for {podcast_name}")
        
        return cleaned, corrections
    
    def _apply_corrections(self, text: str, entity: Dict) -> Tuple[str, int]:
        """Apply corrections for a single entity
        
        Returns:
            Tuple of (corrected_text, number_of_replacements)
        """
        correct = entity['correct']
        variants = entity.get('variants', [])
        
        total_replacements = 0
        
        for variant in variants:
            # Create case-insensitive pattern with word boundaries
            # This prevents partial matches (e.g., "Heath" in "Heather")
            pattern = r'\b' + re.escape(variant) + r'\b'
            
            # Count replacements before applying
            matches = re.findall(pattern, text, re.IGNORECASE)
            count = len(matches)
            
            if count > 0:
                # Replace while preserving the case of the first letter
                def replace_with_case(match):
                    original = match.group(0)
                    if original[0].isupper():
                        return correct
                    else:
                        return correct.lower()
                
                text = re.sub(pattern, replace_with_case, text, flags=re.IGNORECASE)
                total_replacements += count
        
        return text, total_replacements
    
    def add_custom_correction(self, podcast: str, entity_type: str, 
                            correct: str, variants: List[str]):
        """Add a custom correction at runtime"""
        if podcast not in self.entities:
            self.entities[podcast] = {}
        
        if entity_type not in self.entities[podcast]:
            self.entities[podcast][entity_type] = []
        
        self.entities[podcast][entity_type].append({
            'correct': correct,
            'variants': variants
        })
        
        # Save back to file
        try:
            with open(self.entities_file, 'w') as f:
                yaml.dump(self.entities, f, default_flow_style=False)
            logger.info(f"Added correction: {correct} for {podcast}")
        except Exception as e:
            logger.error(f"Failed to save correction: {e}")


# Singleton instance
transcript_cleaner = TranscriptCleaner()