@echo off
echo 🐳 Building Docker container for Gary Stock Analysis...

REM Build the Docker image
docker build -t gary-stock-analysis .

echo 🚀 Running stock analysis in Docker with Plotly + ORCA...

REM Run the container with environment variables
docker run --rm ^
  -v "%cd%\output:/app/output" ^
  -e TELEGRAM_BOT_TOKEN=8324596740:AAH7j1rsRUddl0J-81vdeXoVFL666Y4MRYU ^
  -e TELEGRAM_CHAT_ID=1051226560 ^
  gary-stock-analysis

echo ✅ Docker analysis complete!
echo 📊 Check the output directory for generated images
pause 