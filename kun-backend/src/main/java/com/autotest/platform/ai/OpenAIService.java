package com.autotest.platform.ai;

import com.autotest.platform.service.PlatformSettingService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.ai.openai.api.ResponseFormat;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

@Service
@RequiredArgsConstructor
@Slf4j
public class OpenAIService {
    private static final Duration MODEL_CALL_TIMEOUT = Duration.ofSeconds(90);

    private final ChatClient.Builder chatClientBuilder;
    private final ObjectProvider<OpenAiChatModel> openAiChatModelProvider;
    private final PlatformSettingService platformSettingService;

    @Value("${spring.ai.openai.api-key:}")
    private String fallbackApiKey;

    @Value("${spring.ai.openai.chat.options.model:gpt-4o-mini}")
    private String fallbackModel;

    @Value("${spring.ai.openai.chat.options.temperature:0.7}")
    private double fallbackTemperature;

    @Value("${spring.ai.openai.base-url:https://api.openai.com/v1}")
    private String fallbackBaseUrl;

    public String generateTestScript(String testCaseDescription, String targetUrl, String framework) {
        return generateTestScriptDetailed(
                testCaseDescription,
                targetUrl,
                framework,
                "JAVASCRIPT",
                null,
                null
        ).code();
    }

    public ScriptGenerationResult generateTestScriptDetailed(String testCaseDescription,
                                                             String targetUrl,
                                                             String framework,
                                                             String language,
                                                             String feedback,
                                                             String previousCode) {
        RuntimeModelConfig config = resolveRuntimeConfig(null);
        String normalizedFramework = normalizeFramework(framework);
        String normalizedLanguage = normalizeLanguage(language, normalizedFramework);
        String normalizedTargetUrl = normalizeTargetUrl(targetUrl);
        if (!config.aiEnabled()) {
            log.warn("Spring AI API key not configured, returning mock script");
            String fallback = generateFallbackScript(
                    testCaseDescription,
                    normalizedTargetUrl,
                    normalizedFramework,
                    normalizedLanguage
            );
            return new ScriptGenerationResult(
                    fallback,
                    config.provider(),
                    config.model(),
                    true,
                    "API key 未配置，使用本地兜底模板"
            );
        }

        String systemPrompt = """
                You are a senior test automation engineer.
                Return only executable test code without markdown fences or any extra explanation.
                The script must be directly runnable for the requested framework and language.
                Include required imports, test structure, robust selectors, retries and deterministic assertions.
                Never return pseudo-code.
                For Playwright:
                - Use @playwright/test fixtures directly (test('...', async ({ page }) => {...})).
                - Do NOT manually launch browser/context/page via chromium.launch/firefox.launch/webkit.launch.
                - Never set headless: false. Scripts must run in headless CI/container environments.
                """;
        StringBuilder userPrompt = new StringBuilder(String.format("""
                Generate an automation test script.

                Framework: %s
                Language: %s
                Target URL: %s

                Test Case Details:
                %s
                """, normalizedFramework, normalizedLanguage, normalizedTargetUrl, testCaseDescription));
        if (StringUtils.hasText(previousCode)) {
            userPrompt.append("\n\nCurrent Script (for reference and improvement):\n")
                    .append(previousCode.trim());
        }
        if (StringUtils.hasText(feedback)) {
            userPrompt.append("\n\nOptimization Request from user:\n")
                    .append(feedback.trim());
        }

        try {
            String raw = callModel(config, systemPrompt, userPrompt.toString(), false);
            String cleaned = sanitizeGeneratedCode(raw);
            if (StringUtils.hasText(cleaned)) {
                if (!isRunnableGeneratedScript(cleaned, normalizedFramework)) {
                    String fallback = generateFallbackScript(
                            testCaseDescription,
                            normalizedTargetUrl,
                            normalizedFramework,
                            normalizedLanguage
                    );
                    return new ScriptGenerationResult(
                            fallback,
                            config.provider(),
                            config.model(),
                            true,
                            "模型脚本缺少可执行测试入口，已切换本地兜底模板"
                    );
                }
                return new ScriptGenerationResult(
                        cleaned,
                        config.provider(),
                        config.model(),
                        false,
                        null
                );
            }
            String fallback = generateFallbackScript(
                    testCaseDescription,
                    normalizedTargetUrl,
                    normalizedFramework,
                    normalizedLanguage
            );
            return new ScriptGenerationResult(
                    fallback,
                    config.provider(),
                    config.model(),
                    true,
                    "模型返回为空，使用本地兜底模板"
            );
        } catch (Exception e) {
            log.error("Failed to generate script via Spring AI", e);
            String fallback = generateFallbackScript(
                    testCaseDescription,
                    normalizedTargetUrl,
                    normalizedFramework,
                    normalizedLanguage
            );
            String fallbackReason = "模型调用失败，使用本地兜底模板";
            String message = e.getMessage();
            if (StringUtils.hasText(message)) {
                if (message.contains("超时")) {
                    fallbackReason = "模型调用超时，使用本地兜底模板";
                } else {
                    fallbackReason = "模型调用失败（" + clip(message, 80) + "），使用本地兜底模板";
                }
            }
            return new ScriptGenerationResult(
                    fallback,
                    config.provider(),
                    config.model(),
                    true,
                    fallbackReason
            );
        }
    }

    public String analyzeUserStory(String description, String acceptanceCriteria) {
        RuntimeModelConfig config = resolveRuntimeConfig(null);
        if (!config.aiEnabled()) {
            log.warn("Spring AI API key not configured, returning mock analysis");
            return generateMockAnalysis();
        }

        String systemPrompt = """
                You are a QA analyst.
                Return a single valid JSON object only (no markdown fences).
                All string values must be valid JSON escaped text.
                Never output unescaped double quotes inside string values.
                Use '\\n' for line breaks inside strings.
                Follow this exact shape:
                {
                  "qualityScore": 0-100,
                  "qualityIssues": [{"type":"GIVEN_WHEN_THEN|AMBIGUITY|NON_TESTABLE|MISSING_SCOPE|RISK","severity":"LOW|MEDIUM|HIGH","message":"...","suggestion":"..."}],
                  "optimizedTitle": "...",
                  "optimizedDescription": "...",
                  "optimizedAcceptanceCriteria": "...",
                  "analysisSummary": "...",
                  "validationPoints": [{"description":"...","expectedResult":"...","priority":"LOW|MEDIUM|HIGH|CRITICAL"}],
                  "suggestedTestCases": [{"title":"...","description":"...","testType":"FUNCTIONAL|UI|API|PERFORMANCE|SECURITY|COMPATIBILITY","priority":"LOW|MEDIUM|HIGH|CRITICAL"}]
                }
                """;
        String userPrompt = String.format("""
                Analyze this user story.

                Description:
                %s

                Acceptance Criteria:
                %s

                Evaluate requirement quality, identify concrete defects, and provide a directly usable rewrite.
                Keep optimizedDescription in As / I want / So that format.
                Keep optimizedAcceptanceCriteria in Given / When / Then format.
                """, safeText(description), safeText(acceptanceCriteria));

        try {
            return callModel(config, systemPrompt, userPrompt, true);
        } catch (Exception e) {
            log.error("Failed to analyze user story via Spring AI", e);
            return generateMockAnalysis();
        }
    }

    public String generateTestCases(String userStoryDescription) {
        RuntimeModelConfig config = resolveRuntimeConfig(null);
        if (!config.aiEnabled()) {
            log.warn("Spring AI API key not configured, returning mock test cases");
            return generateMockTestCases();
        }

        String systemPrompt = """
                You are a senior QA test designer.
                Return only a strict JSON object with key "testCases".
                testCases must be an array of high-quality, review-ready cases.
                Each case fields:
                title, description, preconditions, testType, priority, tags, steps.
                steps is an array of objects with:
                stepOrder, action, expectedResult, testData.
                Constraints:
                - Avoid generic titles like "Positive scenario"/"Negative scenario".
                - At least 4 steps per test case.
                - expectedResult must be specific and verifiable.
                - Include business-relevant testData in key steps.
                """;
        String userPrompt = String.format("""
                Generate high-quality test cases from this source.
                %s
                """, safeText(userStoryDescription));

        try {
            return callModel(config, systemPrompt, userPrompt, true);
        } catch (Exception e) {
            log.error("Failed to generate test cases via Spring AI", e);
            return generateMockTestCases();
        }
    }

    public ModelConnectionResult testModelConnection(ModelConnectionRequest request) {
        RuntimeModelConfig config = resolveRuntimeConfig(request);
        if (!config.aiEnabled()) {
            return new ModelConnectionResult(
                    false,
                    config.provider(),
                    config.baseUrl(),
                    config.model(),
                    config.temperature(),
                    0L,
                    "请先配置有效的模型 API Key",
                    ""
            );
        }

        String systemPrompt = "You are a connectivity checker for LLM endpoints.";
        String userPrompt = "Reply with exactly: MODEL_CONNECTION_OK";
        long startedAt = System.currentTimeMillis();
        try {
            String content = callModel(config, systemPrompt, userPrompt, false);
            long latency = Math.max(1L, System.currentTimeMillis() - startedAt);
            String preview = clip(content, 120);
            return new ModelConnectionResult(
                    true,
                    config.provider(),
                    config.baseUrl(),
                    config.model(),
                    config.temperature(),
                    latency,
                    "模型连接测试通过",
                    preview
            );
        } catch (Exception ex) {
            long latency = Math.max(1L, System.currentTimeMillis() - startedAt);
            log.warn("Model connection test failed. provider={}, baseUrl={}, model={}, reason={}",
                    config.provider(), config.baseUrl(), config.model(), ex.getMessage());
            return new ModelConnectionResult(
                    false,
                    config.provider(),
                    config.baseUrl(),
                    config.model(),
                    config.temperature(),
                    latency,
                    "模型连接失败: " + ex.getMessage(),
                    ""
            );
        }
    }

    private String callModel(RuntimeModelConfig config, String systemPrompt, String userPrompt, boolean forceJsonObject) {
        try (ExecutorService executor = Executors.newVirtualThreadPerTaskExecutor()) {
            Future<String> future = executor.submit(() -> {
                ChatClient chatClient = buildChatClient(config);
                ChatClient.ChatClientRequestSpec request = chatClient.prompt()
                        .system(systemPrompt)
                        .user(userPrompt);
                if (forceJsonObject) {
                    request = request.options(buildJsonResponseOptions(config));
                }
                String content = request.call().content();
                return StringUtils.hasText(content) ? content : "";
            });
            try {
                return future.get(MODEL_CALL_TIMEOUT.toMillis(), TimeUnit.MILLISECONDS);
            } catch (TimeoutException timeoutException) {
                future.cancel(true);
                throw new RuntimeException("模型调用超时（" + MODEL_CALL_TIMEOUT.toSeconds() + "秒）", timeoutException);
            } catch (InterruptedException interruptedException) {
                Thread.currentThread().interrupt();
                throw new RuntimeException("模型调用被中断", interruptedException);
            } catch (ExecutionException executionException) {
                Throwable cause = executionException.getCause();
                if (cause instanceof RuntimeException runtimeException) {
                    throw runtimeException;
                }
                throw new RuntimeException(cause == null ? "模型调用失败" : cause.getMessage(), cause);
            }
        }
    }

    private ChatClient buildChatClient(RuntimeModelConfig config) {
        Endpoint endpoint = resolveEndpoint(config.provider(), config.baseUrl());
        OpenAiApi openAiApi = OpenAiApi.builder()
                .baseUrl(endpoint.baseUrl())
                .apiKey(config.apiKey())
                .completionsPath(endpoint.completionsPath())
                .embeddingsPath(endpoint.embeddingsPath())
                .build();

        OpenAiChatOptions options = OpenAiChatOptions.builder()
                .model(config.model())
                .temperature(config.temperature())
                .build();

        OpenAiChatModel baseModel = openAiChatModelProvider.getIfAvailable();
        if (baseModel != null) {
            OpenAiChatModel runtimeModel = baseModel.mutate()
                    .openAiApi(openAiApi)
                    .defaultOptions(options)
                    .build();
            return ChatClient.builder(runtimeModel).defaultOptions(options).build();
        }

        log.warn("OpenAiChatModel bean unavailable, fallback to default ChatClient.Builder");
        return chatClientBuilder.clone().defaultOptions(options).build();
    }

    private OpenAiChatOptions buildJsonResponseOptions(RuntimeModelConfig config) {
        return OpenAiChatOptions.builder()
                .model(config.model())
                .temperature(config.temperature())
                .responseFormat(ResponseFormat.builder().type(ResponseFormat.Type.JSON_OBJECT).build())
                .build();
    }

    @SuppressWarnings("unchecked")
    private RuntimeModelConfig resolveRuntimeConfig(ModelConnectionRequest request) {
        Map<String, Object> settings = platformSettingService.getRuntimeSettings();
        Map<String, Object> integration = new LinkedHashMap<>();
        Object integrationRaw = settings.get("integration");
        if (integrationRaw instanceof Map<?, ?> map) {
            integration.putAll((Map<String, Object>) map);
        }
        Map<String, Object> activeModel = resolveActiveModel(integration);

        String provider = normalizeProvider(firstNonBlank(
                requestValue(request == null ? null : request.provider()),
                stringValue(activeModel.get("provider")),
                stringValue(integration.get("modelProvider")),
                "OPENAI"
        ));
        String model = firstNonBlank(
                requestValue(request == null ? null : request.model()),
                stringValue(activeModel.get("model")),
                stringValue(integration.get("modelName")),
                stringValue(integration.get("openaiModel")),
                fallbackModel
        );
        String apiKey = firstNonBlank(
                requestValue(request == null ? null : request.apiKey()),
                stringValue(activeModel.get("apiKey")),
                stringValue(integration.get("modelApiKey")),
                fallbackApiKey
        );
        String baseUrl = firstNonBlank(
                requestValue(request == null ? null : request.baseUrl()),
                stringValue(activeModel.get("baseUrl")),
                stringValue(integration.get("modelBaseUrl")),
                fallbackBaseUrl,
                defaultBaseUrlByProvider(provider)
        );
        double temperature = resolveTemperature(request, activeModel, integration);

        return new RuntimeModelConfig(provider, baseUrl, apiKey, model, temperature);
    }

    private double resolveTemperature(ModelConnectionRequest request,
                                      Map<String, Object> activeModel,
                                      Map<String, Object> integration) {
        if (request != null && request.temperature() != null) {
            return clampTemperature(request.temperature());
        }
        Object raw = firstNonNull(
                activeModel.get("temperature"),
                activeModel.get("modelTemperature"),
                integration.get("modelTemperature")
        );
        if (raw instanceof Number number) {
            return clampTemperature(number.doubleValue());
        }
        if (raw != null) {
            try {
                return clampTemperature(Double.parseDouble(String.valueOf(raw).trim()));
            } catch (Exception ignored) {
                // fall through
            }
        }
        return clampTemperature(fallbackTemperature);
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> resolveActiveModel(Map<String, Object> integration) {
        Object rawModels = integration.get("models");
        if (!(rawModels instanceof Iterable<?> iterable)) {
            return Map.of();
        }
        String activeModelId = stringValue(integration.get("activeModelId"));
        Map<String, Object> first = null;
        for (Object item : iterable) {
            if (!(item instanceof Map<?, ?> itemMap)) {
                continue;
            }
            Map<String, Object> candidate = new LinkedHashMap<>((Map<String, Object>) itemMap);
            if (first == null) {
                first = candidate;
            }
            if (StringUtils.hasText(activeModelId) && activeModelId.equals(stringValue(candidate.get("id")))) {
                return candidate;
            }
        }
        return first != null ? first : Map.of();
    }

    private Endpoint resolveEndpoint(String provider, String rawBaseUrl) {
        String baseUrl = normalizeBaseUrl(firstNonBlank(rawBaseUrl, defaultBaseUrlByProvider(provider)));
        boolean hasVersionSuffix = baseUrl.matches(".*/v\\d+(?:\\.\\d+)?$");
        String completionsPath = hasVersionSuffix ? "/chat/completions" : "/v1/chat/completions";
        String embeddingsPath = hasVersionSuffix ? "/embeddings" : "/v1/embeddings";
        return new Endpoint(baseUrl, completionsPath, embeddingsPath);
    }

    private String normalizeBaseUrl(String value) {
        String base = firstNonBlank(value, fallbackBaseUrl, "https://api.openai.com/v1");
        if (base.endsWith("/")) {
            return base.substring(0, base.length() - 1);
        }
        return base;
    }

    private String normalizeProvider(String value) {
        String provider = StringUtils.hasText(value) ? value.trim().toUpperCase(Locale.ROOT) : "OPENAI";
        if ("OPENAI".equals(provider) || "ZHIPU".equals(provider) || "DEEPSEEK".equals(provider)) {
            return provider;
        }
        return "OPENAI";
    }

    private String defaultBaseUrlByProvider(String provider) {
        return switch (normalizeProvider(provider)) {
            case "ZHIPU" -> "https://open.bigmodel.cn/api/paas/v4";
            case "DEEPSEEK" -> "https://api.deepseek.com/v1";
            default -> "https://api.openai.com/v1";
        };
    }

    private String requestValue(String value) {
        return StringUtils.hasText(value) ? value.trim() : "";
    }

    private String stringValue(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    private String firstNonBlank(String... values) {
        for (String value : values) {
            if (StringUtils.hasText(value)) {
                return value.trim();
            }
        }
        return "";
    }

    private double clampTemperature(double value) {
        if (Double.isNaN(value) || Double.isInfinite(value)) {
            return 0.7d;
        }
        if (value < 0d) return 0d;
        if (value > 2d) return 2d;
        return value;
    }

    private Object firstNonNull(Object... values) {
        if (values == null) {
            return null;
        }
        for (Object value : values) {
            if (value != null) {
                return value;
            }
        }
        return null;
    }

    private String clip(String value, int limit) {
        String normalized = StringUtils.hasText(value) ? value.trim() : "";
        if (normalized.length() <= limit) {
            return normalized;
        }
        return normalized.substring(0, limit) + "...";
    }

    private String singleLine(String value) {
        if (!StringUtils.hasText(value)) {
            return "";
        }
        return value.replaceAll("\\s+", " ").trim();
    }

    private String safeText(String value) {
        return StringUtils.hasText(value) ? value : "N/A";
    }

    private String normalizeFramework(String framework) {
        String normalized = StringUtils.hasText(framework) ? framework.trim().toUpperCase(Locale.ROOT) : "PLAYWRIGHT";
        if ("PLAYWRIGHT".equals(normalized)
                || "CYPRESS".equals(normalized)
                || "SELENIUM".equals(normalized)
                || "APPIUM".equals(normalized)
                || "REST_ASSURED".equals(normalized)) {
            return normalized;
        }
        return "PLAYWRIGHT";
    }

    private String normalizeLanguage(String language, String framework) {
        String normalized = StringUtils.hasText(language) ? language.trim().toUpperCase(Locale.ROOT) : "";
        if ("JAVASCRIPT".equals(normalized)
                || "TYPESCRIPT".equals(normalized)
                || "PYTHON".equals(normalized)
                || "JAVA".equals(normalized)
                || "CSHARP".equals(normalized)) {
            return normalized;
        }
        if ("SELENIUM".equals(framework) || "REST_ASSURED".equals(framework)) return "JAVA";
        return "JAVASCRIPT";
    }

    private String normalizeTargetUrl(String targetUrl) {
        return StringUtils.hasText(targetUrl) ? targetUrl.trim() : "https://example.com";
    }

    private String sanitizeGeneratedCode(String raw) {
        if (!StringUtils.hasText(raw)) return "";
        String text = raw.trim();
        if (!text.contains("```")) {
            return text;
        }

        String cleaned = text
                .replaceAll("(?s)^```[a-zA-Z0-9_-]*\\s*", "")
                .replaceAll("(?s)\\s*```$", "")
                .trim();
        if (StringUtils.hasText(cleaned)) {
            return cleaned;
        }

        int firstFence = text.indexOf("```");
        int secondFence = text.indexOf("```", firstFence + 3);
        if (firstFence >= 0 && secondFence > firstFence) {
            int lineBreak = text.indexOf('\n', firstFence + 3);
            int start = lineBreak > 0 ? lineBreak + 1 : firstFence + 3;
            if (start < secondFence) {
                return text.substring(start, secondFence).trim();
            }
        }
        return text;
    }

    private boolean isRunnableGeneratedScript(String code, String framework) {
        if (!StringUtils.hasText(code)) {
            return false;
        }
        String normalizedFramework = normalizeFramework(framework);
        if (!"PLAYWRIGHT".equals(normalizedFramework)) {
            return true;
        }
        String lowered = code.toLowerCase(Locale.ROOT);
        return lowered.contains("test(") || lowered.contains("test (");
    }

    private String generateFallbackScript(String testCaseDescription,
                                          String targetUrl,
                                          String framework,
                                          String language) {
        return switch (framework) {
            case "CYPRESS" -> """
                    // Fallback Cypress script generated from test case
                    describe('Generated Test', () => {
                      it('executes the core flow', () => {
                        cy.visit('%s');
                        cy.get('body').should('be.visible');
                      });
                    });
                    """.formatted(targetUrl);
            case "SELENIUM" -> """
                    // Fallback Selenium (%s) script generated from test case
                    import org.openqa.selenium.By;
                    import org.openqa.selenium.WebDriver;
                    import org.openqa.selenium.chrome.ChromeDriver;

                    public class GeneratedSeleniumTest {
                        public static void main(String[] args) {
                            WebDriver driver = new ChromeDriver();
                            try {
                                driver.get("%s");
                                driver.findElement(By.tagName("body"));
                            } finally {
                                driver.quit();
                            }
                        }
                    }
                    """.formatted(language, targetUrl);
            case "REST_ASSURED" -> """
                    // Fallback RestAssured script generated from test case
                    import io.restassured.RestAssured;
                    import io.restassured.response.Response;
                    import static org.hamcrest.Matchers.*;

                    public class GeneratedApiTest {
                        public static void main(String[] args) {
                            Response response = RestAssured.given()
                                    .baseUri("%s")
                                    .when()
                                    .get("/");
                            response.then().statusCode(anyOf(is(200), is(204), is(301), is(302)));
                        }
                    }
                    """.formatted(targetUrl);
            case "APPIUM" -> """
                    // Fallback Appium script generated from test case
                    const { remote } = require('webdriverio');

                    (async () => {
                      const driver = await remote({
                        hostname: '127.0.0.1',
                        port: 4723,
                        path: '/wd/hub',
                        capabilities: {
                          platformName: 'Android',
                          'appium:automationName': 'UiAutomator2'
                        }
                      });
                      try {
                        await driver.pause(1000);
                      } finally {
                        await driver.deleteSession();
                      }
                    })();
                    """;
            default -> """
                    // Fallback Playwright (%s) script generated from test case
                    // Source: %s
                    const { test, expect } = require('@playwright/test');

                    test('generated test', async ({ page }) => {
                      await page.goto('%s');
                      await expect(page.locator('body')).toBeVisible();
                    });
                    """.formatted(language, clip(singleLine(safeText(testCaseDescription)), 160), targetUrl);
        };
    }

    private String generateMockAnalysis() {
        return """
                {
                  "qualityScore": 72,
                  "qualityIssues": [
                    {
                      "type":"GIVEN_WHEN_THEN",
                      "severity":"HIGH",
                      "message":"验收标准未完整体现 Given / When / Then 结构。",
                      "suggestion":"使用可执行条件、触发动作、可验证结果拆分验收标准。"
                    },
                    {
                      "type":"AMBIGUITY",
                      "severity":"MEDIUM",
                      "message":"描述中存在“不同信息”等模糊词，边界不清晰。",
                      "suggestion":"明确可配置图片数量、轮播切换规则与异常兜底策略。"
                    }
                  ],
                  "optimizedTitle":"Banner 轮播图支持配置与展示",
                  "optimizedDescription":"As 终端用户\\nI want 首页 banner 可以展示不同图片和文案\\nSo that 运营可配置最多 3 张图片并自动轮播展示",
                  "optimizedAcceptanceCriteria":"Given 已配置 1-3 张有效 banner 图片\\nWhen 用户进入首页\\nThen 系统按配置顺序轮播展示图片与文案",
                  "analysisSummary": "Mock AI analysis generated.",
                  "validationPoints": [
                    {"description":"Verify user can complete the main flow","expectedResult":"Main flow completes successfully","priority":"HIGH"},
                    {"description":"Verify validation on invalid input","expectedResult":"Validation error is displayed","priority":"MEDIUM"}
                  ],
                  "suggestedTestCases": [
                    {"title":"Main flow happy path","description":"Validate user can complete core scenario","testType":"UI","priority":"HIGH"}
                  ]
                }
                """;
    }

    private String generateMockTestCases() {
        return """
                [
                  {
                    "title":"主流程成功校验",
                    "description":"验证用户在满足前置条件时可以完成核心业务流程",
                    "preconditions":"系统可访问，测试账号可登录，依赖服务可用",
                    "testType":"FUNCTIONAL",
                    "priority":"HIGH",
                    "tags":"mock,generated,happy-path",
                    "steps":[
                      {"stepOrder":1,"action":"打开目标页面并进入业务入口","expectedResult":"页面与入口加载成功","testData":"env=staging"},
                      {"stepOrder":2,"action":"输入有效业务数据并提交","expectedResult":"提交成功，无校验错误","testData":"input=valid"},
                      {"stepOrder":3,"action":"触发核心业务动作","expectedResult":"系统返回成功状态并生成业务结果","testData":"assert=success"},
                      {"stepOrder":4,"action":"刷新页面后重新查看结果","expectedResult":"业务结果正确回显且数据持久化一致","testData":"check=persistence"}
                    ]
                  },
                  {
                    "title":"异常输入拦截校验",
                    "description":"验证非法输入时系统能够准确拦截并给出可理解错误提示",
                    "preconditions":"系统可访问，存在可用于异常校验的非法样例数据",
                    "testType":"FUNCTIONAL",
                    "priority":"HIGH",
                    "tags":"mock,generated,negative",
                    "steps":[
                      {"stepOrder":1,"action":"进入目标功能并定位输入区域","expectedResult":"输入区域可操作","testData":"env=staging"},
                      {"stepOrder":2,"action":"输入非法数据并提交","expectedResult":"系统触发校验逻辑","testData":"input=invalid"},
                      {"stepOrder":3,"action":"查看错误码与提示文案","expectedResult":"错误信息明确且可定位问题","testData":"assert=error-message"},
                      {"stepOrder":4,"action":"回查数据状态","expectedResult":"非法请求未造成错误写入或状态污染","testData":"check=data-integrity"}
                    ]
                  },
                  {
                    "title":"边界条件校验",
                    "description":"验证关键字段在最小值、最大值与空值情况下的处理是否符合规则",
                    "preconditions":"边界测试数据已准备",
                    "testType":"FUNCTIONAL",
                    "priority":"MEDIUM",
                    "tags":"mock,generated,boundary",
                    "steps":[
                      {"stepOrder":1,"action":"准备最小值、最大值和空值数据","expectedResult":"边界数据准备完成","testData":"input=min|max|empty"},
                      {"stepOrder":2,"action":"分别提交边界数据","expectedResult":"系统对每类边界输入返回预期结果","testData":"mode=boundary"},
                      {"stepOrder":3,"action":"核对返回状态与提示","expectedResult":"提示信息与业务规则一致","testData":"assert=boundary-rule"},
                      {"stepOrder":4,"action":"检查系统稳定性与日志","expectedResult":"系统无异常崩溃且日志可追踪","testData":"check=stability-log"}
                    ]
                  }
                ]
                """;
    }

    private record Endpoint(String baseUrl, String completionsPath, String embeddingsPath) {
    }

    private record RuntimeModelConfig(String provider, String baseUrl, String apiKey, String model, double temperature) {
        boolean aiEnabled() {
            if (!StringUtils.hasText(apiKey)) {
                return false;
            }
            return !apiKey.startsWith("sk-local-placeholder");
        }
    }

    public record ModelConnectionRequest(
            String provider,
            String baseUrl,
            String apiKey,
            String model,
            Double temperature
    ) {
    }

    public record ModelConnectionResult(
            boolean reachable,
            String provider,
            String baseUrl,
            String model,
            double temperature,
            long latencyMs,
            String message,
            String preview
    ) {
    }

    public record ScriptGenerationResult(
            String code,
            String provider,
            String model,
            boolean fallbackUsed,
            String fallbackReason
    ) {
    }
}
