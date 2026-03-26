FROM nginx:alpine

COPY nginx.conf.template /etc/nginx/nginx.conf.template
COPY nginx-http-only.conf.template /etc/nginx/nginx-http-only.conf.template
COPY mta-sts.conf.template /etc/nginx/mta-sts.conf.template
COPY mta-sts-http-only.conf.template /etc/nginx/mta-sts-http-only.conf.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80 443

ENTRYPOINT ["/entrypoint.sh"]
