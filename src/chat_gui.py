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
from tkinter import colorchooser
import os
import sys
import re

class ErrorMonitor:
    """Monitors and tracks application errors"""
    def __init__(self):
        self.error_count = 0
        self.recent_errors = []
        self.MAX_RECENT_ERRORS = 10

    def log_error(self, error_msg, exc_info=None, source=None):
        """Log an error and keep track of it"""
        self.error_count += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_entry = {
            'timestamp': timestamp,
            'message': str(error_msg),
            'source': source or 'Unknown',
            'traceback': None
        }
        
        if exc_info:
            import traceback
            error_entry['traceback'] = ''.join(traceback.format_exception(*exc_info))
        
        self.recent_errors.append(error_entry)
        if len(self.recent_errors) > self.MAX_RECENT_ERRORS:
            self.recent_errors.pop(0)
        
        # Log to file
        logging.error(
            "[%s] %s - %s%s",
            source or 'Unknown',
            error_msg,
            f"\nTraceback:\n{error_entry['traceback']}" if error_entry['traceback'] else "",
            f"\nTotal Errors: {self.error_count}"
        )

    def get_error_summary(self):
        """Get a summary of recent errors"""
        return {
            'total_errors': self.error_count,
            'recent_errors': self.recent_errors
        }

class ChatGUI:
    # Default color scheme
    DEFAULT_COLORS = {
        "DARK_BG": "#1E1E1E",
        "DARKER_BG": "#252526",
        "INPUT_BG": "#2D2D2D",
        "TEXT_COLOR": "#D4D4D4",
        "BUTTON_BG": "#333333",
        "BUTTON_ACTIVE": "#404040",
        "ACCENT": "#007ACC",
        "USER_MSG_BG": "#333333",
        "AI_MSG_BG": "#2D2D2D",
        "TIMESTAMP_COLOR": "#666666"
    }
    
    def __init__(self):
        # Initialize error monitor
        self.error_monitor = ErrorMonitor()
        
        # Load or create settings
        self.colors = self._load_color_settings()
        self.text_settings = {
            "paragraph_indent": 0,
            "first_line_indent": 0,
            "line_spacing": 1.2,
            "text_align": "left",
            "font_family": "Segoe UI",
            "font_size": "12",
            "message_spacing": 10
        }
        
        # Store last AI message for copy functionality
        self.last_ai_message = ""
        
        # Initialize chat backend first to get persona name
        try:
            self.system_message = load_system_message()
            self.chat = PersistentChat()
            # Extract persona name from system message
            match = re.search(r"You are ([^,]+)", self.system_message)
            if match:
                self.current_persona_name = match.group(1).strip()
            else:
                self.current_persona_name = "AI"
        except Exception as e:
            self.current_persona_name = "AI"
            logging.error(f"Error initializing chat: {str(e)}")
        
        # Create themed root window
        self.root = ThemedTk(theme="equilux")
        self.root.title(self.current_persona_name)
        
        # Message queue and state tracking
        self.msg_queue = Queue()
        self.is_processing = False
        self.should_autoscroll = True
        self.chat_history = []
        
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
        """Create and configure all GUI widgets"""
        # Create main container
        main_container = ttk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Create HTML display with embedded CSS for emoji support
        initial_html = """
        <style>
            * { font-family: 'Segoe UI', 'Segoe UI Emoji', 'Segoe UI Symbol', 'Noto Color Emoji', Arial; }
            .emoji { color: initial !important; }
            .message-content { white-space: pre-wrap; }
        </style>
        <div id="chat-container"></div>
        """
        
        self.chat_display = HTMLLabel(
            main_container,
            background=self.colors["DARK_BG"],
            foreground=self.colors["TEXT_COLOR"],
            html=initial_html
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.chat_display.fit_height = False
        
        # Menu bar
        self.menubar = tk.Menu(self.root)
        self.root.config(menu=self.menubar)
        
        # Settings menu
        self.settings_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Settings", menu=self.settings_menu)
        self.settings_menu.add_command(label="Customize Colors", command=self._show_color_dialog)
        self.settings_menu.add_command(label="Text Formatting", command=self._show_format_dialog)
        self.settings_menu.add_command(label="Reset Colors", command=self._reset_colors)
        
        # Bottom frame for input and buttons
        self.bottom_frame = ttk.Frame(main_container)
        self.bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        # Input area
        self.input_frame = ttk.Frame(self.bottom_frame)
        self.input_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.input_area = scrolledtext.ScrolledText(
            self.input_frame,
            height=3,
            bg=self.colors["INPUT_BG"],
            fg=self.colors["TEXT_COLOR"],
            insertbackground=self.colors["TEXT_COLOR"],
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
            command=self._copy_last_ai_message,
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
            background=self.colors["BUTTON_BG"],
            foreground=self.colors["TEXT_COLOR"],
            padding=5
        )
        
        style.configure(
            "Accent.TButton",
            background=self.colors["ACCENT"],
            foreground=self.colors["TEXT_COLOR"],
            padding=5
        )
        
        style.map("TButton",
            background=[("active", self.colors["BUTTON_ACTIVE"])],
            foreground=[("active", self.colors["TEXT_COLOR"])]
        )
        
        style.map("Accent.TButton",
            background=[("active", self.colors["ACCENT"])],
            foreground=[("active", self.colors["TEXT_COLOR"])]
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
            # Use a slightly more forgiving threshold
            is_at_bottom = current_pos >= 0.95
            if is_at_bottom:
                self.should_autoscroll = True
            return is_at_bottom
        except Exception as e:
            logging.error("[chat_gui.py] Error checking scroll position: %s", str(e), exc_info=True)
            return False  # Default to not auto-scrolling on error
            
    def process_messages(self):
        """Process messages from the queue and update the chat display"""
        try:
            messages_processed = False
            while not messages_processed:
                try:
                    message_html = self.msg_queue.get_nowait()
                    
                    # Build complete chat history
                    full_html = f'''
                    <div style="font-family: Segoe UI Emoji, Segoe UI Symbol, Noto Color Emoji, Arial;">
                        <div>Welcome to X.AI Persistent Chat!</div>
                        {"".join(msg["html"] for msg in self.chat_history)}
                    </div>
                    '''
                    
                    self.chat_display.set_html(full_html)
                    self.msg_queue.task_done()
                    
                    # Only auto-scroll if we should
                    if self.should_autoscroll:
                        self.chat_display.update()
                        self.chat_display.yview_moveto(1.0)
                except Empty:
                    messages_processed = True
                except Exception as e:
                    self.error_monitor.log_error(
                        f"Error processing message: {str(e)}",
                        exc_info=sys.exc_info(),
                        source="chat_gui.py"
                    )
                    messagebox.showerror("Error", "Failed to process message. Check the logs for details.")
                    messages_processed = True
        except Exception as e:
            self.error_monitor.log_error(
                f"Critical error in message processing loop: {str(e)}",
                exc_info=sys.exc_info(),
                source="chat_gui.py"
            )
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
        """Process a message using the chat backend"""
        try:
            response = self.chat.chat(message)
            self._add_message("AI", response)
        except ConnectionError as e:
            self.error_monitor.log_error(
                f"Network error while processing message: {str(e)}",
                exc_info=sys.exc_info(),
                source="chat_gui.py"
            )
            error_msg = "Sorry, I encountered a network error. Please check your connection and try again."
            self._add_message("AI", error_msg)
        except Exception as e:
            self.error_monitor.log_error(
                f"Error processing message through chat backend: {str(e)}",
                exc_info=sys.exc_info(),
                source="chat_gui.py"
            )
            error_msg = f"Sorry, I encountered an error: {str(e)}. Please try again."
            self._add_message("AI", error_msg)
        finally:
            # Reset processing state
            self.is_processing = False
            self.root.after(0, self._update_processing_state)
            
    def _add_message(self, sender, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Update last AI message for copy functionality and handle persona name
        if sender == "AI":
            self.last_ai_message = message
            sender = self.current_persona_name
            # Update window title
            self.root.title(self.current_persona_name)
        
        # Calculate spacings
        message_spacing = int(self.text_settings['message_spacing'])
        line_spacing = max(1.0, float(self.text_settings['line_spacing']))
        
        # Process emojis in message
        def process_emojis(text):
            return re.sub(
                r'([\U0001F300-\U0001F9FF]|[\u2600-\u26FF]|[\u2700-\u27BF])',
                r'<span class="emoji">\1</span>',
                text
            )
        
        # Base styles for the message container
        base_style = f"""
            font-family: 'Segoe UI', 'Segoe UI Emoji', 'Segoe UI Symbol', 'Noto Color Emoji', Arial;
            font-size: {self.text_settings['font_size']}px;
            padding-left: {self.text_settings['paragraph_indent']}px;
            text-indent: {self.text_settings['first_line_indent']}px;
            text-align: {self.text_settings['text_align']};
            margin-bottom: {message_spacing}px;
        """
        
        # Content specific style with explicit line height
        content_style = f"line-height: {line_spacing}em !important;"
        
        if sender == self.current_persona_name:
            # Process markdown and emojis for AI messages
            processed_message = process_emojis(markdown.markdown(message))
            
            message_html = f"""
                <div class="message ai-message" style="{base_style} padding: 10px; background-color: {self.colors['AI_MSG_BG']}; border-left: 3px solid {self.colors['ACCENT']};">
                    <div class="timestamp" style="color: {self.colors['TIMESTAMP_COLOR']}; font-size: 0.8em;">{timestamp}</div>
                    <div class="sender" style="color: {self.colors['ACCENT']}; font-weight: bold;">{sender}</div>
                    <div class="message-content" style="{content_style} margin-top: 5px; color: {self.colors['TEXT_COLOR']}; white-space: pre-wrap;">{processed_message}</div>
                </div>
            """
        else:
            # Process emojis for user messages
            processed_message = process_emojis(message)
            
            message_html = f"""
                <div class="message user-message" style="{base_style} padding: 10px; background-color: {self.colors['USER_MSG_BG']};">
                    <div class="timestamp" style="color: {self.colors['TIMESTAMP_COLOR']}; font-size: 0.8em;">{timestamp}</div>
                    <div class="sender" style="color: {self.colors['TEXT_COLOR']}; font-weight: bold;">{sender}</div>
                    <div class="message-content" style="{content_style} margin-top: 5px; color: {self.colors['TEXT_COLOR']}; white-space: pre-wrap;">{processed_message}</div>
                </div>
            """
        
        # Store both the message data and HTML representation
        message_obj = {
            "data": {
                "sender": sender,
                "message": message,
                "timestamp": timestamp
            },
            "html": message_html
        }
        
        # Store message for history
        self.chat_history.append(message_obj)
        
        # Add to message queue for display
        self.msg_queue.put(message_html)

    def _on_closing(self):
        """Handle window closing"""
        try:
            if hasattr(self, 'chat'):
                # Clean up chat resources if needed
                pass
                
            # Log error summary before closing
            error_summary = self.error_monitor.get_error_summary()
            if error_summary['total_errors'] > 0:
                logging.warning(
                    "Session ended with %d total errors. Recent errors:\n%s",
                    error_summary['total_errors'],
                    json.dumps(error_summary['recent_errors'], indent=2)
                )
        except Exception as e:
            self.error_monitor.log_error(
                f"Error during cleanup: {str(e)}",
                exc_info=sys.exc_info(),
                source="chat_gui.py"
            )
        finally:
            self.root.destroy()
            
    def _copy_last_ai_message(self):
        """Copy the last AI message to clipboard"""
        if self.last_ai_message:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.last_ai_message)
            self.root.update()  # Required for clipboard to work

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
        
    def _show_color_dialog(self):
        """Show color customization dialog"""
        color_dialog = tk.Toplevel(self.root)
        color_dialog.title("Color Settings")
        color_dialog.transient(self.root)
        
        # Set initial minimum size
        color_dialog.minsize(400, 300)
        
        # Create main frame with padding
        main_frame = ttk.Frame(color_dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create scrollable frame
        canvas = tk.Canvas(main_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        # Create a frame inside canvas to control the minimum width
        min_width_frame = ttk.Frame(canvas, width=380)
        min_width_frame.pack(fill=tk.X)
        min_width_frame.pack_propagate(False)
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=canvas.winfo_reqwidth())
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Color picker buttons
        for color_key in self.colors.keys():
            frame = ttk.Frame(scrollable_frame)
            frame.pack(fill="x", padx=5, pady=2)
            
            label = ttk.Label(frame, text=color_key.replace("_", " ").title())
            label.pack(side="left", padx=5)
            
            color_preview = tk.Label(frame, bg=self.colors[color_key], width=8)
            color_preview.pack(side="right", padx=5)
            
            button = ttk.Button(
                frame, 
                text="Choose", 
                command=lambda k=color_key, p=color_preview: self._pick_color(k, p)
            )
            button.pack(side="right", padx=5)
        
        # Apply and Cancel buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side="bottom", fill="x", pady=(10, 0))
        
        apply_btn = ttk.Button(
            button_frame, 
            text="Apply", 
            command=lambda: self._apply_colors(color_dialog)
        )
        apply_btn.pack(side="right", padx=5)
        
        cancel_btn = ttk.Button(
            button_frame, 
            text="Cancel", 
            command=color_dialog.destroy
        )
        cancel_btn.pack(side="right", padx=5)
        
        # Pack canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Make dialog modal
        color_dialog.grab_set()
        color_dialog.focus_set()

    def _pick_color(self, color_key, preview_label):
        """Open color picker for specific color setting"""
        color = colorchooser.askcolor(color=self.colors[color_key], title=f"Choose {color_key}")
        if color[1]:  # If color was picked (not cancelled)
            self.colors[color_key] = color[1]
            preview_label.configure(bg=color[1])

    def _apply_colors(self, dialog):
        """Apply color changes and save settings"""
        self._save_color_settings()
        self._update_colors()
        dialog.destroy()

    def _reset_colors(self):
        """Reset colors to default"""
        self.colors = self.DEFAULT_COLORS.copy()
        self._save_color_settings()
        self._update_colors()

    def _update_colors(self):
        """Update UI with current colors"""
        self.root.configure(bg=self.colors["DARK_BG"])
        self.chat_display.configure(background=self.colors["DARK_BG"])
        self.input_area.configure(
            bg=self.colors["INPUT_BG"],
            fg=self.colors["TEXT_COLOR"],
            insertbackground=self.colors["TEXT_COLOR"]
        )
        self._configure_styles()
        self._refresh_messages()

    def _load_color_settings(self):
        """Load color settings from file"""
        try:
            settings_path = os.path.join(os.path.dirname(__file__), "color_settings.json")
            if os.path.exists(settings_path):
                with open(settings_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logging.error("Error loading color settings: %s", str(e))
        return self.DEFAULT_COLORS.copy()

    def _save_color_settings(self):
        """Save color settings to file"""
        try:
            settings_path = os.path.join(os.path.dirname(__file__), "color_settings.json")
            with open(settings_path, 'w') as f:
                json.dump(self.colors, f, indent=4)
        except Exception as e:
            logging.error("Error saving color settings: %s", str(e))

    def _refresh_messages(self):
        """Refresh all messages with new colors"""
        current_messages = self.chat_history.copy()
        self.chat_history = []
        self.chat_display.set_html("")
        for msg in current_messages:
            self._add_message(msg["data"]["sender"], msg["data"]["message"])

    def _show_format_dialog(self):
        """Show text formatting dialog"""
        format_dialog = tk.Toplevel(self.root)
        format_dialog.title("Text Formatting")
        format_dialog.transient(self.root)
        
        # Set initial minimum size
        format_dialog.minsize(500, 400)
        
        # Create main frame with padding
        main_frame = ttk.Frame(format_dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Indentation settings
        indent_frame = ttk.LabelFrame(main_frame, text="Indentation", padding="5")
        indent_frame.pack(fill="x", pady=(0, 10))
        
        # Paragraph indent
        para_frame = ttk.Frame(indent_frame)
        para_frame.pack(fill="x", pady=2)
        ttk.Label(para_frame, text="Paragraph Indent:").pack(side="left", padx=5)
        para_indent = ttk.Scale(
            para_frame,
            from_=0,
            to=50,
            orient="horizontal",
            value=self.text_settings["paragraph_indent"]
        )
        para_indent.pack(side="left", fill="x", expand=True, padx=5)
        
        # First line indent
        first_frame = ttk.Frame(indent_frame)
        first_frame.pack(fill="x", pady=2)
        ttk.Label(first_frame, text="First Line Indent:").pack(side="left", padx=5)
        first_indent = ttk.Scale(
            first_frame,
            from_=0,
            to=50,
            orient="horizontal",
            value=self.text_settings["first_line_indent"]
        )
        first_indent.pack(side="left", fill="x", expand=True, padx=5)
        
        # Spacing settings
        spacing_frame = ttk.LabelFrame(main_frame, text="Spacing", padding="5")
        spacing_frame.pack(fill="x", pady=(0, 10))
        
        # Line spacing
        line_frame = ttk.Frame(spacing_frame)
        line_frame.pack(fill="x", pady=2)
        ttk.Label(line_frame, text="Line Height:").pack(side="left", padx=5)
        line_spacing = ttk.Scale(
            line_frame,
            from_=1.0,
            to=2.0,
            orient="horizontal",
            value=self.text_settings["line_spacing"]
        )
        line_spacing.pack(side="left", fill="x", expand=True, padx=5)
        
        # Message spacing
        msg_frame = ttk.Frame(spacing_frame)
        msg_frame.pack(fill="x", pady=2)
        ttk.Label(msg_frame, text="Message Spacing:").pack(side="left", padx=5)
        message_spacing = ttk.Scale(
            msg_frame,
            from_=5,
            to=30,
            orient="horizontal",
            value=self.text_settings["message_spacing"]
        )
        message_spacing.pack(side="left", fill="x", expand=True, padx=5)
        
        # Text alignment
        align_frame = ttk.LabelFrame(main_frame, text="Text Alignment", padding="5")
        align_frame.pack(fill="x", pady=(0, 10))
        
        alignment = tk.StringVar(value=self.text_settings["text_align"])
        for align in ["left", "center", "right"]:
            ttk.Radiobutton(
                align_frame,
                text=align.title(),
                value=align,
                variable=alignment
            ).pack(side="left", padx=10)
        
        # Font settings
        font_frame = ttk.LabelFrame(main_frame, text="Font Settings", padding="5")
        font_frame.pack(fill="x", pady=(0, 10))
        
        # Font family
        ttk.Label(font_frame, text="Font:").pack(side="left", padx=5)
        font_family = ttk.Combobox(
            font_frame,
            values=sorted(font.families()),
            width=20
        )
        font_family.set(self.text_settings["font_family"])
        font_family.pack(side="left", padx=5)
        
        # Font size
        ttk.Label(font_frame, text="Size:").pack(side="left", padx=5)
        font_size = ttk.Spinbox(
            font_frame,
            from_=8,
            to=24,
            width=5
        )
        font_size.set(self.text_settings["font_size"])
        font_size.pack(side="left", padx=5)
        
        # Preview
        preview_frame = ttk.LabelFrame(main_frame, text="Preview", padding="5")
        preview_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        preview_text = HTMLLabel(
            preview_frame,
            html=self._format_preview_text(),
            background=self.colors["DARK_BG"],
            foreground=self.colors["TEXT_COLOR"]
        )
        preview_text.pack(fill="both", expand=True, padx=5, pady=5)
        
        def update_preview(*args):
            self.text_settings.update({
                "paragraph_indent": int(para_indent.get()),
                "first_line_indent": int(first_indent.get()),
                "line_spacing": float(line_spacing.get()),
                "text_align": alignment.get(),
                "font_family": font_family.get(),
                "font_size": font_size.get(),
                "message_spacing": int(message_spacing.get())
            })
            preview_text.set_html(self._format_preview_text())
        
        # Bind updates to all controls
        para_indent.configure(command=update_preview)
        first_indent.configure(command=update_preview)
        line_spacing.configure(command=update_preview)
        alignment.trace_add("write", update_preview)
        font_family.bind("<<ComboboxSelected>>", update_preview)
        font_size.bind("<Return>", update_preview)
        font_size.bind("<FocusOut>", update_preview)
        message_spacing.configure(command=update_preview)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill="x", pady=(0, 5))
        
        ttk.Button(
            button_frame,
            text="Apply",
            command=lambda: self._apply_format_settings(format_dialog)
        ).pack(side="right", padx=5)
        
        ttk.Button(
            button_frame,
            text="Cancel",
            command=format_dialog.destroy
        ).pack(side="right", padx=5)
        
        # Set dialog size based on content
        format_dialog.update_idletasks()
        width = main_frame.winfo_reqwidth() + 40
        height = main_frame.winfo_reqheight() + 40
        x = format_dialog.winfo_screenwidth()//2 - width//2
        y = format_dialog.winfo_screenheight()//2 - height//2
        format_dialog.geometry(f"{width}x{height}+{x}+{y}")
        
        format_dialog.grab_set()
        format_dialog.focus_set()

    def _format_preview_text(self):
        """Generate preview text with current formatting"""
        line_height = max(1.0, float(self.text_settings['line_spacing']))
        
        return f"""
        <div class="preview-text" style="
            font-family: {self.text_settings['font_family']}, 'Segoe UI Emoji', 'Segoe UI Symbol', 'Noto Color Emoji', Arial;
            font-size: {self.text_settings['font_size']}px;
            line-height: {line_height}em;
            text-align: {self.text_settings['text_align']};
            padding-left: {self.text_settings['paragraph_indent']}px;
            text-indent: {self.text_settings['first_line_indent']}px;
            white-space: pre-wrap;
            color: {self.colors['TEXT_COLOR']};
            background-color: {self.colors['USER_MSG_BG']};
            padding: 10px;">
            The line spacing is set to {line_height} em.

            This is a preview of how your text will look.
                        
            Multiple paragraphs will show the spacing effect.
            Each line should be properly spaced.
            
            Emojis should render in color: 😊 🌟 💡
            
            Indentation and alignment are also visible here.
        </div>
        """

    def _apply_format_settings(self, dialog):
        """Apply text formatting settings and close dialog"""
        self._refresh_messages()  # Refresh all messages with new formatting
        dialog.destroy()

    def run(self):
        """Start the GUI event loop"""
        self.root.mainloop()

if __name__ == "__main__":
    # Create and run the GUI
    gui = ChatGUI()
    gui.run()
