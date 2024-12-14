# XAI Persistent Chat

A Python-based chat interface that uses LangGraph for memory management and the XAI API for chat completions. This implementation maintains conversation history across multiple sessions and provides persistent memory storage.

## Features

- Persistent conversation history across sessions
- LangGraph-based memory management
- Integration with XAI API
- Timestamped message tracking
- Metadata support for additional context
- Simple command-line interface

## Installation

### Quick Setup (Windows)

1. Run the setup script to create a virtual environment and install dependencies:
```bash
setup_venv.bat
```

2. The virtual environment will be automatically activated. You can now run the chat interface:
```bash
python persistent_chat.py
```

3. To deactivate the virtual environment when you're done:
```bash
deactivate
```

### Manual Setup

1. Create a virtual environment:
```bash
python -m venv venv
```

2. Activate the virtual environment:
   - Windows:
   ```bash
   venv\Scripts\activate
   ```
   - Unix/MacOS:
   ```bash
   source venv/bin/activate
   ```

3. Install the required dependencies:
```bash
python -m pip install -r requirements.txt
```

4. Run the chat interface:
```bash
python persistent_chat.py
```

## Usage

The chat interface provides a simple command-line interface. Type your messages and press Enter to send them. Type 'exit' or 'quit' to end the conversation.

All conversations are automatically saved to `chat_memory.json` in the current directory. This file maintains the conversation history across multiple sessions.

## Configuration

- `model`: The XAI model to use (default: "grok-1")
- `memory_file`: The file to store conversation history (default: "chat_memory.json")
- API settings can be configured in the `persistent_chat.py` file

## Dependencies

- httpx: For making HTTP requests to the XAI API
- pydantic: For data validation and settings management
- langgraph: For conversation memory management

## System Notes

- **Drive Configuration**: This script was originally developed on a Windows 10 system where the root system exists on the `G:` drive instead of the typical `C:` drive. Some elements of the script may need adjustment when running on systems with different drive configurations.
