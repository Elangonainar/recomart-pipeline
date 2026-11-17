FROM python:3.10-slim

WORKDIR /app

# Install system dependencies & SQLite CLI
RUN apt-get update && apt-get install -y --no-install-recommends     build-essential     sqlite3     git     && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files into container
COPY . .

# Set environment variables
ENV AIRFLOW__CORE__LOAD_EXAMPLES=False
ENV AIRFLOW_HOME=/app/airflow

# Make entrypoint script executable
RUN chmod +x entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["./entrypoint.sh"]
