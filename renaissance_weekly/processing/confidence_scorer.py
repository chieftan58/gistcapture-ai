"""Score transcript quality and flag potential issues"""

import re
from typing import Dict, List, Tuple
from collections import Counter

from ..utils.logging import get_logger

logger = get_logger(__name__)


class TranscriptConfidenceScorer:
    """Analyze transcripts for quality issues and suspicious patterns"""
    
    def __init__(self):
        # Common transcription error patterns
        self.error_patterns = [
            # Suspicious character combinations
            (r'\b\w+[0-9]+\w+\b', 'mixed_alphanumeric', 0.3),  # words with numbers
            (r'\b(?:[A-Z]\.){3,}\b', 'excessive_abbreviations', 0.5),
            (r'\b\w{20,}\b', 'excessively_long_words', 0.2),
            (r'[^\x00-\x7F]+', 'non_ascii_characters', 0.4),
            
            # Repeated patterns suggesting errors
            (r'(\b\w+\b)(\s+\1){3,}', 'excessive_word_repetition', 0.1),
            (r'[\?\!]{3,}', 'excessive_punctuation', 0.3),
            
            # Common ASR errors
            (r'\b(um|uh|ah|er|mm)\b', 'filler_words', 0.8),  # High confidence, expected
            (r'\[inaudible\]|\[unclear\]|\[crosstalk\]', 'transcription_markers', 0.9),
            
            # Capitalization issues
            (r'\b[a-z]+(?:[A-Z][a-z]+)+\b', 'mixed_case_words', 0.3),
            (r'^[a-z]', 'sentence_lowercase_start', 0.6, re.MULTILINE),
        ]
        
        # Known problematic entity patterns
        self.entity_issues = [
            # Common name mangling
            (r'\b(Heath|Hieth)\s+(Raboy|Rabois)\b', 'Keith Rabois'),
            (r'\bDavid\s+Sachs\b', 'David Sacks'),
            (r'\bAndreessen\s+Horovitz\b', 'Andreessen Horowitz'),
            (r'\bPeter\s+Teal\b', 'Peter Thiel'),
            (r'\bElon\s+Must\b', 'Elon Musk'),
            
            # Company name issues
            (r'\bOpen\s+AI\b', 'OpenAI'),
            (r'\bSpace\s+X\b', 'SpaceX'),
            (r'\bPay\s+Pal\b', 'PayPal'),
            (r'\bAir\s+BnB\b', 'Airbnb'),
        ]
    
    def score_transcript(self, transcript: str, podcast_name: str = "") -> Dict:
        """Calculate confidence score and identify issues"""
        
        if not transcript:
            return {
                "confidence_score": 0.0,
                "issues": ["Empty transcript"],
                "entity_errors": [],
                "recommendations": ["Re-transcribe episode"]
            }
        
        issues = []
        total_penalty = 0.0
        entity_errors = []
        
        # Check for error patterns
        for pattern, issue_type, penalty, *flags in self.error_patterns:
            regex_flags = flags[0] if flags else 0
            matches = list(re.finditer(pattern, transcript, regex_flags))
            
            if matches:
                count = len(matches)
                # Normalize penalty based on transcript length
                normalized_penalty = (penalty * count) / (len(transcript) / 1000)
                total_penalty += normalized_penalty
                
                if penalty < 0.7:  # Only report significant issues
                    sample = matches[0].group(0) if matches else ""
                    issues.append({
                        "type": issue_type,
                        "count": count,
                        "penalty": normalized_penalty,
                        "sample": sample[:50]
                    })
        
        # Check for known entity errors
        for pattern, correct_entity in self.entity_issues:
            if re.search(pattern, transcript, re.IGNORECASE):
                entity_errors.append({
                    "found": re.search(pattern, transcript, re.IGNORECASE).group(0),
                    "should_be": correct_entity
                })
                total_penalty += 0.2  # Each entity error reduces confidence
        
        # Calculate final score
        confidence_score = max(0.0, 1.0 - total_penalty)
        
        # Generate recommendations
        recommendations = []
        if confidence_score < 0.7:
            recommendations.append("Consider re-transcribing with different service")
        if entity_errors:
            recommendations.append("Run entity correction before summarization")
        if any(i["type"] == "transcription_markers" for i in issues):
            recommendations.append("Original audio quality may be poor")
        
        return {
            "confidence_score": confidence_score,
            "issues": issues,
            "entity_errors": entity_errors,
            "recommendations": recommendations,
            "stats": {
                "word_count": len(transcript.split()),
                "sentence_count": len(re.findall(r'[.!?]+', transcript)),
                "avg_word_length": sum(len(w) for w in transcript.split()) / max(len(transcript.split()), 1)
            }
        }
    
    def compare_transcripts(self, transcript1: str, transcript2: str) -> float:
        """Compare two transcripts to detect if they're the same content"""
        
        # Tokenize and normalize
        def normalize(text):
            # Remove punctuation and lowercase
            text = re.sub(r'[^\w\s]', ' ', text.lower())
            # Remove extra whitespace
            text = ' '.join(text.split())
            return text
        
        norm1 = normalize(transcript1)
        norm2 = normalize(transcript2)
        
        # Quick length check
        len_ratio = len(norm1) / max(len(norm2), 1)
        if len_ratio < 0.8 or len_ratio > 1.2:
            return 0.0  # Too different in length
        
        # Word frequency comparison
        words1 = Counter(norm1.split())
        words2 = Counter(norm2.split())
        
        # Calculate Jaccard similarity
        intersection = sum((words1 & words2).values())
        union = sum((words1 | words2).values())
        
        return intersection / max(union, 1)
    
    def flag_suspicious_episodes(self, episodes: List[Dict]) -> List[Dict]:
        """Identify episodes that need review"""
        
        flagged = []
        
        for episode in episodes:
            score_result = self.score_transcript(
                episode.get('transcript', ''),
                episode.get('podcast', '')
            )
            
            if score_result['confidence_score'] < 0.7 or score_result['entity_errors']:
                flagged.append({
                    'episode': episode,
                    'confidence_score': score_result['confidence_score'],
                    'entity_errors': score_result['entity_errors'],
                    'top_issues': score_result['issues'][:3]
                })
        
        return sorted(flagged, key=lambda x: x['confidence_score'])


# Singleton instance
confidence_scorer = TranscriptConfidenceScorer()