# syntax=docker/dockerfile:1.7
# Multi-stage build for Spring Boot application
FROM maven:3.9.9-eclipse-temurin-21 AS builder

WORKDIR /app

# Copy pom first for dependency cache
COPY pom.xml ./

# Copy source code
COPY src ./src

# Build the application (cache Maven local repo to accelerate rebuilds)
# Add HTTP retry to reduce transient central repository download failures.
RUN --mount=type=cache,target=/root/.m2 mvn -B \
    -Dmaven.wagon.http.retryHandler.count=6 \
    -Dmaven.wagon.http.retryHandler.requestSentEnabled=true \
    clean package -DskipTests

# Runtime stage
FROM eclipse-temurin:21-jre-jammy

WORKDIR /app

# Install runtime utilities, Node.js and Playwright browser runtime, then create non-root user
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
      > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --create-home appuser

# Playwright runner dependencies and browser binaries
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY playwright-runner /app/playwright-runner
RUN cd /app/playwright-runner && \
    npm install --omit=dev && \
    npx playwright install --with-deps chromium && \
    rm -rf /var/lib/apt/lists/*

# Copy the built JAR from builder stage
COPY --from=builder /app/target/*.jar app.jar

# Change ownership
RUN chown -R appuser:appgroup /app /ms-playwright

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/api/actuator/health || exit 1

# Run the application
ENTRYPOINT ["java", "-XX:+UseContainerSupport", "-XX:MaxRAMPercentage=75.0", "-jar", "app.jar"]
