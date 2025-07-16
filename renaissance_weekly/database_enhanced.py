"""Enhanced database module with bulletproof error handling and extensive logging"""

import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
import json

from .models import Episode, TranscriptSource
from .config import DB_PATH
from .utils.logging import get_logger

logger = get_logger(__name__)


class EnhancedPodcastDatabase:
    """Enhanced database handler with comprehensive logging and error handling"""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        logger.info(f"🗄️ Initializing Enhanced Database at: {self.db_path}")
        logger.info(f"   File exists: {self.db_path.exists()}")
        if self.db_path.exists():
            logger.info(f"   File size: {self.db_path.stat().st_size:,} bytes")
            logger.info(f"   Last modified: {datetime.fromtimestamp(self.db_path.stat().st_mtime)}")
        self._init_database()
    
    def _init_database(self):
        """Initialize database with proper error handling"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Check if episodes table exists
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM sqlite_master 
                    WHERE type='table' AND name='episodes'
                """)
                table_exists = cursor.fetchone()[0] > 0
                
                if not table_exists:
                    logger.warning("❌ Episodes table does not exist - creating new database")
                    self._create_episodes_table(conn)
                    self._create_indexes(conn)
                else:
                    # Verify schema
                    cursor.execute("PRAGMA table_info(episodes)")
                    columns = {row[1] for row in cursor.fetchall()}
                    logger.info(f"✅ Episodes table exists with {len(columns)} columns")
                    
                    # Get row count
                    cursor.execute("SELECT COUNT(*) FROM episodes")
                    count = cursor.fetchone()[0]
                    logger.info(f"📊 Database contains {count} episodes")
                    
                conn.commit()
                
        except sqlite3.Error as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise
    
    def save_episode(self, episode: Episode, transcript: Optional[str] = None, 
                     transcript_source: Optional[TranscriptSource] = None,
                     summary: Optional[str] = None, paragraph_summary: Optional[str] = None,
                     transcription_mode: str = 'test') -> int:
        """Save or update an episode with comprehensive logging"""
        
        # Log the save attempt
        logger.info(f"\n{'='*60}")
        logger.info(f"💾 SAVING EPISODE TO DATABASE")
        logger.info(f"   Database: {self.db_path}")
        logger.info(f"   Podcast: {episode.podcast}")
        logger.info(f"   Title: {episode.title[:80]}...")
        logger.info(f"   Published: {episode.published} (type: {type(episode.published)})")
        logger.info(f"   GUID: {episode.guid}")
        logger.info(f"   Mode: {transcription_mode}")
        logger.info(f"   Has transcript: {'Yes' if transcript else 'No'} ({len(transcript) if transcript else 0} chars)")
        logger.info(f"   Has summary: {'Yes' if summary else 'No'} ({len(summary) if summary else 0} chars)")
        logger.info(f"   Has paragraph: {'Yes' if paragraph_summary else 'No'}")
        
        try:
            # Convert dates to consistent format
            if isinstance(episode.published, str):
                published_str = episode.published
            elif hasattr(episode.published, 'isoformat'):
                published_str = episode.published.isoformat()
            else:
                published_str = str(episode.published)
            
            logger.info(f"   Normalized date: {published_str}")
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Check if episode already exists
                cursor.execute("""
                    SELECT id, transcription_mode, 
                           LENGTH(transcript), LENGTH(transcript_test),
                           LENGTH(summary), LENGTH(summary_test)
                    FROM episodes
                    WHERE podcast = ? AND title = ? AND date(published) = date(?)
                """, (episode.podcast, episode.title, published_str))
                
                existing = cursor.fetchone()
                
                if existing:
                    logger.info(f"📝 Episode exists with ID: {existing[0]}")
                    logger.info(f"   Existing mode: {existing[1]}")
                    logger.info(f"   Existing transcript: {existing[2]} chars")
                    logger.info(f"   Existing transcript_test: {existing[3]} chars")
                    logger.info(f"   Existing summary: {existing[4]} chars")
                    logger.info(f"   Existing summary_test: {existing[5]} chars")
                
                # Prepare episode data
                episode_data = {
                    'podcast': episode.podcast,
                    'title': episode.title,
                    'published': published_str,
                    'audio_url': episode.audio_url,
                    'transcript_url': episode.transcript_url,
                    'description': episode.description,
                    'link': episode.link,
                    'duration': episode.duration,
                    'guid': episode.guid,
                    'transcript_source': transcript_source.value if transcript_source else None,
                    'transcription_mode': transcription_mode,
                    'updated_at': datetime.now().isoformat()
                }
                
                # Set mode-specific columns
                if transcription_mode == 'test':
                    episode_data['transcript_test'] = transcript
                    episode_data['summary_test'] = summary
                    episode_data['paragraph_summary_test'] = paragraph_summary
                else:  # full mode
                    episode_data['transcript'] = transcript
                    episode_data['summary'] = summary
                    episode_data['paragraph_summary'] = paragraph_summary
                
                if existing:
                    # Update existing record
                    update_fields = []
                    update_values = []
                    
                    # Always update these fields
                    for field in ['audio_url', 'transcript_url', 'description', 'link', 
                                 'duration', 'guid', 'transcript_source', 'transcription_mode', 'updated_at']:
                        if field in episode_data and episode_data[field] is not None:
                            update_fields.append(f"{field} = ?")
                            update_values.append(episode_data[field])
                    
                    # Update mode-specific fields
                    if transcription_mode == 'test':
                        if transcript:
                            update_fields.append("transcript_test = ?")
                            update_values.append(transcript)
                        if summary:
                            update_fields.append("summary_test = ?")
                            update_values.append(summary)
                        if paragraph_summary:
                            update_fields.append("paragraph_summary_test = ?")
                            update_values.append(paragraph_summary)
                    else:
                        if transcript:
                            update_fields.append("transcript = ?")
                            update_values.append(transcript)
                        if summary:
                            update_fields.append("summary = ?")
                            update_values.append(summary)
                        if paragraph_summary:
                            update_fields.append("paragraph_summary = ?")
                            update_values.append(paragraph_summary)
                    
                    # Add WHERE clause values
                    update_values.extend([episode.podcast, episode.title, published_str])
                    
                    update_sql = f"""
                        UPDATE episodes 
                        SET {', '.join(update_fields)}
                        WHERE podcast = ? AND title = ? AND date(published) = date(?)
                    """
                    
                    logger.info(f"🔄 Updating existing episode...")
                    logger.debug(f"   SQL: {update_sql}")
                    logger.debug(f"   Values: {[v[:50] if isinstance(v, str) and len(v) > 50 else v for v in update_values]}")
                    
                    cursor.execute(update_sql, update_values)
                    row_id = existing[0]
                    
                else:
                    # Insert new record
                    insert_sql = """
                        INSERT INTO episodes (
                            podcast, title, published, audio_url, transcript_url,
                            description, link, duration, guid, transcript,
                            transcript_source, summary, transcript_test, summary_test,
                            transcription_mode, paragraph_summary, paragraph_summary_test
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    
                    insert_values = (
                        episode_data['podcast'], episode_data['title'], episode_data['published'],
                        episode_data['audio_url'], episode_data['transcript_url'],
                        episode_data['description'], episode_data['link'],
                        episode_data['duration'], episode_data['guid'],
                        episode_data.get('transcript'), episode_data['transcript_source'],
                        episode_data.get('summary'), episode_data.get('transcript_test'),
                        episode_data.get('summary_test'), episode_data['transcription_mode'],
                        episode_data.get('paragraph_summary'), episode_data.get('paragraph_summary_test')
                    )
                    
                    logger.info(f"➕ Inserting new episode...")
                    logger.debug(f"   Values: {[v[:50] if isinstance(v, str) and len(v) > 50 else v for v in insert_values]}")
                    
                    cursor.execute(insert_sql, insert_values)
                    row_id = cursor.lastrowid
                
                # Commit the transaction
                conn.commit()
                logger.info(f"✅ Database commit successful! Row ID: {row_id}")
                
                # Verify the save was successful
                cursor.execute("""
                    SELECT id, LENGTH(transcript), LENGTH(transcript_test),
                           LENGTH(summary), LENGTH(summary_test)
                    FROM episodes
                    WHERE podcast = ? AND title = ? AND date(published) = date(?)
                """, (episode.podcast, episode.title, published_str))
                
                verification = cursor.fetchone()
                if verification:
                    logger.info(f"✅ VERIFIED: Episode saved with ID {verification[0]}")
                    logger.info(f"   Transcript: {verification[1]} chars")
                    logger.info(f"   Transcript_test: {verification[2]} chars")
                    logger.info(f"   Summary: {verification[3]} chars")
                    logger.info(f"   Summary_test: {verification[4]} chars")
                else:
                    logger.error(f"❌ VERIFICATION FAILED: Could not find saved episode!")
                
                logger.info(f"{'='*60}\n")
                return row_id
                
        except sqlite3.Error as e:
            logger.error(f"❌ DATABASE ERROR: {e}")
            logger.error(f"   Error type: {type(e).__name__}")
            logger.error(f"   Episode: {episode.podcast} - {episode.title}")
            logger.info(f"{'='*60}\n")
            # Re-raise to ensure caller knows save failed
            raise
    
    def get_transcript(self, episode: Episode, transcription_mode: str = None) -> Tuple[Optional[str], Optional[TranscriptSource]]:
        """Get cached transcript with extensive logging"""
        
        logger.info(f"\n{'='*60}")
        logger.info(f"🔍 TRANSCRIPT CACHE LOOKUP")
        logger.info(f"   Database: {self.db_path}")
        logger.info(f"   Podcast: {episode.podcast}")
        logger.info(f"   Title: {episode.title[:80]}...")
        logger.info(f"   Published: {episode.published} (type: {type(episode.published)})")
        logger.info(f"   GUID: {episode.guid}")
        logger.info(f"   Mode requested: {transcription_mode}")
        
        try:
            # Convert date to consistent format
            if isinstance(episode.published, str):
                published_str = episode.published
            elif hasattr(episode.published, 'isoformat'):
                published_str = episode.published.isoformat()
            else:
                published_str = str(episode.published)
            
            logger.info(f"   Normalized date: {published_str}")
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Determine which column to check based on mode
                if transcription_mode == 'test':
                    transcript_column = 'transcript_test'
                elif transcription_mode == 'full':
                    transcript_column = 'transcript'
                else:
                    transcript_column = None
                
                logger.info(f"   Using column: {transcript_column or 'BOTH (backwards compat)'}")
                
                # Try multiple lookup strategies
                result = None
                
                # Strategy 1: GUID lookup (most reliable)
                if episode.guid:
                    if transcript_column:
                        query = f"""
                            SELECT {transcript_column}, transcript_source, id, transcription_mode
                            FROM episodes
                            WHERE guid = ? AND {transcript_column} IS NOT NULL
                        """
                        cursor.execute(query, (episode.guid,))
                    else:
                        cursor.execute("""
                            SELECT COALESCE(transcript, transcript_test), transcript_source, id, transcription_mode
                            FROM episodes 
                            WHERE guid = ? AND (transcript IS NOT NULL OR transcript_test IS NOT NULL)
                        """, (episode.guid,))
                    
                    result = cursor.fetchone()
                    if result:
                        logger.info(f"✅ Found by GUID! ID: {result[2]}, Mode: {result[3]}")
                
                # Strategy 2: Title + Date lookup
                if not result:
                    if transcript_column:
                        query = f"""
                            SELECT {transcript_column}, transcript_source, id, transcription_mode
                            FROM episodes 
                            WHERE podcast = ? AND title = ? AND date(published) = date(?)
                            AND {transcript_column} IS NOT NULL
                        """
                        cursor.execute(query, (episode.podcast, episode.title, published_str))
                    else:
                        cursor.execute("""
                            SELECT COALESCE(transcript, transcript_test), transcript_source, id, transcription_mode
                            FROM episodes 
                            WHERE podcast = ? AND title = ? AND date(published) = date(?)
                            AND (transcript IS NOT NULL OR transcript_test IS NOT NULL)
                        """, (episode.podcast, episode.title, published_str))
                    
                    result = cursor.fetchone()
                    if result:
                        logger.info(f"✅ Found by Title+Date! ID: {result[2]}, Mode: {result[3]}")
                
                # Strategy 3: Title only (handles date mismatches)
                if not result:
                    if transcript_column:
                        query = f"""
                            SELECT {transcript_column}, transcript_source, id, transcription_mode, published
                            FROM episodes 
                            WHERE podcast = ? AND title = ?
                            AND {transcript_column} IS NOT NULL
                            ORDER BY published DESC
                            LIMIT 1
                        """
                        cursor.execute(query, (episode.podcast, episode.title))
                    else:
                        cursor.execute("""
                            SELECT COALESCE(transcript, transcript_test), transcript_source, id, transcription_mode, published
                            FROM episodes 
                            WHERE podcast = ? AND title = ?
                            AND (transcript IS NOT NULL OR transcript_test IS NOT NULL)
                            ORDER BY published DESC
                            LIMIT 1
                        """, (episode.podcast, episode.title))
                    
                    result = cursor.fetchone()
                    if result:
                        logger.warning(f"⚠️ Found by Title only! ID: {result[2]}, Mode: {result[3]}")
                        logger.warning(f"   Date mismatch: DB has {result[4]}, looking for {published_str}")
                
                if result:
                    transcript, source_str = result[0], result[1]
                    source = TranscriptSource(source_str) if source_str else TranscriptSource.GENERATED
                    logger.info(f"✅ TRANSCRIPT FOUND!")
                    logger.info(f"   Length: {len(transcript)} chars")
                    logger.info(f"   Source: {source.value}")
                    logger.info(f"{'='*60}\n")
                    return transcript, source
                else:
                    logger.info(f"❌ NO TRANSCRIPT FOUND")
                    # Log what's in the database for this episode
                    cursor.execute("""
                        SELECT id, transcription_mode, 
                               LENGTH(transcript), LENGTH(transcript_test),
                               published
                        FROM episodes
                        WHERE podcast = ? AND title = ?
                    """, (episode.podcast, episode.title))
                    
                    existing = cursor.fetchall()
                    if existing:
                        logger.info(f"   Found {len(existing)} matching episodes in DB:")
                        for row in existing:
                            logger.info(f"     ID: {row[0]}, Mode: {row[1]}, Full: {row[2]}, Test: {row[3]}, Date: {row[4]}")
                    else:
                        logger.info(f"   No episodes found with this podcast/title combination")
                    
                    logger.info(f"{'='*60}\n")
                    return None, None
                    
        except sqlite3.Error as e:
            logger.error(f"❌ DATABASE ERROR during lookup: {e}")
            logger.info(f"{'='*60}\n")
            return None, None
    
    def get_episode_summary(self, podcast: str, title: str, published: datetime,
                          transcription_mode: str = 'test') -> Optional[str]:
        """Get cached summary with logging"""
        
        logger.info(f"📝 Looking up summary for: {podcast} - {title[:50]}... (mode: {transcription_mode})")
        
        try:
            # Convert date
            if isinstance(published, str):
                published_str = published
            elif hasattr(published, 'isoformat'):
                published_str = published.isoformat()
            else:
                published_str = str(published)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Determine which columns to check
                if transcription_mode == 'test':
                    summary_col = 'summary_test'
                    paragraph_col = 'paragraph_summary_test'
                else:
                    summary_col = 'summary'
                    paragraph_col = 'paragraph_summary'
                
                # Get both summary types
                cursor.execute(f"""
                    SELECT {summary_col}, {paragraph_col}
                    FROM episodes
                    WHERE podcast = ? AND title = ? AND date(published) = date(?)
                """, (podcast, title, published_str))
                
                result = cursor.fetchone()
                if result and result[0]:  # If we have a full summary
                    logger.info(f"✅ Found cached summary ({len(result[0])} chars)")
                    return result[0]
                else:
                    logger.info(f"❌ No cached summary found")
                    return None
                    
        except sqlite3.Error as e:
            logger.error(f"Database error getting summary: {e}")
            return None
    
    def _create_episodes_table(self, conn: sqlite3.Connection):
        """Create episodes table - implementation from original"""
        # Copy implementation from original database.py
        pass
    
    def _create_indexes(self, conn: sqlite3.Connection):
        """Create database indexes - implementation from original"""
        # Copy implementation from original database.py
        pass