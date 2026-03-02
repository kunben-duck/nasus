FROM nginx:1.27-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY pages /usr/share/nginx/html/pages
COPY shared /usr/share/nginx/html/shared

EXPOSE 80
