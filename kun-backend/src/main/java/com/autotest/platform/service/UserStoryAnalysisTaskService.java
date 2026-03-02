package com.autotest.platform.service;

import com.autotest.platform.dto.UserStoryDTO;
import jakarta.annotation.PreDestroy;
import lombok.Builder;
import lombok.Getter;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.UnaryOperator;

@Service
@Slf4j
public class UserStoryAnalysisTaskService {

    private static final Duration TASK_RETENTION = Duration.ofHours(6);
    private static final int MAX_TASK_COUNT = 1000;

    private final Map<String, AnalysisTask> tasks = new ConcurrentHashMap<>();
    private final AtomicLong threadId = new AtomicLong(0);
    private final ExecutorService executor = Executors.newFixedThreadPool(
            Math.max(2, Runtime.getRuntime().availableProcessors() / 2),
            runnable -> {
                Thread thread = new Thread(runnable);
                thread.setName("us-analyze-" + threadId.incrementAndGet());
                thread.setDaemon(true);
                return thread;
            }
    );

    public AnalysisTask submit(
            Long userStoryId,
            String userStoryNumber,
            String requestedBy,
            Callable<UserStoryDTO.AIAnalysisResponse> taskSupplier) {
        cleanupIfNeeded();

        String taskId = UUID.randomUUID().toString();
        LocalDateTime now = LocalDateTime.now();
        AnalysisTask queued = AnalysisTask.builder()
                .taskId(taskId)
                .userStoryId(userStoryId)
                .userStoryNumber(userStoryNumber)
                .requestedBy(requestedBy)
                .status(TaskStatus.QUEUED)
                .createdAt(now)
                .build();
        tasks.put(taskId, queued);

        executor.submit(() -> {
            updateTask(taskId, current -> current.toBuilder()
                    .status(TaskStatus.RUNNING)
                    .startedAt(LocalDateTime.now())
                    .build());
            try {
                UserStoryDTO.AIAnalysisResponse result = taskSupplier.call();
                updateTask(taskId, current -> current.toBuilder()
                        .status(TaskStatus.SUCCEEDED)
                        .finishedAt(LocalDateTime.now())
                        .result(result)
                        .errorMessage(null)
                        .build());
            } catch (Exception ex) {
                log.warn("US analyze task failed. taskId={}, userStoryId={}, reason={}",
                        taskId, userStoryId, ex.getMessage(), ex);
                updateTask(taskId, current -> current.toBuilder()
                        .status(TaskStatus.FAILED)
                        .finishedAt(LocalDateTime.now())
                        .errorMessage(safeErrorMessage(ex))
                        .build());
            }
        });

        return queued;
    }

    public Optional<AnalysisTask> getTask(String taskId) {
        return Optional.ofNullable(tasks.get(taskId));
    }

    public Optional<AnalysisTask> findLatestTaskByUserStoryId(Long userStoryId) {
        cleanupIfNeeded();
        return tasks.values().stream()
                .filter(task -> task.getUserStoryId() != null && task.getUserStoryId().equals(userStoryId))
                .max(Comparator.comparing(AnalysisTask::getCreatedAt));
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }

    private void updateTask(String taskId, UnaryOperator<AnalysisTask> updater) {
        tasks.computeIfPresent(taskId, (key, current) -> updater.apply(current));
    }

    private void cleanupIfNeeded() {
        LocalDateTime expiredBefore = LocalDateTime.now().minus(TASK_RETENTION);
        tasks.entrySet().removeIf(entry -> {
            AnalysisTask task = entry.getValue();
            return task.isTerminal()
                    && task.getFinishedAt() != null
                    && task.getFinishedAt().isBefore(expiredBefore);
        });

        if (tasks.size() <= MAX_TASK_COUNT) {
            return;
        }

        List<AnalysisTask> terminals = tasks.values().stream()
                .filter(AnalysisTask::isTerminal)
                .sorted(Comparator.comparing(task -> Optional.ofNullable(task.getFinishedAt()).orElse(task.getCreatedAt())))
                .toList();

        int overflow = tasks.size() - MAX_TASK_COUNT;
        for (int i = 0; i < overflow && i < terminals.size(); i++) {
            tasks.remove(terminals.get(i).getTaskId());
        }
    }

    private String safeErrorMessage(Exception ex) {
        String message = ex.getMessage();
        if (message == null || message.isBlank()) {
            return "分析任务执行失败";
        }
        return message.length() > 240 ? message.substring(0, 240) + "..." : message;
    }

    public enum TaskStatus {
        QUEUED,
        RUNNING,
        SUCCEEDED,
        FAILED
    }

    @Getter
    @Builder(toBuilder = true)
    public static class AnalysisTask {
        private final String taskId;
        private final Long userStoryId;
        private final String userStoryNumber;
        private final String requestedBy;
        private final TaskStatus status;
        private final LocalDateTime createdAt;
        private final LocalDateTime startedAt;
        private final LocalDateTime finishedAt;
        private final UserStoryDTO.AIAnalysisResponse result;
        private final String errorMessage;

        public boolean isTerminal() {
            return status == TaskStatus.SUCCEEDED || status == TaskStatus.FAILED;
        }
    }
}
