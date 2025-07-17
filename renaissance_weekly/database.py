"""Database module for Renaissance Weekly"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any

from .models import Episode, TranscriptSource
from .config import DB_PATH
from .utils.logging import get_logger

logger = get_logger(__name__)


class PodcastDatabase:
    """Handle all database operations for podcast episodes and transcripts"""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize database tables with migration support"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Check if episodes table exists
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='episodes'
                """)
                table_exists = cursor.fetchone() is not None
                
                if table_exists:
                    # Check if we need to migrate the schema
                    cursor.execute("PRAGMA table_info(episodes)")
                    columns = {row[1] for row in cursor.fetchall()}
                    
                    required_columns = {
                        'podcast', 'title', 'published', 'audio_url', 
                        'transcript_url', 'description', 'link', 'duration', 
                        'guid', 'transcript', 'transcript_source', 'summary',
                        'transcription_mode', 'transcript_test', 'summary_test',
                        'paragraph_summary', 'paragraph_summary_test'
                    }
                    
                    if not required_columns.issubset(columns):
                        logger.warning("Database schema outdated, migrating...")
                        self._migrate_database(conn, columns)
                else:
                    # Create new table
                    self._create_episodes_table(conn)
                
                # Create or update indexes
                self._create_indexes(conn)
                
                conn.commit()
                
        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            # If all else fails, backup and recreate
            self._backup_and_recreate()
    
    def _create_episodes_table(self, conn: sqlite3.Connection):
        """Create the episodes table"""
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                podcast TEXT NOT NULL,
                title TEXT NOT NULL,
                published DATETIME NOT NULL,
                audio_url TEXT,
                transcript_url TEXT,
                description TEXT,
                link TEXT,
                duration TEXT,
                guid TEXT,
                transcript TEXT,
                transcript_source TEXT,
                summary TEXT,
                transcript_test TEXT,
                summary_test TEXT,
                paragraph_summary TEXT,
                paragraph_summary_test TEXT,
                transcription_mode TEXT DEFAULT 'test',
                processing_status TEXT DEFAULT 'pending',
                failure_reason TEXT,
                retry_count INTEGER DEFAULT 0,
                retry_strategy TEXT,
                processing_started_at DATETIME,
                processing_completed_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(podcast, title, published)
            )
        """)
    
    def _create_indexes(self, conn: sqlite3.Connection):
        """Create database indexes"""
        cursor = conn.cursor()
        
        # Drop existing indexes if they exist (to avoid conflicts)
        cursor.execute("DROP INDEX IF EXISTS idx_episodes_podcast_published")
        cursor.execute("DROP INDEX IF EXISTS idx_episodes_guid")
        cursor.execute("DROP INDEX IF EXISTS idx_episodes_processing_status")
        
        # Create new indexes
        cursor.execute("""
            CREATE INDEX idx_episodes_podcast_published 
            ON episodes(podcast, published DESC)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_episodes_guid 
            ON episodes(guid)
        """)
        
        # Add index on processing_status for frequent queries
        cursor.execute("""
            CREATE INDEX idx_episodes_processing_status 
            ON episodes(processing_status)
        """)
    
    def _migrate_database(self, conn: sqlite3.Connection, existing_columns: set):
        """Migrate database to new schema with proper transaction handling"""
        cursor = conn.cursor()
        
        # Start a transaction
        cursor.execute("BEGIN TRANSACTION")
        
        try:
            # Create a temporary table with the new schema
            cursor.execute("""
                CREATE TABLE episodes_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    podcast TEXT NOT NULL,
                    title TEXT NOT NULL,
                    published DATETIME NOT NULL,
                    audio_url TEXT,
                    transcript_url TEXT,
                    description TEXT,
                    link TEXT,
                    duration TEXT,
                    guid TEXT,
                    transcript TEXT,
                    transcript_source TEXT,
                    summary TEXT,
                    transcript_test TEXT,
                    summary_test TEXT,
                    paragraph_summary TEXT,
                    paragraph_summary_test TEXT,
                    transcription_mode TEXT DEFAULT 'test',
                    processing_status TEXT DEFAULT 'pending',
                    failure_reason TEXT,
                    retry_count INTEGER DEFAULT 0,
                    retry_strategy TEXT,
                    processing_started_at DATETIME,
                    processing_completed_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(podcast, title, published)
                )
            """)
            
            # Copy data from old table to new table
            # Only copy columns that exist in both tables
            # IMPORTANT: We're implementing Option A - clearing all summaries and transcripts
            common_columns = existing_columns.intersection({
                'id', 'podcast', 'title', 'published', 'audio_url', 
                'transcript_url', 'description', 'link', 'duration', 
                'guid', 'transcript_source',  # Note: removed 'transcript' and 'summary'
                'transcription_mode', 'created_at', 'updated_at'
            })
            
            if common_columns:
                # If transcription_mode doesn't exist in old table, add it with default 'test'
                if 'transcription_mode' not in existing_columns and 'transcription_mode' in common_columns:
                    # Remove transcription_mode from common columns  
                    common_columns_without_mode = common_columns - {'transcription_mode'}
                    if common_columns_without_mode:
                        columns_str = ', '.join(common_columns_without_mode)
                        cursor.execute(f"""
                            INSERT INTO episodes_new ({columns_str}, transcription_mode)
                            SELECT {columns_str}, 'test' FROM episodes
                        """)
                        logger.info("Added transcription_mode='test' to existing records during migration")
                else:
                    columns_str = ', '.join(common_columns)
                    cursor.execute(f"""
                        INSERT INTO episodes_new ({columns_str})
                        SELECT {columns_str} FROM episodes
                    """)
            
            # Drop old table and rename new table
            cursor.execute("DROP TABLE episodes")
            cursor.execute("ALTER TABLE episodes_new RENAME TO episodes")
            
            # Recreate indexes
            self._create_indexes(conn)
            
            # Commit the transaction
            cursor.execute("COMMIT")
            logger.info("✅ Database migration completed successfully")
            
        except sqlite3.Error as e:
            logger.error(f"Migration failed: {e}")
            # Rollback the entire transaction
            cursor.execute("ROLLBACK")
            raise
    
    def _backup_and_recreate(self):
        """Backup existing database and create a new one"""
        if self.db_path.exists():
            # Create backup
            backup_path = self.db_path.with_suffix('.backup')
            logger.warning(f"Backing up existing database to {backup_path}")
            
            import shutil
            shutil.move(str(self.db_path), str(backup_path))
        
        # Create fresh database
        with sqlite3.connect(self.db_path) as conn:
            self._create_episodes_table(conn)
            self._create_indexes(conn)
            conn.commit()
        
        logger.info("✅ Created fresh database")
    
    def save_episode(self, episode: Episode, transcript: Optional[str] = None, 
                     transcript_source: Optional[TranscriptSource] = None,
                     summary: Optional[str] = None, paragraph_summary: Optional[str] = None,
                     transcription_mode: str = 'full') -> int:
        """Save or update an episode in the database"""
        logger.info(f"💾 Saving episode: {episode.podcast} - {episode.title[:50]}...")
        logger.info(f"   GUID: {episode.guid}")
        logger.info(f"   Mode: {transcription_mode}")
        logger.info(f"   Transcript: {len(transcript) if transcript else 0} chars")
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Convert episode to dict for storage
                # Handle published date - could be datetime or string
                if isinstance(episode.published, str):
                    published_str = episode.published
                elif hasattr(episode.published, 'isoformat'):
                    published_str = episode.published.isoformat()
                else:
                    published_str = str(episode.published)
                    
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
                
                # CRITICAL FIX: Only update transcript/summary fields when explicitly provided
                # This prevents overwriting existing data during episode fetching
                if transcript is not None or summary is not None or paragraph_summary is not None:
                    # We have actual content to save
                    if transcription_mode == 'test':
                        episode_data['transcript_test'] = transcript
                        episode_data['summary_test'] = summary
                        episode_data['paragraph_summary_test'] = paragraph_summary
                        # Don't touch full mode columns - preserve existing data
                    else:  # full mode
                        episode_data['transcript'] = transcript
                        episode_data['summary'] = summary
                        episode_data['paragraph_summary'] = paragraph_summary
                        # Don't touch test mode columns - preserve existing data
                else:
                    # No transcript/summary provided - this is just an episode metadata update
                    # Preserve ALL existing transcript/summary data by not setting these fields
                    # They will be excluded from the UPDATE/INSERT queries below
                    pass
                
                # Use INSERT OR REPLACE for atomic operation
                # First check if record exists to preserve the ID
                cursor.execute("""
                    SELECT id FROM episodes
                    WHERE podcast = ? AND title = ? AND published = ?
                """, (episode_data['podcast'], episode_data['title'], episode_data['published']))
                
                existing_id = cursor.fetchone()
                
                if existing_id:
                    # Build dynamic UPDATE query based on what fields we have
                    update_fields = ['podcast = ?', 'title = ?', 'published = ?', 
                                   'audio_url = ?', 'transcript_url = ?', 'description = ?',
                                   'link = ?', 'duration = ?', 'guid = ?', 
                                   'transcription_mode = ?', 'updated_at = ?']
                    
                    update_values = [
                        episode_data['podcast'], episode_data['title'], episode_data['published'],
                        episode_data['audio_url'], episode_data['transcript_url'],
                        episode_data['description'], episode_data['link'],
                        episode_data['duration'], episode_data['guid'],
                        episode_data['transcription_mode'], episode_data['updated_at']
                    ]
                    
                    # Only update transcript/summary fields if they're present in episode_data
                    if 'transcript' in episode_data:
                        update_fields.append('transcript = ?')
                        update_values.append(episode_data['transcript'])
                        update_fields.append('transcript_source = ?')
                        update_values.append(episode_data['transcript_source'])
                    
                    if 'summary' in episode_data:
                        update_fields.append('summary = ?')
                        update_values.append(episode_data['summary'])
                    
                    if 'paragraph_summary' in episode_data:
                        update_fields.append('paragraph_summary = ?')
                        update_values.append(episode_data['paragraph_summary'])
                    
                    if 'transcript_test' in episode_data:
                        update_fields.append('transcript_test = ?')
                        update_values.append(episode_data['transcript_test'])
                    
                    if 'summary_test' in episode_data:
                        update_fields.append('summary_test = ?')
                        update_values.append(episode_data['summary_test'])
                    
                    if 'paragraph_summary_test' in episode_data:
                        update_fields.append('paragraph_summary_test = ?')
                        update_values.append(episode_data['paragraph_summary_test'])
                    
                    # Add the WHERE clause value
                    update_values.append(existing_id[0])
                    
                    cursor.execute(f"""
                        UPDATE episodes SET {', '.join(update_fields)}
                        WHERE id = ?
                    """, update_values)
                else:
                    # Insert new record
                    cursor.execute("""
                        INSERT INTO episodes (
                            podcast, title, published, audio_url, transcript_url,
                            description, link, duration, guid, transcript,
                            transcript_source, summary, transcript_test, summary_test,
                            transcription_mode, paragraph_summary, paragraph_summary_test
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        episode_data['podcast'], episode_data['title'], episode_data['published'],
                        episode_data['audio_url'], episode_data['transcript_url'],
                        episode_data['description'], episode_data['link'],
                        episode_data['duration'], episode_data['guid'],
                        episode_data.get('transcript'), episode_data['transcript_source'],
                        episode_data.get('summary'), episode_data.get('transcript_test'),
                        episode_data.get('summary_test'), episode_data['transcription_mode'],
                        episode_data.get('paragraph_summary'), episode_data.get('paragraph_summary_test')
                    ))
                
                conn.commit()
                # For UPDATE operations, lastrowid is 0, so use existing_id
                row_id = existing_id[0] if existing_id else cursor.lastrowid
                
                # Verify the save was successful
                if row_id > 0:
                    # Immediately verify we can retrieve what we just saved
                    test_transcript, _ = self.get_transcript(episode, transcription_mode)
                    if test_transcript != transcript:
                        logger.error(f"❌ CACHE VERIFICATION FAILED after save!")
                        logger.error(f"   Saved {len(transcript) if transcript else 0} chars but retrieved {len(test_transcript) if test_transcript else 0} chars")
                        logger.error(f"   Episode: {episode.podcast} - {episode.title}")
                        logger.error(f"   GUID: {episode.guid}")
                        logger.error(f"   Mode: {transcription_mode}")
                    else:
                        logger.debug(f"✅ Cache verification passed - transcript retrievable")
                
                return row_id
                
        except sqlite3.Error as e:
            logger.error(f"Database error saving episode: {e}")
            return -1
    
    def get_transcript(self, episode: Episode, transcription_mode: str = None) -> Tuple[Optional[str], Optional[TranscriptSource]]:
        """Get cached transcript for an episode matching the transcription mode"""
        try:
            # Enhanced debug logging
            logger.info(f"\n{'='*60}")
            logger.info(f"🔍 DATABASE TRANSCRIPT LOOKUP")
            logger.info(f"   Database: {self.db_path}")
            logger.info(f"   Mode: {transcription_mode}")
            logger.info(f"   Podcast: {episode.podcast}")
            logger.info(f"   Title: {episode.title[:80]}...")
            logger.info(f"   GUID: {episode.guid}")
            logger.info(f"   Published: {episode.published} (type: {type(episode.published)})")
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Determine which column to use based on mode
                if transcription_mode == 'test':
                    transcript_column = 'transcript_test'
                elif transcription_mode == 'full':
                    transcript_column = 'transcript'
                else:
                    # Backwards compatibility - try both columns
                    transcript_column = None
                
                # Try to find by guid first (most reliable)
                if episode.guid:
                    if transcript_column:
                        query = f"""
                            SELECT {transcript_column}, transcript_source 
                            FROM episodes
                            WHERE guid = ? AND {transcript_column} IS NOT NULL
                        """
                        logger.info(f"🔍 Executing GUID query for column: {transcript_column}")
                        logger.debug(f"🔍 GUID query: {query} with param: {episode.guid}")
                        cursor.execute(query, (episode.guid,))
                    else:
                        # Backwards compatibility - check both columns
                        cursor.execute("""
                            SELECT COALESCE(transcript, transcript_test), transcript_source 
                            FROM episodes 
                            WHERE guid = ? AND (transcript IS NOT NULL OR transcript_test IS NOT NULL)
                        """, (episode.guid,))
                    result = cursor.fetchone()
                    logger.info(f"🔍 GUID query result: {result is not None}")
                    if result:
                        transcript, source_str = result
                        source = TranscriptSource(source_str) if source_str else None
                        logger.info(f"✅ Found transcript by GUID: {len(transcript) if transcript else 0} chars")
                        return transcript, source
                
                # Fall back to matching by podcast, title, and date
                logger.info("🔍 GUID lookup failed, trying title/date match...")
                
                # Handle published date - could be datetime or string
                if isinstance(episode.published, str):
                    published_str = episode.published
                elif hasattr(episode.published, 'isoformat'):
                    published_str = episode.published.isoformat()
                else:
                    published_str = str(episode.published)
                    
                if transcript_column:
                    cursor.execute(f"""
                        SELECT {transcript_column}, transcript_source 
                        FROM episodes 
                        WHERE podcast = ? AND title = ? AND date(published) = date(?)
                        AND {transcript_column} IS NOT NULL
                    """, (episode.podcast, episode.title, published_str))
                else:
                    # Backwards compatibility
                    cursor.execute("""
                        SELECT COALESCE(transcript, transcript_test), transcript_source 
                        FROM episodes 
                        WHERE podcast = ? AND title = ? AND date(published) = date(?)
                        AND (transcript IS NOT NULL OR transcript_test IS NOT NULL)
                    """, (episode.podcast, episode.title, published_str))
                
                result = cursor.fetchone()
                logger.info(f"🔍 Title/date query result: {result is not None}")
                if result:
                    transcript, source_str = result
                    source = TranscriptSource(source_str) if source_str else None
                    logger.info(f"✅ Found transcript by title/date: {len(transcript) if transcript else 0} chars")
                    return transcript, source
                
                # Final fallback: Try matching by just podcast and title (most flexible)
                logger.info("🔍 Title/date lookup failed, trying title-only match...")
                if transcript_column:
                    cursor.execute(f"""
                        SELECT {transcript_column}, transcript_source, published
                        FROM episodes 
                        WHERE podcast = ? AND title = ?
                        AND {transcript_column} IS NOT NULL
                        ORDER BY published DESC
                        LIMIT 1
                    """, (episode.podcast, episode.title))
                else:
                    cursor.execute("""
                        SELECT COALESCE(transcript, transcript_test), transcript_source, published
                        FROM episodes 
                        WHERE podcast = ? AND title = ?
                        AND (transcript IS NOT NULL OR transcript_test IS NOT NULL)
                        ORDER BY published DESC
                        LIMIT 1
                    """, (episode.podcast, episode.title))
                
                result = cursor.fetchone()
                if result:
                    transcript, source_str, db_published = result
                    source = TranscriptSource(source_str) if source_str else None
                    logger.info(f"✅ Found transcript by title-only: {len(transcript) if transcript else 0} chars")
                    logger.info(f"   DB published: {db_published}, Episode published: {episode.published}")
                    return transcript, source
                
                logger.info("❌ No transcript found in database")
                return None, None
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting transcript: {e}")
            return None, None
    
    def get_episode(self, podcast: str, title: str, published: datetime) -> Optional[Dict]:
        """Get a specific episode from the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM episodes 
                    WHERE podcast = ? AND title = ? AND date(published) = date(?)
                """, (podcast, title, published.isoformat()))
                
                result = cursor.fetchone()
                if result:
                    columns = [desc[0] for desc in cursor.description]
                    return dict(zip(columns, result))
                
                return None
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting episode: {e}")
            return None
    
    def get_recent_episodes(self, days_back: int = 7) -> List[Dict]:
        """Get recent episodes from the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM episodes 
                    WHERE published >= datetime('now', '-' || ? || ' days')
                    ORDER BY published DESC
                """, (days_back,))
                
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                
                return [dict(zip(columns, row)) for row in results]
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting recent episodes: {e}")
            return []
    
    def get_episodes_with_summaries(self, days_back: int = 7, transcription_mode: str = None) -> List[Dict]:
        """Get episodes that have summaries (both paragraph and full)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                if transcription_mode == 'test':
                    cursor.execute("""
                        SELECT * FROM episodes 
                        WHERE published >= datetime('now', '-' || ? || ' days')
                        AND summary_test IS NOT NULL AND summary_test != ''
                        ORDER BY published DESC
                    """, (days_back,))
                elif transcription_mode == 'full':
                    cursor.execute("""
                        SELECT * FROM episodes 
                        WHERE published >= datetime('now', '-' || ? || ' days')
                        AND summary IS NOT NULL AND summary != ''
                        ORDER BY published DESC
                    """, (days_back,))
                else:
                    # Backwards compatibility - get episodes with any summaries
                    cursor.execute("""
                        SELECT * FROM episodes 
                        WHERE published >= datetime('now', '-' || ? || ' days')
                        AND ((summary IS NOT NULL AND summary != '') OR 
                             (summary_test IS NOT NULL AND summary_test != ''))
                        ORDER BY published DESC
                    """, (days_back,))
                
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                
                return [dict(zip(columns, row)) for row in results]
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting episodes with summaries: {e}")
            return []
    
    def get_episode_summary(self, podcast: str, title: str, published: datetime, transcription_mode: str = None) -> Optional[str]:
        """Get summary for a specific episode if it exists, optionally filtered by mode"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Handle both datetime and string published dates
                if isinstance(published, datetime):
                    published_str = published.isoformat()
                else:
                    published_str = published
                
                # Determine which column to use based on mode
                if transcription_mode == 'test':
                    summary_column = 'summary_test'
                elif transcription_mode == 'full':
                    summary_column = 'summary'
                else:
                    # Backwards compatibility - try both columns
                    summary_column = None
                
                if summary_column:
                    cursor.execute(f"""
                        SELECT {summary_column}
                        FROM episodes 
                        WHERE podcast = ? AND title = ? AND published = ?
                        AND {summary_column} IS NOT NULL
                    """, (podcast, title, published_str))
                else:
                    # Backwards compatibility - check both columns
                    cursor.execute("""
                        SELECT COALESCE(summary, summary_test)
                        FROM episodes 
                        WHERE podcast = ? AND title = ? AND published = ?
                        AND (summary IS NOT NULL OR summary_test IS NOT NULL)
                    """, (podcast, title, published_str))
                
                row = cursor.fetchone()
                return row[0] if row else None
                
        except Exception as e:
            logger.error(f"Error fetching episode summary: {e}")
            return None
    
    def get_episodes_without_transcripts(self, days_back: int = 7) -> List[Dict]:
        """Get episodes that don't have transcripts yet"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM episodes 
                    WHERE published >= datetime('now', '-' || ? || ' days')
                    AND (transcript IS NULL OR transcript = '')
                    ORDER BY published DESC
                """, (days_back,))
                
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                
                return [dict(zip(columns, row)) for row in results]
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting episodes without transcripts: {e}")
            return []
    
    def get_last_episode_dates(self, podcast_names: List[str]) -> Dict[str, Optional[datetime]]:
        """Get the most recent episode date for each podcast"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Create placeholders for IN clause
                placeholders = ','.join(['?' for _ in podcast_names])
                
                cursor.execute(f"""
                    SELECT podcast, MAX(published) as last_published
                    FROM episodes
                    WHERE podcast IN ({placeholders})
                    GROUP BY podcast
                """, podcast_names)
                
                results = cursor.fetchall()
                
                # Convert to dictionary with datetime objects
                last_dates = {}
                for podcast, date_str in results:
                    if date_str:
                        # Parse the ISO format date string
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        # Ensure timezone awareness
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        last_dates[podcast] = dt
                    else:
                        last_dates[podcast] = None
                
                # Add None for podcasts not found in results
                for podcast_name in podcast_names:
                    if podcast_name not in last_dates:
                        last_dates[podcast_name] = None
                
                return last_dates
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting last episode dates: {e}")
            return {name: None for name in podcast_names}
    
    def get_last_episode_info(self, podcast_names: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """Get the most recent episode info (date and title) for each podcast"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Create placeholders for IN clause
                placeholders = ','.join(['?' for _ in podcast_names])
                
                # Use a subquery to get the most recent episode for each podcast
                cursor.execute(f"""
                    SELECT e.podcast, e.published, e.title
                    FROM episodes e
                    INNER JOIN (
                        SELECT podcast, MAX(published) as max_published
                        FROM episodes
                        WHERE podcast IN ({placeholders})
                        GROUP BY podcast
                    ) latest ON e.podcast = latest.podcast AND e.published = latest.max_published
                """, podcast_names)
                
                results = cursor.fetchall()
                
                # Convert to dictionary with episode info
                last_episodes = {}
                for podcast, date_str, title in results:
                    if date_str:
                        # Parse the ISO format date string
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        # Ensure timezone awareness
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        last_episodes[podcast] = {
                            'date': dt,
                            'title': title
                        }
                    else:
                        last_episodes[podcast] = None
                
                # Add None for podcasts not found in results
                for podcast_name in podcast_names:
                    if podcast_name not in last_episodes:
                        last_episodes[podcast_name] = None
                
                return last_episodes
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting last episode info: {e}")
            return {name: None for name in podcast_names}
    
    def clear_old_episodes(self, days_to_keep: int = 30):
        """Clear episodes older than specified days"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM episodes 
                    WHERE published < datetime('now', '-' || ? || ' days')
                """, (days_to_keep,))
                
                deleted_count = cursor.rowcount
                conn.commit()
                
                if deleted_count > 0:
                    logger.info(f"Cleared {deleted_count} old episodes from database")
                    
        except sqlite3.Error as e:
            logger.error(f"Database error clearing old episodes: {e}")
    
    def update_episode_status(self, episode_id: int, status: str, 
                            failure_reason: Optional[str] = None,
                            retry_strategy: Optional[str] = None):
        """Update the processing status of an episode"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                if status in ['downloading', 'transcribing', 'summarizing']:
                    cursor.execute("""
                        UPDATE episodes 
                        SET processing_status = ?, processing_started_at = ?, updated_at = ?
                        WHERE id = ?
                    """, (status, datetime.now().isoformat(), datetime.now().isoformat(), episode_id))
                elif status == 'completed':
                    cursor.execute("""
                        UPDATE episodes 
                        SET processing_status = ?, processing_completed_at = ?, updated_at = ?
                        WHERE id = ?
                    """, (status, datetime.now().isoformat(), datetime.now().isoformat(), episode_id))
                elif 'failed' in status:
                    cursor.execute("""
                        UPDATE episodes 
                        SET processing_status = ?, failure_reason = ?, retry_count = retry_count + 1, 
                            retry_strategy = ?, updated_at = ?
                        WHERE id = ?
                    """, (status, failure_reason, retry_strategy, datetime.now().isoformat(), episode_id))
                else:
                    cursor.execute("""
                        UPDATE episodes 
                        SET processing_status = ?, updated_at = ?
                        WHERE id = ?
                    """, (status, datetime.now().isoformat(), episode_id))
                
                conn.commit()
                
        except sqlite3.Error as e:
            logger.error(f"Database error updating episode status: {e}")
    
    def get_failed_episodes(self, days_back: int = 7) -> List[Dict]:
        """Get episodes that failed processing"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM episodes 
                    WHERE published >= datetime('now', '-' || ? || ' days')
                    AND processing_status LIKE '%failed%'
                    ORDER BY published DESC
                """, (days_back,))
                
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                
                return [dict(zip(columns, row)) for row in results]
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting failed episodes: {e}")
            return []
    
    def get_episodes_by_status(self, status: str, days_back: int = 7) -> List[Dict]:
        """Get episodes with a specific processing status"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM episodes 
                    WHERE published >= datetime('now', '-' || ? || ' days')
                    AND processing_status = ?
                    ORDER BY published DESC
                """, (days_back, status))
                
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                
                return [dict(zip(columns, row)) for row in results]
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting episodes by status: {e}")
            return []
    
    def get_retry_eligible_episodes(self, max_retries: int = 3) -> List[Dict]:
        """Get failed episodes that haven't exceeded retry limit"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM episodes 
                    WHERE processing_status LIKE '%failed%'
                    AND retry_count < ?
                    ORDER BY published DESC
                """, (max_retries,))
                
                results = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                
                return [dict(zip(columns, row)) for row in results]
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting retry eligible episodes: {e}")
            return []
    
    def get_episode_failure_info(self, guid: str) -> Dict:
        """Get failure information for a specific episode"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT processing_status, failure_reason, retry_count, retry_strategy
                    FROM episodes 
                    WHERE guid = ?
                """, (guid,))
                
                result = cursor.fetchone()
                if result:
                    return {
                        'processing_status': result[0],
                        'failure_reason': result[1],
                        'retry_count': result[2],
                        'retry_strategy': result[3]
                    }
                return {}
                
        except sqlite3.Error as e:
            logger.error(f"Database error getting episode failure info: {e}")
            return {}
    
    def update_episode_status(self, guid: str, status: str, 
                            failure_reason: Optional[str] = None,
                            retry_strategy: Optional[str] = None) -> bool:
        """Update episode processing status and retry information"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # First get current retry count
                cursor.execute("SELECT retry_count FROM episodes WHERE guid = ?", (guid,))
                result = cursor.fetchone()
                current_retry_count = result[0] if result else 0
                
                # Update status
                if failure_reason:
                    cursor.execute("""
                        UPDATE episodes 
                        SET processing_status = ?, failure_reason = ?, 
                            retry_count = ?, retry_strategy = ?,
                            updated_at = ?
                        WHERE guid = ?
                    """, (status, failure_reason, current_retry_count + 1, 
                          retry_strategy, datetime.now().isoformat(), guid))
                else:
                    cursor.execute("""
                        UPDATE episodes 
                        SET processing_status = ?, retry_strategy = ?,
                            updated_at = ?
                        WHERE guid = ?
                    """, (status, retry_strategy, datetime.now().isoformat(), guid))
                
                conn.commit()
                return cursor.rowcount > 0
                
        except sqlite3.Error as e:
            logger.error(f"Database error updating episode status: {e}")
            return False