#!/usr/bin/env python3
"""Command to validate and fix entity errors in existing transcripts"""

import asyncio
import click
from datetime import datetime, timedelta

from renaissance_weekly.database import PodcastDatabase
from renaissance_weekly.processing.entity_validator import entity_validator
from renaissance_weekly.processing.transcript_cleaner import transcript_cleaner
from renaissance_weekly.utils.logging import get_logger

logger = get_logger(__name__)


async def validate_episode_entities(episode_data: dict):
    """Validate entities in a single episode"""
    
    podcast = episode_data['podcast']
    title = episode_data['title']
    transcript = episode_data['transcript']
    
    if not transcript:
        return
    
    logger.info(f"\nValidating: {podcast} - {title[:50]}...")
    
    # Step 1: Apply known corrections
    cleaned_transcript, basic_corrections = transcript_cleaner.clean_transcript(transcript, podcast)
    
    # Step 2: High-confidence pattern corrections
    cleaned_transcript, pattern_corrections = entity_validator.apply_high_confidence_corrections(cleaned_transcript)
    
    # Step 3: AI-powered validation (for suspicious entities)
    validation_result = await entity_validator.validate_transcript_entities(
        cleaned_transcript[:10000],  # Sample for efficiency
        podcast
    )
    
    all_corrections = basic_corrections + pattern_corrections
    
    if validation_result.get('corrections'):
        logger.info("🤖 AI-suggested corrections:")
        for correction in validation_result['corrections']:
            if correction['confidence'] > 0.7:
                logger.info(f"   - {correction['incorrect']} → {correction['correct']} "
                          f"(confidence: {correction['confidence']:.2f})")
                logger.info(f"     Reason: {correction['reason']}")
                all_corrections.append(f"AI: {correction['incorrect']} → {correction['correct']}")
    
    if all_corrections:
        logger.info(f"✅ Total corrections for this episode: {len(all_corrections)}")
        
        # Update database if transcript was changed
        if cleaned_transcript != transcript:
            db = PodcastDatabase()
            db.save_episode_transcript(podcast, title, cleaned_transcript)
            logger.info("💾 Updated transcript in database")
    else:
        logger.info("✓ No corrections needed")


@click.command()
@click.option('--days', default=30, help='Number of days back to check')
@click.option('--podcast', default=None, help='Specific podcast to check')
@click.option('--dry-run', is_flag=True, help='Show corrections without applying')
async def validate_entities(days: int, podcast: str, dry_run: bool):
    """Validate and fix entity errors in transcripts"""
    
    logger.info("🔍 Entity Validation Tool")
    logger.info(f"Checking episodes from last {days} days")
    
    if dry_run:
        logger.info("DRY RUN - No changes will be saved")
    
    # Get episodes with transcripts
    db = PodcastDatabase()
    since_date = datetime.now() - timedelta(days=days)
    
    query = """
        SELECT podcast, title, transcript, published
        FROM episodes
        WHERE transcript IS NOT NULL
        AND published >= ?
    """
    
    params = [since_date.isoformat()]
    
    if podcast:
        query += " AND podcast = ?"
        params.append(podcast)
    
    query += " ORDER BY published DESC"
    
    episodes = db.execute_query(query, params)
    
    logger.info(f"Found {len(episodes)} episodes to validate")
    
    # Process each episode
    for episode in episodes:
        await validate_episode_entities(episode)
    
    logger.info("\n✅ Validation complete!")


def main():
    """Run the entity validation command"""
    asyncio.run(validate_entities())


if __name__ == "__main__":
    main()