FROM nginx:alpine

COPY nginx.conf.template /etc/nginx/nginx.conf.template
COPY nginx-http-only.conf.template /etc/nginx/nginx-http-only.conf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80 443

ENTRYPOINT ["/entrypoint.sh"]
