package com.autotest.platform.service;

import com.autotest.platform.dto.TestCaseDTO;
import com.autotest.platform.dto.TestExecutionDTO;
import com.autotest.platform.entity.ExecutionScreenshot;
import com.autotest.platform.entity.ExecutionTimeline;
import com.autotest.platform.entity.TestCase;
import com.autotest.platform.entity.TestExecution;
import com.autotest.platform.entity.TestScript;
import com.autotest.platform.entity.UserStory;
import com.autotest.platform.event.TestExecutionRequestedEvent;
import com.autotest.platform.repository.TestCaseRepository;
import com.autotest.platform.repository.TestExecutionRepository;
import com.autotest.platform.repository.TestScriptRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.List;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class TestExecutionService {

    private final TestExecutionRepository testExecutionRepository;
    private final TestCaseRepository testCaseRepository;
    private final TestScriptRepository testScriptRepository;
    private final TenantContextService tenantContextService;
    private final ApplicationEventPublisher applicationEventPublisher;
    private final UserStoryService userStoryService;
    @Value("${platform.file-storage.local-path:./uploads}")
    private String fileStoragePath;

    @Cacheable(value = "executions", key = "#id")
    @Transactional(readOnly = true)
    public TestExecutionDTO getExecutionById(Long id) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestExecution execution = testExecutionRepository.findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> new RuntimeException("Execution not found: " + id));
        return mapToDTO(execution);
    }

    @Transactional(readOnly = true)
    public TestExecutionDTO getExecutionByIdForWorker(Long id) {
        TestExecution execution = testExecutionRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("Execution not found: " + id));
        return mapToDTO(execution);
    }

    @Transactional(readOnly = true)
    public ExecutionRuntimeContext getExecutionRuntimeContextForWorker(Long id) {
        TestExecution execution = testExecutionRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("Execution not found: " + id));
        TestCase testCase = execution.getTestCase();
        TestScript script = execution.getTestScript();
        return new ExecutionRuntimeContext(
                execution.getId(),
                execution.getExecutionId(),
                execution.getBrowser(),
                execution.getEnvironment(),
                execution.getPreviewMode(),
                execution.getScriptRecordId(),
                script != null ? script.getId() : null,
                script != null ? script.getName() : null,
                script != null ? script.getCode() : null,
                testCase != null ? testCase.getId() : null,
                testCase != null ? testCase.getCaseNumber() : null,
                testCase != null ? testCase.getTitle() : null,
                testCase != null ? testCase.getDescription() : null
        );
    }

    @Transactional(readOnly = true)
    public TestExecutionDTO getExecutionByExecutionId(String executionId) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestExecution execution = testExecutionRepository.findByExecutionIdAndTenantId(executionId, tenantId)
                .orElseThrow(() -> new RuntimeException("Execution not found: " + executionId));
        return mapToDTO(execution);
    }

    @Transactional(readOnly = true)
    public Page<TestExecutionDTO> getAllExecutions(Pageable pageable) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testExecutionRepository.findByTenantId(tenantId, pageable).map(this::mapToDTO);
    }

    @Transactional(readOnly = true)
    public List<TestExecutionDTO> getExecutionsByTestCase(Long testCaseId) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testExecutionRepository.findByTestCaseId(tenantId, testCaseId).stream()
                .map(this::mapToDTO)
                .collect(Collectors.toList());
    }

    @Transactional(readOnly = true)
    public Page<TestExecutionDTO> getExecutionsByStatus(TestExecution.ExecutionStatus status, Pageable pageable) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testExecutionRepository.findByStatus(tenantId, status, pageable).map(this::mapToDTO);
    }

    @Transactional
    @CacheEvict(value = "executions", allEntries = true)
    public TestExecutionDTO createExecution(TestExecutionDTO.CreateRequest request, String username) {
        TenantContextService.CurrentTenant currentTenant = tenantContextService.resolveCurrentTenant(username);
        Long tenantId = currentTenant.tenant().getId();

        TestCase testCase = testCaseRepository.findByIdAndTenantId(request.getTestCaseId(), tenantId)
                .orElseThrow(() -> new RuntimeException("Test Case not found: " + request.getTestCaseId()));

        boolean previewMode = Boolean.TRUE.equals(request.getPreviewMode());
        TestScript selectedScript = resolveExecutionScript(tenantId, testCase, request);
        if (!previewMode) {
            if (selectedScript == null) {
                throw new RuntimeException("该用例暂无可执行脚本，请先在脚本工作室完成采纳/审核");
            }
            if (!isExecutableScriptStatus(selectedScript.getStatus())) {
                throw new RuntimeException("脚本尚未审核通过，请先在脚本工作室完成审核后再执行");
            }
        }

        String executionId = "EXEC-" + UUID.randomUUID().toString().substring(0, 8).toUpperCase();

        TestExecution execution = TestExecution.builder()
                .tenantId(tenantId)
                .executionId(executionId)
                .testCase(testCase)
                .testScript(selectedScript)
                .scriptRecordId(normalizeRecordId(request.getScriptRecordId()))
                .previewMode(previewMode)
                .status(TestExecution.ExecutionStatus.PENDING)
                .executedBy(username)
                .browser(request.getBrowser())
                .environment(request.getEnvironment())
                .build();

        TestExecution savedExecution = testExecutionRepository.save(execution);
        log.info("Created Test Execution: {}", savedExecution.getExecutionId());
        Long executionDbId = savedExecution.getId();
        if (TransactionSynchronizationManager.isActualTransactionActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    applicationEventPublisher.publishEvent(new TestExecutionRequestedEvent(executionDbId));
                    log.debug("Published execution event after commit. executionId={}", executionDbId);
                }
            });
        } else {
            applicationEventPublisher.publishEvent(new TestExecutionRequestedEvent(executionDbId));
            log.debug("Published execution event immediately (no active tx). executionId={}", executionDbId);
        }

        return mapToDTO(savedExecution);
    }

    @Transactional
    @CacheEvict(value = "executions", key = "#id")
    public TestExecutionDTO startExecution(Long id) {
        TestExecution execution = findExecutionForUpdate(id);

        execution.setStatus(TestExecution.ExecutionStatus.RUNNING);
        execution.setStartedAt(LocalDateTime.now());

        TestExecution updatedExecution = testExecutionRepository.save(execution);
        log.info("Started Test Execution: {}", updatedExecution.getExecutionId());
        return mapToDTO(updatedExecution);
    }

    @Transactional
    @CacheEvict(value = "executions", key = "#id")
    public TestExecutionDTO completeExecution(Long id, TestExecution.ExecutionResult result, String logs) {
        TestExecution execution = findExecutionForUpdate(id);

        execution.setStatus(TestExecution.ExecutionStatus.COMPLETED);
        execution.setResult(result);
        if (logs != null && !logs.isBlank()) {
            execution.setLogs(logs);
        }
        execution.setCompletedAt(LocalDateTime.now());
        if (!StringUtils.hasText(execution.getReportPath())) {
            execution.setReportPath(buildReportPath(execution));
        }
        if (!StringUtils.hasText(execution.getVideoPath())) {
            execution.setVideoPath(buildVideoPath(execution));
        }

        if (execution.getStartedAt() != null) {
            execution.setDuration(
                    java.time.Duration.between(execution.getStartedAt(), execution.getCompletedAt()).toMillis()
            );
        }

        TestExecution updatedExecution = testExecutionRepository.save(execution);
        markUserStoryExecutionCompleted(updatedExecution);
        log.info("Completed Test Execution: {} with result: {}",
                updatedExecution.getExecutionId(), result);
        return mapToDTO(updatedExecution);
    }

    @Transactional
    @CacheEvict(value = "executions", key = "#executionId")
    public void updateExecutionArtifacts(Long executionId, String reportPath, String videoPath) {
        TestExecution execution = findExecutionForUpdate(executionId);
        if (StringUtils.hasText(reportPath)) {
            execution.setReportPath(reportPath.trim());
        }
        if (StringUtils.hasText(videoPath)) {
            execution.setVideoPath(videoPath.trim());
        }
        testExecutionRepository.save(execution);
    }

    @Transactional
    @CacheEvict(value = "executions", key = "#id")
    public TestExecutionDTO failExecution(Long id, String errorMessage) {
        TestExecution execution = findExecutionForUpdate(id);

        execution.setStatus(TestExecution.ExecutionStatus.FAILED);
        execution.setResult(TestExecution.ExecutionResult.ERROR);
        execution.setErrorMessage(errorMessage);
        execution.setCompletedAt(LocalDateTime.now());
        if (!StringUtils.hasText(execution.getReportPath())) {
            execution.setReportPath(buildReportPath(execution));
        }
        if (!StringUtils.hasText(execution.getVideoPath())) {
            execution.setVideoPath(buildVideoPath(execution));
        }
        if (execution.getStartedAt() != null) {
            execution.setDuration(Duration.between(execution.getStartedAt(), execution.getCompletedAt()).toMillis());
        }

        TestExecution updatedExecution = testExecutionRepository.save(execution);
        markUserStoryExecutionCompleted(updatedExecution);
        log.error("Failed Test Execution: {} - {}", updatedExecution.getExecutionId(), errorMessage);
        return mapToDTO(updatedExecution);
    }

    @Transactional
    @CacheEvict(value = "executions", key = "#id")
    public void cancelExecution(Long id) {
        TestExecution execution = findExecutionForUpdate(id);

        execution.setStatus(TestExecution.ExecutionStatus.CANCELLED);
        testExecutionRepository.save(execution);
        log.info("Cancelled Test Execution: {}", execution.getExecutionId());
    }

    @Transactional(readOnly = true)
    public List<TestExecutionDTO> getRecentExecutions(int limit) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testExecutionRepository.findRecentExecutions(tenantId, PageRequest.of(0, limit))
                .stream()
                .map(this::mapToDTO)
                .collect(Collectors.toList());
    }

    @Transactional(readOnly = true)
    public long countExecutions() {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testExecutionRepository.countByTenantId(tenantId);
    }

    @Transactional(readOnly = true)
    public long countByStatus(TestExecution.ExecutionStatus status) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testExecutionRepository.countByStatus(tenantId, status);
    }

    @Transactional(readOnly = true)
    public long countByResult(TestExecution.ExecutionResult result) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testExecutionRepository.countByResult(tenantId, result);
    }

    @Transactional(readOnly = true)
    public Double getAverageExecutionTime() {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return testExecutionRepository.getAverageDuration(tenantId);
    }

    @Transactional
    @CacheEvict(value = "executions", key = "#executionId")
    public TestExecutionDTO.ExecutionTimelineDTO appendTimeline(Long executionId,
                                                                Integer stepOrder,
                                                                String stepName,
                                                                ExecutionTimeline.StepStatus status,
                                                                Long duration,
                                                                String details,
                                                                String screenshotPath) {
        TestExecution execution = findExecutionForUpdate(executionId);

        ExecutionTimeline timeline = ExecutionTimeline.builder()
                .execution(execution)
                .stepOrder(stepOrder)
                .stepName(stepName)
                .status(status)
                .duration(duration)
                .details(details)
                .screenshotPath(screenshotPath)
                .build();
        execution.getTimeline().add(timeline);
        testExecutionRepository.save(execution);
        return mapTimeline(timeline);
    }

    @Transactional
    @CacheEvict(value = "executions", key = "#executionId")
    public TestExecutionDTO.ExecutionScreenshotDTO appendScreenshot(Long executionId,
                                                                    String filePath,
                                                                    String stepName,
                                                                    Integer stepNumber,
                                                                    String description,
                                                                    ExecutionScreenshot.ScreenshotType type) {
        TestExecution execution = findExecutionForUpdate(executionId);

        ExecutionScreenshot screenshot = ExecutionScreenshot.builder()
                .execution(execution)
                .filePath(filePath)
                .stepName(stepName)
                .stepNumber(stepNumber)
                .description(description)
                .type(type)
                .build();
        execution.getScreenshots().add(screenshot);
        testExecutionRepository.save(execution);
        return mapScreenshot(screenshot);
    }

    @Transactional
    @CacheEvict(value = "executions", key = "#executionId")
    public void appendLog(Long executionId, String logLine) {
        if (logLine == null || logLine.isBlank()) {
            return;
        }
        TestExecution execution = findExecutionForUpdate(executionId);
        String current = execution.getLogs();
        String next = (current == null || current.isBlank()) ? logLine : current + "\n" + logLine;
        execution.setLogs(next);
        testExecutionRepository.save(execution);
    }

    private TestExecutionDTO mapToDTO(TestExecution execution) {
        return TestExecutionDTO.builder()
                .id(execution.getId())
                .executionId(execution.getExecutionId())
                .testCase(mapTestCase(execution.getTestCase()))
                .scriptId(execution.getTestScript() != null ? execution.getTestScript().getId() : null)
                .scriptName(execution.getTestScript() != null ? execution.getTestScript().getName() : null)
                .scriptStatus(execution.getTestScript() != null && execution.getTestScript().getStatus() != null
                        ? execution.getTestScript().getStatus().name()
                        : null)
                .scriptRecordId(execution.getScriptRecordId())
                .previewMode(Boolean.TRUE.equals(execution.getPreviewMode()))
                .status(TestExecutionDTO.ExecutionStatus.valueOf(execution.getStatus().name()))
                .result(execution.getResult() != null ?
                        TestExecutionDTO.ExecutionResult.valueOf(execution.getResult().name()) : null)
                .logs(execution.getLogs())
                .errorMessage(execution.getErrorMessage())
                .videoPath(execution.getVideoPath())
                .reportPath(execution.getReportPath())
                .duration(execution.getDuration())
                .executedBy(execution.getExecutedBy())
                .browser(execution.getBrowser())
                .environment(execution.getEnvironment())
                .screenshots(execution.getScreenshots() == null ? List.of() : execution.getScreenshots().stream()
                        .sorted(Comparator.comparing(ExecutionScreenshot::getCapturedAt, Comparator.nullsLast(Comparator.naturalOrder())))
                        .map(this::mapScreenshot)
                        .collect(Collectors.toList()))
                .timeline(execution.getTimeline() == null ? List.of() : execution.getTimeline().stream()
                        .sorted(Comparator.comparing(ExecutionTimeline::getStepOrder, Comparator.nullsLast(Comparator.naturalOrder())))
                        .map(this::mapTimeline)
                        .collect(Collectors.toList()))
                .createdAt(execution.getCreatedAt())
                .startedAt(execution.getStartedAt())
                .completedAt(execution.getCompletedAt())
                .build();
    }

    private TestCaseDTO mapTestCase(TestCase testCase) {
        if (testCase == null) {
            return null;
        }
        return TestCaseDTO.builder()
                .id(testCase.getId())
                .caseNumber(testCase.getCaseNumber())
                .title(testCase.getTitle())
                .status(TestCaseDTO.Status.valueOf(testCase.getStatus().name()))
                .testType(TestCaseDTO.TestType.valueOf(testCase.getTestType().name()))
                .priority(TestCaseDTO.Priority.valueOf(testCase.getPriority().name()))
                .build();
    }

    private TestExecutionDTO.ExecutionTimelineDTO mapTimeline(ExecutionTimeline timeline) {
        return TestExecutionDTO.ExecutionTimelineDTO.builder()
                .stepOrder(timeline.getStepOrder())
                .stepName(timeline.getStepName())
                .status(timeline.getStatus() != null ? timeline.getStatus().name() : null)
                .duration(timeline.getDuration())
                .details(timeline.getDetails())
                .screenshotPath(timeline.getScreenshotPath())
                .timestamp(timeline.getTimestamp())
                .build();
    }

    private TestExecutionDTO.ExecutionScreenshotDTO mapScreenshot(ExecutionScreenshot screenshot) {
        return TestExecutionDTO.ExecutionScreenshotDTO.builder()
                .filePath(screenshot.getFilePath())
                .stepName(screenshot.getStepName())
                .stepNumber(screenshot.getStepNumber())
                .description(screenshot.getDescription())
                .type(screenshot.getType() != null ? screenshot.getType().name() : null)
                .capturedAt(screenshot.getCapturedAt())
                .build();
    }

    private TestExecution findExecutionForUpdate(Long executionId) {
        return tenantContextService.tryResolveCurrentTenantId()
                .map(tenantId -> testExecutionRepository.findByIdAndTenantId(executionId, tenantId)
                        .orElseThrow(() -> new RuntimeException("Execution not found: " + executionId)))
                .orElseGet(() -> testExecutionRepository.findById(executionId)
                        .orElseThrow(() -> new RuntimeException("Execution not found: " + executionId)));
    }

    private TestScript resolveExecutionScript(Long tenantId, TestCase testCase, TestExecutionDTO.CreateRequest request) {
        if (request == null || testCase == null) {
            return null;
        }
        if (request.getScriptId() != null) {
            TestScript selected = testScriptRepository.findByIdAndTenantId(request.getScriptId(), tenantId)
                    .orElseThrow(() -> new RuntimeException("Script not found: " + request.getScriptId()));
            if (selected.getTestCase() == null || selected.getTestCase().getId() == null
                    || !selected.getTestCase().getId().equals(testCase.getId())) {
                throw new RuntimeException("脚本与当前测试用例不匹配");
            }
            return selected;
        }
        return testScriptRepository.findByTestCaseIdAndTenantId(testCase.getId(), tenantId).orElse(null);
    }

    private boolean isExecutableScriptStatus(TestScript.Status status) {
        if (status == null) return false;
        return status == TestScript.Status.PRODUCTION || status == TestScript.Status.READY;
    }

    private String normalizeRecordId(String recordId) {
        if (!StringUtils.hasText(recordId)) return null;
        return recordId.trim();
    }

    @Transactional(readOnly = true)
    public ExecutionArtifact resolveArtifact(Long executionId, String artifactPath) {
        if (!StringUtils.hasText(artifactPath)) {
            throw new RuntimeException("Artifact path is required");
        }
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestExecution execution = testExecutionRepository.findByIdAndTenantId(executionId, tenantId)
                .orElseThrow(() -> new RuntimeException("Execution not found: " + executionId));
        Path executionRoot = resolveExecutionArtifactRoot(execution.getExecutionId());
        String normalizedRelative = normalizeArtifactRelativePath(artifactPath);
        Path resolved = executionRoot.resolve(normalizedRelative).normalize();
        if (!resolved.startsWith(executionRoot)) {
            throw new RuntimeException("Invalid artifact path");
        }
        if (!Files.exists(resolved) || Files.isDirectory(resolved)) {
            throw new RuntimeException("Artifact not found");
        }

        String contentType = "application/octet-stream";
        try {
            String probed = Files.probeContentType(resolved);
            if (StringUtils.hasText(probed)) {
                contentType = probed;
            } else if (resolved.getFileName().toString().toLowerCase().endsWith(".json")) {
                contentType = "application/json";
            } else if (resolved.getFileName().toString().toLowerCase().endsWith(".webm")) {
                contentType = "video/webm";
            } else if (resolved.getFileName().toString().toLowerCase().endsWith(".mp4")) {
                contentType = "video/mp4";
            } else if (resolved.getFileName().toString().toLowerCase().endsWith(".png")) {
                contentType = "image/png";
            } else if (resolved.getFileName().toString().toLowerCase().endsWith(".jpg")
                    || resolved.getFileName().toString().toLowerCase().endsWith(".jpeg")) {
                contentType = "image/jpeg";
            }
        } catch (IOException ignored) {
            // keep fallback content type
        }
        return new ExecutionArtifact(resolved, contentType, resolved.getFileName().toString());
    }

    public Path resolveExecutionArtifactRoot(String executionCode) {
        String normalizedExecutionCode = StringUtils.hasText(executionCode)
                ? executionCode.replaceAll("[^A-Za-z0-9_-]", "")
                : "unknown";
        Path storageRoot = Paths.get(fileStoragePath == null ? "./uploads" : fileStoragePath).toAbsolutePath().normalize();
        return storageRoot.resolve("executions").resolve(normalizedExecutionCode).normalize();
    }

    private String normalizeArtifactRelativePath(String raw) {
        String normalized = String.valueOf(raw)
                .replace('\\', '/')
                .replaceAll("^/+", "");
        if (!StringUtils.hasText(normalized) || normalized.contains("..")) {
            throw new RuntimeException("Invalid artifact path");
        }
        return normalized;
    }

    private String buildReportPath(TestExecution execution) {
        String executionKey = execution != null && StringUtils.hasText(execution.getExecutionId())
                ? execution.getExecutionId()
                : "unknown";
        return "/reports/" + executionKey + ".json";
    }

    private String buildVideoPath(TestExecution execution) {
        String executionKey = execution != null && StringUtils.hasText(execution.getExecutionId())
                ? execution.getExecutionId()
                : "unknown";
        return "/videos/" + executionKey + ".mp4";
    }

    private void markUserStoryExecutionCompleted(TestExecution execution) {
        if (execution == null || execution.getTestCase() == null || execution.getTestCase().getUserStory() == null) {
            return;
        }
        Long userStoryId = execution.getTestCase().getUserStory().getId();
        if (userStoryId == null) {
            return;
        }
        userStoryService.transitionWorkflowStatus(userStoryId, UserStory.Status.DONE);
    }

    public record ExecutionRuntimeContext(
            Long executionId,
            String executionCode,
            String browser,
            String environment,
            Boolean previewMode,
            String scriptRecordId,
            Long scriptId,
            String scriptName,
            String scriptCode,
            Long testCaseId,
            String caseNumber,
            String caseTitle,
            String caseDescription
    ) {
    }

    public record ExecutionArtifact(
            Path filePath,
            String contentType,
            String fileName
    ) {
    }
}
