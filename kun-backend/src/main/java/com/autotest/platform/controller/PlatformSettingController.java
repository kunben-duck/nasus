package com.autotest.platform.controller;

import com.autotest.platform.ai.OpenAIService;
import com.autotest.platform.dto.ApiResponse;
import com.autotest.platform.dto.PlatformSettingsDTO;
import com.autotest.platform.service.PlatformSettingService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/settings")
@RequiredArgsConstructor
@CrossOrigin(origins = "*")
public class PlatformSettingController {

    private final PlatformSettingService platformSettingService;
    private final OpenAIService openAIService;

    @GetMapping
    public ResponseEntity<ApiResponse<PlatformSettingsDTO>> getSettings() {
        return ResponseEntity.ok(ApiResponse.success(platformSettingService.getSettings()));
    }

    @PutMapping
    public ResponseEntity<ApiResponse<PlatformSettingsDTO>> updateSettings(
            @RequestBody Map<String, Object> patch,
            Authentication authentication) {
        String username = authentication != null ? authentication.getName() : "system";
        PlatformSettingsDTO updated = platformSettingService.updateSettings(patch, username);
        return ResponseEntity.ok(ApiResponse.success("Settings updated", updated));
    }

    @PostMapping("/integration/model/test")
    public ResponseEntity<ApiResponse<Map<String, Object>>> testModelConnection(
            @RequestBody(required = false) OpenAIService.ModelConnectionRequest request) {
        OpenAIService.ModelConnectionResult result = openAIService.testModelConnection(request);
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("reachable", result.reachable());
        payload.put("provider", result.provider());
        payload.put("baseUrl", result.baseUrl());
        payload.put("model", result.model());
        payload.put("temperature", result.temperature());
        payload.put("latencyMs", result.latencyMs());
        payload.put("preview", result.preview());
        payload.put("message", result.message());

        return ResponseEntity.ok(ApiResponse.success(result.message(), payload));
    }
}
