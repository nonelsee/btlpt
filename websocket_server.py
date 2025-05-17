import os
import uuid
import json
import logging
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from redis import asyncio as aioredis

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
# Use environment variables or default settings for Redis
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", None)

redis = aioredis.from_url(REDIS_URL, password=REDIS_PASSWORD)

# User data storage (in-memory for simplicity)
# In production, you'd want to store this in Redis or a database
user_data = {}

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def get():
    return FileResponse("templates/index.html")

@app.on_event("startup")
async def startup_event():
    # Clear matching queue on startup to avoid old users
    await redis.delete("matching_queue")
    logger.info(f"Server started, matching queue cleared, using Redis at {REDIS_URL}")

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    logger.info(f"User {user_id} connected")
    
    # Initialize user data
    user_data[user_id] = {
        "username": user_id,  # Default username is user_id until set
        "websocket": websocket
    }
    
    # Register personal channel for user
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"user:{user_id}")
    
    # Create two tasks to run in parallel
    receive_task = asyncio.create_task(receive_messages(websocket, user_id))
    listen_task = asyncio.create_task(listen_redis(websocket, pubsub, user_id))
    
    try:
        # Wait until one of the tasks completes
        done, pending = await asyncio.wait(
            [receive_task, listen_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Cancel the remaining task
        for task in pending:
            task.cancel()
            
    except Exception as e:
        logger.error(f"Error in websocket handler: {str(e)}")
    finally:
        # Clean up when connection closes
        await clean_up(user_id, pubsub)
        if user_id in user_data:
            del user_data[user_id]
        logger.info(f"User {user_id} disconnected")

async def receive_messages(websocket: WebSocket, user_id: str):
    """Handle messages from client to server"""
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            logger.info(f"Received message from {user_id}: {message['type']}")
            
            if message['type'] == 'set_username':
                # Handle username setting
                user_data[user_id]["username"] = message['username']
                logger.info(f"User {user_id} set username to {message['username']}")
                
                # Add user to matching queue after username is set
                await redis.rpush("matching_queue", user_id)
                logger.info(f"User {user_id} ({message['username']}) added to matching queue")
                
            elif message['type'] == 'chat' and 'room_id' in message:
                # Add field to mark not to send back to sender
                message_obj = json.loads(data)
                message_obj['exclude_sender'] = user_id
                
                # Add username if not present
                if 'username' not in message_obj and user_id in user_data:
                    message_obj['username'] = user_data[user_id]["username"]
                
                modified_data = json.dumps(message_obj)
                
                # Send message to chat room with marker field
                await redis.publish(f"room:{message['room_id']}", modified_data)
                
            elif message['type'] == 'image' and 'room_id' in message:
                # Handle image messages
                message_obj = json.loads(data)
                message_obj['exclude_sender'] = user_id
                
                # Add username if not present
                if 'username' not in message_obj and user_id in user_data:
                    message_obj['username'] = user_data[user_id]["username"]
                
                modified_data = json.dumps(message_obj)
                
                # Send image message to chat room
                await redis.publish(f"room:{message['room_id']}", modified_data)
                
            elif message['type'] == 'find_match':
                # Handle find new match request
                await redis.rpush("matching_queue", user_id)
                logger.info(f"User {user_id} requested new match")
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for {user_id}")
    except Exception as e:
        logger.error(f"Error in receive_messages: {str(e)}")

async def listen_redis(websocket: WebSocket, pubsub, user_id: str):
    """Listen for messages from Redis and send to client"""
    try:
        # Register to also listen for chat room messages (when matched)
        current_room = None
        
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"].decode('utf-8')
                logger.info(f"Redis message for {user_id}: {data[:50]}...")
                
                try:
                    msg_data = json.loads(data)
                    
                    # Check if this message should exclude the sender
                    if (msg_data.get("type") in ["chat", "image"] and 
                        msg_data.get("exclude_sender") == user_id):
                        # Skip this message for the sender
                        continue
                        
                    # Forward message to client
                    await websocket.send_text(data)
                    
                    # If this is a match notification, subscribe to the chat room
                    if msg_data.get("type") == "matched" and "room_id" in msg_data:
                        current_room = msg_data["room_id"]
                        # Register to receive messages from chat room
                        await pubsub.subscribe(f"room:{current_room}")
                        logger.info(f"User {user_id} subscribed to room {current_room}")
                        
                        # Add partner's username to the match message if available
                        partner_id = msg_data.get("partner")
                        if partner_id in user_data:
                            msg_data["partner_username"] = user_data[partner_id]["username"]
                            await websocket.send_text(json.dumps(msg_data))
                            
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse JSON from Redis: {data}")
                    # Still send raw data if not JSON
                    await websocket.send_text(data)
    except asyncio.CancelledError:
        logger.info(f"Redis listener for {user_id} cancelled")
    except Exception as e:
        logger.error(f"Error in listen_redis: {str(e)}")

async def clean_up(user_id: str, pubsub):
    """Clean up when user disconnects"""
    try:
        # Unsubscribe from channels
        await pubsub.unsubscribe()
        
        # Remove user from matching queue if still there
        await redis.lrem("matching_queue", 0, user_id)
        logger.info(f"Cleaned up resources for user {user_id}")
    except Exception as e:
        logger.error(f"Error in clean_up: {str(e)}")

# Run server when file is executed directly
if __name__ == "__main__":
    import uvicorn
    # Use 0.0.0.0 to accept connections from any IP address
    HOST = os.environ.get("HOST", "0.0.0.0")
    PORT = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host=HOST, port=PORT)