FROM python:3.11-slim

WORKDIR /app
ENV MATAROA_BOT_DIR=/app

# Install dependencies
RUN apt-get update && \
    apt-get install -y gcc libffi-dev libnacl-dev libssl-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot code into the container
COPY mataroa.py .

CMD [ "python", "mataroa.py" ]
