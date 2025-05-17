import os
import asyncio 
import json 
import uuid 
import logging
from redis import asyncio as aioredis

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Use environment variables or default settings for Redis
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)

async def match_users():
    """Service to match users from queue"""
    redis = await aioredis.from_url(REDIS_URL, password=REDIS_PASSWORD)
    try:
        logger.info(f"Matching service started, using Redis at {REDIS_URL}")
        while True:
            try:
                # Get number of users in queue
                queue_length = await redis.llen("matching_queue")
                if queue_length >= 2:
                    # Use pipeline transaction to get and remove 2 users from queue start
                    async with redis.pipeline(transaction=True) as pipe:
                        await pipe.lpop("matching_queue", 2)
                        users = await pipe.execute()
                    
                    # Decode bytes to string
                    users = [user.decode() for user in users[0]]
                    
                    if len(users) == 2:
                        user1, user2 = users
                        room_id = f"room_{uuid.uuid4().hex}"
                        logger.info(f"Matched: {user1} with {user2} in room {room_id}")
                        
                        # Notify user 1
                        await redis.publish(
                            f"user:{user1}", 
                            json.dumps({
                                "type": "matched",
                                "room_id": room_id,
                                "partner": user2
                            })
                        )
                        
                        # Notify user 2
                        await redis.publish(
                            f"user:{user2}", 
                            json.dumps({
                                "type": "matched",
                                "room_id": room_id,
                                "partner": user1
                            })
                        )
                # Pause to reduce CPU load
                await asyncio.sleep(0.5)
            except (aioredis.ConnectionError, aioredis.TimeoutError) as e:
                logger.error(f"Redis connection error: {e}")
                await asyncio.sleep(2)  # Wait before reconnecting
            except Exception as e:
                logger.error(f"Unexpected error in match_users: {e}")
                await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info("Matching service is shutting down...")
        await redis.close()
        logger.info("Redis connection closed")

async def main():
    task = asyncio.create_task(match_users())
    try:
        logger.info("Starting matcher service")
        await task
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("Matcher service stopped")

if __name__ == "__main__":
    asyncio.run(main())