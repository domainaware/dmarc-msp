FROM alpine:3

RUN apk add --no-cache postfix gettext ca-certificates && \
    adduser -D -h /var/mail/dmarc -u 1000 -s /sbin/nologin dmarc && \
    mkdir -p /var/mail/dmarc/Maildir/new \
             /var/mail/dmarc/Maildir/cur \
             /var/mail/dmarc/Maildir/tmp && \
    chown -R dmarc:dmarc /var/mail/dmarc

COPY main.cf.template /etc/postfix/main.cf.template
COPY master.cf /etc/postfix/master.cf
RUN chmod 644 /etc/postfix/main.cf.template /etc/postfix/master.cf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 25 587

ENTRYPOINT ["/entrypoint.sh"]
