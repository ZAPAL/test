FROM python:3.10-slim

# Установка ffmpeg для обработки голоса
RUN apt-get update && apt-get install -y ffmpeg

# Создаем пользователя, так как HF не любит root
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:${PATH}"

WORKDIR /app
COPY --chown=user . .

RUN pip install --no-cache-dir -r requirements.txt

# Запуск бота
CMD ["python", "main.py"]
