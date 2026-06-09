FROM python:3.11-slim

WORKDIR /app
ENV MATAROA_BOT_DIR=/app/.state
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system mataroa && adduser --system --ingroup mataroa --home /app mataroa

# Copy the bot code into the container
COPY --chown=mataroa:mataroa mataroa.py handlers.py constants.py storage.py ./

RUN mkdir -p /app/.state && chown mataroa:mataroa /app/.state && chmod 700 /app/.state

USER mataroa

CMD [ "python", "mataroa.py" ]
