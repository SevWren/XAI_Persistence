@echo off
echo Creating Python virtual environment...
python -m venv venv

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing dependencies...
python -m pip install -r requirements.txt

echo Setup complete! You can now run the chat interface using:
echo python persistent_chat.py
echo.
echo To deactivate the virtual environment, type: deactivate
