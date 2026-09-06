FROM docker:cli

RUN apk add --no-cache python3

WORKDIR /app
COPY scaler.py .

CMD ["python3", "scaler.py"]
