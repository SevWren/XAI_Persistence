import tkinter as tk
from tkinter import ttk, scrolledtext, font, messagebox
from ttkthemes import ThemedTk
import json
from pathlib import Path
import threading
from queue import Queue, Empty
import pyperclip
from datetime import datetime
import markdown
from tkhtmlview import HTMLLabel
from persistent_chat import PersistentChat, load_system_message
import logging

class ChatGUI:
    # Color scheme
    DARK_BG = "#1E1E1E"
    DARKER_BG = "#252526"
    ACCENT = "#007ACC"
    TEXT_COLOR = "#D4D4D4"
    INPUT_BG = "#2D2D2D"
    BUTTON_BG = "#333333"
    BUTTON_ACTIVE = "#404040"
    
    def __init__(self):
        # Create themed root window
        self.root = ThemedTk(theme="equilux")
        self.root.title("X.AI Persistent Chat")
        self.root.configure(bg=self.DARK_BG)
        
        # Initialize chat backend
        try:
            self.system_message = load_system_message()
            self.chat = PersistentChat()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to initialize chat: {str(e)}")
            self.root.destroy()
            return
        
        # Message queue and state tracking
        self.msg_queue = Queue()
        self.is_processing = False
        self.should_autoscroll = True  # Track if we should auto-scroll
        self.chat_history = []  # Store all messages
        
        # Configure window size and position
        window_width = 1000
        window_height = 800
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        center_x = int(screen_width/2 - window_width/2)
        center_y = int(screen_height/2 - window_height/2)
        self.root.geometry(f'{window_width}x{window_height}+{center_x}+{center_y}')
        
        self._create_widgets()
        self._configure_styles()
        self._setup_bindings()
        
        # Start message processing
        self.process_messages()
        
        # Set up window close handler
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
    def _create_widgets(self):
        # Main container
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Chat display area
        self.chat_frame = ttk.Frame(self.main_frame)
        self.chat_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Create chat display with HTML support
        self.chat_display = HTMLLabel(
            self.chat_frame,
            background=self.DARKER_BG,
            foreground=self.TEXT_COLOR,
            html='<div style="font-family: Segoe UI Emoji, Segoe UI Symbol, Noto Color Emoji, Arial;">Welcome to X.AI Persistent Chat!</div>'
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True)
        
        # Bind scroll events
        self.chat_display.bind('<MouseWheel>', self._on_scroll)
        
        # Bottom frame for input and buttons
        self.bottom_frame = ttk.Frame(self.main_frame)
        self.bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        # Input area
        self.input_frame = ttk.Frame(self.bottom_frame)
        self.input_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.input_area = scrolledtext.ScrolledText(
            self.input_frame,
            height=3,
            bg=self.INPUT_BG,
            fg=self.TEXT_COLOR,
            insertbackground=self.TEXT_COLOR,
            relief=tk.FLAT
        )
        self.input_area.pack(fill=tk.X, expand=True)
        
        # Buttons frame
        self.button_frame = ttk.Frame(self.bottom_frame)
        self.button_frame.pack(fill=tk.X)
        
        # Send button
        self.send_button = ttk.Button(
            self.button_frame,
            text="Send",
            command=self._send_message,
            style="Accent.TButton"
        )
        self.send_button.pack(side=tk.RIGHT, padx=5)
        
        # Copy button
        self.copy_button = ttk.Button(
            self.button_frame,
            text="Copy Last Response",
            command=self._copy_last_response,
            style="TButton"
        )
        self.copy_button.pack(side=tk.RIGHT, padx=5)
        
        # Clear button
        self.clear_button = ttk.Button(
            self.button_frame,
            text="Clear Chat",
            command=self._clear_chat,
            style="TButton"
        )
        self.clear_button.pack(side=tk.LEFT, padx=5)
        
    def _configure_styles(self):
        style = ttk.Style()
        
        # Configure button styles
        style.configure(
            "TButton",
            background=self.BUTTON_BG,
            foreground=self.TEXT_COLOR,
            padding=5
        )
        
        style.configure(
            "Accent.TButton",
            background=self.ACCENT,
            foreground=self.TEXT_COLOR,
            padding=5
        )
        
        style.map("TButton",
            background=[("active", self.BUTTON_ACTIVE)],
            foreground=[("active", self.TEXT_COLOR)]
        )
        
        style.map("Accent.TButton",
            background=[("active", self.ACCENT)],
            foreground=[("active", self.TEXT_COLOR)]
        )
        
    def _setup_bindings(self):
        # Bind Ctrl+Enter to send
        self.input_area.bind("<Control-Return>", lambda e: self._send_message())
        
        # Bind Ctrl+C to copy selected text
        self.root.bind("<Control-c>", lambda e: self._copy_selected())
        
        # Bind Ctrl+V to paste
        self.root.bind("<Control-v>", lambda e: self._paste_to_input())
        
    def _on_scroll(self, event):
        """Handle scroll events to determine if auto-scroll should be enabled"""
        if event.delta < 0:  # Scrolling down
            # Check if we're at the bottom
            current_pos = self.chat_display.yview()[1]
            if current_pos >= 0.9999:  # Allow small margin of error
                self.should_autoscroll = True
            else:
                self.should_autoscroll = False
        else:  # Scrolling up
            self.should_autoscroll = False
            
    def _check_scroll_position(self):
        """Check if we're at the bottom of the chat"""
        try:
            current_pos = self.chat_display.yview()[1]
            if current_pos >= 0.9999:
                self.should_autoscroll = True
            return current_pos >= 0.9999
        except:
            return True
            
    def process_messages(self):
        """Process messages from the queue and update the chat display"""
        try:
            while True:
                try:
                    message_html = self.msg_queue.get_nowait()
                    
                    # Add to history and rebuild display
                    self.chat_history.append(message_html)
                    
                    # Build complete chat history
                    full_html = f'''
                    <div style="font-family: Segoe UI Emoji, Segoe UI Symbol, Noto Color Emoji, Arial;">
                        <div>Welcome to X.AI Persistent Chat!</div>
                        {"".join(self.chat_history)}
                    </div>
                    '''
                    
                    self.chat_display.set_html(full_html)
                    self.msg_queue.task_done()
                    
                    # Only auto-scroll if we should
                    if self.should_autoscroll:
                        self.chat_display.update()
                        self.chat_display.yview_moveto(1.0)
                except Empty:
                    break
                    
        finally:
            # Schedule next update
            self.root.after(100, self.process_messages)
            
    def _send_message(self):
        if self.is_processing:
            return
            
        message = self.input_area.get("1.0", tk.END).strip()
        if message:
            # Clear input area
            self.input_area.delete("1.0", tk.END)
            
            # Add user message to chat
            self._add_message("User", message)
            
            # Show processing state
            self.is_processing = True
            self._update_processing_state()
            
            # Create a thread for the API call
            thread = threading.Thread(target=self._process_message, args=(message,))
            thread.daemon = True
            thread.start()
            
    def _update_processing_state(self):
        """Update UI elements based on processing state"""
        if self.is_processing:
            self.input_area.config(state='disabled')
            self.send_button.config(state='disabled')
            self.send_button.config(text="Processing...")
        else:
            self.input_area.config(state='normal')
            self.send_button.config(state='normal')
            self.send_button.config(text="Send")
            self.input_area.focus_set()
            
    def _process_message(self, message):
        try:
            # Get response from chat backend
            response = self.chat.chat(message)
            
            # Add AI response to chat
            self.root.after(0, self._add_message, "AI", response)
        except Exception as e:
            # Handle any errors
            error_msg = f"Error: {str(e)}"
            logging.error(f"Message processing error: {str(e)}")
            self.root.after(0, self._add_message, "System", error_msg)
        finally:
            # Reset processing state
            self.is_processing = False
            self.root.after(0, self._update_processing_state)
            
    def _add_message(self, sender, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Convert message to HTML
        if sender == "AI":
            # Preserve emoji characters in markdown conversion
            message_html = f"""
                <div class="message ai-message" style="margin: 10px 0; padding: 10px; background-color: {self.DARKER_BG}; border-left: 3px solid {self.ACCENT};">
                    <div class="timestamp" style="color: #666; font-size: 0.8em;">{timestamp}</div>
                    <div class="sender" style="color: {self.ACCENT}; font-weight: bold;">{sender}</div>
                    <div class="content" style="margin-top: 5px; white-space: pre-wrap;">{markdown.markdown(message)}</div>
                </div>
            """
        else:
            message_html = f"""
                <div class="message user-message" style="margin: 10px 0; padding: 10px; background-color: {self.INPUT_BG};">
                    <div class="timestamp" style="color: #666; font-size: 0.8em;">{timestamp}</div>
                    <div class="sender" style="color: {self.TEXT_COLOR}; font-weight: bold;">{sender}</div>
                    <div class="content" style="margin-top: 5px; white-space: pre-wrap;">{message}</div>
                </div>
            """
        
        # Add to message queue
        self.msg_queue.put(message_html)
        
    def _on_closing(self):
        """Handle window closing"""
        try:
            if hasattr(self, 'chat'):
                # Clean up chat resources if needed
                pass
        finally:
            self.root.destroy()
            
    def _copy_last_response(self):
        # Get the last AI response
        # For now, just copy all text
        text = self.chat_display.get_text()
        if text:
            pyperclip.copy(text)
            
    def _copy_selected(self):
        try:
            selected = self.root.selection_get()
            if selected:
                pyperclip.copy(selected)
        except:
            pass
            
    def _paste_to_input(self):
        try:
            text = pyperclip.paste()
            if text:
                self.input_area.insert(tk.INSERT, text)
        except:
            pass
            
    def _clear_chat(self):
        self.chat_history = []  # Clear history
        self.chat_display.set_html("<div>Chat cleared!</div>")
        
    def run(self):
        """Start the GUI event loop"""
        self.root.mainloop()

if __name__ == "__main__":
    # Create and run the GUI
    gui = ChatGUI()
    gui.run()
