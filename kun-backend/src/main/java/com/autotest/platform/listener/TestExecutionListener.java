package com.autotest.platform.listener;

import com.autotest.platform.dto.TestExecutionDTO;
import com.autotest.platform.entity.ExecutionScreenshot;
import com.autotest.platform.entity.ExecutionTimeline;
import com.autotest.platform.entity.TestExecution;
import com.autotest.platform.event.TestExecutionRequestedEvent;
import com.autotest.platform.service.TestExecutionService;
import com.autotest.platform.websocket.ExecutionWebSocketController;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Component
@RequiredArgsConstructor
@Slf4j
public class TestExecutionListener {

    private static final String PLAYWRIGHT_RUNNER_PATH = "/app/playwright-runner/runner.mjs";
    private static final Pattern LOCALHOST_URL_PATTERN = Pattern.compile("(?i)https?://(?:localhost|127\\.0\\.0\\.1)(?::\\d+)?");

    private final TestExecutionService testExecutionService;
    private final ExecutionWebSocketController webSocketController;
    private final ObjectMapper objectMapper;

    @Value("${platform.file-storage.local-path:./uploads}")
    private String fileStoragePath;

    @Value("${platform.execution.localhost-rewrite-base-url:}")
    private String localhostRewriteBaseUrl;

    @Async
    @EventListener
    public void handleTestExecutionRequested(TestExecutionRequestedEvent event) {
        if (event == null || event.executionId() == null) {
            return;
        }
        handleTestExecution(event.executionId());
    }

    private void handleTestExecution(Long executionId) {
        log.info("Received test execution task: {}", executionId);
        TestExecutionDTO initial = null;
        try {
            initial = testExecutionService.getExecutionByIdForWorker(executionId);
            if (initial.getStatus() == TestExecutionDTO.ExecutionStatus.PENDING
                    || initial.getStatus() == TestExecutionDTO.ExecutionStatus.QUEUED) {
                testExecutionService.startExecution(executionId);
            }

            TestExecutionDTO execution = testExecutionService.getExecutionByIdForWorker(executionId);
            TestExecutionService.ExecutionRuntimeContext runtime = testExecutionService.getExecutionRuntimeContextForWorker(executionId);
            String modeText = Boolean.TRUE.equals(execution.getPreviewMode()) ? "Preview" : "Standard";
            String scriptLabel = execution.getScriptName() != null
                    ? execution.getScriptName()
                    : (execution.getScriptId() != null ? "Script#" + execution.getScriptId() : "N/A");
            testExecutionService.appendLog(executionId, "Execution mode: " + modeText + ", script: " + scriptLabel);
            testExecutionService.appendLog(executionId, "Switch to real Playwright execution engine");

            webSocketController.sendExecutionUpdate(
                    execution.getExecutionId(),
                    TestExecutionDTO.ExecutionStatus.RUNNING,
                    0,
                    "Playwright 执行已启动"
            );

            runPlaywrightExecution(executionId, execution, runtime);

        } catch (Exception e) {
            log.error("Error executing test: {}", executionId, e);
            String message = "Execution failed: " + e.getMessage();
            testExecutionService.appendLog(executionId, message);
            testExecutionService.failExecution(executionId, e.getMessage());

            TestExecutionDTO failed = initial != null
                    ? testExecutionService.getExecutionByIdForWorker(executionId)
                    : TestExecutionDTO.builder().executionId("UNKNOWN").build();
            webSocketController.sendExecutionUpdate(
                    failed.getExecutionId(),
                    TestExecutionDTO.ExecutionStatus.FAILED,
                    100,
                    message
            );
        }
    }

    private void runPlaywrightExecution(Long executionId,
                                        TestExecutionDTO execution,
                                        TestExecutionService.ExecutionRuntimeContext runtime) throws Exception {
        if (runtime == null || !StringUtils.hasText(runtime.scriptCode())) {
            throw new RuntimeException("执行失败：脚本内容为空，无法启动 Playwright");
        }

        String executionCode = StringUtils.hasText(runtime.executionCode()) ? runtime.executionCode() : "EXEC-UNKNOWN";
        String browser = StringUtils.hasText(runtime.browser()) ? runtime.browser().trim().toLowerCase(Locale.ROOT) : "chromium";
        if (!List.of("chromium", "firefox", "webkit").contains(browser)) {
            browser = "chromium";
        }

        Path executionRoot = Paths.get(fileStoragePath).toAbsolutePath().normalize()
                .resolve("executions")
                .resolve(executionCode);
        Path scriptsDir = executionRoot.resolve("scripts");
        Path artifactsDir = executionRoot.resolve("artifacts");
        Files.createDirectories(scriptsDir);
        Files.createDirectories(artifactsDir);

        String scriptFileName = normalizeScriptFileName(runtime.scriptName(), runtime.caseNumber());
        Path scriptFile = scriptsDir.resolve(scriptFileName);
        String rewrittenScriptCode = rewriteLocalhostUrls(runtime.scriptCode());
        if (!rewrittenScriptCode.equals(runtime.scriptCode())) {
            testExecutionService.appendLog(executionId,
                    "Detected localhost URL in script and rewrote to: " + normalizeRewriteBaseUrl(localhostRewriteBaseUrl));
        }
        Files.writeString(scriptFile, rewrittenScriptCode, StandardCharsets.UTF_8);
        testExecutionService.appendLog(executionId, "Script materialized: " + scriptFile);

        TestExecutionDTO.ExecutionTimelineDTO startStep = testExecutionService.appendTimeline(
                executionId,
                1,
                "Playwright Runner Boot",
                ExecutionTimeline.StepStatus.STARTED,
                0L,
                "初始化真实浏览器执行环境",
                null
        );
        webSocketController.sendTimelineUpdate(executionCode, startStep);
        webSocketController.sendExecutionUpdate(
                executionCode,
                TestExecutionDTO.ExecutionStatus.RUNNING,
                10,
                "浏览器引擎已初始化"
        );

        Path resultFile = artifactsDir.resolve("result.json");
        List<String> processLogLines = runPlaywrightRunner(executionId, scriptFile, artifactsDir, browser, resultFile);
        PlaywrightRunResult runResult = readRunResult(resultFile);

        if (runResult == null) {
            throw new RuntimeException("Playwright result missing");
        }

        int totalTests = runResult.getTests() == null ? 0 : runResult.getTests().size();
        int stepOrder = 2;
        if (totalTests == 0) {
            TestExecutionDTO.ExecutionTimelineDTO timeline = testExecutionService.appendTimeline(
                    executionId,
                    stepOrder++,
                    "Playwright Test",
                    runResult.isSuccess() ? ExecutionTimeline.StepStatus.COMPLETED : ExecutionTimeline.StepStatus.FAILED,
                    runResult.getDurationMs(),
                    defaultIfBlank(runResult.getErrorMessage(), runResult.isSuccess() ? "无测试用例结果，执行已完成" : "未读取到测试结果"),
                    null
            );
            webSocketController.sendTimelineUpdate(executionCode, timeline);
        } else {
            for (PlaywrightTestResult testResult : runResult.getTests()) {
                boolean passed = "passed".equalsIgnoreCase(defaultIfBlank(testResult.getStatus(), ""));
                boolean skipped = "skipped".equalsIgnoreCase(defaultIfBlank(testResult.getStatus(), ""));
                ExecutionTimeline.StepStatus status = skipped
                        ? ExecutionTimeline.StepStatus.SKIPPED
                        : (passed ? ExecutionTimeline.StepStatus.COMPLETED : ExecutionTimeline.StepStatus.FAILED);
                String details = passed
                        ? "断言通过"
                        : defaultIfBlank(testResult.getError(), "断言失败或执行异常");
                TestExecutionDTO.ExecutionTimelineDTO timeline = testExecutionService.appendTimeline(
                        executionId,
                        stepOrder++,
                        defaultIfBlank(testResult.getTitle(), "Playwright Test"),
                        status,
                        testResult.getDurationMs(),
                        details,
                        null
                );
                webSocketController.sendTimelineUpdate(executionCode, timeline);
            }
        }

        Map<String, ActionScreenshotCapture> actionScreenshotMap = indexActionScreenshots(runResult.getActionScreenshots());
        List<Path> screenshotFiles = resolveArtifactFiles(artifactsDir, runResult.getScreenshotFiles());
        int screenshotIndex = 1;
        for (Path screenshot : screenshotFiles) {
            String screenshotRelative = toRelativePath(artifactsDir, screenshot);
            ActionScreenshotCapture capture = actionScreenshotMap.getOrDefault(screenshotRelative, null);
            String screenshotUrl = toArtifactUrl(executionId, executionRoot, screenshot);
            String stepName = capture != null
                    ? "Action: " + defaultIfBlank(capture.getAction(), "step")
                    : "Playwright Artifact";
            String details = capture != null
                    ? buildScreenshotDescription(capture)
                    : "真实浏览器执行截图";
            TestExecutionDTO.ExecutionScreenshotDTO screenshotDTO = testExecutionService.appendScreenshot(
                    executionId,
                    screenshotUrl,
                    stepName,
                    capture != null && capture.getStepNumber() != null ? capture.getStepNumber() : screenshotIndex++,
                    details,
                    ExecutionScreenshot.ScreenshotType.SUCCESS
            );
            webSocketController.sendScreenshotUpdate(executionCode, screenshotDTO);
            if (capture != null && capture.getStepNumber() != null) {
                screenshotIndex = Math.max(screenshotIndex, capture.getStepNumber() + 1);
            }
        }

        Path reportFile = resolveSingleArtifactFile(artifactsDir, runResult.getReportFile());
        Path videoFile = resolveFirstArtifactFile(artifactsDir, runResult.getVideoFiles());
        String reportUrl = reportFile != null ? toArtifactUrl(executionId, executionRoot, reportFile) : null;
        String videoUrl = videoFile != null ? toArtifactUrl(executionId, executionRoot, videoFile) : null;
        testExecutionService.updateExecutionArtifacts(executionId, reportUrl, videoUrl);

        String mergedLogs = testExecutionService.getExecutionByIdForWorker(executionId).getLogs();
        if (runResult.isSuccess()) {
            testExecutionService.completeExecution(executionId, TestExecution.ExecutionResult.PASS, mergedLogs);
            webSocketController.sendExecutionUpdate(
                    executionCode,
                    TestExecutionDTO.ExecutionStatus.COMPLETED,
                    100,
                    "Playwright 执行完成，全部断言通过"
            );
        } else {
            String failureMessage = defaultIfBlank(runResult.getErrorMessage(), "Playwright 执行失败");
            testExecutionService.completeExecution(executionId, TestExecution.ExecutionResult.FAIL, mergedLogs);
            testExecutionService.appendLog(executionId, "Playwright failure: " + failureMessage);
            webSocketController.sendExecutionUpdate(
                    executionCode,
                    TestExecutionDTO.ExecutionStatus.COMPLETED,
                    100,
                    "Playwright 执行完成，但存在失败断言"
            );
        }

        testExecutionService.appendLog(executionId, "Playwright process logs captured: " + processLogLines.size());
    }

    private List<String> runPlaywrightRunner(Long executionId,
                                             Path scriptFile,
                                             Path artifactsDir,
                                             String browser,
                                             Path resultFile) throws Exception {
        if (!Files.exists(Paths.get(PLAYWRIGHT_RUNNER_PATH))) {
            throw new RuntimeException("Playwright runner not found: " + PLAYWRIGHT_RUNNER_PATH);
        }

        List<String> command = List.of(
                "node",
                PLAYWRIGHT_RUNNER_PATH,
                "--script", scriptFile.toString(),
                "--output", artifactsDir.toString(),
                "--browser", browser,
                "--result", resultFile.toString()
        );
        ProcessBuilder processBuilder = new ProcessBuilder(command);
        processBuilder.redirectErrorStream(true);
        processBuilder.directory(artifactsDir.toFile());
        Process process = processBuilder.start();

        List<String> lines = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                String normalized = line.strip();
                lines.add(normalized);
                if (!normalized.isEmpty()) {
                    testExecutionService.appendLog(executionId, "[PW] " + normalized);
                }
            }
        }

        int exitCode = process.waitFor();
        testExecutionService.appendLog(executionId, "Playwright process exited with code: " + exitCode);
        if (exitCode != 0 && !Files.exists(resultFile)) {
            throw new RuntimeException("Playwright process failed and result file missing");
        }
        return lines;
    }

    private PlaywrightRunResult readRunResult(Path resultFile) throws Exception {
        if (!Files.exists(resultFile)) {
            return null;
        }
        return objectMapper.readValue(resultFile.toFile(), PlaywrightRunResult.class);
    }

    private List<Path> resolveArtifactFiles(Path artifactsDir, List<String> relatives) {
        if (relatives == null || relatives.isEmpty()) return List.of();
        List<Path> files = new ArrayList<>();
        for (String relative : relatives) {
            Path resolved = resolveSingleArtifactFile(artifactsDir, relative);
            if (resolved != null) {
                files.add(resolved);
            }
        }
        return files;
    }

    private Path resolveFirstArtifactFile(Path artifactsDir, List<String> relatives) {
        if (relatives == null || relatives.isEmpty()) return null;
        for (String relative : relatives) {
            Path resolved = resolveSingleArtifactFile(artifactsDir, relative);
            if (resolved != null) return resolved;
        }
        return null;
    }

    private Path resolveSingleArtifactFile(Path artifactsDir, String relative) {
        if (!StringUtils.hasText(relative)) return null;
        String normalized = relative.replace('\\', '/').replaceAll("^/+", "");
        if (normalized.contains("..")) return null;
        Path resolved = artifactsDir.resolve(normalized).normalize();
        if (!resolved.startsWith(artifactsDir)) return null;
        if (!Files.exists(resolved) || Files.isDirectory(resolved)) return null;
        return resolved;
    }

    private String toArtifactUrl(Long executionId, Path executionRoot, Path file) {
        Path normalizedRoot = executionRoot.toAbsolutePath().normalize();
        Path normalizedFile = file.toAbsolutePath().normalize();
        if (!normalizedFile.startsWith(normalizedRoot)) {
            throw new RuntimeException("Artifact path out of execution root");
        }
        String relative = normalizedRoot.relativize(normalizedFile).toString().replace('\\', '/');
        return "/api/executions/" + executionId + "/artifacts/" + relative;
    }

    private String normalizeScriptFileName(String scriptName, String caseNumber) {
        String source = StringUtils.hasText(scriptName) ? scriptName : (StringUtils.hasText(caseNumber) ? caseNumber : "generated-script");
        String safe = source.replaceAll("[^A-Za-z0-9._-]", "-");
        if (!safe.endsWith(".spec.js")) {
            if (safe.endsWith(".js")) {
                safe = safe.substring(0, safe.length() - 3) + ".spec.js";
            } else {
                safe = safe + ".spec.js";
            }
        }
        if (safe.length() > 120) {
            safe = safe.substring(0, 120);
            if (!safe.endsWith(".spec.js")) {
                safe = safe.replaceAll("\\.js$", "") + ".spec.js";
            }
        }
        return safe.toLowerCase(Locale.ROOT);
    }

    private String rewriteLocalhostUrls(String scriptCode) {
        if (!StringUtils.hasText(scriptCode)) {
            return scriptCode;
        }
        String rewriteBaseUrl = normalizeRewriteBaseUrl(localhostRewriteBaseUrl);
        if (!StringUtils.hasText(rewriteBaseUrl)) {
            return scriptCode;
        }
        return LOCALHOST_URL_PATTERN.matcher(scriptCode).replaceAll(Matcher.quoteReplacement(rewriteBaseUrl));
    }

    private String normalizeRewriteBaseUrl(String rawBaseUrl) {
        if (!StringUtils.hasText(rawBaseUrl)) {
            return "";
        }
        String normalized = rawBaseUrl.trim();
        while (normalized.endsWith("/")) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }
        return normalized;
    }

    private String defaultIfBlank(String value, String fallback) {
        return StringUtils.hasText(value) ? value.trim() : fallback;
    }

    private String toRelativePath(Path baseDir, Path targetFile) {
        Path normalizedBase = baseDir.toAbsolutePath().normalize();
        Path normalizedFile = targetFile.toAbsolutePath().normalize();
        if (!normalizedFile.startsWith(normalizedBase)) {
            return "";
        }
        return normalizedBase.relativize(normalizedFile).toString().replace('\\', '/');
    }

    private Map<String, ActionScreenshotCapture> indexActionScreenshots(List<ActionScreenshotCapture> captures) {
        if (captures == null || captures.isEmpty()) {
            return Map.of();
        }
        Map<String, ActionScreenshotCapture> map = new HashMap<>();
        for (ActionScreenshotCapture capture : captures) {
            if (capture == null || !StringUtils.hasText(capture.getFile())) continue;
            String normalized = capture.getFile().replace('\\', '/').replaceAll("^/+", "");
            map.put(normalized, capture);
        }
        return map;
    }

    private String buildScreenshotDescription(ActionScreenshotCapture capture) {
        String target = StringUtils.hasText(capture.getTarget())
                ? capture.getTarget().trim()
                : "关键动作完成";
        if (target.length() > 120) {
            target = target.substring(0, 120) + "...";
        }
        return "动作截图: " + target;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @JsonIgnoreProperties(ignoreUnknown = true)
    private static class PlaywrightRunResult {
        private boolean success;
        private String status;
        private long durationMs;
        private String errorMessage;
        private String reportFile;
        private List<String> videoFiles;
        private List<String> screenshotFiles;
        private List<ActionScreenshotCapture> actionScreenshots;
        private List<String> traceFiles;
        private List<PlaywrightTestResult> tests;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @JsonIgnoreProperties(ignoreUnknown = true)
    private static class ActionScreenshotCapture {
        private Integer stepNumber;
        private String action;
        private String target;
        private String phase;
        private String file;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @JsonIgnoreProperties(ignoreUnknown = true)
    private static class PlaywrightTestResult {
        private String title;
        private String status;
        private long durationMs;
        private String error;
    }
}
