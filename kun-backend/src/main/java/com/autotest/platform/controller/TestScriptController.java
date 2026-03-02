package com.autotest.platform.controller;

import com.autotest.platform.dto.ApiResponse;
import com.autotest.platform.dto.PageResponse;
import com.autotest.platform.dto.TestCaseDTO;
import com.autotest.platform.dto.TestExecutionDTO;
import com.autotest.platform.dto.TestScriptDTO;
import com.autotest.platform.entity.NotificationMessage;
import com.autotest.platform.entity.TestScript;
import com.autotest.platform.service.NotificationService;
import com.autotest.platform.service.TenantContextService;
import com.autotest.platform.service.TestCaseService;
import com.autotest.platform.service.TestExecutionService;
import com.autotest.platform.service.TestScriptGenerationService;
import com.autotest.platform.service.TestScriptGenerationTaskService;
import com.autotest.platform.service.TestScriptService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@RestController
@RequestMapping("/test-scripts")
@RequiredArgsConstructor
@Slf4j
@CrossOrigin(origins = "*")
public class TestScriptController {
    
    private final TestScriptService testScriptService;
    private final TestCaseService testCaseService;
    private final TestScriptGenerationService scriptGenerationService;
    private final TestScriptGenerationTaskService scriptGenerationTaskService;
    private final NotificationService notificationService;
    private final TenantContextService tenantContextService;
    private final TestExecutionService testExecutionService;
    
    @GetMapping
    public ResponseEntity<ApiResponse<PageResponse<TestScriptDTO>>> getAllTestScripts(
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(defaultValue = "createdAt,desc") String[] sort) {
        
        Pageable pageable = PageRequest.of(page, size, Sort.by(sort[0]).descending());
        PageResponse<TestScriptDTO> scripts = PageResponse.from(testScriptService.getAllTestScripts(pageable));
        return ResponseEntity.ok(ApiResponse.success(scripts));
    }
    
    @GetMapping("/{id}")
    public ResponseEntity<ApiResponse<TestScriptDTO>> getTestScriptById(@PathVariable Long id) {
        TestScriptDTO script = testScriptService.getTestScriptById(id);
        return ResponseEntity.ok(ApiResponse.success(script));
    }
    
    @GetMapping("/test-case/{testCaseId}")
    public ResponseEntity<ApiResponse<TestScriptDTO>> getTestScriptByTestCaseId(@PathVariable Long testCaseId) {
        TestScriptDTO script = testScriptService.getTestScriptByTestCaseId(testCaseId);
        return ResponseEntity.ok(ApiResponse.success(script));
    }
    
    @GetMapping("/type/{type}")
    public ResponseEntity<ApiResponse<PageResponse<TestScriptDTO>>> getTestScriptsByType(
            @PathVariable TestScript.ScriptType type,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        
        Pageable pageable = PageRequest.of(page, size);
        PageResponse<TestScriptDTO> scripts = PageResponse.from(testScriptService.getTestScriptsByType(type, pageable));
        return ResponseEntity.ok(ApiResponse.success(scripts));
    }
    
    @PostMapping
    public ResponseEntity<ApiResponse<TestScriptDTO>> createTestScript(
            @RequestBody TestScriptDTO.CreateRequest request) {
        
        TestScriptDTO createdScript = testScriptService.createTestScript(request);
        return ResponseEntity.ok(ApiResponse.success("Test Script created", createdScript));
    }
    
    @PutMapping("/{id}")
    public ResponseEntity<ApiResponse<TestScriptDTO>> updateTestScript(
            @PathVariable Long id,
            @RequestBody TestScriptDTO.UpdateRequest request) {
        
        TestScriptDTO updatedScript = testScriptService.updateTestScript(id, request);
        return ResponseEntity.ok(ApiResponse.success("Test Script updated", updatedScript));
    }
    
    @DeleteMapping("/{id}")
    public ResponseEntity<ApiResponse<Void>> deleteTestScript(@PathVariable Long id) {
        testScriptService.deleteTestScript(id);
        return ResponseEntity.ok(ApiResponse.success("Test Script deleted", null));
    }
    
    @PostMapping("/generate")
    public ResponseEntity<ApiResponse<TestScriptDTO.AIGenerateResponse>> generateScript(
            @RequestBody TestScriptDTO.AIGenerateRequest request,
            Authentication authentication) {
        if (request == null || request.getTestCaseId() == null) {
            return ResponseEntity.badRequest().body(ApiResponse.error(400, "testCaseId 不能为空"));
        }
        String requestedBy = authentication != null ? authentication.getName() : "system";
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestScriptGenerationService.GenerateResult generated = scriptGenerationService.generateAndPersist(
                new TestScriptGenerationService.GenerateCommand(
                        request.getTestCaseId(),
                        request.getScriptType(),
                        request.getLanguage(),
                        request.getTargetUrl(),
                        request.getAdditionalInstructions(),
                        request.getFeedback(),
                        requestedBy,
                        tenantId
                ),
                null
        );

        TestScriptDTO.AIGenerateResponse response = TestScriptDTO.AIGenerateResponse.builder()
                .generatedCode(generated.record() != null ? generated.record().getGeneratedCode() : "")
                .explanation(generated.modelResult().fallbackUsed()
                        ? defaultIfBlank(generated.modelResult().fallbackReason(), "模型不可用，已使用本地模板")
                        : "脚本已通过 Spring AI 生成并持久化")
                .dependencies(generated.record() != null
                        ? generated.record().getDependencies().toArray(String[]::new)
                        : new String[0])
                .scriptId(generated.script() != null ? generated.script().getId() : null)
                .recordId(generated.record() != null ? generated.record().getRecordId() : null)
                .version(generated.record() != null ? generated.record().getVersion() : null)
                .runCommand(generated.record() != null ? generated.record().getRunCommand() : null)
                .modelProvider(generated.modelResult().provider())
                .modelName(generated.modelResult().model())
                .build();
        
        return ResponseEntity.ok(ApiResponse.success(
                "Script generated and saved",
                response
        ));
    }

    @PostMapping("/test-cases/{testCaseId}/generation")
    public ResponseEntity<ApiResponse<ScriptGenerationTaskView>> generateScriptAsync(
            @PathVariable Long testCaseId,
            @RequestBody(required = false) TestScriptDTO.AIGenerateRequest request,
            Authentication authentication) {
        return submitScriptGenerationTask(testCaseId, request, authentication, false);
    }

    @PostMapping("/test-cases/{testCaseId}/generation/refine")
    public ResponseEntity<ApiResponse<ScriptGenerationTaskView>> refineScriptAsync(
            @PathVariable Long testCaseId,
            @RequestBody TestScriptDTO.AIGenerateRequest request,
            Authentication authentication) {
        return submitScriptGenerationTask(testCaseId, request, authentication, true);
    }

    @GetMapping("/generation-tasks/{taskId}")
    public ResponseEntity<ApiResponse<ScriptGenerationTaskView>> getScriptGenerationTask(@PathVariable String taskId) {
        return scriptGenerationTaskService.getTask(taskId)
                .map(task -> ResponseEntity.ok(ApiResponse.success(ScriptGenerationTaskView.from(task, true, 1500L))))
                .orElseGet(() -> ResponseEntity.status(HttpStatus.NOT_FOUND)
                        .body(ApiResponse.error(404, "脚本生成任务不存在或已过期")));
    }

    @GetMapping("/test-cases/{testCaseId}/generation/latest")
    public ResponseEntity<ApiResponse<LatestScriptGenerationView>> getLatestScriptGeneration(@PathVariable Long testCaseId) {
        TestCaseDTO testCase = testCaseService.getTestCaseById(testCaseId);
        Optional<TestScriptGenerationTaskService.ScriptGenerationTask> latestTask =
                scriptGenerationTaskService.findLatestTaskByTestCaseId(testCaseId);
        if (latestTask.isPresent()) {
            TestScriptGenerationTaskService.ScriptGenerationTask task = latestTask.get();
            if (!task.isTerminal()) {
                return ResponseEntity.ok(ApiResponse.success(LatestScriptGenerationView.fromTask(task, 1500L)));
            }
            if (task.getStatus() == TestScriptGenerationTaskService.TaskStatus.FAILED) {
                return ResponseEntity.ok(ApiResponse.success(LatestScriptGenerationView.fromTask(task, 1500L)));
            }
            if (task.getStatus() == TestScriptGenerationTaskService.TaskStatus.SUCCEEDED && task.getResult() != null) {
                return ResponseEntity.ok(ApiResponse.success(LatestScriptGenerationView.fromTask(task, 1500L)));
            }
        }

        return scriptGenerationService.getLatestSession(testCaseId)
                .map(session -> ResponseEntity.ok(ApiResponse.success(
                        LatestScriptGenerationView.fromPersisted(testCaseId, testCase.getCaseNumber(), session)
                )))
                .orElseGet(() -> ResponseEntity.ok(ApiResponse.success(
                        LatestScriptGenerationView.empty(testCaseId, testCase.getCaseNumber())
                )));
    }

    @GetMapping("/test-cases/{testCaseId}/generation/records")
    public ResponseEntity<ApiResponse<PageResponse<TestScriptDTO.ScriptGenerationRecordDTO>>> getScriptGenerationRecords(
            @PathVariable Long testCaseId,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "5") int size) {
        int normalizedPage = Math.max(0, page);
        int normalizedSize = Math.max(1, Math.min(100, size));
        PageResponse<TestScriptDTO.ScriptGenerationRecordDTO> records = PageResponse.from(
                scriptGenerationService.getRecords(testCaseId, PageRequest.of(normalizedPage, normalizedSize))
        );
        return ResponseEntity.ok(ApiResponse.success(records));
    }

    @GetMapping("/test-cases/{testCaseId}/generation/records/{recordId}")
    public ResponseEntity<ApiResponse<TestScriptDTO.ScriptGenerationRecordDTO>> getScriptGenerationRecordDetail(
            @PathVariable Long testCaseId,
            @PathVariable String recordId) {
        return scriptGenerationService.getRecordByRecordId(testCaseId, recordId)
                .map(item -> ResponseEntity.ok(ApiResponse.success(item)))
                .orElseGet(() -> ResponseEntity.status(HttpStatus.NOT_FOUND)
                        .body(ApiResponse.error(404, "未找到对应的脚本生成记录")));
    }

    @DeleteMapping("/test-cases/{testCaseId}/generation/records/{recordId}")
    public ResponseEntity<ApiResponse<LatestScriptGenerationView>> deleteScriptGenerationRecord(
            @PathVariable Long testCaseId,
            @PathVariable String recordId) {
        TestCaseDTO testCase = testCaseService.getTestCaseById(testCaseId);
        Optional<TestScriptDTO.ScriptGenerationSessionDTO> latest = scriptGenerationService.deleteRecordByRecordId(testCaseId, recordId);
        LatestScriptGenerationView view = latest
                .map(session -> LatestScriptGenerationView.fromPersisted(testCaseId, testCase.getCaseNumber(), session))
                .orElseGet(() -> LatestScriptGenerationView.empty(testCaseId, testCase.getCaseNumber()));
        return ResponseEntity.ok(ApiResponse.success("脚本生成记录已删除", view));
    }

    @PostMapping("/test-cases/{testCaseId}/generation/records/{recordId}/adopt")
    public ResponseEntity<ApiResponse<TestScriptDTO.ScriptGenerationRecordDTO>> adoptScriptGenerationRecord(
            @PathVariable Long testCaseId,
            @PathVariable String recordId,
            Authentication authentication) {
        String requestedBy = authentication != null ? authentication.getName() : "system";
        TestScriptDTO.ScriptGenerationRecordDTO adopted = scriptGenerationService
                .adoptRecordByRecordId(testCaseId, recordId, requestedBy);
        return ResponseEntity.ok(ApiResponse.success("脚本已采纳到工作室，状态已更新为待审核", adopted));
    }

    @PostMapping("/test-cases/{testCaseId}/generation/records/{recordId}/preview")
    public ResponseEntity<ApiResponse<TestExecutionDTO>> previewScriptGenerationRecord(
            @PathVariable Long testCaseId,
            @PathVariable String recordId,
            @RequestBody(required = false) ScriptPreviewRequest request,
            Authentication authentication) {
        TestScriptDTO.ScriptGenerationRecordDTO record = scriptGenerationService.getRecordByRecordId(testCaseId, recordId)
                .orElseThrow(() -> new RuntimeException("未找到对应的脚本生成记录"));
        String requestedBy = authentication != null ? authentication.getName() : "system";
        TestExecutionDTO.CreateRequest createRequest = TestExecutionDTO.CreateRequest.builder()
                .testCaseId(testCaseId)
                .scriptId(record.getScriptId())
                .scriptRecordId(record.getRecordId())
                .previewMode(true)
                .browser(defaultIfBlank(request != null ? request.getBrowser() : null, "chromium"))
                .environment(defaultIfBlank(request != null ? request.getEnvironment() : null, "staging"))
                .build();
        TestExecutionDTO created = testExecutionService.createExecution(createRequest, requestedBy);
        TestExecutionDTO started = testExecutionService.startExecution(created.getId());
        return ResponseEntity.ok(ApiResponse.success("脚本预览执行已启动", started));
    }
    
    @GetMapping("/stats")
    public ResponseEntity<ApiResponse<ScriptStats>> getScriptStats() {
        ScriptStats stats = ScriptStats.builder()
                .total(testScriptService.countTestScripts())
                .ready(testScriptService.countByStatus(TestScript.Status.READY))
                .draft(testScriptService.countByStatus(TestScript.Status.DRAFT))
                .generating(testScriptService.countByStatus(TestScript.Status.GENERATING))
                .build();
        return ResponseEntity.ok(ApiResponse.success(stats));
    }
    
    @lombok.Data
    @lombok.Builder
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class ScriptStats {
        private long total;
        private long ready;
        private long draft;
        private long generating;
    }

    @lombok.Data
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class ScriptPreviewRequest {
        private String browser;
        private String environment;
    }

    private ResponseEntity<ApiResponse<ScriptGenerationTaskView>> submitScriptGenerationTask(
            Long testCaseId,
            TestScriptDTO.AIGenerateRequest request,
            Authentication authentication,
            boolean requireFeedback) {
        TestCaseDTO testCase = testCaseService.getTestCaseById(testCaseId);
        if (testCase == null) {
            return ResponseEntity.badRequest().body(ApiResponse.error(400, "测试用例不存在"));
        }
        String feedback = request != null && StringUtils.hasText(request.getFeedback())
                ? request.getFeedback().trim()
                : null;
        if (requireFeedback && !StringUtils.hasText(feedback)) {
            return ResponseEntity.badRequest().body(ApiResponse.error(400, "请输入优化建议后再执行二次生成"));
        }

        String requestedBy = authentication != null ? authentication.getName() : "system";
        Long tenantId = tenantContextService.requireCurrentTenantId();
        Optional<TestScriptGenerationTaskService.ScriptGenerationTask> latestTask =
                scriptGenerationTaskService.findLatestTaskByTestCaseId(testCaseId);
        if (latestTask.isPresent() && !latestTask.get().isTerminal()) {
            ScriptGenerationTaskView running = ScriptGenerationTaskView.from(latestTask.get(), true, 1500L);
            ApiResponse<ScriptGenerationTaskView> runningResponse = ApiResponse.<ScriptGenerationTaskView>builder()
                    .success(true)
                    .code(202)
                    .message("已有进行中的脚本生成任务")
                    .data(running)
                    .timestamp(LocalDateTime.now())
                    .build();
            return ResponseEntity.status(HttpStatus.ACCEPTED).body(runningResponse);
        }

        TestScriptGenerationTaskService.ScriptGenerationTask task = scriptGenerationTaskService.submit(
                testCaseId,
                defaultIfBlank(testCase.getCaseNumber(), "TC-" + testCaseId),
                requestedBy,
                logger -> {
                    try {
                        TestScriptGenerationService.GenerateResult result = scriptGenerationService.generateAndPersist(
                                new TestScriptGenerationService.GenerateCommand(
                                        testCaseId,
                                        request != null ? request.getScriptType() : null,
                                        request != null ? request.getLanguage() : null,
                                        request != null ? request.getTargetUrl() : null,
                                        request != null ? request.getAdditionalInstructions() : null,
                                        feedback,
                                        requestedBy,
                                        tenantId
                                ),
                                logger
                        );
                        publishScriptGenerationNotification(
                                requestedBy,
                                tenantId,
                                testCase,
                                true,
                                result.record(),
                                null
                        );
                        return result.session();
                    } catch (Exception ex) {
                        publishScriptGenerationNotification(
                                requestedBy,
                                tenantId,
                                testCase,
                                false,
                                null,
                                ex
                        );
                        throw ex;
                    }
                }
        );

        ScriptGenerationTaskView view = ScriptGenerationTaskView.from(task, true, 1500L);
        ApiResponse<ScriptGenerationTaskView> response = ApiResponse.<ScriptGenerationTaskView>builder()
                .success(true)
                .code(202)
                .message("脚本生成任务已提交")
                .data(view)
                .timestamp(LocalDateTime.now())
                .build();
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(response);
    }

    private void publishScriptGenerationNotification(String requestedBy,
                                                     Long tenantId,
                                                     TestCaseDTO testCase,
                                                     boolean succeeded,
                                                     TestScriptDTO.ScriptGenerationRecordDTO record,
                                                     Exception error) {
        String caseNumber = defaultIfBlank(testCase.getCaseNumber(), "TC-" + testCase.getId());
        String caseTitle = defaultIfBlank(testCase.getTitle(), "未命名测试用例");
        String title = succeeded
                ? String.format("%s 脚本生成完成", caseNumber)
                : String.format("%s 脚本生成失败", caseNumber);
        String content = succeeded
                ? String.format("测试用例「%s」已生成脚本版本 V%s。", caseTitle, record != null ? record.getVersion() : "-")
                : String.format("测试用例「%s」脚本生成失败：%s", caseTitle, safeErrorMessage(error));
        NotificationMessage.NotificationType type = succeeded
                ? NotificationMessage.NotificationType.SCRIPT_GENERATION_SUCCEEDED
                : NotificationMessage.NotificationType.SCRIPT_GENERATION_FAILED;
        NotificationMessage.NotificationLevel level = succeeded
                ? NotificationMessage.NotificationLevel.SUCCESS
                : NotificationMessage.NotificationLevel.ERROR;
        safePublishNotification(
                requestedBy,
                tenantId,
                type,
                level,
                title,
                content,
                "TEST_CASE",
                String.valueOf(testCase.getId())
        );
    }

    private void safePublishNotification(String requestedBy,
                                         Long tenantId,
                                         NotificationMessage.NotificationType type,
                                         NotificationMessage.NotificationLevel level,
                                         String title,
                                         String content,
                                         String relatedResourceType,
                                         String relatedResourceId) {
        try {
            notificationService.publishToUser(
                    requestedBy,
                    tenantId,
                    type,
                    level,
                    title,
                    content,
                    relatedResourceType,
                    relatedResourceId
            );
        } catch (Exception ex) {
            NotificationMessage.NotificationType compatibleType = toLegacyCompatibleType(type);
            if (compatibleType != type) {
                try {
                    notificationService.publishToUser(
                            requestedBy,
                            tenantId,
                            compatibleType,
                            level,
                            title,
                            content,
                            relatedResourceType,
                            relatedResourceId
                    );
                    return;
                } catch (Exception retryEx) {
                    log.warn("Failed to publish compatibility notification. user={}, tenant={}, type={}, reason={}",
                            requestedBy, tenantId, compatibleType, retryEx.getMessage());
                }
            }
            log.warn("Failed to publish script generation notification. user={}, tenant={}, type={}, reason={}",
                    requestedBy, tenantId, type, ex.getMessage());
        }
    }

    private NotificationMessage.NotificationType toLegacyCompatibleType(NotificationMessage.NotificationType type) {
        if (type == NotificationMessage.NotificationType.SCRIPT_GENERATION_SUCCEEDED) {
            return NotificationMessage.NotificationType.CASE_GENERATION_SUCCEEDED;
        }
        if (type == NotificationMessage.NotificationType.SCRIPT_GENERATION_FAILED) {
            return NotificationMessage.NotificationType.CASE_GENERATION_FAILED;
        }
        return type;
    }

    private String safeErrorMessage(Exception ex) {
        if (ex == null) return "未知错误";
        String message = ex.getMessage();
        if (!StringUtils.hasText(message)) return "未知错误";
        String normalized = message.trim();
        return normalized.length() > 240 ? normalized.substring(0, 240) + "..." : normalized;
    }

    private String defaultIfBlank(String value, String fallback) {
        return StringUtils.hasText(value) ? value.trim() : fallback;
    }

    private record ScriptGenerationTaskView(
            String taskId,
            Long testCaseId,
            String caseNumber,
            String status,
            String requestedBy,
            LocalDateTime createdAt,
            LocalDateTime startedAt,
            LocalDateTime finishedAt,
            Long pollIntervalMs,
            String pollPath,
            List<TestScriptDTO.ScriptGenerationEventDTO> events,
            TestScriptDTO.ScriptGenerationSessionDTO result,
            String errorMessage
    ) {
        static ScriptGenerationTaskView from(
                TestScriptGenerationTaskService.ScriptGenerationTask task,
                boolean includeResult,
                long pollIntervalMs) {
            return new ScriptGenerationTaskView(
                    task.getTaskId(),
                    task.getTestCaseId(),
                    task.getCaseNumber(),
                    task.getStatus().name(),
                    task.getRequestedBy(),
                    task.getCreatedAt(),
                    task.getStartedAt(),
                    task.getFinishedAt(),
                    pollIntervalMs,
                    "/api/test-scripts/generation-tasks/" + task.getTaskId(),
                    task.getEvents() == null ? List.of() : task.getEvents(),
                    includeResult ? task.getResult() : null,
                    task.getErrorMessage()
            );
        }
    }

    private record LatestScriptGenerationView(
            Long testCaseId,
            String caseNumber,
            String status,
            String taskId,
            Long pollIntervalMs,
            String pollPath,
            LocalDateTime generatedAt,
            List<TestScriptDTO.ScriptGenerationEventDTO> events,
            TestScriptDTO.ScriptGenerationSessionDTO result,
            String errorMessage,
            boolean hasRecord
    ) {
        static LatestScriptGenerationView fromTask(
                TestScriptGenerationTaskService.ScriptGenerationTask task,
                long pollIntervalMs) {
            LocalDateTime generatedAt = Optional.ofNullable(task.getFinishedAt())
                    .orElse(Optional.ofNullable(task.getStartedAt()).orElse(task.getCreatedAt()));
            TestScriptDTO.ScriptGenerationSessionDTO result = task.getResult();
            return new LatestScriptGenerationView(
                    task.getTestCaseId(),
                    task.getCaseNumber(),
                    task.getStatus().name(),
                    task.getTaskId(),
                    pollIntervalMs,
                    "/api/test-scripts/generation-tasks/" + task.getTaskId(),
                    generatedAt,
                    task.getEvents() == null ? List.of() : task.getEvents(),
                    result,
                    task.getErrorMessage(),
                    result != null && result.getLatestRecord() != null
            );
        }

        static LatestScriptGenerationView fromPersisted(
                Long testCaseId,
                String caseNumber,
                TestScriptDTO.ScriptGenerationSessionDTO result) {
            return new LatestScriptGenerationView(
                    testCaseId,
                    caseNumber,
                    "SUCCEEDED",
                    null,
                    null,
                    null,
                    result != null ? result.getUpdatedAt() : null,
                    List.of(),
                    result,
                    null,
                    result != null && result.getLatestRecord() != null
            );
        }

        static LatestScriptGenerationView empty(Long testCaseId, String caseNumber) {
            return new LatestScriptGenerationView(
                    testCaseId,
                    caseNumber,
                    "NONE",
                    null,
                    null,
                    null,
                    null,
                    List.of(),
                    null,
                    null,
                    false
            );
        }
    }
}
