from typing import Dict, List, Optional
import json
import time
import logging
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from openai import OpenAI
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
XAI_API_KEY = "xai-0DFdM4PCQmUb9yXEMepx0L1j8bF5CBZ8no3JGG2jqiO6r3XH31HnnZfW0i8mwpNK7r9esnPis17bnsCd" #Never change this! Confirmed Working
XAI_BASE_URL = "https://api.x.ai/v1" #Never change this! Confirmed Working
XAI_MODEL = "grok-beta"  #Never change this! Confirmed Working

class PersonaConfig(BaseModel):
    """Validation model for the persona configuration"""
    name: str
    age: int
    base_description: str
    personality_traits: List[str]
    user_context: Dict[str, str]
    interaction_guidelines: List[str]
    reminder: str

def load_system_message(reload: bool = False) -> str:
    """Load and format the system message from the persona configuration file
    
    Args:
        reload (bool): If True, forces reload of the persona file even if cached
    """
    global SYSTEM_MESSAGE
    
    try:
        # Use absolute path based on script location
        script_dir = Path(__file__).parent
        persona_path = script_dir / "ai_persona.json"
        
        if not persona_path.exists():
            raise FileNotFoundError(f"Persona file not found: {persona_path}")
            
        with open(persona_path, "r", encoding="utf-8") as f:
            persona_data = json.load(f)
        
        # Validate persona data
        try:
            persona = PersonaConfig(**persona_data)
        except Exception as e:
            logging.error(f"Invalid persona configuration: {str(e)}")
            raise ValueError("Persona configuration is invalid") from e
        
        # Format the system message from the validated persona data
        system_message = f"""You are {persona.name}, {persona.base_description}

Personality Traits:
{chr(10).join(f"- {trait}" for trait in persona.personality_traits)}

Context: Chatting with {persona.user_context['name']} ({persona.user_context['location']}) who needs {persona.user_context['needs']}.

You should:
{chr(10).join(f"{i+1}. {guideline}" for i, guideline in enumerate(persona.interaction_guidelines))}

Remember: {persona.reminder}"""
        
        return system_message
        
    except Exception as e:
        error_msg = f"Error loading persona configuration: {str(e)}"
        logging.error(error_msg)
        # Return a basic system message as fallback
        return """You are Grok, a helpful AI assistant. Be direct, honest, and factual while maintaining a sense of humor."""

def reload_persona() -> str:
    """Reload the persona configuration and return the new system message"""
    global SYSTEM_MESSAGE
    SYSTEM_MESSAGE = load_system_message(reload=True)
    return SYSTEM_MESSAGE

# Default system message for the LLM
SYSTEM_MESSAGE = load_system_message()

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
    def __init__(self, model: str = XAI_MODEL, memory_file: str = "chat_memory.json"):
        self.model = model
        self.memory_file = Path(memory_file)
        self.memory = self._load_memory()
        self.rate_limiter = RateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW)
        
        # Use OpenAI client with X.AI base URL
        self.client = OpenAI(
            api_key=XAI_API_KEY,
            base_url=XAI_BASE_URL
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
                
                # Log request details
                logging.debug("Making API request with model: %s, messages: %s", self.model, messages)
                
                # Make the request using the OpenAI client
                completion = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages
                )
                
                # Record the request
                self.rate_limiter.add_request()
                
                # Return the response content
                return completion.choices[0].message.content
                
            except Exception as e:
                error_msg = f"Error making API request: {str(e)}"
                logging.error(error_msg)
                if attempt < RETRY_ATTEMPTS - 1:
                    logging.info("Retrying request (attempt %d/%d)", attempt + 1, RETRY_ATTEMPTS)
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                raise ValueError(error_msg)

    def chat(self, message: str) -> str:
        """Process a message using the XAI API"""
        try:
            # Input validation
            if not message or not message.strip():
                return "Message cannot be empty"
            
            # Prepare the conversation history with system message
            messages = [{"role": "system", "content": SYSTEM_MESSAGE}]
            messages.extend([
                {"role": msg.role, "content": msg.content}
                for msg in self.memory.messages
                if msg.role != "system"  # Skip any stored system messages
            ])
            messages.append({"role": "user", "content": message})
            
            # Make API request
            assistant_message = self._make_api_request(messages)
            
            # Update memory (excluding system message)
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
            pass
