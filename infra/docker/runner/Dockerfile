FROM mcr.microsoft.com/playwright:v1.58.2-noble

ENV NODE_ENV=production

WORKDIR /app

COPY apps/runner/package*.json ./
RUN npm install --omit=dev --ignore-scripts \
    && npm cache clean --force

COPY apps/runner/src ./src

RUN chown -R pwuser:pwuser /app
USER pwuser

EXPOSE 8090

CMD ["node", "src/server.mjs"]
