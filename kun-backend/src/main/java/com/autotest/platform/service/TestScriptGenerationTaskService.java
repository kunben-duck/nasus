package com.autotest.platform.service;

import com.autotest.platform.dto.TestScriptDTO;
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
public class TestScriptGenerationTaskService {

    private static final Duration TASK_RETENTION = Duration.ofHours(6);
    private static final int MAX_TASK_COUNT = 1000;

    private final Map<String, ScriptGenerationTask> tasks = new ConcurrentHashMap<>();
    private final AtomicLong threadId = new AtomicLong(0);
    private final ExecutorService executor = Executors.newFixedThreadPool(
            Math.max(2, Runtime.getRuntime().availableProcessors() / 2),
            runnable -> {
                Thread thread = new Thread(runnable);
                thread.setName("tc-script-gen-" + threadId.incrementAndGet());
                thread.setDaemon(true);
                return thread;
            }
    );

    public ScriptGenerationTask submit(
            Long testCaseId,
            String caseNumber,
            String requestedBy,
            TaskWorker worker) {
        cleanupIfNeeded();

        String taskId = UUID.randomUUID().toString();
        LocalDateTime now = LocalDateTime.now();
        ScriptGenerationTask queued = ScriptGenerationTask.builder()
                .taskId(taskId)
                .testCaseId(testCaseId)
                .caseNumber(caseNumber)
                .requestedBy(requestedBy)
                .status(TaskStatus.QUEUED)
                .createdAt(now)
                .events(List.of(buildEvent(now, "QUEUED", "已提交脚本生成任务，等待执行")))
                .build();
        tasks.put(taskId, queued);

        executor.submit(() -> {
            updateTask(taskId, current -> current.toBuilder()
                    .status(TaskStatus.RUNNING)
                    .startedAt(LocalDateTime.now())
                    .build());
            appendEvent(taskId, "RUNNING", "任务开始执行，正在准备测试用例上下文");
            try {
                TestScriptDTO.ScriptGenerationSessionDTO result = worker.run((stage, message) -> appendEvent(taskId, stage, message));
                updateTask(taskId, current -> current.toBuilder()
                        .status(TaskStatus.SUCCEEDED)
                        .finishedAt(LocalDateTime.now())
                        .result(result)
                        .errorMessage(null)
                        .build());
                appendEvent(taskId, "SUCCEEDED", "脚本已生成，可在结果面板查看并继续优化");
            } catch (Exception ex) {
                log.warn("Script generation task failed. taskId={}, caseId={}, reason={}",
                        taskId, testCaseId, ex.getMessage(), ex);
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

    public Optional<ScriptGenerationTask> getTask(String taskId) {
        return Optional.ofNullable(tasks.get(taskId));
    }

    public Optional<ScriptGenerationTask> findLatestTaskByTestCaseId(Long testCaseId) {
        cleanupIfNeeded();
        return tasks.values().stream()
                .filter(task -> task.getTestCaseId() != null && task.getTestCaseId().equals(testCaseId))
                .max(Comparator.comparing(ScriptGenerationTask::getCreatedAt));
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }

    private void updateTask(String taskId, UnaryOperator<ScriptGenerationTask> updater) {
        tasks.computeIfPresent(taskId, (key, current) -> updater.apply(current));
    }

    private void appendEvent(String taskId, String stage, String message) {
        updateTask(taskId, current -> {
            List<TestScriptDTO.ScriptGenerationEventDTO> nextEvents = new ArrayList<>(current.getEvents());
            nextEvents.add(buildEvent(LocalDateTime.now(), stage, message));
            return current.toBuilder().events(nextEvents).build();
        });
    }

    private TestScriptDTO.ScriptGenerationEventDTO buildEvent(LocalDateTime at, String stage, String message) {
        return TestScriptDTO.ScriptGenerationEventDTO.builder()
                .occurredAt(at)
                .stage(stage)
                .message(message)
                .build();
    }

    private void cleanupIfNeeded() {
        LocalDateTime expiredBefore = LocalDateTime.now().minus(TASK_RETENTION);
        tasks.entrySet().removeIf(entry -> {
            ScriptGenerationTask task = entry.getValue();
            return task.isTerminal()
                    && task.getFinishedAt() != null
                    && task.getFinishedAt().isBefore(expiredBefore);
        });

        if (tasks.size() <= MAX_TASK_COUNT) return;

        List<ScriptGenerationTask> terminals = tasks.values().stream()
                .filter(ScriptGenerationTask::isTerminal)
                .sorted(Comparator.comparing(task -> Optional.ofNullable(task.getFinishedAt()).orElse(task.getCreatedAt())))
                .toList();

        int overflow = tasks.size() - MAX_TASK_COUNT;
        for (int i = 0; i < overflow && i < terminals.size(); i++) {
            tasks.remove(terminals.get(i).getTaskId());
        }
    }

    private String safeErrorMessage(Exception ex) {
        String message = ex.getMessage();
        if (message == null || message.isBlank()) return "脚本生成任务执行失败";
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
        TestScriptDTO.ScriptGenerationSessionDTO run(TaskEventLogger logger) throws Exception;
    }

    @FunctionalInterface
    public interface TaskEventLogger {
        void log(String stage, String message);
    }

    @Getter
    @Builder(toBuilder = true)
    public static class ScriptGenerationTask {
        private final String taskId;
        private final Long testCaseId;
        private final String caseNumber;
        private final String requestedBy;
        private final TaskStatus status;
        private final LocalDateTime createdAt;
        private final LocalDateTime startedAt;
        private final LocalDateTime finishedAt;
        @Builder.Default
        private final List<TestScriptDTO.ScriptGenerationEventDTO> events = List.of();
        private final TestScriptDTO.ScriptGenerationSessionDTO result;
        private final String errorMessage;

        public boolean isTerminal() {
            return status == TaskStatus.SUCCEEDED || status == TaskStatus.FAILED;
        }
    }
}
