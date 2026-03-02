package com.autotest.platform.controller;

import com.autotest.platform.ai.OpenAIService;
import com.autotest.platform.dto.ApiResponse;
import com.autotest.platform.dto.PageResponse;
import com.autotest.platform.dto.TestCaseDTO;
import com.autotest.platform.dto.UserStoryDTO;
import com.autotest.platform.entity.NotificationMessage;
import com.autotest.platform.entity.UserStory;
import com.autotest.platform.service.NotificationService;
import com.autotest.platform.service.TestCaseService;
import com.autotest.platform.service.UserStoryAnalysisTaskService;
import com.autotest.platform.service.UserStoryCaseGenerationTaskService;
import com.autotest.platform.service.UserStoryService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
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

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.EnumSet;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@RestController
@RequestMapping("/user-stories")
@RequiredArgsConstructor
@Slf4j
@CrossOrigin(origins = "*")
public class UserStoryController {
    
    private final UserStoryService userStoryService;
    private final TestCaseService testCaseService;
    private final UserStoryAnalysisTaskService analysisTaskService;
    private final UserStoryCaseGenerationTaskService caseGenerationTaskService;
    private final NotificationService notificationService;
    private final OpenAIService openAIService;
    private final ObjectMapper objectMapper;
    private static final Pattern ISSUE_KEY_PATTERN = Pattern.compile("([A-Z][A-Z0-9]+-\\d+)");
    private static final int CASE_GENERATION_CONVERSATION_RETENTION = 6;
    
    @GetMapping
    public ResponseEntity<ApiResponse<PageResponse<UserStoryDTO>>> getAllUserStories(
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) UserStory.Status status,
            @RequestParam(required = false) UserStory.Priority priority,
            @RequestParam(required = false) String sprint,
            @RequestParam(defaultValue = "createdAt,desc") String[] sort) {

        String sortField = "createdAt";
        Sort.Direction direction = Sort.Direction.DESC;
        if (sort.length > 0 && sort[0] != null && !sort[0].isBlank()) {
            String firstSort = sort[0];
            if (firstSort.contains(",")) {
                String[] split = firstSort.split(",");
                if (split.length > 0 && !split[0].isBlank()) {
                    sortField = split[0].trim();
                }
                if (split.length > 1 && "asc".equalsIgnoreCase(split[1].trim())) {
                    direction = Sort.Direction.ASC;
                }
            } else {
                sortField = firstSort.trim();
            }
        }
        if (sort.length > 1 && "asc".equalsIgnoreCase(sort[1])) {
            direction = Sort.Direction.ASC;
        }

        Pageable pageable = PageRequest.of(page, size, Sort.by(direction, sortField));
        String normalizedKeyword = keyword == null ? null : keyword.trim();
        if (normalizedKeyword != null && normalizedKeyword.isEmpty()) {
            normalizedKeyword = null;
        }
        String normalizedSprint = sprint == null ? null : sprint.trim();
        if (normalizedSprint != null && normalizedSprint.isEmpty()) {
            normalizedSprint = null;
        }

        boolean hasFilters = normalizedKeyword != null || status != null || priority != null || normalizedSprint != null;
        PageResponse<UserStoryDTO> userStories = hasFilters
                ? PageResponse.from(userStoryService.getUserStoriesByFilters(normalizedKeyword, status, priority, normalizedSprint, pageable))
                : PageResponse.from(userStoryService.getAllUserStories(pageable));
        return ResponseEntity.ok(ApiResponse.success(userStories));
    }
    
    @GetMapping("/{id}")
    public ResponseEntity<ApiResponse<UserStoryDTO>> getUserStoryById(@PathVariable Long id) {
        UserStoryDTO userStory = userStoryService.getUserStoryById(id);
        return ResponseEntity.ok(ApiResponse.success(userStory));
    }
    
    @GetMapping("/number/{usNumber}")
    public ResponseEntity<ApiResponse<UserStoryDTO>> getUserStoryByNumber(@PathVariable String usNumber) {
        UserStoryDTO userStory = userStoryService.getUserStoryByNumber(usNumber);
        return ResponseEntity.ok(ApiResponse.success(userStory));
    }
    
    @GetMapping("/search")
    public ResponseEntity<ApiResponse<PageResponse<UserStoryDTO>>> searchUserStories(
            @RequestParam String keyword,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        
        Pageable pageable = PageRequest.of(page, size);
        PageResponse<UserStoryDTO> userStories = PageResponse.from(userStoryService.searchUserStories(keyword, pageable));
        return ResponseEntity.ok(ApiResponse.success(userStories));
    }
    
    @GetMapping("/status/{status}")
    public ResponseEntity<ApiResponse<PageResponse<UserStoryDTO>>> getUserStoriesByStatus(
            @PathVariable UserStory.Status status,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        
        Pageable pageable = PageRequest.of(page, size);
        PageResponse<UserStoryDTO> userStories = PageResponse.from(userStoryService.getUserStoriesByStatus(status, pageable));
        return ResponseEntity.ok(ApiResponse.success(userStories));
    }
    
    @GetMapping("/sprint/{sprint}")
    public ResponseEntity<ApiResponse<List<UserStoryDTO>>> getUserStoriesBySprint(@PathVariable String sprint) {
        List<UserStoryDTO> userStories = userStoryService.getUserStoriesBySprint(sprint);
        return ResponseEntity.ok(ApiResponse.success(userStories));
    }

    @GetMapping("/sprints")
    public ResponseEntity<ApiResponse<List<String>>> getAllSprints() {
        return ResponseEntity.ok(ApiResponse.success(userStoryService.getAllSprints()));
    }
    
    @PostMapping
    public ResponseEntity<ApiResponse<UserStoryDTO>> createUserStory(
            @RequestBody UserStoryDTO.CreateRequest request,
            Authentication authentication) {
        
        UserStoryDTO createdUS = userStoryService.createUserStory(request, authentication.getName());
        return ResponseEntity.ok(ApiResponse.success("User Story created", createdUS));
    }
    
    @PutMapping("/{id}")
    public ResponseEntity<ApiResponse<UserStoryDTO>> updateUserStory(
            @PathVariable Long id,
            @RequestBody UserStoryDTO.UpdateRequest request) {
        
        UserStoryDTO updatedUS = userStoryService.updateUserStory(id, request);
        return ResponseEntity.ok(ApiResponse.success("User Story updated", updatedUS));
    }
    
    @DeleteMapping("/{id}")
    public ResponseEntity<ApiResponse<Void>> deleteUserStory(@PathVariable Long id) {
        UserStoryDTO userStory = userStoryService.getUserStoryById(id);
        if (userStory.getStatus() == UserStory.Status.ANALYZING) {
            return ResponseEntity.badRequest().body(ApiResponse.error(400, "US 正在分析中，暂不允许删除"));
        }
        boolean analyzingTaskRunning = analysisTaskService.findLatestTaskByUserStoryId(id)
                .map(task -> !task.isTerminal())
                .orElse(false);
        if (analyzingTaskRunning) {
            return ResponseEntity.badRequest().body(ApiResponse.error(400, "US 正在分析中，暂不允许删除"));
        }
        boolean generationTaskRunning = caseGenerationTaskService.findLatestTaskByUserStoryId(id)
                .map(task -> !task.isTerminal())
                .orElse(false);
        if (generationTaskRunning) {
            return ResponseEntity.badRequest().body(ApiResponse.error(400, "US 正在生成用例中，暂不允许删除"));
        }
        userStoryService.deleteUserStory(id);
        return ResponseEntity.ok(ApiResponse.success("User Story deleted", null));
    }
    
    @PostMapping("/{id}/analyze")
    public ResponseEntity<ApiResponse<AnalyzeTaskView>> analyzeUserStory(
            @PathVariable Long id,
            @RequestBody(required = false) UserStoryDTO.AIAnalysisRequest request,
            Authentication authentication) {
        UserStoryDTO userStory = userStoryService.getUserStoryById(id);
        if (userStory.getStatus() == UserStory.Status.ARCHIVED) {
            return ResponseEntity.badRequest().body(ApiResponse.error(400, "US 已归档，无法继续分析"));
        }
        String description = request != null && StringUtils.hasText(request.getDescription())
                ? request.getDescription()
                : userStory.getDescription();
        String acceptanceCriteria = request != null && StringUtils.hasText(request.getAcceptanceCriteria())
                ? request.getAcceptanceCriteria()
                : userStory.getAcceptanceCriteria();
        String requestedBy = authentication != null ? authentication.getName() : "system";

        Optional<UserStoryAnalysisTaskService.AnalysisTask> latestTask = analysisTaskService.findLatestTaskByUserStoryId(id);
        if (latestTask.isPresent() && !latestTask.get().isTerminal()) {
            AnalyzeTaskView runningView = AnalyzeTaskView.from(latestTask.get(), true, 2000L);
            ApiResponse<AnalyzeTaskView> runningResponse = ApiResponse.<AnalyzeTaskView>builder()
                    .success(true)
                    .code(202)
                    .message("已有进行中的分析任务")
                    .data(runningView)
                    .timestamp(LocalDateTime.now())
                    .build();
            return ResponseEntity.status(HttpStatus.ACCEPTED).body(runningResponse);
        }

        userStoryService.transitionWorkflowStatus(id, UserStory.Status.ANALYZING);
        UserStoryAnalysisTaskService.AnalysisTask task = analysisTaskService.submit(
                id,
                userStory.getUsNumber(),
                requestedBy,
                () -> {
                    try {
                        UserStoryDTO.AIAnalysisResponse analysis = analyzeUserStoryNow(userStory, description, acceptanceCriteria);
                        userStoryService.saveLatestAnalysis(id, analysis);
                        userStoryService.transitionWorkflowStatusIfCurrent(
                                id,
                                EnumSet.of(UserStory.Status.ANALYZING, UserStory.Status.DRAFT, UserStory.Status.READY),
                                UserStory.Status.READY
                        );
                        publishAnalysisNotification(requestedBy, userStory, true, analysis, null);
                        return analysis;
                    } catch (Exception ex) {
                        userStoryService.transitionWorkflowStatusIfCurrent(
                                id,
                                EnumSet.of(UserStory.Status.ANALYZING),
                                UserStory.Status.DRAFT
                        );
                        publishAnalysisNotification(requestedBy, userStory, false, null, ex);
                        throw ex;
                    }
                }
        );

        AnalyzeTaskView view = AnalyzeTaskView.from(task, true, 2000L);
        ApiResponse<AnalyzeTaskView> response = ApiResponse.<AnalyzeTaskView>builder()
                .success(true)
                .code(202)
                .message("分析任务已提交")
                .data(view)
                .timestamp(LocalDateTime.now())
                .build();
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(response);
    }

    @PostMapping("/{id}/analyze/sync")
    public ResponseEntity<ApiResponse<UserStoryDTO.AIAnalysisResponse>> analyzeUserStorySync(
            @PathVariable Long id,
            @RequestBody(required = false) UserStoryDTO.AIAnalysisRequest request) {
        UserStoryDTO userStory = userStoryService.getUserStoryById(id);
        if (userStory.getStatus() == UserStory.Status.ARCHIVED) {
            return ResponseEntity.badRequest().body(ApiResponse.error(400, "US 已归档，无法继续分析"));
        }
        String description = request != null && StringUtils.hasText(request.getDescription())
                ? request.getDescription()
                : userStory.getDescription();
        String acceptanceCriteria = request != null && StringUtils.hasText(request.getAcceptanceCriteria())
                ? request.getAcceptanceCriteria()
                : userStory.getAcceptanceCriteria();
        try {
            userStoryService.transitionWorkflowStatus(id, UserStory.Status.ANALYZING);
            UserStoryDTO.AIAnalysisResponse response = analyzeUserStoryNow(userStory, description, acceptanceCriteria);
            userStoryService.saveLatestAnalysis(id, response);
            userStoryService.transitionWorkflowStatusIfCurrent(
                    id,
                    EnumSet.of(UserStory.Status.ANALYZING, UserStory.Status.DRAFT, UserStory.Status.READY),
                    UserStory.Status.READY
            );
            return ResponseEntity.ok(ApiResponse.success("Analysis completed", response));
        } catch (Exception ex) {
            userStoryService.transitionWorkflowStatusIfCurrent(
                    id,
                    EnumSet.of(UserStory.Status.ANALYZING),
                    UserStory.Status.DRAFT
            );
            throw ex;
        }
    }

    @GetMapping("/analysis-tasks/{taskId}")
    public ResponseEntity<ApiResponse<AnalyzeTaskView>> getAnalyzeTask(@PathVariable String taskId) {
        return analysisTaskService.getTask(taskId)
                .map(task -> ResponseEntity.ok(ApiResponse.success(AnalyzeTaskView.from(task, true, 2000L))))
                .orElseGet(() -> ResponseEntity.status(HttpStatus.NOT_FOUND)
                        .body(ApiResponse.error(404, "分析任务不存在或已过期")));
    }

    @GetMapping("/{id}/analysis/latest")
    public ResponseEntity<ApiResponse<LatestAnalysisView>> getLatestAnalysis(@PathVariable Long id) {
        UserStoryDTO userStory = userStoryService.getUserStoryById(id);
        Optional<UserStoryAnalysisTaskService.AnalysisTask> latestTask = analysisTaskService.findLatestTaskByUserStoryId(id);
        if (latestTask.isPresent()) {
            UserStoryAnalysisTaskService.AnalysisTask task = latestTask.get();
            if (!task.isTerminal()) {
                return ResponseEntity.ok(ApiResponse.success(LatestAnalysisView.fromTask(task, 2000L)));
            }
            if (task.getStatus() == UserStoryAnalysisTaskService.TaskStatus.SUCCEEDED && task.getResult() != null) {
                return ResponseEntity.ok(ApiResponse.success(LatestAnalysisView.fromTask(task, 2000L)));
            }
            if (task.getStatus() == UserStoryAnalysisTaskService.TaskStatus.FAILED) {
                return ResponseEntity.ok(ApiResponse.success(LatestAnalysisView.fromTask(task, 2000L)));
            }
        }

        Optional<UserStoryService.LatestAnalysisSnapshot> persisted = userStoryService.getLatestAnalysis(id);
        if (persisted.isPresent()) {
            UserStoryService.LatestAnalysisSnapshot snapshot = persisted.get();
            return ResponseEntity.ok(ApiResponse.success(
                    LatestAnalysisView.fromPersisted(id, userStory.getUsNumber(), snapshot.analysis(), snapshot.analyzedAt())
            ));
        }
        return ResponseEntity.ok(ApiResponse.success(LatestAnalysisView.empty(id, userStory.getUsNumber())));
    }
    
    @PostMapping("/{id}/generate-test-cases")
    public ResponseEntity<ApiResponse<CaseGenerationTaskView>> generateTestCases(
            @PathVariable Long id,
            @RequestBody(required = false) GenerateTestCasesRequest request,
            Authentication authentication) {
        return submitCaseGenerationTask(id, request, authentication, false);
    }

    @PostMapping("/{id}/case-generation/refine")
    public ResponseEntity<ApiResponse<CaseGenerationTaskView>> refineGeneratedTestCases(
            @PathVariable Long id,
            @RequestBody GenerateTestCasesRequest request,
            Authentication authentication) {
        return submitCaseGenerationTask(id, request, authentication, true);
    }

    @GetMapping("/case-generation-tasks/{taskId}")
    public ResponseEntity<ApiResponse<CaseGenerationTaskView>> getCaseGenerationTask(@PathVariable String taskId) {
        return caseGenerationTaskService.getTask(taskId)
                .map(task -> ResponseEntity.ok(ApiResponse.success(CaseGenerationTaskView.from(task, true, 1500L))))
                .orElseGet(() -> ResponseEntity.status(HttpStatus.NOT_FOUND)
                        .body(ApiResponse.error(404, "用例生成任务不存在或已过期")));
    }

    @GetMapping("/{id}/case-generation/latest")
    public ResponseEntity<ApiResponse<LatestCaseGenerationView>> getLatestCaseGeneration(@PathVariable Long id) {
        UserStoryDTO userStory = userStoryService.getUserStoryById(id);
        Optional<UserStoryService.LatestCaseGenerationSnapshot> persisted = userStoryService.getLatestCaseGeneration(id);
        Optional<UserStoryCaseGenerationTaskService.CaseGenerationTask> latestTask = caseGenerationTaskService.findLatestTaskByUserStoryId(id);
        if (latestTask.isPresent()) {
            UserStoryCaseGenerationTaskService.CaseGenerationTask task = latestTask.get();
            if (!task.isTerminal()) {
                return ResponseEntity.ok(ApiResponse.success(LatestCaseGenerationView.fromTask(task, 1500L)));
            }
            if (task.getStatus() == UserStoryCaseGenerationTaskService.TaskStatus.FAILED) {
                return ResponseEntity.ok(ApiResponse.success(LatestCaseGenerationView.fromTask(task, 1500L)));
            }
            if (task.getStatus() == UserStoryCaseGenerationTaskService.TaskStatus.SUCCEEDED) {
                if (persisted.isPresent() && persisted.get().session() != null) {
                    UserStoryService.LatestCaseGenerationSnapshot snapshot = persisted.get();
                    return ResponseEntity.ok(ApiResponse.success(
                            LatestCaseGenerationView.fromSucceededTaskWithPersisted(
                                    task,
                                    snapshot.session(),
                                    snapshot.generatedAt(),
                                    1500L
                            )
                    ));
                }
                if (task.getResult() != null) {
                    return ResponseEntity.ok(ApiResponse.success(LatestCaseGenerationView.fromTask(task, 1500L)));
                }
            }
        }

        if (persisted.isPresent()) {
            UserStoryService.LatestCaseGenerationSnapshot snapshot = persisted.get();
            return ResponseEntity.ok(ApiResponse.success(
                    LatestCaseGenerationView.fromPersisted(id, userStory.getUsNumber(), snapshot.session(), snapshot.generatedAt())
            ));
        }
        return ResponseEntity.ok(ApiResponse.success(LatestCaseGenerationView.empty(id, userStory.getUsNumber())));
    }

    @PostMapping("/{id}/case-generation/adopt")
    public ResponseEntity<ApiResponse<List<TestCaseDTO>>> adoptGeneratedTestCases(
            @PathVariable Long id,
            @RequestBody(required = false) AdoptGeneratedCasesRequest request,
            Authentication authentication) {
        UserStoryDTO userStory = userStoryService.getUserStoryById(id);
        UserStory.Status currentStatus = userStory.getStatus();
        if (currentStatus == UserStory.Status.ARCHIVED) {
            return ResponseEntity.badRequest().body(ApiResponse.error(400, "US 已归档，无法继续采纳"));
        }
        if (currentStatus == UserStory.Status.ANALYZING) {
            return ResponseEntity.badRequest().body(
                    ApiResponse.error(400, "US 当前为分析中，请稍后再采纳生成草稿")
            );
        }
        UserStoryDTO.CaseGenerationSessionDTO latestSession = resolveLatestGenerationSession(id)
                .orElseThrow(() -> new RuntimeException("未找到可采纳的生成结果，请先生成用例"));

        List<UserStoryDTO.GeneratedTestCaseDraftDTO> drafts = resolveGenerationDrafts(latestSession);
        if (drafts.isEmpty()) {
            throw new RuntimeException("当前没有可采纳的测试用例草稿");
        }

        Set<String> selectedDraftIds = new LinkedHashSet<>();
        if (request != null && request.getDraftIds() != null) {
            request.getDraftIds().stream()
                    .filter(StringUtils::hasText)
                    .map(String::trim)
                    .forEach(selectedDraftIds::add);
        }
        if (selectedDraftIds.isEmpty()) {
            drafts.stream()
                    .map(UserStoryDTO.GeneratedTestCaseDraftDTO::getDraftId)
                    .filter(StringUtils::hasText)
                    .forEach(selectedDraftIds::add);
        }

        List<String> adopted = new ArrayList<>(Optional.ofNullable(latestSession.getAdoptedDraftIds()).orElse(List.of()));
        Set<String> adoptedSet = new LinkedHashSet<>(adopted);

        List<UserStoryDTO.GeneratedTestCaseDraftDTO> draftsToAdopt = drafts.stream()
                .filter(draft -> selectedDraftIds.contains(defaultIfBlank(draft.getDraftId(), "")))
                .filter(draft -> !adoptedSet.contains(defaultIfBlank(draft.getDraftId(), "")))
                .collect(Collectors.toList());
        if (draftsToAdopt.isEmpty()) {
            throw new RuntimeException("所选草稿已采纳，无需重复采纳");
        }

        String operator = authentication != null ? authentication.getName() : "system";
        List<TestCaseDTO> createdCases = draftsToAdopt.stream()
                .map(draft -> testCaseService.createTestCase(toCreateRequest(draft, id, userStory), operator))
                .collect(Collectors.toList());
        if (createdCases.isEmpty()) {
            throw new RuntimeException("未匹配到可采纳的草稿，请刷新后重试");
        }

        draftsToAdopt.stream()
                .map(UserStoryDTO.GeneratedTestCaseDraftDTO::getDraftId)
                .filter(StringUtils::hasText)
                .forEach(draftId -> {
            if (!adopted.contains(draftId)) {
                adopted.add(draftId);
            }
        });
        UserStoryDTO.CaseGenerationSessionDTO updatedSession = latestSession.toBuilder()
                .adoptedDraftIds(adopted)
                .summary("已累计采纳 " + adopted.size() + " 条草稿，本次创建 " + createdCases.size() + " 条关联用例")
                .updatedAt(LocalDateTime.now())
                .build();
        userStoryService.saveLatestCaseGeneration(id, updatedSession);
        userStoryService.transitionWorkflowStatus(id, UserStory.Status.PENDING_EXECUTION);

        return ResponseEntity.ok(ApiResponse.success("已采纳并创建关联测试用例", createdCases));
    }

    @DeleteMapping("/{id}/case-generation/records/{recordId}")
    public ResponseEntity<ApiResponse<UserStoryDTO.CaseGenerationSessionDTO>> deleteCaseGenerationRecord(
            @PathVariable Long id,
            @PathVariable String recordId) {
        UserStoryDTO.CaseGenerationSessionDTO latestSession = resolveLatestGenerationSession(id)
                .orElseThrow(() -> new RuntimeException("未找到可删除的生成记录"));
        String normalizedRecordId = defaultIfBlank(recordId, "").trim();
        if (!StringUtils.hasText(normalizedRecordId)) {
            throw new RuntimeException("记录ID不能为空");
        }

        UserStoryDTO.CaseGenerationSessionDTO updatedSession = removeCaseGenerationRecord(latestSession, normalizedRecordId);
        userStoryService.saveLatestCaseGeneration(id, updatedSession);
        return ResponseEntity.ok(ApiResponse.success("生成记录已删除", updatedSession));
    }

    @PostMapping("/import/test-connection")
    public ResponseEntity<ApiResponse<Map<String, Object>>> testImportConnection(
            @RequestBody(required = false) ImportRequest request) {
        String sourceType = normalizeSourceType(request == null ? null : request.getSourceType());
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("sourceType", sourceType);

        if ("JIRA".equals(sourceType)) {
            if (!StringUtils.hasText(request == null ? null : request.getServerUrl())) {
                return ResponseEntity.badRequest()
                        .body(ApiResponse.error(400, "JIRA Server URL 不能为空"));
            }
            return ResponseEntity.ok(ApiResponse.success(pingServer(request.getServerUrl())));
        }

        payload.put("reachable", true);
        payload.put("message", sourceType + " 本地导入模式可用");
        return ResponseEntity.ok(ApiResponse.success(payload));
    }

    @PostMapping("/import")
    public ResponseEntity<ApiResponse<List<UserStoryDTO>>> importUserStories(
            @RequestBody ImportRequest request,
            Authentication authentication) {
        String username = authentication != null ? authentication.getName() : "system";
        int maxCount = request.getMaxCount() != null && request.getMaxCount() > 0
                ? Math.min(request.getMaxCount(), 50)
                : 20;
        List<ImportSeed> seeds = parseImportSeeds(request, maxCount);

        if (seeds.isEmpty()) {
            return ResponseEntity.badRequest()
                    .body(ApiResponse.error(400, "没有可导入的数据，请检查导入内容"));
        }

        AtomicInteger sequence = new AtomicInteger(1);
        List<UserStoryDTO> created = new ArrayList<>();
        for (ImportSeed seed : seeds) {
            String usNumber = buildImportUsNumber(request.getProjectKey(), sequence.getAndIncrement());
            UserStoryDTO.CreateRequest createRequest = UserStoryDTO.CreateRequest.builder()
                    .usNumber(usNumber)
                    .title(seed.title())
                    .description(seed.description())
                    .acceptanceCriteria(seed.acceptanceCriteria())
                    .priority(request.getPriority() != null ? request.getPriority() : UserStory.Priority.MEDIUM)
                    .sprint(StringUtils.hasText(request.getSprint()) ? request.getSprint() : "Sprint 1")
                    .epic(StringUtils.hasText(request.getEpic()) ? request.getEpic() : "Imported")
                    .storyPoints(StringUtils.hasText(request.getStoryPoints()) ? request.getStoryPoints() : "3")
                    .build();
            created.add(userStoryService.createUserStory(createRequest, username));
        }

        return ResponseEntity.ok(ApiResponse.success("US 导入成功", created));
    }

    private UserStoryDTO.AIAnalysisResponse analyzeUserStoryNow(
            UserStoryDTO userStory,
            String description,
            String acceptanceCriteria) {
        String analysisRaw = openAIService.analyzeUserStory(description, acceptanceCriteria);
        return parseAIAnalysisResponse(
                analysisRaw,
                userStory.getTitle(),
                description,
                acceptanceCriteria
        );
    }

    private record AnalyzeTaskView(
            String taskId,
            Long userStoryId,
            String userStoryNumber,
            String status,
            String requestedBy,
            LocalDateTime createdAt,
            LocalDateTime startedAt,
            LocalDateTime finishedAt,
            Long pollIntervalMs,
            String pollPath,
            UserStoryDTO.AIAnalysisResponse result,
            String errorMessage
    ) {
        static AnalyzeTaskView from(
                UserStoryAnalysisTaskService.AnalysisTask task,
                boolean includeResult,
                long pollIntervalMs) {
            return new AnalyzeTaskView(
                    task.getTaskId(),
                    task.getUserStoryId(),
                    task.getUserStoryNumber(),
                    task.getStatus().name(),
                    task.getRequestedBy(),
                    task.getCreatedAt(),
                    task.getStartedAt(),
                    task.getFinishedAt(),
                    pollIntervalMs,
                    "/api/user-stories/analysis-tasks/" + task.getTaskId(),
                    includeResult ? task.getResult() : null,
                    task.getErrorMessage()
            );
        }
    }

    private record LatestAnalysisView(
            Long userStoryId,
            String userStoryNumber,
            String status,
            String taskId,
            Long pollIntervalMs,
            String pollPath,
            LocalDateTime analyzedAt,
            UserStoryDTO.AIAnalysisResponse result,
            String errorMessage,
            boolean hasResult
    ) {
        static LatestAnalysisView fromTask(UserStoryAnalysisTaskService.AnalysisTask task, long pollIntervalMs) {
            LocalDateTime analyzedAt = Optional.ofNullable(task.getFinishedAt())
                    .orElse(Optional.ofNullable(task.getStartedAt()).orElse(task.getCreatedAt()));
            return new LatestAnalysisView(
                    task.getUserStoryId(),
                    task.getUserStoryNumber(),
                    task.getStatus().name(),
                    task.getTaskId(),
                    pollIntervalMs,
                    "/api/user-stories/analysis-tasks/" + task.getTaskId(),
                    analyzedAt,
                    task.getResult(),
                    task.getErrorMessage(),
                    task.getResult() != null
            );
        }

        static LatestAnalysisView fromPersisted(
                Long userStoryId,
                String userStoryNumber,
                UserStoryDTO.AIAnalysisResponse result,
                LocalDateTime analyzedAt) {
            return new LatestAnalysisView(
                    userStoryId,
                    userStoryNumber,
                    "SUCCEEDED",
                    null,
                    null,
                    null,
                    analyzedAt,
                    result,
                    null,
                    result != null
            );
        }

        static LatestAnalysisView empty(Long userStoryId, String userStoryNumber) {
            return new LatestAnalysisView(
                    userStoryId,
                    userStoryNumber,
                    "NONE",
                    null,
                    null,
                    null,
                    null,
                    null,
                    null,
                    false
            );
        }
    }

    private ResponseEntity<ApiResponse<CaseGenerationTaskView>> submitCaseGenerationTask(
            Long id,
            GenerateTestCasesRequest request,
            Authentication authentication,
            boolean requireFeedback) {
        UserStoryDTO userStory = userStoryService.getUserStoryById(id);
        UserStory.Status currentStatus = userStory.getStatus();
        if (currentStatus == UserStory.Status.ARCHIVED) {
            return ResponseEntity.badRequest().body(ApiResponse.error(400, "US 已归档，无法生成用例"));
        }
        int count = normalizeGenerateCount(request == null ? null : request.getCount());
        String feedback = request != null && StringUtils.hasText(request.getFeedback())
                ? request.getFeedback().trim()
                : null;
        if (requireFeedback && !StringUtils.hasText(feedback)) {
            return ResponseEntity.badRequest().body(ApiResponse.error(400, "请输入修复意见后再进行二次生成"));
        }

        String requestedBy = authentication != null ? authentication.getName() : "system";
        Optional<UserStoryCaseGenerationTaskService.CaseGenerationTask> latestTask = caseGenerationTaskService.findLatestTaskByUserStoryId(id);
        if (latestTask.isPresent() && !latestTask.get().isTerminal()) {
            CaseGenerationTaskView runningView = CaseGenerationTaskView.from(latestTask.get(), true, 1500L);
            ApiResponse<CaseGenerationTaskView> runningResponse = ApiResponse.<CaseGenerationTaskView>builder()
                    .success(true)
                    .code(202)
                    .message("已有进行中的用例生成任务")
                    .data(runningView)
                    .timestamp(LocalDateTime.now())
                    .build();
            return ResponseEntity.status(HttpStatus.ACCEPTED).body(runningResponse);
        }

        Optional<UserStoryService.LatestCaseGenerationSnapshot> persistedSnapshot = userStoryService.getLatestCaseGeneration(id);
        UserStoryDTO.CaseGenerationSessionDTO previousSession = persistedSnapshot.map(UserStoryService.LatestCaseGenerationSnapshot::session).orElse(null);
        int nextVersion = previousSession != null && previousSession.getVersion() != null
                ? previousSession.getVersion() + 1
                : 1;
        String sessionId = previousSession != null && StringUtils.hasText(previousSession.getSessionId())
                ? previousSession.getSessionId()
                : UUID.randomUUID().toString();
        List<UserStoryDTO.CaseGenerationMessageDTO> conversationSeed = buildConversationSeed(previousSession, feedback);

        UserStoryCaseGenerationTaskService.CaseGenerationTask task = caseGenerationTaskService.submit(
                id,
                userStory.getUsNumber(),
                requestedBy,
                logger -> {
                    try {
                        logger.log("CONTEXT", "正在整理 US 描述与验收标准");
                        String promptSource = buildCaseGenerationPrompt(userStory, count, previousSession, conversationSeed);

                        logger.log("MODEL", "正在调用大模型生成测试用例草稿");
                        String aiRaw = openAIService.generateTestCases(promptSource);

                        logger.log("PARSING", "正在解析模型输出并归一化结构");
                        List<TestCaseDTO.CreateRequest> parsedRequests = parseGeneratedTestCases(aiRaw, id);
                        logger.log("QUALITY", "正在执行质量检查与覆盖补齐");
                        List<TestCaseDTO.CreateRequest> generatedRequests = optimizeGeneratedTestCases(
                                userStory,
                                id,
                                parsedRequests,
                                count,
                                logger
                        );
                        if (generatedRequests.isEmpty()) {
                            logger.log("FALLBACK", "模型结果不可用，使用高质量回退草稿");
                            generatedRequests = buildFallbackTestCases(userStory, id, count);
                        }

                        List<UserStoryDTO.GeneratedTestCaseDraftDTO> drafts = toDraftCases(generatedRequests, count);
                        logger.log("DRAFT", "已整理 " + drafts.size() + " 条候选用例草稿");

                        UserStoryDTO.CaseGenerationSessionDTO session = buildCaseGenerationSession(
                                sessionId,
                                nextVersion,
                                userStory,
                                previousSession,
                                conversationSeed,
                                drafts,
                                feedback
                        );
                        userStoryService.saveLatestCaseGeneration(id, session);
                        userStoryService.transitionWorkflowStatus(id, UserStory.Status.IN_PROGRESS);
                        publishCaseGenerationNotification(requestedBy, userStory, true, session, null);
                        return session;
                    } catch (Exception ex) {
                        publishCaseGenerationNotification(requestedBy, userStory, false, null, ex);
                        throw ex;
                    }
                }
        );

        CaseGenerationTaskView view = CaseGenerationTaskView.from(task, true, 1500L);
        ApiResponse<CaseGenerationTaskView> response = ApiResponse.<CaseGenerationTaskView>builder()
                .success(true)
                .code(202)
                .message("用例生成任务已提交")
                .data(view)
                .timestamp(LocalDateTime.now())
                .build();
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(response);
    }

    private void publishAnalysisNotification(String requestedBy,
                                             UserStoryDTO userStory,
                                             boolean succeeded,
                                             UserStoryDTO.AIAnalysisResponse analysis,
                                             Exception error) {
        if (userStory == null || userStory.getTenantId() == null) return;
        String usNumber = defaultIfBlank(userStory.getUsNumber(), "US");
        String usTitle = defaultIfBlank(userStory.getTitle(), "未命名需求");
        String title = succeeded
                ? String.format("%s 分析完成", usNumber)
                : String.format("%s 分析失败", usNumber);
        String content = succeeded
                ? String.format("US「%s」质量分析已完成，评分 %d 分。", usTitle, analysis != null && analysis.getQualityScore() != null ? analysis.getQualityScore() : 0)
                : String.format("US「%s」分析任务执行失败：%s", usTitle, safeErrorMessage(error));
        NotificationMessage.NotificationType type = succeeded
                ? NotificationMessage.NotificationType.US_ANALYSIS_SUCCEEDED
                : NotificationMessage.NotificationType.US_ANALYSIS_FAILED;
        NotificationMessage.NotificationLevel level = succeeded
                ? NotificationMessage.NotificationLevel.SUCCESS
                : NotificationMessage.NotificationLevel.ERROR;
        safePublishNotification(
                requestedBy,
                userStory.getTenantId(),
                type,
                level,
                title,
                content,
                "USER_STORY",
                String.valueOf(userStory.getId())
        );
    }

    private void publishCaseGenerationNotification(String requestedBy,
                                                   UserStoryDTO userStory,
                                                   boolean succeeded,
                                                   UserStoryDTO.CaseGenerationSessionDTO session,
                                                   Exception error) {
        if (userStory == null || userStory.getTenantId() == null) return;
        String usNumber = defaultIfBlank(userStory.getUsNumber(), "US");
        String usTitle = defaultIfBlank(userStory.getTitle(), "未命名需求");
        int draftCount = session != null && session.getDraftCases() != null ? session.getDraftCases().size() : 0;
        String title = succeeded
                ? String.format("%s 用例生成完成", usNumber)
                : String.format("%s 用例生成失败", usNumber);
        String content = succeeded
                ? String.format("US「%s」已生成 %d 条候选测试用例草稿。", usTitle, draftCount)
                : String.format("US「%s」测试用例生成失败：%s", usTitle, safeErrorMessage(error));
        NotificationMessage.NotificationType type = succeeded
                ? NotificationMessage.NotificationType.CASE_GENERATION_SUCCEEDED
                : NotificationMessage.NotificationType.CASE_GENERATION_FAILED;
        NotificationMessage.NotificationLevel level = succeeded
                ? NotificationMessage.NotificationLevel.SUCCESS
                : NotificationMessage.NotificationLevel.ERROR;
        safePublishNotification(
                requestedBy,
                userStory.getTenantId(),
                type,
                level,
                title,
                content,
                "USER_STORY",
                String.valueOf(userStory.getId())
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
            log.warn("Failed to publish notification. user={}, tenant={}, type={}, reason={}",
                    requestedBy, tenantId, type, ex.getMessage());
        }
    }

    private Optional<UserStoryDTO.CaseGenerationSessionDTO> resolveLatestGenerationSession(Long userStoryId) {
        Optional<UserStoryService.LatestCaseGenerationSnapshot> persisted = userStoryService.getLatestCaseGeneration(userStoryId);
        if (persisted.isPresent() && persisted.get().session() != null) {
            return persisted.map(UserStoryService.LatestCaseGenerationSnapshot::session);
        }

        Optional<UserStoryCaseGenerationTaskService.CaseGenerationTask> latestTask = caseGenerationTaskService.findLatestTaskByUserStoryId(userStoryId);
        if (latestTask.isPresent()) {
            UserStoryCaseGenerationTaskService.CaseGenerationTask task = latestTask.get();
            if (task.getStatus() == UserStoryCaseGenerationTaskService.TaskStatus.SUCCEEDED && task.getResult() != null) {
                return Optional.of(task.getResult());
            }
        }
        return Optional.empty();
    }

    private int normalizeGenerateCount(Integer count) {
        if (count == null) return 3;
        return Math.max(1, Math.min(20, count));
    }

    private String toWorkflowStatusLabel(UserStory.Status status) {
        if (status == null) {
            return "未知状态";
        }
        return switch (status) {
            case DRAFT -> "待分析";
            case ANALYZING -> "分析中";
            case READY -> "待生成用例";
            case IN_PROGRESS -> "待采纳";
            case PENDING_EXECUTION -> "待执行";
            case DONE -> "执行完毕";
            case ARCHIVED -> "已归档";
        };
    }

    private List<UserStoryDTO.CaseGenerationMessageDTO> buildConversationSeed(
            UserStoryDTO.CaseGenerationSessionDTO previousSession,
            String feedback) {
        List<UserStoryDTO.CaseGenerationMessageDTO> conversation = new ArrayList<>();
        if (previousSession != null && previousSession.getConversation() != null) {
            List<UserStoryDTO.CaseGenerationMessageDTO> history = previousSession.getConversation().stream()
                    .filter(item -> item != null && StringUtils.hasText(item.getContent()))
                    .filter(item -> !isSystemCaseGenerationMessage(item.getContent()))
                    .collect(Collectors.toList());
            int from = Math.max(0, history.size() - 20);
            conversation.addAll(history.subList(from, history.size()));
        }
        if (StringUtils.hasText(feedback)) {
            conversation.add(UserStoryDTO.CaseGenerationMessageDTO.builder()
                    .role("user")
                    .content(feedback.trim())
                    .createdAt(LocalDateTime.now())
                    .build());
        }
        return conversation;
    }

    private String buildCaseGenerationPrompt(
            UserStoryDTO userStory,
            int count,
            UserStoryDTO.CaseGenerationSessionDTO previousSession,
            List<UserStoryDTO.CaseGenerationMessageDTO> conversationSeed) {
        StringBuilder prompt = new StringBuilder("""
                User Story:
                编号: %s
                标题: %s
                描述: %s
                验收标准: %s

                请基于以上 US 生成 %d 条“可直接评审并可落地自动化”的测试用例草稿。
                硬性要求：
                1) 覆盖主流程成功、异常输入/失败分支、边界条件。
                2) 禁止泛化标题，例如 Positive scenario、Negative scenario、自动生成。
                3) 每条用例至少 4 个步骤；每个步骤都必须包含可执行 action 和可验证 expectedResult。
                4) 必须提供关键步骤的测试数据 testData，断言要体现业务规则。
                5) 优先引用 Given / When / Then 语义组织前置条件与断言。

                输出格式：
                仅输出 JSON 对象，不要 Markdown，不要解释文字。
                {
                  "testCases": [
                    {
                      "title": "...",
                      "description": "...",
                      "preconditions": "...",
                      "testType": "FUNCTIONAL|UI|API|PERFORMANCE|SECURITY|COMPATIBILITY",
                      "priority": "CRITICAL|HIGH|MEDIUM|LOW",
                      "tags": ["..."],
                      "steps": [
                        {"stepOrder": 1, "action": "...", "expectedResult": "...", "testData": "..."}
                      ]
                    }
                  ]
                }""".formatted(
                userStory.getUsNumber(),
                defaultIfBlank(userStory.getTitle(), "未命名"),
                defaultIfBlank(userStory.getDescription(), ""),
                defaultIfBlank(userStory.getAcceptanceCriteria(), ""),
                count
        ));

        if (previousSession != null && previousSession.getDraftCases() != null && !previousSession.getDraftCases().isEmpty()) {
            prompt.append("\n\n上一轮草稿摘要：");
            int index = 1;
            for (UserStoryDTO.GeneratedTestCaseDraftDTO draft : previousSession.getDraftCases().stream().limit(8).toList()) {
                prompt.append("\n")
                        .append(index++)
                        .append(". ")
                        .append(defaultIfBlank(draft.getTitle(), "未命名草稿"))
                        .append(" | ")
                        .append(defaultIfBlank(draft.getDescription(), "-"));
            }
        }

        if (conversationSeed != null && !conversationSeed.isEmpty()) {
            prompt.append("\n\n对话上下文（最新在后）：");
            int from = Math.max(0, conversationSeed.size() - 8);
            for (int i = from; i < conversationSeed.size(); i++) {
                UserStoryDTO.CaseGenerationMessageDTO msg = conversationSeed.get(i);
                prompt.append("\n- ")
                        .append(defaultIfBlank(msg.getRole(), "user"))
                        .append(": ")
                        .append(defaultIfBlank(msg.getContent(), ""));
            }
            prompt.append("\n请重点响应用户最新反馈，并输出可直接评审的用例草稿。");
        }
        return prompt.toString();
    }

    private UserStoryDTO.CaseGenerationSessionDTO buildCaseGenerationSession(
            String sessionId,
            int version,
            UserStoryDTO userStory,
            UserStoryDTO.CaseGenerationSessionDTO previousSession,
            List<UserStoryDTO.CaseGenerationMessageDTO> conversationSeed,
            List<UserStoryDTO.GeneratedTestCaseDraftDTO> drafts,
            String feedback) {
        LocalDateTime now = LocalDateTime.now();
        List<UserStoryDTO.CaseGenerationMessageDTO> conversation = new ArrayList<>();
        if (conversationSeed != null) {
            conversation.addAll(conversationSeed);
        }
        List<UserStoryDTO.CaseGenerationMessageDTO> trimmedConversation = trimConversation(
                conversation,
                CASE_GENERATION_CONVERSATION_RETENTION
        );
        String normalizedFeedback = StringUtils.hasText(feedback) ? feedback.trim() : null;

        List<String> adoptedDraftIds = new ArrayList<>();
        if (previousSession != null && previousSession.getAdoptedDraftIds() != null) {
            previousSession.getAdoptedDraftIds().stream()
                    .filter(StringUtils::hasText)
                    .map(String::trim)
                    .forEach(draftId -> {
                        if (!adoptedDraftIds.contains(draftId)) {
                            adoptedDraftIds.add(draftId);
                        }
                    });
        }

        List<UserStoryDTO.CaseGenerationRecordDTO> generationRecords = buildGenerationRecords(
                previousSession,
                version,
                userStory,
                drafts,
                normalizedFeedback,
                trimmedConversation,
                now
        );

        return UserStoryDTO.CaseGenerationSessionDTO.builder()
                .sessionId(sessionId)
                .version(version)
                .summary(defaultIfBlank(userStory.getUsNumber(), "US") + " 本轮生成 " + drafts.size() + " 条候选草稿")
                .updatedAt(now)
                .conversation(trimmedConversation)
                .draftCases(drafts)
                .adoptedDraftIds(adoptedDraftIds)
                .generationRecords(generationRecords)
                .build();
    }

    private List<UserStoryDTO.CaseGenerationMessageDTO> trimConversation(
            List<UserStoryDTO.CaseGenerationMessageDTO> conversation,
            int retention) {
        if (conversation == null || conversation.isEmpty()) {
            return List.of();
        }
        int max = Math.max(1, retention);
        List<UserStoryDTO.CaseGenerationMessageDTO> filtered = conversation.stream()
                .filter(item -> item != null && StringUtils.hasText(item.getContent()))
                .filter(item -> !isSystemCaseGenerationMessage(item.getContent()))
                .collect(Collectors.toList());
        if (filtered.size() <= max) {
            return filtered;
        }
        return new ArrayList<>(filtered.subList(filtered.size() - max, filtered.size()));
    }

    private boolean isSystemCaseGenerationMessage(String content) {
        if (!StringUtils.hasText(content)) {
            return true;
        }
        String normalized = content.trim();
        return normalized.matches("^已根据你的反馈重新生成\\s*\\d+\\s*条候选用例草稿.*")
                || normalized.matches("^已生成\\s*\\d+\\s*条候选用例草稿.*");
    }

    private List<UserStoryDTO.CaseGenerationRecordDTO> buildGenerationRecords(
            UserStoryDTO.CaseGenerationSessionDTO previousSession,
            int version,
            UserStoryDTO userStory,
            List<UserStoryDTO.GeneratedTestCaseDraftDTO> drafts,
            String feedback,
            List<UserStoryDTO.CaseGenerationMessageDTO> conversation,
            LocalDateTime generatedAt) {
        List<UserStoryDTO.CaseGenerationRecordDTO> records = new ArrayList<>(resolveGenerationRecords(previousSession));
        records.add(UserStoryDTO.CaseGenerationRecordDTO.builder()
                .recordId("GEN-" + UUID.randomUUID().toString().substring(0, 8).toUpperCase(Locale.ROOT))
                .version(version)
                .summary(defaultIfBlank(userStory.getUsNumber(), "US") + " 第 " + version + " 轮生成 " + drafts.size() + " 条候选草稿")
                .feedback(defaultIfBlank(feedback, null))
                .generatedAt(generatedAt)
                .conversation(conversation)
                .draftCases(drafts)
                .build());

        List<UserStoryDTO.CaseGenerationRecordDTO> normalized = records.stream()
                .filter(record -> record != null)
                .collect(Collectors.toList());
        return normalized;
    }

    private List<UserStoryDTO.CaseGenerationRecordDTO> resolveGenerationRecords(
            UserStoryDTO.CaseGenerationSessionDTO session) {
        if (session == null) {
            return List.of();
        }

        List<UserStoryDTO.CaseGenerationRecordDTO> records = Optional.ofNullable(session.getGenerationRecords())
                .orElse(List.of())
                .stream()
                .filter(item -> item != null && item.getDraftCases() != null && !item.getDraftCases().isEmpty())
                .collect(Collectors.toList());
        if (!records.isEmpty()) {
            return records;
        }

        List<UserStoryDTO.GeneratedTestCaseDraftDTO> legacyDrafts = Optional.ofNullable(session.getDraftCases()).orElse(List.of());
        if (legacyDrafts.isEmpty()) {
            return List.of();
        }

        return List.of(UserStoryDTO.CaseGenerationRecordDTO.builder()
                .recordId("GEN-LEGACY")
                .version(session.getVersion())
                .summary(defaultIfBlank(session.getSummary(), "历史生成记录"))
                .feedback(null)
                .generatedAt(session.getUpdatedAt())
                .conversation(Optional.ofNullable(session.getConversation()).orElse(List.of()))
                .draftCases(legacyDrafts)
                .build());
    }

    private List<UserStoryDTO.GeneratedTestCaseDraftDTO> resolveGenerationDrafts(
            UserStoryDTO.CaseGenerationSessionDTO session) {
        if (session == null) {
            return List.of();
        }
        Map<String, UserStoryDTO.GeneratedTestCaseDraftDTO> draftMap = new LinkedHashMap<>();

        for (UserStoryDTO.CaseGenerationRecordDTO record : resolveGenerationRecords(session)) {
            List<UserStoryDTO.GeneratedTestCaseDraftDTO> drafts = Optional.ofNullable(record.getDraftCases()).orElse(List.of());
            for (UserStoryDTO.GeneratedTestCaseDraftDTO draft : drafts) {
                if (draft == null || !StringUtils.hasText(draft.getDraftId())) {
                    continue;
                }
                String draftId = draft.getDraftId().trim();
                draftMap.putIfAbsent(draftId, draft);
            }
        }

        List<UserStoryDTO.GeneratedTestCaseDraftDTO> legacyDrafts = Optional.ofNullable(session.getDraftCases()).orElse(List.of());
        for (UserStoryDTO.GeneratedTestCaseDraftDTO draft : legacyDrafts) {
            if (draft == null || !StringUtils.hasText(draft.getDraftId())) {
                continue;
            }
            String draftId = draft.getDraftId().trim();
            draftMap.putIfAbsent(draftId, draft);
        }

        return new ArrayList<>(draftMap.values());
    }

    private UserStoryDTO.CaseGenerationSessionDTO removeCaseGenerationRecord(
            UserStoryDTO.CaseGenerationSessionDTO session,
            String recordId) {
        List<UserStoryDTO.CaseGenerationRecordDTO> records = new ArrayList<>(resolveGenerationRecords(session));
        int removeIndex = -1;
        for (int i = 0; i < records.size(); i++) {
            UserStoryDTO.CaseGenerationRecordDTO item = records.get(i);
            if (item != null && recordId.equals(defaultIfBlank(item.getRecordId(), "").trim())) {
                removeIndex = i;
                break;
            }
        }
        if (removeIndex < 0) {
            throw new RuntimeException("未找到指定记录，可能已被删除");
        }

        UserStoryDTO.CaseGenerationRecordDTO removedRecord = records.remove(removeIndex);
        Set<String> removedDraftIds = Optional.ofNullable(removedRecord.getDraftCases())
                .orElse(List.of())
                .stream()
                .map(UserStoryDTO.GeneratedTestCaseDraftDTO::getDraftId)
                .filter(StringUtils::hasText)
                .map(String::trim)
                .collect(Collectors.toCollection(LinkedHashSet::new));

        List<String> adoptedDraftIds = Optional.ofNullable(session.getAdoptedDraftIds())
                .orElse(List.of())
                .stream()
                .filter(StringUtils::hasText)
                .map(String::trim)
                .filter(draftId -> !removedDraftIds.contains(draftId))
                .distinct()
                .collect(Collectors.toList());

        LocalDateTime now = LocalDateTime.now();
        if (records.isEmpty()) {
            return session.toBuilder()
                    .summary("暂无历史生成记录")
                    .updatedAt(now)
                    .conversation(List.of())
                    .draftCases(List.of())
                    .adoptedDraftIds(adoptedDraftIds)
                    .generationRecords(List.of())
                    .build();
        }

        UserStoryDTO.CaseGenerationRecordDTO latestRecord = records.get(records.size() - 1);
        List<UserStoryDTO.CaseGenerationMessageDTO> latestConversation = Optional.ofNullable(latestRecord.getConversation())
                .orElse(List.of());
        List<UserStoryDTO.GeneratedTestCaseDraftDTO> latestDrafts = Optional.ofNullable(latestRecord.getDraftCases())
                .orElse(List.of());
        Integer latestVersion = latestRecord.getVersion() != null
                ? latestRecord.getVersion()
                : session.getVersion();
        String latestSummary = defaultIfBlank(
                latestRecord.getSummary(),
                defaultIfBlank(session.getSummary(), "用例草稿生成完成")
        );

        return session.toBuilder()
                .version(latestVersion)
                .summary(latestSummary)
                .updatedAt(now)
                .conversation(latestConversation)
                .draftCases(latestDrafts)
                .adoptedDraftIds(adoptedDraftIds)
                .generationRecords(records)
                .build();
    }

    private List<UserStoryDTO.GeneratedTestCaseDraftDTO> toDraftCases(
            List<TestCaseDTO.CreateRequest> requests,
            int count) {
        return requests.stream()
                .limit(count)
                .map(this::toDraftCase)
                .collect(Collectors.toList());
    }

    private UserStoryDTO.GeneratedTestCaseDraftDTO toDraftCase(TestCaseDTO.CreateRequest request) {
        return UserStoryDTO.GeneratedTestCaseDraftDTO.builder()
                .draftId("DRAFT-" + UUID.randomUUID().toString().substring(0, 8).toUpperCase(Locale.ROOT))
                .title(defaultIfBlank(request.getTitle(), "AI 生成测试用例"))
                .description(defaultIfBlank(request.getDescription(), "自动生成"))
                .preconditions(defaultIfBlank(request.getPreconditions(), "测试环境可用"))
                .testType(request.getTestType() != null ? request.getTestType() : TestCaseDTO.TestType.FUNCTIONAL)
                .priority(request.getPriority() != null ? request.getPriority() : TestCaseDTO.Priority.MEDIUM)
                .steps(request.getSteps() != null ? request.getSteps() : List.of())
                .tags(defaultIfBlank(request.getTags(), "ai-generated-draft"))
                .build();
    }

    private TestCaseDTO.CreateRequest toCreateRequest(
            UserStoryDTO.GeneratedTestCaseDraftDTO draft,
            Long userStoryId,
            UserStoryDTO userStory) {
        return TestCaseDTO.CreateRequest.builder()
                .title(defaultIfBlank(draft.getTitle(), defaultIfBlank(userStory.getTitle(), "AI 生成测试用例")))
                .description(defaultIfBlank(draft.getDescription(), "自动生成"))
                .preconditions(defaultIfBlank(draft.getPreconditions(), "测试环境可用"))
                .testType(draft.getTestType() != null ? draft.getTestType() : TestCaseDTO.TestType.FUNCTIONAL)
                .priority(draft.getPriority() != null ? draft.getPriority() : TestCaseDTO.Priority.MEDIUM)
                .userStoryId(userStoryId)
                .steps(draft.getSteps() != null ? draft.getSteps() : List.of())
                .tags(defaultIfBlank(draft.getTags(), "ai-generated"))
                .build();
    }

    private record CaseGenerationTaskView(
            String taskId,
            Long userStoryId,
            String userStoryNumber,
            String status,
            String requestedBy,
            LocalDateTime createdAt,
            LocalDateTime startedAt,
            LocalDateTime finishedAt,
            Long pollIntervalMs,
            String pollPath,
            List<UserStoryDTO.CaseGenerationEventDTO> events,
            UserStoryDTO.CaseGenerationSessionDTO result,
            String errorMessage
    ) {
        static CaseGenerationTaskView from(
                UserStoryCaseGenerationTaskService.CaseGenerationTask task,
                boolean includeResult,
                long pollIntervalMs) {
            return new CaseGenerationTaskView(
                    task.getTaskId(),
                    task.getUserStoryId(),
                    task.getUserStoryNumber(),
                    task.getStatus().name(),
                    task.getRequestedBy(),
                    task.getCreatedAt(),
                    task.getStartedAt(),
                    task.getFinishedAt(),
                    pollIntervalMs,
                    "/api/user-stories/case-generation-tasks/" + task.getTaskId(),
                    task.getEvents() == null ? List.of() : task.getEvents(),
                    includeResult ? task.getResult() : null,
                    task.getErrorMessage()
            );
        }
    }

    private record LatestCaseGenerationView(
            Long userStoryId,
            String userStoryNumber,
            String status,
            String taskId,
            Long pollIntervalMs,
            String pollPath,
            LocalDateTime generatedAt,
            List<UserStoryDTO.CaseGenerationEventDTO> events,
            UserStoryDTO.CaseGenerationSessionDTO result,
            String errorMessage,
            boolean hasDraft
    ) {
        static LatestCaseGenerationView fromTask(
                UserStoryCaseGenerationTaskService.CaseGenerationTask task,
                long pollIntervalMs) {
            LocalDateTime generatedAt = Optional.ofNullable(task.getFinishedAt())
                    .orElse(Optional.ofNullable(task.getStartedAt()).orElse(task.getCreatedAt()));
            return new LatestCaseGenerationView(
                    task.getUserStoryId(),
                    task.getUserStoryNumber(),
                    task.getStatus().name(),
                    task.getTaskId(),
                    pollIntervalMs,
                    "/api/user-stories/case-generation-tasks/" + task.getTaskId(),
                    generatedAt,
                    task.getEvents() == null ? List.of() : task.getEvents(),
                    task.getResult(),
                    task.getErrorMessage(),
                    task.getResult() != null && task.getResult().getDraftCases() != null && !task.getResult().getDraftCases().isEmpty()
            );
        }

        static LatestCaseGenerationView fromSucceededTaskWithPersisted(
                UserStoryCaseGenerationTaskService.CaseGenerationTask task,
                UserStoryDTO.CaseGenerationSessionDTO persistedResult,
                LocalDateTime generatedAt,
                long pollIntervalMs) {
            LocalDateTime fallbackGeneratedAt = Optional.ofNullable(task.getFinishedAt())
                    .orElse(Optional.ofNullable(task.getStartedAt()).orElse(task.getCreatedAt()));
            LocalDateTime resolvedGeneratedAt = generatedAt != null ? generatedAt : fallbackGeneratedAt;
            return new LatestCaseGenerationView(
                    task.getUserStoryId(),
                    task.getUserStoryNumber(),
                    task.getStatus().name(),
                    task.getTaskId(),
                    pollIntervalMs,
                    "/api/user-stories/case-generation-tasks/" + task.getTaskId(),
                    resolvedGeneratedAt,
                    task.getEvents() == null ? List.of() : task.getEvents(),
                    persistedResult,
                    task.getErrorMessage(),
                    persistedResult != null && persistedResult.getDraftCases() != null && !persistedResult.getDraftCases().isEmpty()
            );
        }

        static LatestCaseGenerationView fromPersisted(
                Long userStoryId,
                String userStoryNumber,
                UserStoryDTO.CaseGenerationSessionDTO result,
                LocalDateTime generatedAt) {
            return new LatestCaseGenerationView(
                    userStoryId,
                    userStoryNumber,
                    "SUCCEEDED",
                    null,
                    null,
                    null,
                    generatedAt,
                    List.of(),
                    result,
                    null,
                    result != null && result.getDraftCases() != null && !result.getDraftCases().isEmpty()
            );
        }

        static LatestCaseGenerationView empty(Long userStoryId, String userStoryNumber) {
            return new LatestCaseGenerationView(
                    userStoryId,
                    userStoryNumber,
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
    
    private UserStoryDTO.AIAnalysisResponse parseAIAnalysisResponse(
            String raw,
            String currentTitle,
            String currentDescription,
            String currentAcceptanceCriteria) {
        String extracted = extractJsonObject(raw);
        try {
            return buildAIAnalysisResponse(
                    objectMapper.readTree(extracted),
                    currentTitle,
                    currentDescription,
                    currentAcceptanceCriteria
            );
        } catch (IOException ex) {
            String repaired = repairJsonLikePayload(extracted);
            if (!repaired.equals(extracted)) {
                try {
                    UserStoryDTO.AIAnalysisResponse repairedResponse = buildAIAnalysisResponse(
                            objectMapper.readTree(repaired),
                            currentTitle,
                            currentDescription,
                            currentAcceptanceCriteria
                    );
                    log.info("AI analysis parsed after payload repair.");
                    return repairedResponse;
                } catch (IOException repairEx) {
                    log.warn("Failed to parse repaired AI analysis payload. rawPreview={}", preview(raw));
                }
            }
            log.warn("Failed to parse AI analysis response, fallback to default. rawPreview={}", preview(raw));
            return UserStoryDTO.AIAnalysisResponse.builder()
                    .qualityScore(extractScoreFallback(raw))
                    .analysisSummary(extractSummaryFallback(raw))
                    .optimizedTitle(defaultIfBlank(extractTextField(raw, "optimizedTitle"), defaultIfBlank(currentTitle, "US 标题待完善")))
                    .optimizedDescription(defaultIfBlank(extractTextField(raw, "optimizedDescription"), defaultIfBlank(currentDescription, "As 业务角色\nI want 完成业务动作\nSo that 达成业务价值")))
                    .optimizedAcceptanceCriteria(defaultIfBlank(
                            extractTextField(raw, "optimizedAcceptanceCriteria"),
                            defaultIfBlank(currentAcceptanceCriteria, "Given 满足前置条件\nWhen 执行关键动作\nThen 结果可被验证")
                    ))
                    .qualityIssues(List.of(
                            UserStoryDTO.QualityIssueDTO.builder()
                                    .type("GIVEN_WHEN_THEN")
                                    .severity("HIGH")
                                    .message("验收标准结构不完整，缺少清晰的 Given / When / Then。")
                                    .suggestion("将业务前置条件、触发动作、预期结果拆分为三段。")
                                    .build(),
                            UserStoryDTO.QualityIssueDTO.builder()
                                    .type("AMBIGUITY")
                                    .severity("MEDIUM")
                                    .message("需求存在描述模糊项，测试边界不明确。")
                                    .suggestion("补充数量限制、异常处理、状态变化规则。")
                                    .build()
                    ))
                    .validationPoints(List.of(UserStoryDTO.ValidationPointDTO.builder()
                            .description("校验核心业务流程可达")
                            .expectedResult("业务流程执行成功")
                            .priority(UserStory.Priority.MEDIUM)
                            .build()))
                    .suggestedTestCases(List.of(UserStoryDTO.TestCaseSuggestionDTO.builder()
                            .title("核心流程验证")
                            .description("覆盖主路径和关键断言")
                            .testType(TestCaseDTO.TestType.FUNCTIONAL)
                            .priority(TestCaseDTO.Priority.MEDIUM)
                            .build()))
                    .build();
        }
    }

    private UserStoryDTO.AIAnalysisResponse buildAIAnalysisResponse(
            JsonNode root,
            String currentTitle,
            String currentDescription,
            String currentAcceptanceCriteria) {
        int qualityScore = normalizeQualityScore(root.path("qualityScore").asInt(70));

        List<UserStoryDTO.QualityIssueDTO> qualityIssues = new ArrayList<>();
        JsonNode issueNode = root.path("qualityIssues");
        if (issueNode.isArray()) {
            for (JsonNode node : issueNode) {
                qualityIssues.add(UserStoryDTO.QualityIssueDTO.builder()
                        .type(node.path("type").asText("GENERAL"))
                        .severity(node.path("severity").asText("MEDIUM"))
                        .message(node.path("message").asText("需求描述存在可优化项"))
                        .suggestion(node.path("suggestion").asText("补全上下文与验收边界"))
                        .build());
            }
        }

        List<UserStoryDTO.ValidationPointDTO> validationPoints = new ArrayList<>();
        JsonNode vpNode = root.path("validationPoints");
        if (vpNode.isArray()) {
            for (JsonNode node : vpNode) {
                validationPoints.add(UserStoryDTO.ValidationPointDTO.builder()
                        .description(node.path("description").asText("待补充验证点"))
                        .expectedResult(node.path("expectedResult").asText("满足业务预期"))
                        .priority(parseUsPriority(node.path("priority").asText("MEDIUM")))
                        .build());
            }
        }

        List<UserStoryDTO.TestCaseSuggestionDTO> suggestions = new ArrayList<>();
        JsonNode tcNode = root.path("suggestedTestCases");
        if (tcNode.isArray()) {
            for (JsonNode node : tcNode) {
                suggestions.add(UserStoryDTO.TestCaseSuggestionDTO.builder()
                        .title(node.path("title").asText("AI 建议测试用例"))
                        .description(node.path("description").asText("根据用户故事生成"))
                        .testType(parseTestType(node.path("testType").asText("FUNCTIONAL")))
                        .priority(parseTestPriority(node.path("priority").asText("MEDIUM")))
                        .build());
            }
        }

        String summary = root.path("analysisSummary").asText("AI 分析完成");
        String optimizedTitle = defaultIfBlank(root.path("optimizedTitle").asText(null), currentTitle);
        String optimizedDescription = defaultIfBlank(root.path("optimizedDescription").asText(null), currentDescription);
        String optimizedAcceptanceCriteria = defaultIfBlank(root.path("optimizedAcceptanceCriteria").asText(null), currentAcceptanceCriteria);
        return UserStoryDTO.AIAnalysisResponse.builder()
                .qualityScore(qualityScore)
                .qualityIssues(qualityIssues)
                .optimizedTitle(optimizedTitle)
                .optimizedDescription(optimizedDescription)
                .optimizedAcceptanceCriteria(optimizedAcceptanceCriteria)
                .analysisSummary(summary)
                .validationPoints(validationPoints)
                .suggestedTestCases(suggestions)
                .build();
    }

    private String extractJsonObject(String raw) {
        if (!StringUtils.hasText(raw)) {
            return "{}";
        }
        String normalized = raw.trim();
        int fenceStart = normalized.indexOf("```");
        if (fenceStart >= 0) {
            normalized = normalized.replace("```json", "").replace("```JSON", "").replace("```", "").trim();
        }
        int start = normalized.indexOf('{');
        int end = normalized.lastIndexOf('}');
        if (start >= 0 && end > start) {
            return normalized.substring(start, end + 1);
        }
        return normalized;
    }

    private String repairJsonLikePayload(String jsonLike) {
        if (!StringUtils.hasText(jsonLike)) {
            return "{}";
        }
        String source = jsonLike.trim();
        StringBuilder repaired = new StringBuilder(source.length() + 32);
        boolean inString = false;
        boolean escaped = false;

        for (int i = 0; i < source.length(); i++) {
            char current = source.charAt(i);
            if (!inString) {
                if (current == '"') {
                    inString = true;
                }
                repaired.append(current);
                continue;
            }

            if (escaped) {
                repaired.append(current);
                escaped = false;
                continue;
            }

            if (current == '\\') {
                repaired.append(current);
                escaped = true;
                continue;
            }

            if (current == '"') {
                char next = nextNonWhitespace(source, i + 1);
                if (next == ',' || next == '}' || next == ']' || next == ':' || next == 0) {
                    inString = false;
                    repaired.append(current);
                } else {
                    repaired.append("\\\"");
                }
                continue;
            }

            repaired.append(current);
        }

        return repaired.toString();
    }

    private char nextNonWhitespace(String source, int startIndex) {
        for (int i = startIndex; i < source.length(); i++) {
            char current = source.charAt(i);
            if (!Character.isWhitespace(current)) {
                return current;
            }
        }
        return 0;
    }

    private int extractScoreFallback(String raw) {
        if (!StringUtils.hasText(raw)) {
            return 60;
        }
        Matcher matcher = Pattern.compile("\"qualityScore\"\\s*:\\s*(\\d{1,3})").matcher(raw);
        if (matcher.find()) {
            try {
                return normalizeQualityScore(Integer.parseInt(matcher.group(1)));
            } catch (NumberFormatException ignored) {
                return 60;
            }
        }
        return 60;
    }

    private String extractSummaryFallback(String raw) {
        return defaultIfBlank(extractTextField(raw, "analysisSummary"), "AI 分析完成（解析回退）");
    }

    private String extractTextField(String raw, String fieldName) {
        if (!StringUtils.hasText(raw) || !StringUtils.hasText(fieldName)) {
            return null;
        }
        String repaired = repairJsonLikePayload(extractJsonObject(raw));
        Matcher matcher = Pattern.compile("\"" + Pattern.quote(fieldName) + "\"\\s*:\\s*\"([\\s\\S]*?)\"\\s*(,|\\}|\\])").matcher(repaired);
        if (matcher.find()) {
            return matcher.group(1)
                    .replace("\\n", "\n")
                    .replace("\\\"", "\"")
                    .trim();
        }
        return null;
    }

    private String preview(String raw) {
        if (!StringUtils.hasText(raw)) {
            return "";
        }
        String normalized = raw.replaceAll("\\s+", " ").trim();
        if (normalized.length() <= 320) {
            return normalized;
        }
        return normalized.substring(0, 320) + "...";
    }

    private int normalizeQualityScore(int score) {
        if (score < 0) return 0;
        if (score > 100) return 100;
        return score;
    }
    
    private List<TestCaseDTO.CreateRequest> parseGeneratedTestCases(String raw, Long userStoryId) {
        String extracted = extractJsonPayload(raw);
        try {
            return parseGeneratedTestCasesFromJson(extracted, userStoryId);
        } catch (IOException ex) {
            String repaired = repairJsonLikePayload(extracted);
            if (!repaired.equals(extracted)) {
                try {
                    List<TestCaseDTO.CreateRequest> repairedRequests = parseGeneratedTestCasesFromJson(repaired, userStoryId);
                    log.info("AI test cases parsed after payload repair.");
                    return repairedRequests;
                } catch (IOException repairEx) {
                    log.warn("Failed to parse repaired AI generated test cases payload. rawPreview={}", preview(raw));
                }
            }
            log.warn("Failed to parse AI generated test cases, fallback to default. rawPreview={}", preview(raw));
            return List.of();
        }
    }

    private List<TestCaseDTO.CreateRequest> parseGeneratedTestCasesFromJson(String jsonPayload, Long userStoryId) throws IOException {
        JsonNode root = objectMapper.readTree(jsonPayload);
        JsonNode casesNode = extractCaseArrayNode(root);
        if (casesNode == null || !casesNode.isArray()) {
            return List.of();
        }

        List<TestCaseDTO.CreateRequest> requests = new ArrayList<>();
        for (JsonNode node : casesNode) {
            if (node == null || node.isNull()) {
                continue;
            }
            JsonNode stepsNode = readNodeByAliases(node, "steps", "testSteps", "test_steps", "caseSteps", "步骤");
            JsonNode tagsNode = readNodeByAliases(node, "tags", "tag", "labels", "label", "标签");
            TestCaseDTO.CreateRequest request = TestCaseDTO.CreateRequest.builder()
                    .title(defaultIfBlank(readTextByAliases(node,
                            "title", "caseTitle", "name", "标题", "用例标题"), "AI 生成测试用例"))
                    .description(defaultIfBlank(readTextByAliases(node,
                            "description", "desc", "objective", "验证目标", "描述"), "自动生成"))
                    .preconditions(defaultIfBlank(readTextByAliases(node,
                            "preconditions", "precondition", "given", "前置条件"), "系统可用，测试账号可登录"))
                    .testType(parseTestType(readTextByAliases(node,
                            "testType", "type", "caseType", "测试类型", "类型")))
                    .priority(parseTestPriority(readTextByAliases(node,
                            "priority", "level", "riskLevel", "优先级", "级别")))
                    .userStoryId(userStoryId)
                    .steps(parseSteps(stepsNode))
                    .tags(parseTags(tagsNode))
                    .build();
            requests.add(request);
        }
        return requests;
    }

    private JsonNode extractCaseArrayNode(JsonNode root) {
        if (root == null || root.isNull()) {
            return null;
        }
        if (root.isArray()) {
            return root;
        }
        if (root.path("testCases").isArray()) return root.path("testCases");
        if (root.path("cases").isArray()) return root.path("cases");
        if (root.path("items").isArray()) return root.path("items");
        if (root.path("list").isArray()) return root.path("list");
        if (root.path("data").isArray()) return root.path("data");
        if (root.path("result").isArray()) return root.path("result");
        if (root.path("data").path("testCases").isArray()) return root.path("data").path("testCases");
        if (root.path("result").path("testCases").isArray()) return root.path("result").path("testCases");
        return null;
    }

    private JsonNode readNodeByAliases(JsonNode node, String... aliases) {
        if (node == null || node.isNull()) {
            return null;
        }
        for (String alias : aliases) {
            if (!StringUtils.hasText(alias)) continue;
            JsonNode value = node.path(alias);
            if (!value.isMissingNode() && !value.isNull()) {
                return value;
            }
        }
        return null;
    }

    private String readTextByAliases(JsonNode node, String... aliases) {
        JsonNode value = readNodeByAliases(node, aliases);
        if (value == null || value.isNull()) {
            return null;
        }
        if (value.isTextual()) {
            return normalizeText(value.asText(""));
        }
        if (value.isNumber() || value.isBoolean()) {
            return normalizeText(value.asText(""));
        }
        return null;
    }

    private Integer readIntByAliases(JsonNode node, int fallback, String... aliases) {
        JsonNode value = readNodeByAliases(node, aliases);
        if (value == null || value.isNull()) {
            return fallback;
        }
        if (value.isInt() || value.isLong()) {
            return value.asInt(fallback);
        }
        String text = normalizeText(value.asText(""));
        if (!StringUtils.hasText(text)) {
            return fallback;
        }
        try {
            return Integer.parseInt(text);
        } catch (NumberFormatException ignored) {
            return fallback;
        }
    }

    private String parseTags(JsonNode tagsNode) {
        Set<String> tags = new LinkedHashSet<>();
        if (tagsNode == null || tagsNode.isNull()) {
            return "ai-generated";
        }
        if (tagsNode.isTextual()) {
            String value = normalizeText(tagsNode.asText(""));
            if (StringUtils.hasText(value)) {
                for (String token : value.split("[,，|/\\s]+")) {
                    String cleaned = normalizeText(token);
                    if (StringUtils.hasText(cleaned)) {
                        tags.add(cleaned.toLowerCase(Locale.ROOT));
                    }
                }
            }
        }
        if (tagsNode.isArray()) {
            for (JsonNode node : tagsNode) {
                if (node == null || node.isNull()) continue;
                String value = normalizeText(node.asText(""));
                if (StringUtils.hasText(value)) {
                    tags.add(value.toLowerCase(Locale.ROOT));
                }
            }
        }
        if (tags.isEmpty()) {
            tags.add("ai-generated");
        } else if (!tags.contains("ai-generated")) {
            tags.add("ai-generated");
        }
        return String.join(",", tags);
    }

    private String extractJsonPayload(String raw) {
        if (!StringUtils.hasText(raw)) {
            return "[]";
        }
        String normalized = raw.trim()
                .replace("```json", "")
                .replace("```JSON", "")
                .replace("```", "")
                .trim();

        int arrayStart = normalized.indexOf('[');
        int objectStart = normalized.indexOf('{');

        if (arrayStart >= 0 && (objectStart < 0 || arrayStart < objectStart)) {
            int arrayEnd = normalized.lastIndexOf(']');
            if (arrayEnd > arrayStart) {
                return normalized.substring(arrayStart, arrayEnd + 1);
            }
        }

        if (objectStart >= 0) {
            int objectEnd = normalized.lastIndexOf('}');
            if (objectEnd > objectStart) {
                return normalized.substring(objectStart, objectEnd + 1);
            }
        }

        return normalized;
    }
    
    private List<TestCaseDTO.CreateRequest> optimizeGeneratedTestCases(
            UserStoryDTO userStory,
            Long userStoryId,
            List<TestCaseDTO.CreateRequest> generatedRequests,
            int count,
            UserStoryCaseGenerationTaskService.TaskEventLogger logger) {
        List<TestCaseDTO.CreateRequest> source = generatedRequests == null ? List.of() : generatedRequests;
        List<TestCaseDTO.CreateRequest> templates = buildHighQualityTemplateCases(userStory, userStoryId, Math.max(count, 8));
        List<TestCaseDTO.CreateRequest> accepted = new ArrayList<>();
        Set<String> titleKeys = new LinkedHashSet<>();

        int replacedCount = 0;

        for (int i = 0; i < source.size() && accepted.size() < count; i++) {
            TestCaseDTO.CreateRequest template = templates.get(i % templates.size());
            TestCaseDTO.CreateRequest merged = mergeCaseWithTemplate(source.get(i), template, userStoryId, false);
            int score = scoreTestCaseQuality(merged);
            if (score < 70) {
                merged = mergeCaseWithTemplate(source.get(i), template, userStoryId, true);
                replacedCount++;
            }

            String key = normalizeForKey(merged.getTitle());
            if (!StringUtils.hasText(key) || titleKeys.contains(key)) {
                continue;
            }
            titleKeys.add(key);
            accepted.add(merged);
        }

        for (TestCaseDTO.CreateRequest template : templates) {
            if (accepted.size() >= count) break;
            String key = normalizeForKey(template.getTitle());
            if (!StringUtils.hasText(key) || titleKeys.contains(key)) {
                continue;
            }
            titleKeys.add(key);
            accepted.add(template);
        }

        int coverageAdjusted = ensureMinimumCoverage(accepted, templates, count);

        if (logger != null) {
            logger.log(
                    "QUALITY",
                    String.format(
                            "模型产出 %d 条，质量通过 %d 条，低质量替换 %d 条，覆盖补齐 %d 条",
                            source.size(),
                            accepted.size(),
                            replacedCount,
                            coverageAdjusted
                    )
            );
        }

        if (accepted.isEmpty()) {
            return buildFallbackTestCases(userStory, userStoryId, count);
        }
        return accepted.stream().limit(count).collect(Collectors.toList());
    }

    private List<TestCaseDTO.CreateRequest> buildFallbackTestCases(UserStoryDTO us, Long userStoryId, int count) {
        return buildHighQualityTemplateCases(us, userStoryId, count).stream()
                .map(item -> withAdditionalTag(item, "ai-fallback"))
                .collect(Collectors.toList());
    }

    private List<TestCaseDTO.CreateRequest> buildHighQualityTemplateCases(
            UserStoryDTO userStory,
            Long userStoryId,
            int count) {
        int safeCount = Math.max(1, count);
        List<TestCaseDTO.CreateRequest> templates = new ArrayList<>();
        for (int i = 0; i < safeCount; i++) {
            templates.add(buildTemplateCase(userStory, userStoryId, i));
        }
        return templates;
    }

    private TestCaseDTO.CreateRequest buildTemplateCase(
            UserStoryDTO userStory,
            Long userStoryId,
            int index) {
        String usNumber = defaultIfBlank(userStory == null ? null : userStory.getUsNumber(), "US");
        String usTitle = defaultIfBlank(userStory == null ? null : userStory.getTitle(), "核心业务需求");
        String acceptance = defaultIfBlank(userStory == null ? null : userStory.getAcceptanceCriteria(), "");
        String given = resolveClause(acceptance, "given", "前置", "假如");
        String when = resolveClause(acceptance, "when", "当", "触发");
        String then = resolveClause(acceptance, "then", "那么", "则");
        String intent = resolveUserIntent(userStory, when);
        String outcome = resolveBusinessOutcome(userStory, then);
        TestCaseDTO.TestType testType = inferTestTypeByContext(userStory);

        int scenario = index % 5;
        int round = (index / 5) + 1;
        String roundSuffix = round > 1 ? "（扩展" + round + "）" : "";

        String title;
        String description;
        TestCaseDTO.Priority priority;
        String tags;
        List<TestCaseDTO.TestStepDTO> steps;

        switch (scenario) {
            case 0 -> {
                title = usNumber + " 主流程成功校验" + roundSuffix;
                description = "验证在满足前置条件时，用户可完成「" + intent + "」，并得到预期业务结果。";
                priority = TestCaseDTO.Priority.HIGH;
                tags = "ai-generated,quality-gated,happy-path";
                steps = List.of(
                        buildStep(1, "准备前置条件：" + defaultIfBlank(given, "业务依赖与账号数据准备完成"),
                                "前置条件满足，系统可执行核心流程", "env=staging;data=valid"),
                        buildStep(2, "进入目标功能并执行动作：" + defaultIfBlank(when, intent),
                                "成功进入目标流程且无报错", "entry=main-flow"),
                        buildStep(3, "提交有效输入并触发核心业务处理",
                                "系统返回成功状态，关键字段校验通过", "input=valid"),
                        buildStep(4, "校验业务结果：" + defaultIfBlank(then, outcome),
                                "页面/接口结果与业务规则一致", "assert=business-rule"),
                        buildStep(5, "刷新或重新进入页面验证结果回显",
                                "结果可追踪且数据持久化正确", "check=persistence")
                );
            }
            case 1 -> {
                title = usNumber + " 边界条件校验" + roundSuffix;
                description = "验证「" + usTitle + "」在边界输入下的处理逻辑、提示与数据一致性。";
                priority = TestCaseDTO.Priority.HIGH;
                tags = "ai-generated,quality-gated,boundary";
                steps = List.of(
                        buildStep(1, "准备边界测试数据（最小值、最大值、空值）",
                                "边界数据准备完成且可被系统接收", "input=min|max|empty"),
                        buildStep(2, "执行关键动作并注入边界数据：" + defaultIfBlank(when, intent),
                                "系统对边界输入给出明确处理结果", "mode=boundary"),
                        buildStep(3, "提交请求并观察返回状态与提示信息",
                                "返回码/页面提示符合边界规则定义", "assert=boundary-rule"),
                        buildStep(4, "校验系统未出现异常崩溃或脏数据",
                                "系统稳定，数据状态符合预期", "check=stability"),
                        buildStep(5, "回查日志或数据记录确认边界处理路径",
                                "边界处理可追踪，日志信息完整", "check=audit-log")
                );
            }
            case 2 -> {
                title = usNumber + " 异常输入拦截校验" + roundSuffix;
                description = "验证非法输入或非法状态下系统具备正确拦截、提示和数据保护能力。";
                priority = TestCaseDTO.Priority.HIGH;
                tags = "ai-generated,quality-gated,negative";
                steps = List.of(
                        buildStep(1, "构造非法输入或非法状态（缺失必填、格式错误、越权参数）",
                                "非法数据构造完成", "input=invalid"),
                        buildStep(2, "执行业务动作：" + defaultIfBlank(when, intent),
                                "系统识别请求并进入校验逻辑", "mode=negative"),
                        buildStep(3, "提交请求并捕获错误响应",
                                "返回明确错误码/错误提示，且文案可理解", "assert=error-response"),
                        buildStep(4, "校验业务数据未被错误写入",
                                "数据库/缓存无异常数据变更", "check=data-integrity"),
                        buildStep(5, "校验审计日志包含失败原因",
                                "失败原因可定位且不泄露敏感信息", "check=security-log")
                );
            }
            case 3 -> {
                title = usNumber + " 重复操作与幂等校验" + roundSuffix;
                description = "验证高频重复触发同一业务动作时，系统结果一致且不会产生重复脏数据。";
                priority = TestCaseDTO.Priority.MEDIUM;
                tags = "ai-generated,quality-gated,idempotent";
                steps = List.of(
                        buildStep(1, "准备可重复触发的有效业务数据",
                                "数据准备完成，满足重复调用条件", "input=repeatable-valid"),
                        buildStep(2, "连续两次执行核心动作：" + intent,
                                "系统均有响应，无超时与异常", "loop=2"),
                        buildStep(3, "比较两次执行的返回结果与状态",
                                "结果一致或符合幂等规则", "assert=idempotent"),
                        buildStep(4, "核对持久化数据记录是否重复",
                                "无重复记录或重复被正确合并", "check=duplicate"),
                        buildStep(5, "验证前端/接口展示状态与数据一致",
                                "展示信息与实际数据一致", "check=consistency")
                );
            }
            default -> {
                title = usNumber + " 数据一致性与回显校验" + roundSuffix;
                description = "验证操作完成后，跨页面/跨接口的状态、数据与展示保持一致。";
                priority = TestCaseDTO.Priority.MEDIUM;
                tags = "ai-generated,quality-gated,consistency";
                steps = List.of(
                        buildStep(1, "准备标准输入并完成一次完整业务操作",
                                "操作执行成功并生成业务结果", "input=standard-valid"),
                        buildStep(2, "在当前页面校验关键结果字段",
                                "关键字段与规则一致", "assert=current-view"),
                        buildStep(3, "刷新页面或切换到关联页面重新查询",
                                "结果回显正确且状态一致", "check=refresh"),
                        buildStep(4, "通过接口或后台查询核对同一条业务数据",
                                "前后端数据一致且无丢失", "check=api-db"),
                        buildStep(5, "校验最终状态满足验收标准：" + defaultIfBlank(then, outcome),
                                "最终状态满足业务验收要求", "assert=acceptance")
                );
            }
        }

        return TestCaseDTO.CreateRequest.builder()
                .title(title)
                .description(description)
                .preconditions(defaultIfBlank(given, "测试环境可用，依赖服务正常"))
                .testType(testType)
                .priority(priority)
                .userStoryId(userStoryId)
                .steps(steps)
                .tags(tags)
                .build();
    }

    private TestCaseDTO.TestType inferTestTypeByContext(UserStoryDTO userStory) {
        String context = (defaultIfBlank(userStory == null ? null : userStory.getTitle(), "")
                + " "
                + defaultIfBlank(userStory == null ? null : userStory.getDescription(), "")
                + " "
                + defaultIfBlank(userStory == null ? null : userStory.getAcceptanceCriteria(), "")).toLowerCase(Locale.ROOT);
        if (context.contains("api") || context.contains("接口") || context.contains("endpoint")) {
            return TestCaseDTO.TestType.API;
        }
        if (context.contains("性能") || context.contains("压测") || context.contains("吞吐") || context.contains("响应时间")) {
            return TestCaseDTO.TestType.PERFORMANCE;
        }
        if (context.contains("安全") || context.contains("鉴权") || context.contains("权限") || context.contains("token")) {
            return TestCaseDTO.TestType.SECURITY;
        }
        if (context.contains("兼容") || context.contains("浏览器") || context.contains("设备")) {
            return TestCaseDTO.TestType.COMPATIBILITY;
        }
        if (context.contains("页面") || context.contains("按钮") || context.contains("弹窗") || context.contains("banner") || context.contains("ui")) {
            return TestCaseDTO.TestType.UI;
        }
        return TestCaseDTO.TestType.FUNCTIONAL;
    }

    private String resolveClause(String acceptanceCriteria, String englishKeyword, String... aliases) {
        if (!StringUtils.hasText(acceptanceCriteria)) {
            return "";
        }
        String[] lines = acceptanceCriteria.split("\\r?\\n|;|；");
        for (String rawLine : lines) {
            String line = normalizeText(rawLine);
            if (!StringUtils.hasText(line)) continue;
            String lower = line.toLowerCase(Locale.ROOT);
            if (lower.startsWith(englishKeyword.toLowerCase(Locale.ROOT))) {
                return removeClausePrefix(line, englishKeyword);
            }
            for (String alias : aliases) {
                if (!StringUtils.hasText(alias)) continue;
                if (line.startsWith(alias)) {
                    return removeClausePrefix(line, alias);
                }
            }
        }
        return "";
    }

    private String removeClausePrefix(String line, String prefix) {
        if (!StringUtils.hasText(line) || !StringUtils.hasText(prefix)) {
            return normalizeText(line);
        }
        String cleaned = line.replaceFirst("(?i)^" + Pattern.quote(prefix) + "\\s*[:：-]?", "");
        return normalizeText(cleaned);
    }

    private String resolveUserIntent(UserStoryDTO userStory, String whenClause) {
        if (isMeaningfulText(whenClause, 4)) {
            return normalizeText(whenClause);
        }
        String description = defaultIfBlank(userStory == null ? null : userStory.getDescription(), "");
        if (StringUtils.hasText(description)) {
            for (String rawLine : description.split("\\r?\\n")) {
                String line = normalizeText(rawLine);
                String lower = line.toLowerCase(Locale.ROOT);
                if (lower.startsWith("i want")) {
                    return removeClausePrefix(line, "i want");
                }
                if (line.startsWith("我希望") || line.startsWith("希望")) {
                    return removeClausePrefix(line, line.startsWith("我希望") ? "我希望" : "希望");
                }
            }
        }
        return "完成「" + defaultIfBlank(userStory == null ? null : userStory.getTitle(), "核心业务操作") + "」";
    }

    private String resolveBusinessOutcome(UserStoryDTO userStory, String thenClause) {
        if (isMeaningfulText(thenClause, 4)) {
            return normalizeText(thenClause);
        }
        String description = defaultIfBlank(userStory == null ? null : userStory.getDescription(), "");
        if (StringUtils.hasText(description)) {
            for (String rawLine : description.split("\\r?\\n")) {
                String line = normalizeText(rawLine);
                String lower = line.toLowerCase(Locale.ROOT);
                if (lower.startsWith("so that")) {
                    return removeClausePrefix(line, "so that");
                }
                if (line.startsWith("从而") || line.startsWith("以便")) {
                    return removeClausePrefix(line, line.startsWith("从而") ? "从而" : "以便");
                }
            }
        }
        return "满足业务验收标准并可被验证";
    }

    private TestCaseDTO.CreateRequest mergeCaseWithTemplate(
            TestCaseDTO.CreateRequest candidate,
            TestCaseDTO.CreateRequest template,
            Long userStoryId,
            boolean forceTemplate) {
        String title = !forceTemplate && isMeaningfulText(candidate == null ? null : candidate.getTitle(), 8)
                && !isGenericTitle(candidate.getTitle())
                ? normalizeText(candidate.getTitle())
                : template.getTitle();
        String description = !forceTemplate && isMeaningfulText(candidate == null ? null : candidate.getDescription(), 12)
                ? normalizeText(candidate.getDescription())
                : template.getDescription();
        String preconditions = !forceTemplate && isMeaningfulText(candidate == null ? null : candidate.getPreconditions(), 8)
                ? normalizeText(candidate.getPreconditions())
                : template.getPreconditions();
        TestCaseDTO.TestType testType = candidate != null && candidate.getTestType() != null
                ? candidate.getTestType()
                : template.getTestType();
        TestCaseDTO.Priority priority = candidate != null && candidate.getPriority() != null
                ? candidate.getPriority()
                : template.getPriority();

        List<TestCaseDTO.TestStepDTO> steps = mergeSteps(
                candidate == null ? List.of() : candidate.getSteps(),
                template.getSteps(),
                forceTemplate
        );
        String tags = mergeTags(
                candidate == null ? null : candidate.getTags(),
                template.getTags(),
                forceTemplate ? "quality-gated" : null
        );
        title = alignTitleByContent(title, description, tags, template.getTitle());
        return TestCaseDTO.CreateRequest.builder()
                .title(title)
                .description(description)
                .preconditions(preconditions)
                .testType(testType)
                .priority(priority)
                .userStoryId(userStoryId)
                .steps(steps)
                .tags(tags)
                .build();
    }

    private List<TestCaseDTO.TestStepDTO> mergeSteps(
            List<TestCaseDTO.TestStepDTO> candidateSteps,
            List<TestCaseDTO.TestStepDTO> templateSteps,
            boolean forceTemplate) {
        List<TestCaseDTO.TestStepDTO> normalizedTemplate = copySteps(templateSteps);
        if (forceTemplate) {
            return normalizedTemplate;
        }
        List<TestCaseDTO.TestStepDTO> normalizedCandidate = copySteps(candidateSteps);
        if (normalizedCandidate.size() < 4) {
            return normalizedTemplate;
        }
        List<TestCaseDTO.TestStepDTO> merged = new ArrayList<>();
        int max = Math.max(normalizedCandidate.size(), normalizedTemplate.size());
        for (int i = 0; i < max; i++) {
            TestCaseDTO.TestStepDTO current = i < normalizedCandidate.size() ? normalizedCandidate.get(i) : null;
            TestCaseDTO.TestStepDTO fallback = i < normalizedTemplate.size() ? normalizedTemplate.get(i) : null;
            if (current == null && fallback == null) continue;
            String action = current == null ? null : normalizeText(current.getAction());
            String expected = current == null ? null : normalizeText(current.getExpectedResult());
            String testData = current == null ? "" : normalizeText(current.getTestData());

            if (!isMeaningfulText(action, 4) && fallback != null) {
                action = fallback.getAction();
            }
            if (!isMeaningfulText(expected, 6) || isWeakAssertion(expected)) {
                expected = fallback != null ? fallback.getExpectedResult() : "系统返回可验证的业务结果";
            }
            if (!StringUtils.hasText(testData) && fallback != null) {
                testData = fallback.getTestData();
            }
            if (!isMeaningfulText(action, 4)) {
                continue;
            }
            merged.add(buildStep(merged.size() + 1, action, expected, testData));
        }
        if (merged.size() < 4) {
            return normalizedTemplate;
        }
        return merged;
    }

    private List<TestCaseDTO.TestStepDTO> copySteps(List<TestCaseDTO.TestStepDTO> source) {
        if (source == null || source.isEmpty()) {
            return List.of();
        }
        List<TestCaseDTO.TestStepDTO> copied = new ArrayList<>();
        int order = 1;
        for (TestCaseDTO.TestStepDTO step : source) {
            if (step == null) continue;
            String action = normalizeText(step.getAction());
            if (!StringUtils.hasText(action)) continue;
            String expected = normalizeText(step.getExpectedResult());
            if (!StringUtils.hasText(expected)) {
                expected = "系统返回可验证的业务结果";
            }
            String testData = normalizeText(step.getTestData());
            copied.add(buildStep(order++, action, expected, testData));
        }
        return copied;
    }

    private TestCaseDTO.TestStepDTO buildStep(int order, String action, String expected, String testData) {
        return TestCaseDTO.TestStepDTO.builder()
                .stepOrder(order)
                .action(defaultIfBlank(normalizeText(action), "执行业务操作"))
                .expectedResult(defaultIfBlank(normalizeText(expected), "系统返回可验证的业务结果"))
                .testData(defaultIfBlank(normalizeText(testData), ""))
                .build();
    }

    private TestCaseDTO.CreateRequest withAdditionalTag(TestCaseDTO.CreateRequest source, String tag) {
        return TestCaseDTO.CreateRequest.builder()
                .title(source.getTitle())
                .description(source.getDescription())
                .preconditions(source.getPreconditions())
                .testType(source.getTestType())
                .priority(source.getPriority())
                .userStoryId(source.getUserStoryId())
                .steps(copySteps(source.getSteps()))
                .tags(appendTag(source.getTags(), tag))
                .build();
    }

    private List<TestCaseDTO.TestStepDTO> parseSteps(JsonNode stepsNode) {
        if (stepsNode == null || stepsNode.isNull()) {
            return List.of();
        }
        if (!stepsNode.isArray()) {
            if (stepsNode.isTextual()) {
                String text = normalizeText(stepsNode.asText(""));
                if (!StringUtils.hasText(text)) {
                    return List.of();
                }
                return List.of(buildStep(1, text, "系统返回可验证的业务结果", ""));
            }
            return List.of();
        }
        List<TestCaseDTO.TestStepDTO> steps = new ArrayList<>();
        int order = 1;
        for (JsonNode node : stepsNode) {
            if (node == null || node.isNull()) continue;
            if (node.isTextual()) {
                String action = normalizeText(node.asText(""));
                if (!StringUtils.hasText(action)) continue;
                steps.add(buildStep(order++, action, "系统返回可验证的业务结果", ""));
                continue;
            }
            String action = defaultIfBlank(readTextByAliases(node, "action", "operation", "step", "步骤", "操作"), "执行步骤");
            String expected = defaultIfBlank(readTextByAliases(node, "expectedResult", "expected", "assertion", "预期结果", "断言"), "系统返回可验证的业务结果");
            String testData = defaultIfBlank(readTextByAliases(node, "testData", "data", "input", "测试数据", "输入"), "");
            int stepOrder = readIntByAliases(node, order, "stepOrder", "order", "序号", "步骤序号");
            steps.add(buildStep(stepOrder, action, expected, testData));
            order++;
        }
        List<TestCaseDTO.TestStepDTO> normalized = copySteps(steps);
        for (int i = 0; i < normalized.size(); i++) {
            normalized.get(i).setStepOrder(i + 1);
        }
        return normalized;
    }

    private int scoreTestCaseQuality(TestCaseDTO.CreateRequest request) {
        if (request == null) return 0;
        int score = 0;
        if (isMeaningfulText(request.getTitle(), 8) && !isGenericTitle(request.getTitle())) score += 20;
        if (isMeaningfulText(request.getDescription(), 12)) score += 15;
        if (isMeaningfulText(request.getPreconditions(), 8)) score += 10;
        List<TestCaseDTO.TestStepDTO> steps = request.getSteps() == null ? List.of() : request.getSteps();
        if (steps.size() >= 4) score += 25;
        long strongActions = steps.stream()
                .filter(step -> isMeaningfulText(step.getAction(), 4))
                .count();
        if (strongActions >= 4) score += 10;
        long strongExpected = steps.stream()
                .filter(step -> isMeaningfulText(step.getExpectedResult(), 6) && !isWeakAssertion(step.getExpectedResult()))
                .count();
        if (strongExpected >= 4) score += 15;
        boolean hasTestData = steps.stream().anyMatch(step -> isMeaningfulText(step.getTestData(), 2));
        if (hasTestData) score += 5;
        return Math.min(100, Math.max(0, score));
    }

    private int ensureMinimumCoverage(
            List<TestCaseDTO.CreateRequest> accepted,
            List<TestCaseDTO.CreateRequest> templates,
            int targetCount) {
        if (accepted == null || accepted.isEmpty() || templates == null || templates.isEmpty() || targetCount <= 0) {
            return 0;
        }
        int adjusted = 0;
        if (!containsCoverageCase(accepted, "HAPPY")) {
            adjusted += upsertCoverageCase(accepted, templates.get(0), targetCount, "HAPPY");
        }
        if (templates.size() > 1 && targetCount >= 2 && !containsCoverageCase(accepted, "BOUNDARY")) {
            adjusted += upsertCoverageCase(accepted, templates.get(1), targetCount, "BOUNDARY");
        }
        if (templates.size() > 2 && targetCount >= 3 && !containsCoverageCase(accepted, "NEGATIVE")) {
            adjusted += upsertCoverageCase(accepted, templates.get(2), targetCount, "NEGATIVE");
        }
        return adjusted;
    }

    private int upsertCoverageCase(
            List<TestCaseDTO.CreateRequest> accepted,
            TestCaseDTO.CreateRequest template,
            int targetCount,
            String coverageType) {
        if (template == null) return 0;
        TestCaseDTO.CreateRequest coverageCase = withAdditionalTag(template, "coverage-fix");
        String key = normalizeForKey(coverageCase.getTitle());
        if (!StringUtils.hasText(key)) {
            return 0;
        }

        if (accepted.size() < targetCount) {
            boolean exists = accepted.stream()
                    .map(TestCaseDTO.CreateRequest::getTitle)
                    .map(this::normalizeForKey)
                    .anyMatch(key::equals);
            if (!exists) {
                accepted.add(coverageCase);
                return 1;
            }
            return 0;
        }

        for (int i = accepted.size() - 1; i >= 0; i--) {
            if (!matchesCoverageType(accepted.get(i), coverageType)) {
                accepted.set(i, coverageCase);
                return 1;
            }
        }
        accepted.set(accepted.size() - 1, coverageCase);
        return 1;
    }

    private boolean containsCoverageCase(List<TestCaseDTO.CreateRequest> cases, String coverageType) {
        return cases.stream().anyMatch(item -> matchesCoverageType(item, coverageType));
    }

    private String alignTitleByContent(String title, String description, String tags, String fallbackTitle) {
        String normalizedTitle = normalizeText(title);
        String source = (defaultIfBlank(description, "") + " " + defaultIfBlank(tags, "")).toLowerCase(Locale.ROOT);
        boolean boundary = source.contains("boundary") || source.contains("边界") || source.contains("最小值") || source.contains("最大值");
        boolean negative = source.contains("negative") || source.contains("异常") || source.contains("错误") || source.contains("失败");
        String lowerTitle = normalizedTitle.toLowerCase(Locale.ROOT);
        boolean titleHasBoundary = lowerTitle.contains("boundary") || normalizedTitle.contains("边界");
        boolean titleHasNegative = lowerTitle.contains("negative") || normalizedTitle.contains("异常") || normalizedTitle.contains("错误");

        if (boundary && !titleHasBoundary) {
            if (StringUtils.hasText(fallbackTitle) && fallbackTitle.contains("边界")) {
                return fallbackTitle;
            }
            if (titleHasNegative) {
                return normalizedTitle.replace("异常输入拦截校验", "边界条件校验");
            }
            return normalizedTitle + "（边界）";
        }
        if (negative && !titleHasNegative) {
            if (StringUtils.hasText(fallbackTitle) && (fallbackTitle.contains("异常") || fallbackTitle.contains("负向"))) {
                return fallbackTitle;
            }
            return normalizedTitle + "（异常）";
        }
        return normalizedTitle;
    }

    private boolean matchesCoverageType(TestCaseDTO.CreateRequest request, String coverageType) {
        if (request == null) return false;
        String source = (
                defaultIfBlank(request.getTitle(), "")
                        + " "
                        + defaultIfBlank(request.getDescription(), "")
                        + " "
                        + defaultIfBlank(request.getTags(), "")
        ).toLowerCase(Locale.ROOT);
        return switch (coverageType) {
            case "HAPPY" -> source.contains("happy")
                    || source.contains("主流程")
                    || source.contains("成功校验")
                    || source.contains("happy-path");
            case "BOUNDARY" -> source.contains("boundary")
                    || source.contains("边界")
                    || source.contains("最小值")
                    || source.contains("最大值");
            case "NEGATIVE" -> source.contains("negative")
                    || source.contains("异常")
                    || source.contains("失败")
                    || source.contains("错误");
            default -> false;
        };
    }

    private boolean isMeaningfulText(String text, int minLength) {
        String normalized = normalizeText(text);
        return StringUtils.hasText(normalized) && normalized.length() >= minLength;
    }

    private boolean isGenericTitle(String title) {
        String normalized = normalizeText(title).toLowerCase(Locale.ROOT);
        if (!StringUtils.hasText(normalized)) return true;
        return normalized.contains("positive scenario")
                || normalized.contains("negative scenario")
                || normalized.contains("自动生成")
                || normalized.contains("test case")
                || normalized.equals("测试用例")
                || normalized.equals("ai 生成测试用例");
    }

    private boolean isWeakAssertion(String expected) {
        String normalized = normalizeText(expected).toLowerCase(Locale.ROOT);
        if (!StringUtils.hasText(normalized)) return true;
        return normalized.equals("步骤执行成功")
                || normalized.equals("执行成功")
                || normalized.equals("成功")
                || normalized.contains("符合预期")
                || normalized.contains("正常");
    }

    private String normalizeForKey(String text) {
        String normalized = normalizeText(text).toLowerCase(Locale.ROOT);
        return normalized.replaceAll("\\s+", "");
    }

    private String normalizeText(String text) {
        if (!StringUtils.hasText(text)) {
            return "";
        }
        String normalized = text
                .replace('\u3000', ' ')
                .replaceAll("[\\t\\r\\n]+", " ")
                .replaceAll("\\s{2,}", " ")
                .trim();
        return normalized;
    }

    private String mergeTags(String primary, String secondary, String extra) {
        Set<String> tags = new LinkedHashSet<>();
        if (StringUtils.hasText(primary)) {
            for (String token : primary.split("[,，|/\\s]+")) {
                String cleaned = normalizeText(token);
                if (StringUtils.hasText(cleaned)) {
                    tags.add(cleaned.toLowerCase(Locale.ROOT));
                }
            }
        }
        if (StringUtils.hasText(secondary)) {
            for (String token : secondary.split("[,，|/\\s]+")) {
                String cleaned = normalizeText(token);
                if (StringUtils.hasText(cleaned)) {
                    tags.add(cleaned.toLowerCase(Locale.ROOT));
                }
            }
        }
        if (StringUtils.hasText(extra)) {
            tags.add(normalizeText(extra).toLowerCase(Locale.ROOT));
        }
        if (tags.isEmpty()) {
            tags.add("ai-generated");
        } else if (!tags.contains("ai-generated")) {
            tags.add("ai-generated");
        }
        return String.join(",", tags);
    }

    private String appendTag(String tags, String tag) {
        return mergeTags(tags, null, tag);
    }

    private UserStory.Priority parseUsPriority(String value) {
        try {
            return UserStory.Priority.valueOf(value.trim().toUpperCase());
        } catch (Exception ex) {
            return UserStory.Priority.MEDIUM;
        }
    }

    private TestCaseDTO.Priority parseTestPriority(String value) {
        if (!StringUtils.hasText(value)) {
            return TestCaseDTO.Priority.MEDIUM;
        }
        String normalized = value.trim().toUpperCase(Locale.ROOT);
        return switch (normalized) {
            case "P0", "L0", "CRITICAL", "SEV-0", "SEV0", "最高", "紧急" -> TestCaseDTO.Priority.CRITICAL;
            case "P1", "L1", "HIGH", "SEV-1", "SEV1", "高" -> TestCaseDTO.Priority.HIGH;
            case "P3", "L3", "LOW", "SEV-3", "SEV3", "低" -> TestCaseDTO.Priority.LOW;
            case "P2", "L2", "MEDIUM", "SEV-2", "SEV2", "中" -> TestCaseDTO.Priority.MEDIUM;
            default -> {
                try {
                    yield TestCaseDTO.Priority.valueOf(normalized);
                } catch (Exception ignored) {
                    yield TestCaseDTO.Priority.MEDIUM;
                }
            }
        };
    }

    private TestCaseDTO.TestType parseTestType(String value) {
        if (!StringUtils.hasText(value)) {
            return TestCaseDTO.TestType.FUNCTIONAL;
        }
        String normalized = value.trim().toUpperCase(Locale.ROOT);
        if (normalized.contains("UI") || normalized.contains("界面") || normalized.contains("页面")) {
            return TestCaseDTO.TestType.UI;
        }
        if (normalized.contains("API") || normalized.contains("接口")) {
            return TestCaseDTO.TestType.API;
        }
        if (normalized.contains("PERF") || normalized.contains("性能")) {
            return TestCaseDTO.TestType.PERFORMANCE;
        }
        if (normalized.contains("SEC") || normalized.contains("安全") || normalized.contains("权限")) {
            return TestCaseDTO.TestType.SECURITY;
        }
        if (normalized.contains("COMPAT") || normalized.contains("兼容")) {
            return TestCaseDTO.TestType.COMPATIBILITY;
        }
        try {
            return TestCaseDTO.TestType.valueOf(normalized);
        } catch (Exception ex) {
            return TestCaseDTO.TestType.FUNCTIONAL;
        }
    }

    private List<ImportSeed> parseImportSeeds(ImportRequest request, int maxCount) {
        if (request == null) {
            return List.of();
        }
        String sourceType = normalizeSourceType(request.getSourceType());
        String content = request.getContent();

        if ("CSV".equals(sourceType)) {
            return parseCsv(content, maxCount);
        }
        if ("EXCEL".equals(sourceType)) {
            return parseTsv(content, maxCount);
        }
        if ("JIRA".equals(sourceType)) {
            return parseJira(content, request.getProjectKey(), request.getServerUrl(), maxCount);
        }
        return parsePlainText(content, maxCount);
    }

    private String normalizeSourceType(String sourceType) {
        if (!StringUtils.hasText(sourceType)) {
            return "TEXT";
        }
        return sourceType.trim().toUpperCase(Locale.ROOT);
    }

    private List<ImportSeed> parseCsv(String content, int maxCount) {
        if (!StringUtils.hasText(content)) {
            return List.of();
        }
        List<ImportSeed> seeds = new ArrayList<>();
        for (String rawLine : content.split("\\r?\\n")) {
            String line = rawLine.trim();
            if (line.isEmpty()) continue;
            String[] cells = line.split(",", -1);
            String title = cells.length > 0 ? cells[0].trim() : "";
            String description = cells.length > 1 ? cells[1].trim() : title;
            String acceptance = cells.length > 2 ? cells[2].trim() : "满足业务验收标准";
            if (!StringUtils.hasText(title)) continue;
            seeds.add(new ImportSeed(title, defaultIfBlank(description, title), defaultIfBlank(acceptance, "满足业务验收标准")));
            if (seeds.size() >= maxCount) break;
        }
        return seeds;
    }

    private List<ImportSeed> parseTsv(String content, int maxCount) {
        if (!StringUtils.hasText(content)) {
            return List.of();
        }
        List<ImportSeed> seeds = new ArrayList<>();
        for (String rawLine : content.split("\\r?\\n")) {
            String line = rawLine.trim();
            if (line.isEmpty()) continue;
            String[] cells = line.split("\\t", -1);
            String title = cells.length > 0 ? cells[0].trim() : "";
            String description = cells.length > 1 ? cells[1].trim() : title;
            String acceptance = cells.length > 2 ? cells[2].trim() : "满足业务验收标准";
            if (!StringUtils.hasText(title)) continue;
            seeds.add(new ImportSeed(title, defaultIfBlank(description, title), defaultIfBlank(acceptance, "满足业务验收标准")));
            if (seeds.size() >= maxCount) break;
        }
        return seeds;
    }

    private List<ImportSeed> parseJira(String content, String projectKey, String serverUrl, int maxCount) {
        List<ImportSeed> seeds = new ArrayList<>();
        if (StringUtils.hasText(content)) {
            Matcher matcher = ISSUE_KEY_PATTERN.matcher(content.toUpperCase(Locale.ROOT));
            while (matcher.find() && seeds.size() < maxCount) {
                String issueKey = matcher.group(1);
                String title = "JIRA 导入 " + issueKey;
                String description = "来源: " + defaultIfBlank(serverUrl, "JIRA") + "\nIssue: " + issueKey;
                seeds.add(new ImportSeed(title, description, "Issue 对应需求可被正确实现"));
            }
        }
        if (seeds.isEmpty()) {
            String key = StringUtils.hasText(projectKey) ? projectKey.toUpperCase(Locale.ROOT) : "JIRA";
            for (int i = 1; i <= Math.min(maxCount, 3); i++) {
                String issue = key + "-" + (1000 + i);
                seeds.add(new ImportSeed("JIRA 导入 " + issue,
                        "来源: " + defaultIfBlank(serverUrl, "JIRA") + "\nIssue: " + issue,
                        "Issue 对应需求可被正确实现"));
            }
        }
        return seeds;
    }

    private List<ImportSeed> parsePlainText(String content, int maxCount) {
        if (!StringUtils.hasText(content)) {
            return List.of();
        }
        List<ImportSeed> seeds = new ArrayList<>();
        for (String rawLine : content.split("\\r?\\n")) {
            String line = rawLine.trim();
            if (line.isEmpty()) continue;
            seeds.add(new ImportSeed(line, line, "满足业务验收标准"));
            if (seeds.size() >= maxCount) break;
        }
        return seeds;
    }

    private String buildImportUsNumber(String projectKey, int index) {
        String prefix = StringUtils.hasText(projectKey)
                ? projectKey.replaceAll("[^A-Za-z0-9]", "").toUpperCase(Locale.ROOT)
                : "IMP";
        String ts = String.valueOf(System.currentTimeMillis());
        String suffix = ts.substring(Math.max(0, ts.length() - 6));
        return prefix + "-" + suffix + "-" + index;
    }

    private String defaultIfBlank(String text, String fallback) {
        return StringUtils.hasText(text) ? text : fallback;
    }

    private String safeErrorMessage(Throwable throwable) {
        if (throwable == null) return "未知错误";
        String message = throwable.getMessage();
        if (!StringUtils.hasText(message)) return "未知错误";
        return message.trim();
    }

    private Map<String, Object> pingServer(String serverUrl) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("target", serverUrl);
        try {
            HttpClient client = HttpClient.newBuilder()
                    .connectTimeout(Duration.ofSeconds(3))
                    .build();
            HttpRequest request = HttpRequest.newBuilder(URI.create(serverUrl))
                    .timeout(Duration.ofSeconds(3))
                    .method("HEAD", HttpRequest.BodyPublishers.noBody())
                    .build();
            HttpResponse<Void> response = client.send(request, HttpResponse.BodyHandlers.discarding());
            int code = response.statusCode();
            result.put("reachable", code >= 200 && code < 500);
            result.put("statusCode", code);
            result.put("message", "连接测试完成");
        } catch (Exception ex) {
            result.put("reachable", false);
            result.put("message", ex.getMessage());
        }
        return result;
    }
    
    @lombok.Data
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class GenerateTestCasesRequest {
        private Integer count;
        private String feedback;
    }

    @lombok.Data
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class AdoptGeneratedCasesRequest {
        private List<String> draftIds;
    }

    @lombok.Data
    @lombok.NoArgsConstructor
    @lombok.AllArgsConstructor
    public static class ImportRequest {
        private String sourceType;
        private String serverUrl;
        private String apiToken;
        private String projectKey;
        private String content;
        private Integer maxCount;
        private String sprint;
        private String epic;
        private String storyPoints;
        private UserStory.Priority priority;
    }

    private record ImportSeed(String title, String description, String acceptanceCriteria) {
    }
}
