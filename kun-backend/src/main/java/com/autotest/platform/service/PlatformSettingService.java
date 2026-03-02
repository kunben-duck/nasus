package com.autotest.platform.service;

import com.autotest.platform.dto.PlatformSettingsDTO;
import com.autotest.platform.entity.PlatformSetting;
import com.autotest.platform.repository.PlatformSettingRepository;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

@Service
@RequiredArgsConstructor
@Slf4j
public class PlatformSettingService {

    private static final String GLOBAL_SCOPE = "GLOBAL";

    private final PlatformSettingRepository platformSettingRepository;
    private final ObjectMapper objectMapper;

    @Transactional
    public PlatformSettingsDTO getSettings() {
        PlatformSetting setting = getOrCreateGlobalSettings();
        Map<String, Object> merged = mergeWithDefaults(readSettings(setting.getSettingsJson()));
        return PlatformSettingsDTO.builder()
                .settings(merged)
                .updatedBy(setting.getUpdatedBy())
                .updatedAt(setting.getUpdatedAt())
                .build();
    }

    @Transactional
    public Map<String, Object> getRuntimeSettings() {
        PlatformSetting setting = getOrCreateGlobalSettings();
        return mergeWithDefaults(readSettings(setting.getSettingsJson()));
    }

    @Transactional
    public PlatformSettingsDTO updateSettings(Map<String, Object> patch, String username) {
        PlatformSetting setting = getOrCreateGlobalSettings();
        Map<String, Object> current = mergeWithDefaults(readSettings(setting.getSettingsJson()));
        deepMerge(current, patch == null ? Map.of() : patch);
        normalizeIntegrationSection(current);

        setting.setSettingsJson(writeSettings(current));
        setting.setUpdatedBy(username);
        PlatformSetting saved = platformSettingRepository.save(setting);

        return PlatformSettingsDTO.builder()
                .settings(current)
                .updatedBy(saved.getUpdatedBy())
                .updatedAt(saved.getUpdatedAt())
                .build();
    }

    private PlatformSetting getOrCreateGlobalSettings() {
        return platformSettingRepository.findByScopeKey(GLOBAL_SCOPE)
                .orElseGet(() -> platformSettingRepository.save(PlatformSetting.builder()
                        .scopeKey(GLOBAL_SCOPE)
                        .settingsJson(writeSettings(defaultSettings()))
                        .updatedBy("system")
                        .build()));
    }

    private Map<String, Object> readSettings(String json) {
        if (json == null || json.isBlank()) {
            return new LinkedHashMap<>();
        }
        try {
            return objectMapper.readValue(json, new TypeReference<>() {});
        } catch (Exception ex) {
            log.warn("Failed to parse platform settings JSON, use defaults. reason={}", ex.getMessage());
            return new LinkedHashMap<>();
        }
    }

    private String writeSettings(Map<String, Object> settings) {
        try {
            return objectMapper.writeValueAsString(settings);
        } catch (Exception ex) {
            throw new RuntimeException("Failed to serialize platform settings", ex);
        }
    }

    @SuppressWarnings("unchecked")
    private void deepMerge(Map<String, Object> current, Map<String, Object> patch) {
        if (patch == null || patch.isEmpty()) {
            return;
        }

        for (Map.Entry<String, Object> entry : patch.entrySet()) {
            Object incoming = entry.getValue();
            if (incoming instanceof Map<?, ?> incomingMap && current.get(entry.getKey()) instanceof Map<?, ?> currentMap) {
                Map<String, Object> currentChild = new LinkedHashMap<>((Map<String, Object>) currentMap);
                deepMerge(currentChild, (Map<String, Object>) incomingMap);
                current.put(entry.getKey(), currentChild);
                continue;
            }
            current.put(entry.getKey(), incoming);
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> mergeWithDefaults(Map<String, Object> persisted) {
        Map<String, Object> merged = defaultSettings();
        deepMerge(merged, persisted == null ? Map.of() : persisted);

        // Backward compatibility: old flat keys from localStorage are auto-upgraded.
        moveFlatIfPresent(merged, persisted, "apiBase", "integration", "apiBase");
        moveFlatIfPresent(merged, persisted, "defaultBrowser", "execution", "defaultBrowser");
        moveFlatIfPresent(merged, persisted, "defaultEnvironment", "execution", "defaultEnvironment");
        moveFlatIfPresent(merged, persisted, "defaultTargetUrl", "execution", "defaultTargetUrl");
        moveFlatIfPresent(merged, persisted, "theme", "general", "theme");
        moveFlatIfPresent(merged, persisted, "language", "general", "language");
        moveFlatIfPresent(merged, persisted, "timezone", "general", "timezone");
        moveFlatIfPresent(merged, persisted, "autoSave", "general", "autoSave");
        moveFlatIfPresent(merged, persisted, "notifications", "general", "notifications");
        moveFlatIfPresent(merged, persisted, "telemetry", "general", "telemetry");
        normalizeIntegrationSection(merged);

        return merged;
    }

    @SuppressWarnings("unchecked")
    private void moveFlatIfPresent(Map<String, Object> merged, Map<String, Object> persisted, String flatKey, String section, String field) {
        if (persisted == null || !persisted.containsKey(flatKey)) {
            return;
        }
        Object value = persisted.get(flatKey);
        Object target = merged.get(section);
        if (target instanceof Map<?, ?> targetMap) {
            Map<String, Object> mutableTarget = new LinkedHashMap<>((Map<String, Object>) targetMap);
            mutableTarget.put(field, value);
            merged.put(section, mutableTarget);
        }
    }

    private Map<String, Object> defaultSettings() {
        Map<String, Object> root = new LinkedHashMap<>();

        Map<String, Object> general = new LinkedHashMap<>();
        general.put("appName", "AutoTest AI");
        general.put("theme", "dark");
        general.put("language", "zh-CN");
        general.put("timezone", "Asia/Shanghai");
        general.put("autoSave", true);
        general.put("notifications", true);
        general.put("telemetry", false);

        Map<String, Object> integration = new LinkedHashMap<>();
        integration.put("apiBase", "/api");
        Map<String, Object> defaultModel = new LinkedHashMap<>();
        defaultModel.put("id", "MODEL-1");
        defaultModel.put("name", "OpenAI 默认模型");
        defaultModel.put("provider", "OPENAI");
        defaultModel.put("baseUrl", "https://api.openai.com/v1");
        defaultModel.put("apiKey", "");
        defaultModel.put("model", "gpt-4o-mini");
        defaultModel.put("temperature", 0.7d);
        integration.put("models", new ArrayList<>(List.of(defaultModel)));
        integration.put("activeModelId", "MODEL-1");
        integration.put("modelProvider", "OPENAI");
        integration.put("modelBaseUrl", "https://api.openai.com/v1");
        integration.put("modelApiKey", "");
        integration.put("modelName", "gpt-4o-mini");
        integration.put("modelTemperature", 0.7d);
        integration.put("openaiModel", "gpt-4o-mini");
        integration.put("jiraServerUrl", "");
        integration.put("jiraProjectKey", "");
        integration.put("githubRepo", "");
        integration.put("githubBranch", "main");

        Map<String, Object> notification = new LinkedHashMap<>();
        notification.put("executionComplete", true);
        notification.put("executionFailed", true);
        notification.put("dailyReport", false);

        Map<String, Object> execution = new LinkedHashMap<>();
        execution.put("defaultBrowser", "chromium");
        execution.put("defaultEnvironment", "staging");
        execution.put("defaultTargetUrl", "https://example.com");

        root.put("general", general);
        root.put("integration", integration);
        root.put("notification", notification);
        root.put("execution", execution);
        return root;
    }

    @SuppressWarnings("unchecked")
    private void normalizeIntegrationSection(Map<String, Object> root) {
        Object integrationObject = root.get("integration");
        if (!(integrationObject instanceof Map<?, ?> map)) {
            return;
        }

        Map<String, Object> integration = new LinkedHashMap<>((Map<String, Object>) map);
        String legacyProvider = normalizeProvider(stringValue(integration.get("modelProvider")));
        String legacyModelName = firstNonBlank(
                stringValue(integration.get("modelName")),
                stringValue(integration.get("openaiModel")),
                "gpt-4o-mini"
        );
        String legacyBaseUrl = firstNonBlank(
                stringValue(integration.get("modelBaseUrl")),
                defaultBaseUrlByProvider(legacyProvider)
        );
        String legacyApiKey = stringValue(integration.get("modelApiKey"));
        double legacyTemperature = parseTemperature(integration.get("modelTemperature"));

        List<Map<String, Object>> normalizedModels = normalizeModelConfigs(
                integration,
                legacyProvider,
                legacyBaseUrl,
                legacyApiKey,
                legacyModelName,
                legacyTemperature
        );
        Map<String, Object> activeModel = resolveActiveModel(
                normalizedModels,
                stringValue(integration.get("activeModelId"))
        );

        String provider = normalizeProvider(stringValue(activeModel.get("provider")));
        String baseUrl = firstNonBlank(
                stringValue(activeModel.get("baseUrl")),
                defaultBaseUrlByProvider(provider)
        );
        String modelName = firstNonBlank(
                stringValue(activeModel.get("model")),
                "gpt-4o-mini"
        );
        String apiKey = stringValue(activeModel.get("apiKey"));
        double temperature = parseTemperature(activeModel.get("temperature"));

        integration.put("models", normalizedModels);
        integration.put("activeModelId", stringValue(activeModel.get("id")));
        integration.put("modelProvider", provider);
        integration.put("modelBaseUrl", baseUrl);
        integration.put("modelApiKey", apiKey);
        integration.put("modelName", modelName);
        integration.put("openaiModel", modelName);
        integration.put("modelTemperature", temperature);

        root.put("integration", integration);
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> normalizeModelConfigs(Map<String, Object> integration,
                                                            String fallbackProvider,
                                                            String fallbackBaseUrl,
                                                            String fallbackApiKey,
                                                            String fallbackModelName,
                                                            double fallbackTemperature) {
        List<Map<String, Object>> normalized = new ArrayList<>();
        Object rawModels = integration.get("models");
        if (rawModels instanceof Iterable<?> iterable) {
            int index = 1;
            for (Object item : iterable) {
                if (!(item instanceof Map<?, ?> itemMap)) {
                    index++;
                    continue;
                }
                Map<String, Object> source = new LinkedHashMap<>((Map<String, Object>) itemMap);
                String provider = normalizeProvider(firstNonBlank(
                        stringValue(source.get("provider")),
                        stringValue(source.get("modelProvider")),
                        fallbackProvider
                ));
                String modelName = firstNonBlank(
                        stringValue(source.get("model")),
                        stringValue(source.get("modelName")),
                        stringValue(source.get("openaiModel")),
                        fallbackModelName,
                        "gpt-4o-mini"
                );
                String baseUrl = firstNonBlank(
                        stringValue(source.get("baseUrl")),
                        stringValue(source.get("modelBaseUrl")),
                        defaultBaseUrlByProvider(provider),
                        fallbackBaseUrl
                );
                String apiKey = firstNonBlank(
                        stringValue(source.get("apiKey")),
                        stringValue(source.get("modelApiKey")),
                        fallbackApiKey
                );
                double temperature = parseTemperature(firstNonNull(
                        source.get("temperature"),
                        source.get("modelTemperature"),
                        fallbackTemperature
                ));
                String id = firstNonBlank(
                        stringValue(source.get("id")),
                        "MODEL-" + index
                );
                String displayName = firstNonBlank(
                        stringValue(source.get("name")),
                        provider + " / " + modelName
                );

                Map<String, Object> normalizedItem = new LinkedHashMap<>();
                normalizedItem.put("id", id);
                normalizedItem.put("name", displayName);
                normalizedItem.put("provider", provider);
                normalizedItem.put("baseUrl", baseUrl);
                normalizedItem.put("apiKey", apiKey);
                normalizedItem.put("model", modelName);
                normalizedItem.put("temperature", temperature);
                normalized.add(normalizedItem);
                index++;
            }
        }

        if (!normalized.isEmpty()) {
            return normalized;
        }

        Map<String, Object> fallbackModel = new LinkedHashMap<>();
        fallbackModel.put("id", "MODEL-1");
        fallbackModel.put("name", "默认模型");
        fallbackModel.put("provider", normalizeProvider(fallbackProvider));
        fallbackModel.put("baseUrl", firstNonBlank(fallbackBaseUrl, defaultBaseUrlByProvider(fallbackProvider)));
        fallbackModel.put("apiKey", fallbackApiKey);
        fallbackModel.put("model", firstNonBlank(fallbackModelName, "gpt-4o-mini"));
        fallbackModel.put("temperature", parseTemperature(fallbackTemperature));
        return new ArrayList<>(List.of(fallbackModel));
    }

    private Map<String, Object> resolveActiveModel(List<Map<String, Object>> models, String activeModelId) {
        if (models == null || models.isEmpty()) {
            return new LinkedHashMap<>();
        }

        if (StringUtils.hasText(activeModelId)) {
            String normalizedActiveId = activeModelId.trim();
            for (Map<String, Object> model : models) {
                if (normalizedActiveId.equals(stringValue(model.get("id")))) {
                    return model;
                }
            }
        }
        return models.get(0);
    }

    private String normalizeProvider(String provider) {
        if (!StringUtils.hasText(provider)) {
            return "OPENAI";
        }
        String normalized = provider.trim().toUpperCase(Locale.ROOT);
        if ("ZHIPU".equals(normalized) || "DEEPSEEK".equals(normalized) || "OPENAI".equals(normalized)) {
            return normalized;
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

    private double parseTemperature(Object raw) {
        if (raw == null) {
            return 0.7d;
        }
        if (raw instanceof Number number) {
            return clampTemperature(number.doubleValue());
        }
        try {
            return clampTemperature(Double.parseDouble(String.valueOf(raw).trim()));
        } catch (Exception ignored) {
            return 0.7d;
        }
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
}
