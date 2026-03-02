package com.autotest.platform.service;

import com.autotest.platform.ai.OpenAIService;
import com.autotest.platform.dto.TestCaseDTO;
import com.autotest.platform.dto.TestScriptDTO;
import com.autotest.platform.entity.TestCase;
import com.autotest.platform.entity.TestScript;
import com.autotest.platform.entity.TestScriptGenerationRecord;
import com.autotest.platform.entity.TestStep;
import com.autotest.platform.repository.TestCaseRepository;
import com.autotest.platform.repository.TestScriptGenerationRecordRepository;
import com.autotest.platform.repository.TestScriptRepository;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
@RequiredArgsConstructor
@Slf4j
public class TestScriptGenerationService {

    private static final int SESSION_HISTORY_LIMIT = 20;
    private static final Pattern MARKDOWN_FENCE_PATTERN = Pattern.compile("(?s)^```[a-zA-Z0-9_-]*\\s*|\\s*```$");
    private static final Pattern SELECTOR_PATTERN = Pattern.compile("([#.][A-Za-z0-9_:-]+|\\[[^\\]]+\\])");
    private static final Pattern PROMPT_LEAKAGE_PATTERN = Pattern.compile("(?m)^(Case|Title|Description|Preconditions|Steps|Additional Instructions):\\s");
    private static final Pattern PLAYWRIGHT_HEADED_PATTERN = Pattern.compile("headless\\s*:\\s*false", Pattern.CASE_INSENSITIVE);
    private static final Pattern PLAYWRIGHT_NO_ARG_LAUNCH_PATTERN = Pattern.compile("(chromium|firefox|webkit)\\.launch\\(\\s*\\)");

    private final TestCaseRepository testCaseRepository;
    private final TestScriptRepository testScriptRepository;
    private final TestScriptGenerationRecordRepository generationRecordRepository;
    private final TenantContextService tenantContextService;
    private final PlatformSettingService platformSettingService;
    private final OpenAIService openAIService;
    private final ObjectMapper objectMapper;

    @Transactional
    public GenerateResult generateAndPersist(GenerateCommand command, TestScriptGenerationTaskService.TaskEventLogger logger) {
        Long tenantId = command.tenantId() != null ? command.tenantId() : tenantContextService.requireCurrentTenantId();
        TestCase testCase = testCaseRepository.findByIdAndTenantId(command.testCaseId(), tenantId)
                .orElseThrow(() -> new RuntimeException("测试用例不存在: " + command.testCaseId()));

        Optional<TestScriptGenerationRecord> latestRecord = generationRecordRepository
                .findFirstByTenantIdAndTestCase_IdOrderByCreatedAtDesc(tenantId, testCase.getId());
        String sessionId = latestRecord
                .map(TestScriptGenerationRecord::getSessionId)
                .filter(StringUtils::hasText)
                .orElse(UUID.randomUUID().toString());
        int version = latestRecord.map(record -> Optional.ofNullable(record.getVersion()).orElse(0) + 1).orElse(1);

        TestScript existingScript = testScriptRepository.findByTestCaseIdAndTenantId(testCase.getId(), tenantId).orElse(null);
        TestScript.ScriptType scriptType = resolveScriptType(command.scriptType(), existingScript);
        TestScript.Language language = resolveLanguage(command.language(), scriptType, existingScript);
        String targetUrl = resolveTargetUrl(command.targetUrl(), existingScript);
        String feedback = normalizeText(command.feedback());
        String additionalInstructions = normalizeText(command.additionalInstructions());

        String testCaseDescription = buildTestCaseDescription(testCase, additionalInstructions);
        String previousCode = existingScript != null ? existingScript.getCode() : null;

        if (logger != null) {
            logger.log("CONTEXT", "已完成测试用例上下文整理");
            logger.log("MODEL", "正在调用大模型生成可执行脚本");
        }
        OpenAIService.ScriptGenerationResult modelResult = openAIService.generateTestScriptDetailed(
                testCaseDescription,
                targetUrl,
                scriptType.name(),
                language.name(),
                feedback,
                previousCode
        );
        if (logger != null) {
            if (modelResult.fallbackUsed()) {
                logger.log("FALLBACK", defaultIfBlank(modelResult.fallbackReason(), "模型不可用，使用本地模板兜底"));
            } else {
                logger.log("MODEL", "模型响应成功，正在归一化脚本内容");
            }
        }

        String generatedCode = ensureExecutableCode(
                modelResult.code(),
                testCase,
                scriptType,
                language,
                targetUrl,
                logger
        );
        List<String> dependencies = detectDependencies(scriptType);

        if (logger != null) {
            logger.log("VERIFY", "脚本结构检查完成，可直接执行");
            logger.log("SAVE", "正在保存脚本到脚本仓库");
        }
        TestScript savedScript = upsertScript(
                tenantId,
                testCase,
                existingScript,
                scriptType,
                language,
                generatedCode,
                targetUrl,
                sessionId,
                version
        );

        if (logger != null) {
            logger.log("HISTORY", "正在写入脚本生成历史记录");
        }
        TestScriptGenerationRecord record = generationRecordRepository.save(
                TestScriptGenerationRecord.builder()
                        .recordId("SGEN-" + UUID.randomUUID().toString().substring(0, 8).toUpperCase(Locale.ROOT))
                        .tenantId(tenantId)
                        .sessionId(sessionId)
                        .version(version)
                        .testCase(testCase)
                        .testScript(savedScript)
                        .scriptType(scriptType)
                        .language(language)
                        .targetUrl(targetUrl)
                        .feedback(feedback)
                        .summary(buildRecordSummary(testCase, version, feedback))
                        .dependenciesJson(writeDependencies(dependencies))
                        .promptText(buildPromptSummary(testCaseDescription, feedback))
                        .generatedCode(generatedCode)
                        .modelProvider(modelResult.provider())
                        .modelName(modelResult.model())
                        .requestedBy(normalizeText(command.requestedBy()))
                        .adopted(Boolean.FALSE)
                        .build()
        );

        TestScriptDTO scriptDTO = toScriptDTO(savedScript);
        TestScriptDTO.ScriptGenerationRecordDTO recordDTO = toRecordDTO(record);
        TestScriptDTO.ScriptGenerationSessionDTO sessionDTO = buildLatestSession(tenantId, testCase, recordDTO);

        if (logger != null) {
            logger.log("DONE", "脚本生成完成，已写入历史版本 V" + version);
        }
        return new GenerateResult(scriptDTO, recordDTO, sessionDTO, modelResult);
    }

    @Transactional(readOnly = true)
    public Optional<TestScriptDTO.ScriptGenerationSessionDTO> getLatestSession(Long testCaseId) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestCase testCase = testCaseRepository.findByIdAndTenantId(testCaseId, tenantId).orElse(null);
        if (testCase == null) return Optional.empty();

        Optional<TestScriptGenerationRecord> latest = generationRecordRepository
                .findFirstByTenantIdAndTestCase_IdOrderByCreatedAtDesc(tenantId, testCaseId);
        if (latest.isEmpty()) return Optional.empty();
        return Optional.of(buildLatestSession(tenantId, testCase, toRecordDTO(latest.get())));
    }

    @Transactional(readOnly = true)
    public Page<TestScriptDTO.ScriptGenerationRecordDTO> getRecords(Long testCaseId, Pageable pageable) {
        Long tenantId = tenantContextService.requireCurrentTenantId();
        testCaseRepository.findByIdAndTenantId(testCaseId, tenantId)
                .orElseThrow(() -> new RuntimeException("测试用例不存在: " + testCaseId));
        return generationRecordRepository.findByTenantAndTestCase(tenantId, testCaseId, pageable)
                .map(this::toRecordDTO);
    }

    @Transactional(readOnly = true)
    public Optional<TestScriptDTO.ScriptGenerationRecordDTO> getRecordByRecordId(Long testCaseId, String recordId) {
        if (!StringUtils.hasText(recordId)) return Optional.empty();
        Long tenantId = tenantContextService.requireCurrentTenantId();
        return generationRecordRepository.findByTenantIdAndTestCase_IdAndRecordId(
                        tenantId,
                        testCaseId,
                        recordId.trim()
                )
                .map(this::toRecordDTO);
    }

    @Transactional
    public Optional<TestScriptDTO.ScriptGenerationSessionDTO> deleteRecordByRecordId(Long testCaseId, String recordId) {
        if (!StringUtils.hasText(recordId)) {
            return Optional.empty();
        }
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestScriptGenerationRecord record = generationRecordRepository.findByTenantIdAndTestCase_IdAndRecordId(
                        tenantId,
                        testCaseId,
                        recordId.trim()
                )
                .orElseThrow(() -> new RuntimeException("未找到对应的脚本生成记录"));
        generationRecordRepository.delete(record);

        TestCase testCase = testCaseRepository.findByIdAndTenantId(testCaseId, tenantId).orElse(null);
        if (testCase == null) {
            return Optional.empty();
        }
        Optional<TestScriptGenerationRecord> latest = generationRecordRepository
                .findFirstByTenantIdAndTestCase_IdOrderByCreatedAtDesc(tenantId, testCaseId);
        if (latest.isEmpty()) {
            return Optional.empty();
        }
        return Optional.of(buildLatestSession(tenantId, testCase, toRecordDTO(latest.get())));
    }

    @Transactional
    public TestScriptDTO.ScriptGenerationRecordDTO adoptRecordByRecordId(Long testCaseId, String recordId, String adoptedBy) {
        if (!StringUtils.hasText(recordId)) {
            throw new RuntimeException("recordId 不能为空");
        }
        Long tenantId = tenantContextService.requireCurrentTenantId();
        TestScriptGenerationRecord record = generationRecordRepository.findByTenantIdAndTestCase_IdAndRecordId(
                        tenantId,
                        testCaseId,
                        recordId.trim()
                )
                .orElseThrow(() -> new RuntimeException("未找到对应的脚本生成记录"));

        TestCase testCase = testCaseRepository.findByIdAndTenantId(testCaseId, tenantId)
                .orElseThrow(() -> new RuntimeException("测试用例不存在: " + testCaseId));

        TestScript existingScript = testScriptRepository.findByTestCaseIdAndTenantId(testCaseId, tenantId).orElse(null);
        TestScript script = upsertScript(
                tenantId,
                testCase,
                existingScript,
                record.getScriptType(),
                record.getLanguage(),
                defaultIfBlank(record.getGeneratedCode(), existingScript != null ? existingScript.getCode() : ""),
                defaultIfBlank(record.getTargetUrl(), resolveTargetUrl(null, existingScript)),
                defaultIfBlank(record.getSessionId(), UUID.randomUUID().toString()),
                Optional.ofNullable(record.getVersion()).orElse(1)
        );

        LocalDateTime adoptedAt = LocalDateTime.now();
        script.setStatus(TestScript.Status.TESTING);
        script.setConfig(mergeScriptConfigWithAdoption(
                script.getConfig(),
                record.getRecordId(),
                defaultIfBlank(adoptedBy, "system"),
                adoptedAt
        ));
        TestScript savedScript = testScriptRepository.save(script);

        record.setTestScript(savedScript);
        record.setAdopted(Boolean.TRUE);
        record.setAdoptedAt(adoptedAt);
        record.setAdoptedBy(defaultIfBlank(adoptedBy, "system"));
        TestScriptGenerationRecord savedRecord = generationRecordRepository.save(record);
        return toRecordDTO(savedRecord);
    }

    private TestScriptDTO.ScriptGenerationSessionDTO buildLatestSession(Long tenantId,
                                                                        TestCase testCase,
                                                                        TestScriptDTO.ScriptGenerationRecordDTO latestRecord) {
        List<TestScriptGenerationRecord> latestRecordsDesc = generationRecordRepository.findByTenantAndTestCase(
                tenantId,
                testCase.getId(),
                PageRequest.of(0, SESSION_HISTORY_LIMIT)
        ).getContent();
        List<TestScriptGenerationRecord> latestRecords = new ArrayList<>(latestRecordsDesc);
        latestRecords.sort((a, b) -> {
            LocalDateTime left = Optional.ofNullable(a.getCreatedAt()).orElse(LocalDateTime.MIN);
            LocalDateTime right = Optional.ofNullable(b.getCreatedAt()).orElse(LocalDateTime.MIN);
            return left.compareTo(right);
        });

        List<TestScriptDTO.ScriptGenerationMessageDTO> conversation = new ArrayList<>();
        for (TestScriptGenerationRecord record : latestRecords) {
            if (StringUtils.hasText(record.getFeedback())) {
                conversation.add(TestScriptDTO.ScriptGenerationMessageDTO.builder()
                        .role("user")
                        .content(record.getFeedback())
                        .createdAt(record.getCreatedAt())
                        .build());
            }
            conversation.add(TestScriptDTO.ScriptGenerationMessageDTO.builder()
                    .role("assistant")
                    .content(defaultIfBlank(record.getSummary(), "已生成新脚本版本"))
                    .createdAt(record.getCreatedAt())
                    .build());
        }

        return TestScriptDTO.ScriptGenerationSessionDTO.builder()
                .testCaseId(testCase.getId())
                .caseNumber(defaultIfBlank(testCase.getCaseNumber(), "TC-" + testCase.getId()))
                .sessionId(latestRecord.getSessionId())
                .version(latestRecord.getVersion())
                .summary(defaultIfBlank(latestRecord.getSummary(), "脚本生成完成"))
                .updatedAt(latestRecord.getGeneratedAt())
                .latestRecord(latestRecord)
                .conversation(conversation)
                .build();
    }

    private TestScript.ScriptType resolveScriptType(TestScriptDTO.ScriptType requested, TestScript existing) {
        if (requested != null) {
            return TestScript.ScriptType.valueOf(requested.name());
        }
        if (existing != null && existing.getScriptType() != null) {
            return existing.getScriptType();
        }
        return TestScript.ScriptType.PLAYWRIGHT;
    }

    private TestScript.Language resolveLanguage(TestScriptDTO.Language requested,
                                                TestScript.ScriptType scriptType,
                                                TestScript existing) {
        if (requested != null) {
            return TestScript.Language.valueOf(requested.name());
        }
        if (existing != null && existing.getLanguage() != null) {
            return existing.getLanguage();
        }
        if (scriptType == TestScript.ScriptType.SELENIUM || scriptType == TestScript.ScriptType.REST_ASSURED) {
            return TestScript.Language.JAVA;
        }
        return TestScript.Language.JAVASCRIPT;
    }

    private String resolveTargetUrl(String requestedTargetUrl, TestScript existingScript) {
        if (StringUtils.hasText(requestedTargetUrl)) {
            return requestedTargetUrl.trim();
        }

        if (existingScript != null && StringUtils.hasText(existingScript.getConfig())) {
            try {
                Map<String, Object> config = objectMapper.readValue(existingScript.getConfig(), new TypeReference<>() {});
                Object targetUrl = config.get("targetUrl");
                if (targetUrl != null && StringUtils.hasText(String.valueOf(targetUrl))) {
                    return String.valueOf(targetUrl).trim();
                }
            } catch (Exception ignored) {
                // fallback below
            }
        }

        Map<String, Object> runtime = platformSettingService.getRuntimeSettings();
        Object executionRaw = runtime.get("execution");
        if (executionRaw instanceof Map<?, ?> executionMap) {
            Object targetUrl = executionMap.get("defaultTargetUrl");
            if (targetUrl != null && StringUtils.hasText(String.valueOf(targetUrl))) {
                return String.valueOf(targetUrl).trim();
            }
        }
        return "https://example.com";
    }

    private TestScript upsertScript(Long tenantId,
                                    TestCase testCase,
                                    TestScript existingScript,
                                    TestScript.ScriptType scriptType,
                                    TestScript.Language language,
                                    String generatedCode,
                                    String targetUrl,
                                    String sessionId,
                                    int version) {
        TestScript script = existingScript != null
                ? existingScript
                : TestScript.builder()
                .tenantId(tenantId)
                .name(defaultIfBlank(testCase.getTitle(), "自动生成脚本") + " - AI Script")
                .testCase(testCase)
                .version("1.0.0")
                .build();

        script.setTenantId(tenantId);
        script.setScriptType(scriptType);
        script.setLanguage(language);
        script.setCode(generatedCode);
        script.setStatus(TestScript.Status.DRAFT);
        script.setConfig(mergeScriptConfig(script.getConfig(), targetUrl, sessionId, version));
        if (!StringUtils.hasText(script.getName())) {
            script.setName(defaultIfBlank(testCase.getTitle(), "自动生成脚本") + " - AI Script");
        }
        return testScriptRepository.save(script);
    }

    private String mergeScriptConfig(String rawConfig,
                                     String targetUrl,
                                     String sessionId,
                                     int version) {
        Map<String, Object> payload = new LinkedHashMap<>();
        if (StringUtils.hasText(rawConfig)) {
            try {
                payload.putAll(objectMapper.readValue(rawConfig, new TypeReference<>() {}));
            } catch (Exception ignored) {
                // Reset invalid config payload
            }
        }
        payload.put("targetUrl", targetUrl);

        Map<String, Object> generation = new LinkedHashMap<>();
        generation.put("sessionId", sessionId);
        generation.put("version", version);
        generation.put("updatedAt", LocalDateTime.now().toString());
        payload.put("generation", generation);

        try {
            return objectMapper.writeValueAsString(payload);
        } catch (Exception ex) {
            log.warn("Failed to serialize script config. reason={}", ex.getMessage());
            return "{\"targetUrl\":\"" + targetUrl.replace("\"", "\\\"") + "\"}";
        }
    }

    private String mergeScriptConfigWithAdoption(String rawConfig,
                                                 String adoptedRecordId,
                                                 String adoptedBy,
                                                 LocalDateTime adoptedAt) {
        Map<String, Object> payload = new LinkedHashMap<>();
        if (StringUtils.hasText(rawConfig)) {
            try {
                payload.putAll(objectMapper.readValue(rawConfig, new TypeReference<>() {}));
            } catch (Exception ignored) {
                // reset invalid config payload
            }
        }

        Map<String, Object> adoption = new LinkedHashMap<>();
        adoption.put("adopted", true);
        adoption.put("recordId", adoptedRecordId);
        adoption.put("adoptedBy", adoptedBy);
        adoption.put("adoptedAt", adoptedAt != null ? adoptedAt.toString() : LocalDateTime.now().toString());
        payload.put("adoption", adoption);

        try {
            return objectMapper.writeValueAsString(payload);
        } catch (Exception ex) {
            log.warn("Failed to merge adoption config. reason={}", ex.getMessage());
            return rawConfig;
        }
    }

    private String ensureExecutableCode(String rawCode,
                                        TestCase testCase,
                                        TestScript.ScriptType scriptType,
                                        TestScript.Language language,
                                        String targetUrl,
                                        TestScriptGenerationTaskService.TaskEventLogger logger) {
        String sanitized = stripMarkdownFences(rawCode);
        if (StringUtils.hasText(sanitized) && isLikelyExecutable(sanitized, scriptType)) {
            String executable = sanitizeRuntimeForExecution(sanitized.trim(), scriptType);
            if (logger != null && !executable.equals(sanitized.trim())) {
                logger.log("NORMALIZE", "脚本包含非容器友好配置，已自动修正运行参数");
            }
            return executable;
        }

        if (logger != null) {
            if (StringUtils.hasText(sanitized)) {
                logger.log("NORMALIZE", "模型脚本结构不完整，自动生成可执行模板");
            } else {
                logger.log("FALLBACK", "模型未返回可用脚本，自动生成可执行模板");
            }
        }
        String template = buildExecutableTemplate(testCase, scriptType, language, targetUrl);
        if (!StringUtils.hasText(template)) {
            throw new RuntimeException("脚本生成失败：无法构造可执行模板");
        }
        return template.trim();
    }

    private String sanitizeRuntimeForExecution(String code, TestScript.ScriptType scriptType) {
        if (!StringUtils.hasText(code) || scriptType != TestScript.ScriptType.PLAYWRIGHT) {
            return defaultIfBlank(code, "");
        }

        String normalized = code;
        normalized = PLAYWRIGHT_HEADED_PATTERN.matcher(normalized).replaceAll("headless: true");
        normalized = PLAYWRIGHT_NO_ARG_LAUNCH_PATTERN.matcher(normalized).replaceAll("$1.launch({ headless: true })");
        return normalized;
    }

    private String stripMarkdownFences(String rawCode) {
        if (!StringUtils.hasText(rawCode)) return "";
        String trimmed = rawCode.trim();
        if (!trimmed.contains("```")) return trimmed;
        return MARKDOWN_FENCE_PATTERN.matcher(trimmed).replaceAll("").trim();
    }

    private boolean isLikelyExecutable(String code, TestScript.ScriptType scriptType) {
        if (!StringUtils.hasText(code)) return false;
        String normalized = code.trim();
        if (normalized.contains("```")) return false;
        if (PROMPT_LEAKAGE_PATTERN.matcher(normalized).find()) return false;
        return switch (scriptType) {
            case CYPRESS -> normalized.contains("describe(") && normalized.contains("cy.");
            case SELENIUM -> normalized.contains("WebDriver") && normalized.contains("class ");
            case REST_ASSURED -> normalized.contains("RestAssured") && normalized.contains("class ");
            case APPIUM -> normalized.contains("appium") || normalized.contains("remote(") || normalized.contains("webdriverio");
            default -> normalized.contains("@playwright/test") && normalized.contains("test(") && normalized.contains("page.");
        };
    }

    private String buildExecutableTemplate(TestCase testCase,
                                           TestScript.ScriptType scriptType,
                                           TestScript.Language language,
                                           String targetUrl) {
        return switch (scriptType) {
            case CYPRESS -> buildCypressTemplate(testCase, targetUrl);
            case SELENIUM -> buildSeleniumTemplate(testCase, targetUrl);
            case REST_ASSURED -> buildRestAssuredTemplate(testCase, targetUrl);
            case APPIUM -> buildAppiumTemplate(testCase);
            default -> buildPlaywrightTemplate(testCase, language, targetUrl);
        };
    }

    private String buildPlaywrightTemplate(TestCase testCase,
                                           TestScript.Language language,
                                           String targetUrl) {
        boolean ts = language == TestScript.Language.TYPESCRIPT;
        String title = defaultIfBlank(testCase.getTitle(), "Generated UI Test");
        String importLine = ts
                ? "import { test, expect } from '@playwright/test';"
                : "const { test, expect } = require('@playwright/test');";
        StringBuilder builder = new StringBuilder();
        builder.append(importLine).append("\n\n");
        builder.append("test('").append(escapeJs(title)).append("', async ({ page }) => {\n");
        builder.append("  await page.goto('").append(escapeJs(targetUrl)).append("');\n");

        List<TestStep> steps = orderedSteps(testCase);
        for (int i = 0; i < steps.size(); i++) {
            TestStep step = steps.get(i);
            String action = defaultIfBlank(step.getAction(), "").toLowerCase(Locale.ROOT);
            String expected = defaultIfBlank(step.getExpectedResult(), "");
            String selector = firstNonBlank(
                    extractSelector(step.getAction()),
                    extractSelector(step.getTestData()),
                    extractSelector(step.getExpectedResult())
            );

            builder.append("  // Step ").append(i + 1).append(": ")
                    .append(escapeJs(resolveStepComment(step))).append("\n");
            if (containsAny(action, "navigate", "open", "访问", "打开")) {
                builder.append("  await page.goto('").append(escapeJs(targetUrl)).append("');\n");
            } else if (containsAny(action, "click", "tap", "点击")) {
                builder.append("  await page.click('").append(escapeJs(defaultIfBlank(selector, "#submit"))).append("');\n");
            } else if (containsAny(action, "input", "type", "fill", "输入", "填写")) {
                builder.append("  await page.fill('")
                        .append(escapeJs(defaultIfBlank(selector, "#input")))
                        .append("', '")
                        .append(escapeJs(resolveInputValue(step)))
                        .append("');\n");
            } else if (containsAny(action, "assert", "verify", "检查", "校验")) {
                if (StringUtils.hasText(selector)) {
                    builder.append("  await expect(page.locator('").append(escapeJs(selector)).append("')).toBeVisible();\n");
                } else {
                    builder.append("  await expect(page.locator('body')).toContainText('")
                            .append(escapeJs(defaultIfBlank(expected, "expected")))
                            .append("');\n");
                }
            } else if (containsAny(action, "wait", "等待")) {
                builder.append("  await page.waitForTimeout(1000);\n");
            } else {
                builder.append("  await page.waitForTimeout(500);\n");
            }

            String urlHint = extractUrlHint(expected);
            if (StringUtils.hasText(urlHint)) {
                builder.append("  await expect(page.url()).toContain('").append(escapeJs(urlHint)).append("');\n");
            } else if (StringUtils.hasText(selector) && containsAny(expected.toLowerCase(Locale.ROOT), "显示", "visible", "存在")) {
                builder.append("  await expect(page.locator('").append(escapeJs(selector)).append("')).toBeVisible();\n");
            }
            builder.append('\n');
        }

        builder.append("  await expect(page.locator('body')).toBeVisible();\n");
        builder.append("});\n");
        return builder.toString();
    }

    private String buildCypressTemplate(TestCase testCase, String targetUrl) {
        String title = defaultIfBlank(testCase.getTitle(), "Generated Cypress Test");
        StringBuilder builder = new StringBuilder();
        builder.append("describe('").append(escapeJs(title)).append("', () => {\n")
                .append("  it('executes generated scenario', () => {\n")
                .append("    cy.visit('").append(escapeJs(targetUrl)).append("');\n");

        List<TestStep> steps = orderedSteps(testCase);
        for (int i = 0; i < steps.size(); i++) {
            TestStep step = steps.get(i);
            String action = defaultIfBlank(step.getAction(), "").toLowerCase(Locale.ROOT);
            String selector = firstNonBlank(
                    extractSelector(step.getAction()),
                    extractSelector(step.getTestData()),
                    extractSelector(step.getExpectedResult())
            );
            builder.append("    // Step ").append(i + 1).append(": ").append(escapeJs(resolveStepComment(step))).append("\n");
            if (containsAny(action, "click", "tap", "点击")) {
                builder.append("    cy.get('").append(escapeJs(defaultIfBlank(selector, "button"))).append("').click();\n");
            } else if (containsAny(action, "input", "type", "fill", "输入", "填写")) {
                builder.append("    cy.get('")
                        .append(escapeJs(defaultIfBlank(selector, "input")))
                        .append("').clear().type('")
                        .append(escapeJs(resolveInputValue(step)))
                        .append("');\n");
            } else if (containsAny(action, "wait", "等待")) {
                builder.append("    cy.wait(1000);\n");
            } else if (containsAny(action, "navigate", "open", "访问", "打开")) {
                builder.append("    cy.visit('").append(escapeJs(targetUrl)).append("');\n");
            } else {
                builder.append("    cy.wait(300);\n");
            }
        }

        builder.append("    cy.get('body').should('be.visible');\n")
                .append("  });\n")
                .append("});\n");
        return builder.toString();
    }

    private String buildSeleniumTemplate(TestCase testCase, String targetUrl) {
        List<TestStep> steps = orderedSteps(testCase);
        StringBuilder builder = new StringBuilder();
        builder.append("import org.junit.jupiter.api.Assertions;\n")
                .append("import org.junit.jupiter.api.Test;\n")
                .append("import org.openqa.selenium.By;\n")
                .append("import org.openqa.selenium.WebDriver;\n")
                .append("import org.openqa.selenium.chrome.ChromeDriver;\n\n")
                .append("public class GeneratedSeleniumTest {\n")
                .append("  @Test\n")
                .append("  void runScenario() {\n")
                .append("    WebDriver driver = new ChromeDriver();\n")
                .append("    try {\n")
                .append("      driver.get(\"").append(escapeJava(targetUrl)).append("\");\n");

        for (int i = 0; i < steps.size(); i++) {
            TestStep step = steps.get(i);
            String action = defaultIfBlank(step.getAction(), "").toLowerCase(Locale.ROOT);
            String selector = firstNonBlank(
                    extractSelector(step.getAction()),
                    extractSelector(step.getTestData()),
                    extractSelector(step.getExpectedResult())
            );
            builder.append("      // Step ").append(i + 1).append(": ").append(escapeJava(resolveStepComment(step))).append("\n");
            if (containsAny(action, "click", "tap", "点击")) {
                builder.append("      driver.findElement(By.cssSelector(\"")
                        .append(escapeJava(defaultIfBlank(selector, "button")))
                        .append("\")).click();\n");
            } else if (containsAny(action, "input", "type", "fill", "输入", "填写")) {
                builder.append("      driver.findElement(By.cssSelector(\"")
                        .append(escapeJava(defaultIfBlank(selector, "input")))
                        .append("\")).sendKeys(\"")
                        .append(escapeJava(resolveInputValue(step)))
                        .append("\");\n");
            } else if (containsAny(action, "wait", "等待")) {
                builder.append("      Thread.sleep(1000);\n");
            } else if (containsAny(action, "navigate", "open", "访问", "打开")) {
                builder.append("      driver.get(\"").append(escapeJava(targetUrl)).append("\");\n");
            }
        }

        builder.append("      Assertions.assertTrue(driver.findElement(By.tagName(\"body\")).isDisplayed());\n")
                .append("    } catch (InterruptedException ex) {\n")
                .append("      Thread.currentThread().interrupt();\n")
                .append("      throw new RuntimeException(ex);\n")
                .append("    } finally {\n")
                .append("      driver.quit();\n")
                .append("    }\n")
                .append("  }\n")
                .append("}\n");
        return builder.toString();
    }

    private String buildRestAssuredTemplate(TestCase testCase, String targetUrl) {
        String title = defaultIfBlank(testCase.getTitle(), "Generated API Test");
        StringBuilder builder = new StringBuilder();
        builder.append("import io.restassured.RestAssured;\n")
                .append("import org.junit.jupiter.api.Test;\n")
                .append("import static org.hamcrest.Matchers.anyOf;\n")
                .append("import static org.hamcrest.Matchers.is;\n\n")
                .append("public class GeneratedApiTest {\n")
                .append("  @Test\n")
                .append("  void runScenario() {\n")
                .append("    // ").append(escapeJava(title)).append("\n")
                .append("    RestAssured.given()\n")
                .append("        .baseUri(\"").append(escapeJava(targetUrl)).append("\")\n")
                .append("        .when()\n")
                .append("        .get(\"/\")\n")
                .append("        .then()\n")
                .append("        .statusCode(anyOf(is(200), is(204), is(301), is(302)));\n")
                .append("  }\n")
                .append("}\n");
        return builder.toString();
    }

    private String buildAppiumTemplate(TestCase testCase) {
        String title = defaultIfBlank(testCase.getTitle(), "Generated Appium Test");
        return "// " + escapeJs(title) + "\n" +
                "const { remote } = require('webdriverio');\n\n" +
                "(async () => {\n" +
                "  const driver = await remote({\n" +
                "    hostname: '127.0.0.1',\n" +
                "    port: 4723,\n" +
                "    path: '/wd/hub',\n" +
                "    capabilities: {\n" +
                "      platformName: 'Android',\n" +
                "      'appium:automationName': 'UiAutomator2'\n" +
                "    }\n" +
                "  });\n" +
                "  try {\n" +
                "    await driver.pause(1000);\n" +
                "  } finally {\n" +
                "    await driver.deleteSession();\n" +
                "  }\n" +
                "})();\n";
    }

    private List<TestStep> orderedSteps(TestCase testCase) {
        if (testCase == null || testCase.getSteps() == null) return List.of();
        return testCase.getSteps().stream()
                .sorted(Comparator.comparing(step -> Optional.ofNullable(step.getStepOrder()).orElse(0)))
                .toList();
    }

    private String extractSelector(String text) {
        if (!StringUtils.hasText(text)) return null;
        Matcher matcher = SELECTOR_PATTERN.matcher(text);
        return matcher.find() ? matcher.group(1) : null;
    }

    private String extractUrlHint(String text) {
        if (!StringUtils.hasText(text)) return null;
        Matcher matcher = Pattern.compile("(https?://[^\\s'\"）)]+|/[A-Za-z0-9_./-]+)").matcher(text);
        return matcher.find() ? matcher.group(1) : null;
    }

    private boolean containsAny(String source, String... keywords) {
        if (!StringUtils.hasText(source) || keywords == null) return false;
        for (String keyword : keywords) {
            if (StringUtils.hasText(keyword) && source.contains(keyword)) return true;
        }
        return false;
    }

    private String firstNonBlank(String... values) {
        if (values == null) return null;
        for (String value : values) {
            if (StringUtils.hasText(value)) return value.trim();
        }
        return null;
    }

    private String resolveInputValue(TestStep step) {
        String testData = normalizeText(step == null ? null : step.getTestData());
        if (StringUtils.hasText(testData)) {
            return testData;
        }
        String action = normalizeText(step == null ? null : step.getAction());
        if (!StringUtils.hasText(action)) return "test-data";
        Matcher quoted = Pattern.compile("[\"']([^\"']{1,120})[\"']").matcher(action);
        if (quoted.find()) return quoted.group(1);
        return "test-data";
    }

    private String resolveStepComment(TestStep step) {
        if (step == null) return "generated step";
        String action = normalizeText(step.getAction());
        String expected = normalizeText(step.getExpectedResult());
        if (StringUtils.hasText(action) && StringUtils.hasText(expected)) {
            return action + " -> " + expected;
        }
        return defaultIfBlank(action, defaultIfBlank(expected, "generated step"));
    }

    private String escapeJs(String value) {
        if (!StringUtils.hasText(value)) return "";
        return value.replace("\\", "\\\\").replace("'", "\\'");
    }

    private String escapeJava(String value) {
        if (!StringUtils.hasText(value)) return "";
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private String buildRunCommand(TestScript.ScriptType scriptType, TestScript.Language language) {
        if (scriptType == null) return "npx playwright test generated.spec.js";
        return switch (scriptType) {
            case CYPRESS -> "npx cypress run --spec generated.cy.js";
            case SELENIUM -> "mvn -Dtest=GeneratedSeleniumTest test";
            case REST_ASSURED -> "mvn -Dtest=GeneratedApiTest test";
            case APPIUM -> "node generated.appium.js";
            default -> language == TestScript.Language.TYPESCRIPT
                    ? "npx playwright test generated.spec.ts"
                    : "npx playwright test generated.spec.js";
        };
    }

    private String buildTestCaseDescription(TestCase testCase, String additionalInstructions) {
        StringBuilder builder = new StringBuilder();
        builder.append("Case: ").append(defaultIfBlank(testCase.getCaseNumber(), "TC-" + testCase.getId())).append("\n");
        builder.append("Title: ").append(defaultIfBlank(testCase.getTitle(), "-")).append("\n");
        builder.append("Description: ").append(defaultIfBlank(testCase.getDescription(), "-")).append("\n");
        builder.append("Preconditions: ").append(defaultIfBlank(testCase.getPreconditions(), "-")).append("\n");
        if (testCase.getSteps() != null && !testCase.getSteps().isEmpty()) {
            builder.append("Steps:\n");
            testCase.getSteps().forEach(step -> builder
                    .append(Optional.ofNullable(step.getStepOrder()).orElse(0))
                    .append(". ")
                    .append(defaultIfBlank(step.getAction(), "-"))
                    .append(" -> ")
                    .append(defaultIfBlank(step.getExpectedResult(), "-"))
                    .append("\n"));
        }
        if (StringUtils.hasText(additionalInstructions)) {
            builder.append("Additional Instructions: ").append(additionalInstructions.trim()).append("\n");
        }
        return builder.toString();
    }

    private String buildRecordSummary(TestCase testCase, int version, String feedback) {
        String caseLabel = defaultIfBlank(testCase.getCaseNumber(), "TC-" + testCase.getId());
        if (StringUtils.hasText(feedback)) {
            return caseLabel + " 第 " + version + " 轮优化生成";
        }
        return caseLabel + " 第 " + version + " 轮脚本生成";
    }

    private String buildPromptSummary(String basePrompt, String feedback) {
        if (!StringUtils.hasText(feedback)) {
            return basePrompt;
        }
        return basePrompt + "\n\nFeedback:\n" + feedback;
    }

    private String writeDependencies(List<String> dependencies) {
        try {
            return objectMapper.writeValueAsString(dependencies == null ? List.of() : dependencies);
        } catch (Exception ex) {
            return "[]";
        }
    }

    private List<String> readDependencies(String json) {
        if (!StringUtils.hasText(json)) return List.of();
        try {
            List<String> parsed = objectMapper.readValue(json, new TypeReference<>() {});
            return parsed == null ? List.of() : parsed.stream().filter(StringUtils::hasText).map(String::trim).toList();
        } catch (Exception ex) {
            return Arrays.stream(json.split(","))
                    .map(String::trim)
                    .filter(StringUtils::hasText)
                    .toList();
        }
    }

    private List<String> detectDependencies(TestScript.ScriptType scriptType) {
        if (scriptType == null) return List.of("@playwright/test");
        return switch (scriptType) {
            case CYPRESS -> List.of("cypress");
            case SELENIUM -> List.of("org.seleniumhq.selenium:selenium-java", "org.junit.jupiter:junit-jupiter");
            case REST_ASSURED -> List.of("io.rest-assured:rest-assured", "org.junit.jupiter:junit-jupiter");
            case APPIUM -> List.of("appium", "webdriverio");
            default -> List.of("@playwright/test");
        };
    }

    private TestScriptDTO.ScriptGenerationRecordDTO toRecordDTO(TestScriptGenerationRecord source) {
        return TestScriptDTO.ScriptGenerationRecordDTO.builder()
                .recordId(source.getRecordId())
                .version(source.getVersion())
                .sessionId(source.getSessionId())
                .summary(source.getSummary())
                .feedback(source.getFeedback())
                .generatedAt(source.getCreatedAt())
                .scriptType(source.getScriptType() == null ? null : TestScriptDTO.ScriptType.valueOf(source.getScriptType().name()))
                .language(source.getLanguage() == null ? null : TestScriptDTO.Language.valueOf(source.getLanguage().name()))
                .targetUrl(source.getTargetUrl())
                .scriptId(source.getTestScript() == null ? null : source.getTestScript().getId())
                .scriptName(source.getTestScript() == null ? null : source.getTestScript().getName())
                .generatedCode(source.getGeneratedCode())
                .dependencies(readDependencies(source.getDependenciesJson()))
                .runCommand(buildRunCommand(source.getScriptType(), source.getLanguage()))
                .modelProvider(source.getModelProvider())
                .modelName(source.getModelName())
                .adopted(Boolean.TRUE.equals(source.getAdopted()))
                .adoptedAt(source.getAdoptedAt())
                .adoptedBy(source.getAdoptedBy())
                .build();
    }

    private String normalizeText(String value) {
        if (!StringUtils.hasText(value)) return null;
        return value.trim();
    }

    private TestScriptDTO toScriptDTO(TestScript script) {
        if (script == null) return null;
        return TestScriptDTO.builder()
                .id(script.getId())
                .name(script.getName())
                .scriptType(script.getScriptType() == null ? null : TestScriptDTO.ScriptType.valueOf(script.getScriptType().name()))
                .language(script.getLanguage() == null ? null : TestScriptDTO.Language.valueOf(script.getLanguage().name()))
                .code(script.getCode())
                .config(script.getConfig())
                .status(script.getStatus() == null ? null : TestScriptDTO.Status.valueOf(script.getStatus().name()))
                .testCase(toTestCaseDTO(script.getTestCase()))
                .version(script.getVersion())
                .filePath(script.getFilePath())
                .createdAt(script.getCreatedAt())
                .updatedAt(script.getUpdatedAt())
                .build();
    }

    private TestCaseDTO toTestCaseDTO(TestCase testCase) {
        if (testCase == null) return null;
        return TestCaseDTO.builder()
                .id(testCase.getId())
                .caseNumber(testCase.getCaseNumber())
                .title(testCase.getTitle())
                .status(testCase.getStatus() == null ? null : TestCaseDTO.Status.valueOf(testCase.getStatus().name()))
                .priority(testCase.getPriority() == null ? null : TestCaseDTO.Priority.valueOf(testCase.getPriority().name()))
                .testType(testCase.getTestType() == null ? null : TestCaseDTO.TestType.valueOf(testCase.getTestType().name()))
                .build();
    }

    private String defaultIfBlank(String value, String fallback) {
        return StringUtils.hasText(value) ? value.trim() : fallback;
    }

    public record GenerateCommand(
            Long testCaseId,
            TestScriptDTO.ScriptType scriptType,
            TestScriptDTO.Language language,
            String targetUrl,
            String additionalInstructions,
            String feedback,
            String requestedBy,
            Long tenantId
    ) {
    }

    public record GenerateResult(
            TestScriptDTO script,
            TestScriptDTO.ScriptGenerationRecordDTO record,
            TestScriptDTO.ScriptGenerationSessionDTO session,
            OpenAIService.ScriptGenerationResult modelResult
    ) {
    }
}
