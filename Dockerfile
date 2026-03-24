FROM python:3.13-alpine

WORKDIR /app

# Install docker CLI for container signaling
RUN apk add --no-cache docker-cli

COPY . .
RUN pip install --no-cache-dir .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["dmarcmsp", "serve"]
