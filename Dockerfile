FROM python:3.13-alpine

WORKDIR /app

# Install docker CLI for container signaling and build deps for any C extensions
RUN apk add --no-cache docker-cli

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .
RUN pip install --no-cache-dir -e .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["dmarcmsp", "serve"]
