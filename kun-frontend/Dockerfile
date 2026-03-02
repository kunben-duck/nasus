FROM nginx:1.27-alpine

RUN apk add --no-cache gettext

ENV PORT=80
ENV API_PROXY_TARGET=http://127.0.0.1:8080

COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY index.html /usr/share/nginx/html/index.html
COPY pages /usr/share/nginx/html/pages
COPY shared /usr/share/nginx/html/shared

EXPOSE 80

CMD ["/bin/sh", "-c", "envsubst '$PORT $API_PROXY_TARGET' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
