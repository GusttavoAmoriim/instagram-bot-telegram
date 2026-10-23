FROM python:3.11-slim

# Instala o ffmpeg e dependências essenciais do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instala as dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia os ficheiros do projeto
COPY . .

# Comando de arranque
CMD ["python", "main.py"]
