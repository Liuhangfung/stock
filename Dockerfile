# Docker with Plotly image generation using kaleido
FROM python:3.9

WORKDIR /app

# Install system dependencies for kaleido
RUN apt-get update && apt-get install -y \
    wget \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages including kaleido
RUN pip install --no-cache-dir \
    pandas==2.1.3 \
    numpy==1.24.3 \
    plotly==5.17.0 \
    requests==2.31.0 \
    openpyxl==3.1.2 \
    kaleido==0.2.1

# Set environment for headless operation
ENV DISPLAY=:99

# Copy application files
COPY . .

# Create startup script with virtual display
RUN echo '#!/bin/bash\n\
Xvfb :99 -screen 0 1920x1080x24 &\n\
sleep 2\n\
export DISPLAY=:99\n\
python hk_stock_analysis_docker.py\n\
' > /app/start.sh && chmod +x /app/start.sh

CMD ["/app/start.sh"] 