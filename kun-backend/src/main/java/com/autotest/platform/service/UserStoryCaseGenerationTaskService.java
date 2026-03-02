package com.autotest.platform.service;

import com.autotest.platform.dto.UserStoryDTO;
import jakarta.annotation.PreDestroy;
import lombok.Builder;
import lombok.Getter;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.UnaryOperator;

@Service
@Slf4j
public class UserStoryCaseGenerationTaskService {

    private static final Duration TASK_RETENTION = Duration.ofHours(6);
    private static final int MAX_TASK_COUNT = 1000;

    private final Map<String, CaseGenerationTask> tasks = new ConcurrentHashMap<>();
    private final AtomicLong threadId = new AtomicLong(0);
    private final ExecutorService executor = Executors.newFixedThreadPool(
            Math.max(2, Runtime.getRuntime().availableProcessors() / 2),
            runnable -> {
                Thread thread = new Thread(runnable);
                thread.setName("us-case-gen-" + threadId.incrementAndGet());
                thread.setDaemon(true);
                return thread;
            }
    );

    public CaseGenerationTask submit(
            Long userStoryId,
            String userStoryNumber,
            String requestedBy,
            TaskWorker worker) {
        cleanupIfNeeded();

        String taskId = UUID.randomUUID().toString();
        LocalDateTime now = LocalDateTime.now();
        CaseGenerationTask queued = CaseGenerationTask.builder()
                .taskId(taskId)
                .userStoryId(userStoryId)
                .userStoryNumber(userStoryNumber)
                .requestedBy(requestedBy)
                .status(TaskStatus.QUEUED)
                .createdAt(now)
                .events(List.of(buildEvent(now, "QUEUED", "已提交用例生成任务，等待执行")))
                .build();
        tasks.put(taskId, queued);

        executor.submit(() -> {
            updateTask(taskId, current -> current.toBuilder()
                    .status(TaskStatus.RUNNING)
                    .startedAt(LocalDateTime.now())
                    .build());
            appendEvent(taskId, "RUNNING", "任务开始执行，正在准备 US 上下文");

            try {
                UserStoryDTO.CaseGenerationSessionDTO result = worker.run((stage, message) -> appendEvent(taskId, stage, message));
                updateTask(taskId, current -> current.toBuilder()
                        .status(TaskStatus.SUCCEEDED)
                        .finishedAt(LocalDateTime.now())
                        .result(result)
                        .errorMessage(null)
                        .build());
                appendEvent(taskId, "SUCCEEDED", "用例草稿已生成，可查看并采纳");
            } catch (Exception ex) {
                log.warn("US case generation task failed. taskId={}, userStoryId={}, reason={}",
                        taskId, userStoryId, ex.getMessage(), ex);
                updateTask(taskId, current -> current.toBuilder()
                        .status(TaskStatus.FAILED)
                        .finishedAt(LocalDateTime.now())
                        .errorMessage(safeErrorMessage(ex))
                        .build());
                appendEvent(taskId, "FAILED", safeErrorMessage(ex));
            }
        });

        return queued;
    }

    public Optional<CaseGenerationTask> getTask(String taskId) {
        return Optional.ofNullable(tasks.get(taskId));
    }

    public Optional<CaseGenerationTask> findLatestTaskByUserStoryId(Long userStoryId) {
        cleanupIfNeeded();
        return tasks.values().stream()
                .filter(task -> task.getUserStoryId() != null && task.getUserStoryId().equals(userStoryId))
                .max(Comparator.comparing(CaseGenerationTask::getCreatedAt));
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }

    private void updateTask(String taskId, UnaryOperator<CaseGenerationTask> updater) {
        tasks.computeIfPresent(taskId, (key, current) -> updater.apply(current));
    }

    private void appendEvent(String taskId, String stage, String message) {
        updateTask(taskId, current -> {
            List<UserStoryDTO.CaseGenerationEventDTO> nextEvents = new ArrayList<>(current.getEvents());
            nextEvents.add(buildEvent(LocalDateTime.now(), stage, message));
            return current.toBuilder().events(nextEvents).build();
        });
    }

    private UserStoryDTO.CaseGenerationEventDTO buildEvent(LocalDateTime at, String stage, String message) {
        return UserStoryDTO.CaseGenerationEventDTO.builder()
                .occurredAt(at)
                .stage(stage)
                .message(message)
                .build();
    }

    private void cleanupIfNeeded() {
        LocalDateTime expiredBefore = LocalDateTime.now().minus(TASK_RETENTION);
        tasks.entrySet().removeIf(entry -> {
            CaseGenerationTask task = entry.getValue();
            return task.isTerminal()
                    && task.getFinishedAt() != null
                    && task.getFinishedAt().isBefore(expiredBefore);
        });

        if (tasks.size() <= MAX_TASK_COUNT) {
            return;
        }

        List<CaseGenerationTask> terminals = tasks.values().stream()
                .filter(CaseGenerationTask::isTerminal)
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
            return "生成任务执行失败";
        }
        return message.length() > 240 ? message.substring(0, 240) + "..." : message;
    }

    public enum TaskStatus {
        QUEUED,
        RUNNING,
        SUCCEEDED,
        FAILED
    }

    @FunctionalInterface
    public interface TaskWorker {
        UserStoryDTO.CaseGenerationSessionDTO run(TaskEventLogger logger) throws Exception;
    }

    @FunctionalInterface
    public interface TaskEventLogger {
        void log(String stage, String message);
    }

    @Getter
    @Builder(toBuilder = true)
    public static class CaseGenerationTask {
        private final String taskId;
        private final Long userStoryId;
        private final String userStoryNumber;
        private final String requestedBy;
        private final TaskStatus status;
        private final LocalDateTime createdAt;
        private final LocalDateTime startedAt;
        private final LocalDateTime finishedAt;
        @Builder.Default
        private final List<UserStoryDTO.CaseGenerationEventDTO> events = List.of();
        private final UserStoryDTO.CaseGenerationSessionDTO result;
        private final String errorMessage;

        public boolean isTerminal() {
            return status == TaskStatus.SUCCEEDED || status == TaskStatus.FAILED;
        }
    }
}
