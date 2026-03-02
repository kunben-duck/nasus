package com.autotest.platform.service;

import com.autotest.platform.listener.TestExecutionListener;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

@Service
@RequiredArgsConstructor
@Slf4j
public class RedisExecutionQueueConsumer {

    private final StringRedisTemplate stringRedisTemplate;
    private final TestExecutionListener testExecutionListener;

    @Value("${platform.execution.queue.redis-key:platform:execution:queue}")
    private String executionQueueRedisKey;

    @Value("${platform.execution.queue.consumer-enabled:true}")
    private boolean consumerEnabled;

    @Value("${platform.execution.queue.poll-interval-ms:300}")
    private long pollIntervalMs;

    @Value("${platform.execution.queue.error-backoff-ms:1000}")
    private long errorBackoffMs;

    private final AtomicBoolean running = new AtomicBoolean(false);
    private final ExecutorService executor = Executors.newSingleThreadExecutor(r -> {
        Thread thread = new Thread(r);
        thread.setName("execution-redis-consumer");
        thread.setDaemon(true);
        return thread;
    });

    @PostConstruct
    public void startConsumer() {
        if (!consumerEnabled) {
            log.info("Redis execution queue consumer disabled by config.");
            return;
        }
        if (!running.compareAndSet(false, true)) {
            return;
        }
        log.info("Starting redis execution queue consumer. key={}", executionQueueRedisKey);
        executor.submit(this::consumeLoop);
    }

    @PreDestroy
    public void stopConsumer() {
        running.set(false);
        executor.shutdownNow();
        try {
            if (!executor.awaitTermination(5, TimeUnit.SECONDS)) {
                log.warn("Redis execution queue consumer did not terminate within timeout.");
            }
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
        }
    }

    private void consumeLoop() {
        while (running.get() && !Thread.currentThread().isInterrupted()) {
            try {
                String payload = stringRedisTemplate.opsForList().rightPop(executionQueueRedisKey);
                if (!StringUtils.hasText(payload)) {
                    sleepQuietly(Math.max(50L, pollIntervalMs));
                    continue;
                }
                Long executionId = parseExecutionId(payload);
                if (executionId == null) {
                    continue;
                }
                testExecutionListener.handleTestExecution(executionId);
            } catch (Exception ex) {
                log.error("Redis execution queue consume failed. key={}, reason={}",
                        executionQueueRedisKey, ex.getMessage(), ex);
                sleepQuietly(Math.max(200L, errorBackoffMs));
            }
        }
        log.info("Redis execution queue consumer stopped. key={}", executionQueueRedisKey);
    }

    private Long parseExecutionId(String payload) {
        String normalized = payload == null ? "" : payload.trim();
        if (!StringUtils.hasText(normalized)) {
            return null;
        }
        try {
            return Long.parseLong(normalized);
        } catch (NumberFormatException ex) {
            log.warn("Skip invalid execution queue payload: {}", payload);
            return null;
        }
    }

    private void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException interruptedException) {
            Thread.currentThread().interrupt();
        }
    }
}
