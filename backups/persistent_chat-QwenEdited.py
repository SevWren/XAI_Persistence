from typing import Dict, List, Optional
import json
import time
import logging
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
import httpx
from pydantic import BaseModel, Field
from collections import deque

# Configure logging with more detailed format
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG for more detailed logging
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler('chat_debug.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# XAI API Configuration
XAI_API_KEY = "xai-nLnYaZ6fLInSwg2Qs8bQPKM3MpDFrEBa0ofC0CpMOZbAh62lifbASg52EPG4Nuk04z3nL8SWty2g4Vwj"
XAI_BASE_URL = "https://api.x.ai/v1"

# Rate limiting configuration
RATE_LIMIT_REQUESTS = 50  # Maximum requests per minute
RATE_LIMIT_WINDOW = 60   # Window size in seconds
RETRY_ATTEMPTS = 3       # Number of retry attempts
RETRY_DELAY = 2         # Delay between retries in seconds

class Message(BaseModel):
    """Message structure for chat history"""
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)

class ChatMemory(BaseModel):
    """Structure for storing chat memory"""
    messages: List[Message] = Field(default_factory=list)
    metadata: Dict = Field(default_factory=dict)

class RateLimiter:
    """Rate limiter implementation"""
    def __init__(self, max_requests: int, window_size: int):
        self.max_requests = max_requests
        self.window_size = window_size
        self.requests = deque()

    def can_make_request(self) -> bool:
        """Check if a request can be made within rate limits"""
        now = datetime.now()
        window_start = now - timedelta(seconds=self.window_size)
        
        # Remove old requests outside the window
        while self.requests and self.requests[0] < window_start:
            self.requests.popleft()
        
        return len(self.requests) < self.max_requests

    def add_request(self):
        """Record a new request"""
        self.requests.append(datetime.now())

    def wait_for_capacity(self):
        """Wait until capacity is available"""
        while not self.can_make_request():
            time.sleep(1)

class PersistentChat:
    def __init__(self, model: str = "grok-1", memory_file: str = "chat_memory.json"):
        self.model = model
        self.memory_file = Path(memory_file)
        self.memory = self._load_memory()
        self.rate_limiter = RateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW)
        
        # Configure client with proper timeout and error handling
        self.client = httpx.Client(
            base_url=XAI_BASE_URL,
            headers={
                "Authorization": f"Bearer {XAI_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            timeout=30.0,  # 30 second timeout
            verify=True,   # Verify SSL certificates
            http2=True    # Enable HTTP/2 support
        )
        logging.info("PersistentChat initialized with model: %s", model)

    def _load_memory(self) -> ChatMemory:
        """Load chat memory from file if it exists"""
        try:
            if self.memory_file.exists():
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    messages = [
                        Message(
                            role=msg['role'],
                            content=msg['content'],
                            timestamp=datetime.fromisoformat(msg['timestamp'])
                        )
                        for msg in data['messages']
                    ]
                    logging.info("Loaded %d messages from memory file", len(messages))
                    return ChatMemory(messages=messages, metadata=data.get('metadata', {}))
        except json.JSONDecodeError as e:
            logging.error("JSON decode error in memory file: %s", str(e))
            # Backup corrupted file
            if self.memory_file.exists():
                backup_path = self.memory_file.with_suffix('.json.backup')
                self.memory_file.rename(backup_path)
                logging.info("Corrupted memory file backed up to %s", backup_path)
        except Exception as e:
            logging.error("Error loading memory file: %s", str(e))
        return ChatMemory()

    def _save_memory(self):
        """Save chat memory to file"""
        try:
            # Create backup before saving
            if self.memory_file.exists():
                backup_path = self.memory_file.with_suffix('.json.bak')
                self.memory_file.rename(backup_path)
            
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'messages': [
                        {
                            'role': msg.role,
                            'content': msg.content,
                            'timestamp': msg.timestamp.isoformat()
                        }
                        for msg in self.memory.messages
                    ],
                    'metadata': self.memory.metadata
                }, f, indent=2, ensure_ascii=False)
            logging.info("Memory saved successfully")
            
            # Remove backup after successful save
            if Path(str(self.memory_file) + '.bak').exists():
                Path(str(self.memory_file) + '.bak').unlink()
        except Exception as e:
            logging.error("Error saving memory: %s", str(e))
            # Restore from backup if save failed
            if Path(str(self.memory_file) + '.bak').exists():
                Path(str(self.memory_file) + '.bak').rename(self.memory_file)
                logging.info("Restored from backup after failed save")

    def _make_api_request(self, messages: List[Dict]) -> str:
        """Make API request with retry logic and rate limiting"""
        for attempt in range(RETRY_ATTEMPTS):
            try:
                # Wait for rate limit capacity
                self.rate_limiter.wait_for_capacity()
                
                # Make the request
                response = self.client.post(
                    "/chat/completions",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 1000
                    }
                )
                
                # Record the request
                self.rate_limiter.add_request()
                
                if response.status_code == 429:  # Rate limit exceeded
                    wait_time = int(response.headers.get('Retry-After', RETRY_DELAY))
                    logging.warning("Rate limit exceeded. Waiting %d seconds", wait_time)
                    time.sleep(wait_time)
                    continue
                
                response.raise_for_status()
                result = response.json()
                return result['choices'][0]['message']['content']
                
            except httpx.HTTPStatusError as e:
                logging.error("HTTP error occurred: %s", str(e))
                if attempt < RETRY_ATTEMPTS - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))  # Exponential backoff
                    continue
                raise
            except httpx.ReadTimeout:
                logging.error("Request timed out")
                if attempt < RETRY_ATTEMPTS - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                raise
            except Exception as e:
                logging.error("Error making API request: %s", str(e))
                if attempt < RETRY_ATTEMPTS - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                raise

    def chat(self, message: str) -> str:
        """Process a message using the XAI API"""
        try:
            # Input validation
            if not message or not message.strip():
                return "Message cannot be empty"
            
            # Prepare the conversation history
            messages = [
                {"role": msg.role, "content": msg.content}
                for msg in self.memory.messages
            ]
            messages.append({"role": "user", "content": message})
            
            # Make API request
            assistant_message = self._make_api_request(messages)
            
            # Update memory
            self.memory.messages.append(Message(role="user", content=message))
            self.memory.messages.append(Message(role="assistant", content=assistant_message))
            self._save_memory()
            
            return assistant_message
            
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logging.error(error_msg)
            return error_msg

    def get_chat_history(self) -> List[Dict]:
        """Get formatted chat history"""
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat()
            }
            for msg in self.memory.messages
        ]

def safe_input(prompt: str = "") -> str:
    """Safe input handling with EOF protection"""
    try:
        # Flush any pending output
        sys.stdout.flush()
        
        # Try to read input
        line = input(prompt)
        
        # Check if input is actually valid
        if not line and sys.stdin.isatty():
            raise EOFError("Empty input received")
        
        return line.strip()
    except EOFError:
        raise  # Re-raise EOFError for proper handling
    except Exception as e:
        logging.error("Input error: %s", str(e))
        raise

def main():
    """Main chat interface with enhanced error handling"""
    print("Starting XAI Persistent Chat...")
    print("Type 'exit' or 'quit' to end the conversation")
    print("Type 'history' to view chat history")
    print("-" * 50)
    
    # Check if running in interactive mode
    if not sys.stdin.isatty():
        logging.error("Script must be run in interactive mode")
        print("Error: This script must be run in an interactive terminal")
        return
    
    chat = PersistentChat()
    eof_count = 0
    max_eof_errors = 5
    
    while True:
        try:
            user_input = safe_input("\nYou: ")
            eof_count = 0  # Reset EOF counter on successful input
            
            if user_input.lower() in ['exit', 'quit']:
                print("\nGoodbye!")
                break
            
            if user_input.lower() == 'history':
                history = chat.get_chat_history()
                print("\nChat History:")
                for msg in history:
                    print(f"{msg['timestamp']} - {msg['role']}: {msg['content']}")
                continue
            
            if not user_input:
                continue
            
            response = chat.chat(user_input)
            print(f"\nAssistant: {response}")
            
        except EOFError:
            eof_count += 1
            logging.error("EOF Error encountered (%d/%d)", eof_count, max_eof_errors)
            if eof_count >= max_eof_errors:
                logging.critical("Maximum EOF errors reached. Exiting.")
                print("\nError: Too many EOF errors encountered. Please check the debug log.")
                print("Try running the script in a different terminal or IDE.")
                break
            # Small delay before retrying
            time.sleep(0.1)
            continue
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
            
        except Exception as e:
            logging.error("Unexpected error: %s", str(e))
            print(f"\nError: {str(e)}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.critical("Fatal error: %s", str(e))
        sys.exit(1)
    finally:
        # Cleanup
        if 'chat' in locals():
            chat.client.close()
